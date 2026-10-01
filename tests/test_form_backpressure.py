"""Contrapresión del envío del formulario público: precomprobación sin bloqueo (reintento, duplicado, cupo lleno), tope de envíos esperando el `FOR UPDATE` (503 temprano),
analítica y aviso al worker DESPUÉS de responder, y la política de reintentos del navegador (templates/form_public.html). La reserva bajo bloqueo sigue siendo la autoridad."""
import json
import shutil
import subprocess
import itertools
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import formsvc, jobs
from app.main import app
from app.models import FormEvent, FormSubmission
from app.routers import forms_public
from tests.test_forms import _create, _event, _person_values, _put, _status, _submit, _url

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _open_forms(client, factory, specs):
    """Un evento y un formulario abierto por cada spec {capacity?, settings?}: devuelve (evento, [formularios]). Todo antes de cerrar la sesión de administración."""
    ev = _event(client, factory)
    forms = []
    for spec in specs:
        f = _create(client, ev)
        if spec.get("settings"):
            _put(client, ev, f, settings=spec["settings"])
        assert _status(client, ev, f, manual_status="activo", **({"capacity": spec["capacity"]} if spec.get("capacity") else {})).status_code == 200
        forms.append(f)
    client.post("/logout")
    return ev, forms


def _open_form(client, factory, capacity=None, **settings):
    ev, (f,) = _open_forms(client, factory, [{"capacity": capacity, "settings": settings}])
    return ev, f


def _count_reserve(monkeypatch):
    calls = []
    real = formsvc.reserve_slot
    monkeypatch.setattr(formsvc, "reserve_slot", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    return calls


# ------------------------------------------------------------------ 1) precomprobación sin bloqueo
def test_replay_and_duplicate_are_answered_before_asking_for_the_lock(client, factory, db, monkeypatch):
    ev, f = _open_form(client, factory)
    assert _submit(client, ev, f, _person_values(), sid="s-a").status_code == 200
    calls = _count_reserve(monkeypatch)
    replay = _submit(client, ev, f, _person_values(), sid="s-a")                         # misma sid: «replayed» sin hacer fila
    assert replay.status_code == 200 and replay.json()["replayed"] is True and calls == []
    dup = _submit(client, ev, f, _person_values(), sid="s-otra")                          # misma cédula con otra sid: duplicado sin hacer fila
    assert dup.status_code == 409 and dup.json()["duplicate"] is True and calls == []
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1
    new = _submit(client, ev, f, {**_person_values(), "cedula": "2002"}, sid="s-b")       # una persona nueva SÍ pide el bloqueo
    assert new.status_code == 200 and calls == [1]


def test_the_lock_is_still_the_final_authority_when_the_precheck_says_nothing(client, factory, db, monkeypatch):
    """Si la precomprobación no ve nada (carrera entre dos envíos), `form_reserve_slot` repite TODAS las comprobaciones: nada se eliminó."""
    ev, (f, g) = _open_forms(client, factory, [{"capacity": 1}, {}])
    assert _submit(client, ev, g, _person_values(), sid="s-a").status_code == 200        # (el otro formulario, sin cupo, sirve para el caso del duplicado)
    assert _submit(client, ev, f, _person_values(), sid="s-a").status_code == 200
    monkeypatch.setattr(formsvc, "precheck", lambda *a, **k: (False, False))
    monkeypatch.setattr(formsvc, "held_count_cached", lambda *a, **k: 0)                  # la caché del «lleno» dice que hay sitio
    replay = _submit(client, ev, f, _person_values(), sid="s-a")
    assert replay.status_code == 200 and replay.json()["replayed"] is True                # reintento: lo resuelve la base
    full = _submit(client, ev, f, {**_person_values(), "cedula": "3003"}, sid="s-c")
    assert full.status_code == 409 and full.json()["stage"] == "closed"                    # cupo lleno: lo resuelve la base
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1
    dup = _submit(client, ev, g, _person_values(), sid="s-z")
    assert dup.status_code == 409 and dup.json()["duplicate"] is True                      # duplicado: lo resuelve la base


def test_precheck_reads_match_the_sql_function_conditions(client, factory, db):
    ev, f = _open_form(client, factory)
    assert _submit(client, ev, f, _person_values(), sid="s-a").status_code == 200
    form = db.get(forms_public.WebForm, f["id"])
    assert formsvc.precheck(db, form, "s-a", "1001", False) == (True, True)
    assert formsvc.precheck(db, form, "s-a", "9999", False) == (False, False)              # la sid confirmada es de OTRA persona: no es reintento
    assert formsvc.precheck(db, form, "s-x", "1001", False) == (False, True)
    assert formsvc.precheck(db, form, "s-x", "1001", True) == (False, False)               # las pruebas no cuentan para duplicados
    assert formsvc.precheck(db, form, None, None, False) == (False, False)


# ------------------------------------------------------------------ 2) tope de esperas por proceso
def test_lock_waiters_cap_rejects_at_once_with_503_and_jitter_and_always_releases(client, factory, db, monkeypatch):
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "1")
    ev, f = _open_form(client, factory)
    gate, entered = threading.Event(), threading.Event()
    real, calls = formsvc.reserve_slot, []

    def slow(*a, **k):
        calls.append(1)
        entered.set()
        gate.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(formsvc, "reserve_slot", slow)
    cycle = itertools.cycle(("1", "2", "3"))
    monkeypatch.setattr(forms_public.random, "choice", lambda options: int(next(cycle)))      # el jitter es aleatorio: se fija la secuencia para que la prueba no dependa del azar
    first = {}
    t = threading.Thread(target=lambda: first.setdefault("r", _submit(TestClient(app, follow_redirects=False), ev, f, _person_values(), sid="s-1")))
    t.start()
    assert entered.wait(10) and forms_public._lock_waiters == 1                           # el primero espera/tiene el bloqueo
    seen = set()
    for i in range(6):
        r = _submit(client, ev, f, {**_person_values(), "cedula": f"70{i}"}, sid=f"s-x{i}")   # el resto rebota al instante
        assert r.status_code == 503 and r.json()["busy"] is True
        seen.add(r.headers["retry-after"])
    assert seen == {"1", "2", "3"}                                                         # Retry-After con jitter: los tres valores posibles
    assert calls == [1]                                                                   # ninguno pidió el bloqueo
    gate.set()
    t.join(15)
    assert first["r"].status_code == 200 and forms_public._lock_waiters == 0             # se libera al terminar
    assert db.query(FormSubmission).filter_by(form_id=f["id"]).count() == 1


