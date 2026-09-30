"""Formularios bajo carga (Fase 0): envío idempotente, cupo sin sobreventa con envíos simultáneos, llaves de cupo denormalizadas, caché del estado
público, límite por IP en memoria y carga a la base por la cola (con reintento)."""
import json
import threading

import pytest

from app import formsvc, jobs
from app.models import FormSubmission, Job, User
from app.routers import forms_public
from app.ttlcache import TTLCache
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _open, _person_values, _put, _state, _status, _submit, _url


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _who(n):
    return {"cedula": f"70{n:04d}", "nombres": f"P{n}", "apellidos": "Q", "correo": f"p{n}@example.com"}


def test_retry_with_the_same_send_key_is_idempotent_but_another_visit_is_a_duplicate(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    first = _submit(client, ev, f, _person_values(), sid="visita-1")
    retry = _submit(client, ev, f, _person_values(), sid="visita-1")            # el navegador reintentó tras un corte de red
    assert first.status_code == 200 and retry.status_code == 200 and retry.json()["replayed"] is True
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1
    other = _submit(client, ev, f, _person_values(), sid="visita-2")            # otra visita, misma cédula: es un duplicado de verdad
    assert other.status_code == 409 and other.json()["duplicate"] is True


def test_simultaneous_submissions_never_oversell_the_capacity(factory, db, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "0")          # aquí se verifica la integridad del cupo bajo el bloqueo, no el rechazo temprano (test_form_backpressure.py)

    from app.main import app
    from tests.test_forms import _status as status

    with TestClient(app, follow_redirects=False) as admin:
        ev = _event(admin, factory)
        f = _create(admin, ev)
        assert status(admin, ev, f, capacity=4).status_code == 200
        _open(admin, ev, f)
    results = []

    def go(n):
        with TestClient(app, follow_redirects=False) as c:
            results.append(_submit(c, ev, f, _who(n), sid=f"s{n}").status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results).count(200) == 4 and all(code in (200, 409) for code in results)         # exactamente el cupo, nadie más
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 4
    assert db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").count() == 4      # exactamente el cupo, confirmadas


def test_quota_counts_use_stored_keys_and_rebuild_them_when_missing_or_when_rules_change(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    f = _create(client, ev)
    cat = {"id": "cat", "type": "select", "label": "Categoría", "options": ["VIP", "General"]}
    rules = {"quotas": {"rules": [{"id": "r1", "label": "VIP", "match": "all", "conds": [{"field": "cat", "op": "equals", "value": "VIP"}], "limit": 2}]}}
    assert _put(client, ev, f, design=_design(_basic_fields() + [cat]), settings=rules).status_code == 200
    _open(client, ev, f)
    assert _submit(client, ev, f, {**_who(1), "cat": "VIP"}, sid="a").status_code == 200
    assert _submit(client, ev, f, {**_who(2), "cat": "General"}, sid="b").status_code == 200
    stored = {s.person_id: s.quota_keys for s in db.query(FormSubmission).filter_by(form_id=f["id"])}
    assert stored["700001"].startswith("|") and "~" in stored["700001"] and stored["700002"] == ""                            # solo la de VIP cumple la regla

    db.query(FormSubmission).filter_by(form_id=f["id"]).update({"quota_keys": None})                # inscripciones anteriores a esta versión
    db.commit()
    assert _state(client, ev, f)["quota"]["left"] == {"cat": {"VIP": 1}}                             # se recalculan solas y el conteo sigue bien
    assert db.query(FormSubmission).filter(FormSubmission.form_id == f["id"], FormSubmission.quota_keys == None).count() == 0  # noqa: E711

    login(client, "coord1")                                                                          # el coordinador cambia la regla: ahora cuenta General
    rules["quotas"]["rules"][0]["conds"][0]["value"] = "General"
    assert _put(client, ev, f, settings=rules).status_code == 200
    client.post("/logout")
    assert _state(client, ev, f)["quota"]["left"] == {"cat": {"General": 1}}
    assert _submit(client, ev, f, {**_who(3), "cat": "General"}, sid="c").status_code == 200
    assert _submit(client, ev, f, {**_who(4), "cat": "General"}, sid="d").status_code == 409


def test_public_state_is_cached_for_a_few_seconds_and_edits_clear_it(client, factory, monkeypatch):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    monkeypatch.setattr(formsvc, "public_cache", TTLCache(60))
    calls = []
    real = forms_public._state
    monkeypatch.setattr(forms_public, "_state", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert _state(client, ev, f)["stage"] == "form" and _state(client, ev, f)["stage"] == "form"
    assert len(calls) == 1                                                                             # la segunda llamada salió de la memoria
    page = client.get(_url(ev, f))
    assert page.status_code == 200 and "s-maxage" in page.headers["cache-control"]                     # el cascarón se puede guardar unos segundos
    login(client, "coord1")
    _status(client, ev, f, capacity=5)                                                                 # una edición vacía la caché (en este proceso)
    client.post("/logout")
    _state(client, ev, f)
    assert len(calls) == 2


def test_test_links_and_closed_forms_are_never_cached_publicly(client, factory, monkeypatch):
    ev = _event(client, factory)
    f = _create(client, ev)
    key = f["test_key"]
    client.post("/logout")
    test_page = client.get(f"{_url(ev, f)}?k={key}")
    assert test_page.status_code == 200 and "s-maxage" not in test_page.headers["cache-control"]        # el enlace de pruebas nunca se guarda en cachés compartidas
    assert client.get(_url(ev, f)).status_code == 404                                                   # en pruebas y sin la clave: no existe


def test_public_rate_limit_is_per_ip_and_in_memory(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    forms_public._limiter.reset()
    for n in range(60):
        assert _submit(client, ev, f, {**_who(n), "correo": "mal"}, sid=f"x{n}").status_code == 422       # cada intento cuenta (aunque falle la validación)
    assert _submit(client, ev, f, _who(99), sid="z").status_code == 429
    other_ip = client.post(f"{_url(ev, f)}/submit", json={"values": _who(98), "sid": "y"}, headers={"X-Forwarded-For": "203.0.113.9"})
    assert other_ip.status_code == 200                                                                  # otra persona (otra IP) no se ve afectada


def test_realtime_feed_goes_through_the_queue_and_survives_a_failure(client, factory, db, monkeypatch):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"feed": "realtime"})
    _open(client, ev, f)
    monkeypatch.setattr(jobs, "kick", lambda: None)                                                    # el worker todavía no corrió
    assert _submit(client, ev, f, _person_values()).status_code == 200
    assert db.query(User).filter_by(id="1001").first() is None                                          # la petición NO cargó a la base: eso va a la cola
    job = db.query(Job).filter_by(kind="form_feed").one()
    assert job.status == "queued" and json.loads(job.payload_json)["submission_id"]

    boom = {"n": 0}
    real = formsvc.run_feed_job

    def flaky(sub_id):
        boom["n"] += 1
        if boom["n"] == 1:
            raise RuntimeError("base caída un momento")
        return real(sub_id)

    monkeypatch.setattr(formsvc, "run_feed_job", flaky)
    assert jobs.run_once() == 1
    db.expire_all()
    job = db.query(Job).filter_by(kind="form_feed").one()
    assert job.status == "queued" and job.attempts == 1 and "base caída" in job.last_error                # falló: queda para reintentar
    job.run_at = job.run_at.replace(year=2000)                                                          # adelanta el reintento
    db.commit()
    assert jobs.run_once() == 1
    db.expire_all()
    assert db.query(Job).filter_by(kind="form_feed").one().status == "done"
    assert db.query(User).filter_by(id="1001").first().first_name == "Ana"                                # ahora sí quedó en la base del evento
