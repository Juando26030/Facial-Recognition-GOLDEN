"""Camino caliente del formulario público bajo carga (D2.3): caché servida sin pool de hilos, una sola recarga por clave, un solo conteo de cupo, conexión soltada antes de validar,
vía rápida del «cupo lleno», bloqueo más corto y contrapresión (lock_timeout → 503 + Retry-After). La integridad (sin sobreventa ni duplicados, `replayed`) NO cambia."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app import email_check, formsvc
from app.database import engine
from app.models import FormEvent, FormSubmission
from app.routers import forms_public
from app.ttlcache import TTLCache
from tests.test_forms import _create, _event, _person_values, _state, _status, _submit, _url


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _open_form(client, factory, capacity=None):
    ev = _event(client, factory)
    f = _create(client, ev)
    _status(client, ev, f, manual_status="activo", **({"capacity": capacity} if capacity else {}))
    client.post("/logout")
    return ev, f


# ------------------------------------------------------------------ 1) estado y página: acierto de caché sin hilos ni base; una sola recarga; un solo conteo
def test_get_or_compute_reloads_once_when_many_threads_hit_an_expired_key():
    cache, calls = TTLCache(60), []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return {"v": len(calls)}

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get_or_compute("k", slow))) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and all(r == {"v": 1} for r in results)                     # 12 hilos, UNA recarga
    with pytest.raises(RuntimeError):                                                    # si la recarga falla no se guarda nada y el siguiente lo intenta
        cache.get_or_compute("otra", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert cache.get_or_compute("otra", lambda: 5) == 5


def test_state_and_page_cache_hits_use_neither_the_thread_pool_nor_the_database(client, factory, monkeypatch):
    ev, f = _open_form(client, factory)
    monkeypatch.setattr(formsvc.public_cache, "ttl", 60)                               # conftest apaga la caché (FORM_PUBLIC_CACHE_SECONDS=0): aquí se enciende
    first = client.get(f"{_url(ev, f)}/state").json()
    page = client.get(_url(ev, f))
    assert first["stage"] == "form" and page.status_code == 200

    def boom(*a, **k):
        raise AssertionError("un acierto de caché no debe usar el pool de hilos ni la base")

    monkeypatch.setattr(forms_public, "run_in_threadpool", boom)
    monkeypatch.setattr(forms_public, "SessionLocal", boom)
    assert client.get(f"{_url(ev, f)}/state").json() == first                          # se sirve en el bucle de eventos
    again = client.get(_url(ev, f))
    assert again.status_code == 200 and again.text == page.text and again.headers["cache-control"].startswith("public")
    # con parámetros (clave de pruebas, token, enlace) NO hay caché: sí va al hilo
    with pytest.raises(AssertionError):
        client.get(f"{_url(ev, f)}/state", params={"t": "x"})


def test_a_cache_miss_does_one_capacity_count_and_it_is_a_single_statement(client, factory, monkeypatch):
    ev, f = _open_form(client, factory, capacity=10)
    formsvc.invalidate_public_cache()
    calls, statements = [], []
    real = formsvc.held_count
    monkeypatch.setattr(formsvc, "held_count", lambda db, form: (calls.append(1), real(db, form))[1])

    @event.listens_for(engine, "before_cursor_execute")
    def spy(conn, cursor, statement, *a):
        statements.append(statement)

    try:
        st = _state(client, ev, f)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert st["stage"] == "form" and st["capacity_left"] == 10
    assert len(calls) == 1                                                             # antes: dos (estado del cupo + «quedan N cupos»)
    held_sql = [s for s in statements if "form_payments" in s and "form_submissions" in s]
    assert len(held_sql) == 1 and "count" in held_sql[0].lower()                       # y en UNA sola consulta (antes dos)


# ------------------------------------------------------------------ 2a) validar sin conexión; correo con caché
def test_validation_and_dns_run_without_holding_a_database_connection(client, factory, monkeypatch):
    ev, f = _open_form(client, factory)
    seen = {}
    real = forms_public.formlib.validate_submission
    baseline = engine.pool.checkedout()                                                # las fixtures de la prueba pueden tener una conexión propia abierta

    def spy(design, values, uploaded, checker):
        seen["checked_out"] = engine.pool.checkedout()
        return real(design, values, uploaded, checker)

    monkeypatch.setattr(forms_public.formlib, "validate_submission", spy)
    assert _submit(client, ev, f, _person_values()).status_code == 200
    assert seen["checked_out"] == baseline                                                    # la conexión del primer SELECT ya volvió al pool cuando se valida (DNS, archivos, CPU)


def test_email_domain_lookups_are_cached_including_dns_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(email_check, "_domain_cache", {})
    monkeypatch.setattr(email_check, "_domain_receives_mail", lambda d: (calls.append(d), None if d == "caido.example" else True)[1])
    for _ in range(5):
        assert email_check.check_email("a@ok.example") == (True, "")
        assert email_check.check_email("b@caido.example") == (True, "")                # el DNS no respondió: NO se rechaza y tampoco se reintenta en cada envío
    assert sorted(calls) == ["caido.example", "ok.example"]
    assert email_check._DNS_LIFETIME <= 2.0 and email_check._UNKNOWN_SECONDS == 60


# ------------------------------------------------------------------ 2b) vía rápida del cupo lleno
def test_full_form_rejects_without_asking_for_the_lock_and_replays_still_work(client, factory, monkeypatch):
    ev, f = _open_form(client, factory, capacity=1)
    assert _submit(client, ev, f, _person_values(), sid="s-a").status_code == 200
    calls = []
    real = formsvc.reserve_slot
    monkeypatch.setattr(formsvc, "reserve_slot", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    other = {**_person_values(), "cedula": "2002"}
    r = _submit(client, ev, f, other, sid="s-b")
    assert r.status_code == 409 and r.json()["stage"] == "closed" and calls == []      # rechazado SIN pedir el bloqueo de la fila
    replay = _submit(client, ev, f, _person_values(), sid="s-a")                       # reintento de la inscripción ya confirmada, con el formulario lleno
    assert replay.status_code == 200 and replay.json()["replayed"] is True and calls == []       # ahora también el reintento se responde con la precomprobación, sin bloqueo


def test_stale_room_hint_never_oversells_and_a_freed_slot_is_seen_at_once(client, factory, db):
    ev, f = _open_form(client, factory, capacity=1)
    assert _submit(client, ev, f, _person_values(), sid="s-a").status_code == 200
    formsvc._held_cache.set(f["id"], 0)                                                # caché DESACTUALIZADA que dice «hay cupo»
    r = _submit(client, ev, f, {**_person_values(), "cedula": "2002"}, sid="s-b")
    assert r.status_code == 409 and db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").count() == 1      # la base (con bloqueo) manda
    assert formsvc._held_cache.get(f["id"]) == 1                                       # y deja marcado «lleno» para los siguientes
    from tests.conftest import login
    login(client, "coord1")
    sub_id = db.query(FormSubmission).filter_by(form_id=f["id"]).one().id
    assert client.delete(f"/api/events/{ev.id}/forms/{f['id']}/submissions/{sub_id}").status_code == 200        # se libera el cupo…
    client.post("/logout")
    assert _submit(client, ev, f, {**_person_values(), "cedula": "3003"}, sid="s-c").status_code == 200        # …y se ve en el acto (la caché se invalida)


# ------------------------------------------------------------------ 2c) qué corre con el bloqueo tomado
def test_only_reserve_insert_and_commit_run_while_the_form_row_is_locked(client, factory):
    ev, f = _open_form(client, factory)
    log = []

    @event.listens_for(engine, "before_cursor_execute")
    def stmt(conn, cursor, statement, *a):
        log.append(("sql", statement.lower()))

    @event.listens_for(engine, "commit")
    def commit(conn):
        log.append(("commit", ""))

    try:
        assert _submit(client, ev, f, _person_values()).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", stmt)
        event.remove(engine, "commit", commit)
    start = next(i for i, (k, s) in enumerate(log) if k == "sql" and "form_reserve_slot" in s)
    end = next(i for i, (k, s) in enumerate(log) if k == "commit" and i > start)
    locked = [s for k, s in log[start:end] if k == "sql"]
    assert len(locked) == 2 and "form_reserve_slot" in locked[0] and locked[1].startswith("insert into form_submissions")      # reserva + INSERT (+ COMMIT) = 3 idas y vueltas
    assert not any("from events" in s or "form_events" in s for s in locked)                                                   # sin SELECT Event ni INSERT FormEvent con el bloqueo
    after = [s for k, s in log[end:] if k == "sql"]
    assert any(s.startswith("insert into form_events") for s in after)                                                          # la marca de analítica se guarda DESPUÉS del commit


def test_submit_analytics_event_is_still_recorded(client, factory, db):
    ev, f = _open_form(client, factory)
    assert _submit(client, ev, f, _person_values(), sid="sx").status_code == 200
    ev_rows = db.query(FormEvent).filter_by(form_id=f["id"], kind="submit").all()
    assert [e.sid for e in ev_rows] == ["sx"] and ev_rows[0].is_test is False


# ------------------------------------------------------------------ 2d) contrapresión
def test_waiting_for_the_form_lock_gives_up_with_503_and_a_retry_with_the_same_sid_is_replayed(client, factory, db, monkeypatch):
    ev, f = _open_form(client, factory)
    monkeypatch.setattr(formsvc, "FORM_LOCK_TIMEOUT_MS", 300)
    holder = engine.connect()
    tx = holder.begin()
    holder.execute(text("SELECT id FROM web_forms WHERE id = :i FOR UPDATE"), {"i": f["id"]})      # otro envío tiene la fila del formulario bloqueada
    t0 = time.time()
    try:
        r = _submit(client, ev, f, _person_values(), sid="s-lock")
    finally:
        tx.rollback()
        holder.close()
    assert r.status_code == 503 and r.headers["retry-after"] in ("1", "2", "3") and r.json()["busy"] is True
    assert 0.25 < time.time() - t0 < 3                                                   # esperó ~lock_timeout, no 60 s
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 0
    ok = _submit(client, ev, f, _person_values(), sid="s-lock")                          # el navegador reintenta con la MISMA sid
    assert ok.status_code == 200 and "replayed" not in ok.json()
    again = _submit(client, ev, f, _person_values(), sid="s-lock")
    assert again.status_code == 200 and again.json()["replayed"] is True and db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1


# ------------------------------------------------------------------ integridad con carga concurrente (cupo exacto, sin duplicados)
def test_concurrent_burst_keeps_exact_capacity_and_no_duplicates(client, factory, db, monkeypatch):
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "0")          # integridad con la fila peleada por todos; el tope de esperas (503 temprano) se prueba en test_form_backpressure.py
    ev, f = _open_form(client, factory, capacity=8)
    outcomes, url = [], f"{_url(ev, f)}/submit"

    def go(cedula, sid):
        with TestClient(client.app, follow_redirects=False) as c:
            r = c.post(url, json={"values": {**_person_values(), "cedula": cedula}, "sid": sid})
            outcomes.append((cedula, sid, r.status_code, r.json()))

    jobs = [(f"9{i:03d}", f"sid{i}") for i in range(20)] + [("9000", "sid-dup-a"), ("9000", "sid-dup-b")] + [("9001", "sid1")] * 2      # 20 personas + 2 duplicados de cédula + reintentos de sid
    threads = [threading.Thread(target=go, args=j) for j in jobs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not [o for o in outcomes if o[2] >= 500], [o for o in outcomes if o[2] >= 500]
    rows = db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").all()
    assert len(rows) == 8                                                                # cupo EXACTO: ni una de más ni una de menos
    persons = [r.person_id for r in rows]
    sids = [r.sid for r in rows]
    assert len(set(persons)) == len(persons) and len(set(sids)) == len(sids)            # sin cédulas ni sid repetidas
    assert all(code in (200, 409) for _, _, code, _ in outcomes)
    assert sum(1 for _, _, code, body in outcomes if code == 200 and not body.get("replayed")) == 8