def test_counter_is_released_on_errors_and_the_full_form_fast_path_does_not_count(client, factory, monkeypatch):
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "1")
    ev, (f, f2) = _open_forms(client, factory, [{}, {"capacity": 1}])

    def boom(*a, **k):
        raise RuntimeError("falla dentro del bloqueo")

    with monkeypatch.context() as m:
        m.setattr(formsvc, "reserve_slot", boom)
        r = _submit(TestClient(app, follow_redirects=False, raise_server_exceptions=False), ev, f, _person_values(), sid="s-e")
        assert r.status_code == 500 and forms_public._lock_waiters == 0                   # finally: el contador vuelve a 0
    assert _submit(client, ev, f, _person_values(), sid="s-ok").status_code == 200        # y el formulario sigue sirviendo
    assert _submit(client, ev, f2, _person_values(), sid="s-1").status_code == 200
    assert forms_public._enter_lock_zone() is True                                        # la zona está llena…
    try:
        rejected = _submit(client, ev, f2, {**_person_values(), "cedula": "5005"}, sid="s-2")
        assert rejected.status_code == 409 and forms_public._lock_waiters == 1            # …y el «cupo lleno» sale igual (409), sin contarse ni rebotar
        busy = _submit(client, ev, f, {**_person_values(), "cedula": "6006"}, sid="s-3")
        assert busy.status_code == 503
    finally:
        forms_public._leave_lock_zone()
    assert forms_public._lock_waiters == 0


def test_cap_zero_disables_the_limit(client, factory, monkeypatch):
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "0")
    ev, f = _open_form(client, factory)
    forms_public._enter_lock_zone()
    forms_public._enter_lock_zone()
    try:
        assert _submit(client, ev, f, _person_values(), sid="s-1").status_code == 200
    finally:
        forms_public._leave_lock_zone()
        forms_public._leave_lock_zone()


# ------------------------------------------------------------------ 3) después de responder
def test_analytics_and_kick_run_after_the_response_and_kick_only_when_a_job_was_queued(client, factory, db, monkeypatch):
    kicks = []
    monkeypatch.setattr(jobs, "kick", lambda *a: kicks.append(1))
    ev, (f, f2) = _open_forms(client, factory, [{}, {"settings": {"feed": "realtime"}}])      # el primero con feed manual: no se encola nada
    r = _submit(client, ev, f, _person_values(), sid="s-a")
    assert r.status_code == 200 and kicks == []
    assert db.query(FormEvent).filter_by(form_id=f["id"], kind="submit").count() == 1     # la analítica sí se registró (tarea posterior)
    assert _submit(client, ev, f2, _person_values(), sid="s-b").status_code == 200
    assert kicks == [1]                                                                   # feed en tiempo real: se encoló → una sola aviso


def test_respond_defers_or_inlines_the_after_tasks(monkeypatch):
    ran = []
    resp = forms_public._respond({"ok": True}, [lambda: ran.append(1)])
    assert resp.background is not None and ran == []                                      # se ejecutará después de enviar la respuesta
    monkeypatch.setenv("SUBMIT_AFTER_RESPONSE", "0")
    assert forms_public._respond({"ok": True}, [lambda: ran.append(2)]) == {"ok": True} and ran == [2]
    forms_public._run_after([lambda: (_ for _ in ()).throw(RuntimeError("x")), lambda: ran.append(3)])
    assert ran == [2, 3]                                                                  # un fallo posterior no impide los siguientes


def test_the_analytics_insert_never_waits_longer_than_its_own_timeout(client, factory, db, monkeypatch):
    """El INSERT de `form_events` (FK a web_forms → FOR KEY SHARE) hacía fila detrás de los reservadores sin límite: ahora tiene su propio `lock_timeout` y, si vence, solo pierde la marca."""
    from sqlalchemy import text
    from app.database import engine
    monkeypatch.setattr(forms_public, "EVENT_LOCK_TIMEOUT_MS", 200)
    ev, f = _open_form(client, factory)
    holder = engine.connect()
    tx = holder.begin()
    holder.execute(text("SELECT id FROM web_forms WHERE id = :i FOR UPDATE"), {"i": f["id"]})
    t0 = time.time()
    try:
        forms_public._record_submit_event(f["id"], "sid-x", None, False)
    finally:
        tx.rollback()
        holder.close()
    assert 0.15 < time.time() - t0 < 3 and db.query(FormEvent).filter_by(form_id=f["id"], sid="sid-x").count() == 0


# ------------------------------------------------------------------ 4) política de reintentos del navegador (templates/form_public.html)
@pytest.mark.skipif(shutil.which("node") is None, reason="sin node")
def test_browser_retry_policy_retries_busy_and_infra_429_but_not_app_errors(tmp_path):
    html = (ROOT / "templates" / "form_public.html").read_text(encoding="utf8")
    start = html.index("const isBusy")
    end = html.index("async function api(")
    js = html[start:end] + '''
const H = (o) => ({ get: (k) => o[k.toLowerCase()] });
const R = (status, headers) => ({ status, headers: H(headers || {}) });
const out = {
  busy503: isBusy(R(503)), busy502: isBusy(R(502)), busy504: isBusy(R(504)),
  cloudRun429: isBusy(R(429, { "content-type": "text/plain; charset=utf-8" })),
  app429: isBusy(R(429, { "content-type": "application/json" })),
  ok200: isBusy(R(200)), conflict409: isBusy(R(409, { "content-type": "application/json" })), notFound404: isBusy(R(404)),
};
const d = (res, a) => { const v = []; for (let i = 0; i < 200; i++) v.push(retryDelay(res, a)); return [Math.min(...v), Math.max(...v)]; };
out.d0 = d(R(503), 0); out.d1 = d(R(503), 1); out.d5 = d(R(503), 5); out.ra = d(R(503, { "retry-after": "30" }), 0); out.raSmall = d(R(503, { "retry-after": "1" }), 4);
console.log(JSON.stringify(out));
'''
    f = tmp_path / "retry.js"
    f.write_text(js, encoding="utf8")
    r = subprocess.run(["node", str(f)], capture_output=True, text=True, encoding="utf8", timeout=30)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["busy503"] and o["busy502"] and o["busy504"] and o["cloudRun429"]
    assert not o["app429"] and not o["ok200"] and not o["conflict409"] and not o["notFound404"]
    assert 1500 <= o["d0"][0] and o["d0"][1] <= 3000                                      # 1,5 s + hasta 1,5 s de azar
    assert 3000 <= o["d1"][0] and o["d1"][1] <= 4500
    assert 12000 <= o["d5"][0] and o["d5"][1] <= 13500                                    # la espera crece hasta 12 s y se queda ahí
    assert o["ra"][0] >= 30000                                                            # respeta Retry-After como mínimo
    assert o["raSmall"][0] >= 12000                                                       # Retry-After pequeño no acorta la espera creciente
    assert "DEADLINE = 150000" in html and "RETRY_WAIT" not in html                       # ~150 s en total, ya no 5 intentos


# ------------------------------------------------------------------ 5) tope activo con envíos simultáneos: integridad intacta, rebote solo 409 o 503 «busy»
def test_default_cap_is_three_per_process(monkeypatch):
    monkeypatch.delenv("FORM_MAX_LOCK_WAITERS", raising=False)
    assert forms_public._max_lock_waiters() == 3
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "abc")
    assert forms_public._max_lock_waiters() == 3                                          # un valor inválido no apaga el tope


def test_simultaneous_submissions_with_the_cap_on_never_oversell_and_retries_fill_exactly_the_capacity(factory, db, monkeypatch):
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "2")
    with TestClient(app, follow_redirects=False) as admin:
        ev = _event(admin, factory)
        f = _create(admin, ev)
        assert _status(admin, ev, f, manual_status="activo", capacity=4).status_code == 200
    payloads = [({"cedula": f"90{n:03d}", "nombres": f"P{n}", "apellidos": "Q", "correo": f"p{n}@example.com"}, f"sid-{n}") for n in range(12)]
    results, gate = {}, threading.Barrier(len(payloads))

    def go(values, sid):
        with TestClient(app, follow_redirects=False) as c:
            gate.wait()
            r = _submit(c, ev, f, values, sid=sid)
            results[sid] = (r.status_code, r.headers.get("retry-after"), r.json())

    threads = [threading.Thread(target=go, args=p) for p in payloads]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 12
    assert sum(1 for code, _, _ in results.values() if code == 200) <= 4                                # nunca más que el cupo
    for code, retry_after, body in results.values():
        assert code in (200, 409, 503)                                                                  # ningún otro código
        if code == 503:
            assert body["busy"] is True and retry_after in ("1", "2", "3")                              # rebote con Retry-After
        if code == 409:
            assert body["stage"] == "closed"
    assert db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").count() == sum(1 for code, _, _ in results.values() if code == 200)
    assert forms_public._lock_waiters == 0                                                              # el contador quedó en cero
    with TestClient(app, follow_redirects=False) as c:                                                  # el navegador reintenta los 503 (misma sid), uno tras otro
        for values, sid in payloads:
            if results[sid][0] == 503:
                r = _submit(c, ev, f, values, sid=sid)
                assert r.status_code in (200, 409)                                                      # sin cola ya no hay rebote
                results[sid] = (r.status_code, None, r.json())
    codes = [code for code, _, _ in results.values()]
    assert codes.count(200) == 4 and codes.count(409) == 8                                              # exactamente el cupo; el resto «cupo lleno»
    assert db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").count() == 4
