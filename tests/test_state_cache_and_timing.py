"""A) caché stale-while-revalidate que nunca bloquea, B) submit con UNA sola espera de hilo, C) diagnóstico de esperas (Server-Timing / log) solo con token o variable,
D) `s-maxage` público SOLO para el estado anónimo y solo con FORM_STATE_CDN_SECONDS > 0."""
import asyncio
import inspect
import logging
import threading
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient as StarletteClient

from app import formsvc, timing
from app.routers import forms_public
from app.ttlcache import TTLCache
from scripts.load_cfg import timing_token
from tests.test_form_load_path import _open_form
from tests.test_forms import _url


# ------------------------------------------------------------------ A) stale-while-revalidate
def test_ttlcache_peek_reports_fresh_stale_and_nothing():
    c = TTLCache(0.05)
    assert c.peek("k", 5) == (None, None)
    c.set("k", 1)
    assert c.peek("k", 5) == (1, "fresh")
    time.sleep(0.08)
    assert c.peek("k", 5) == (1, "stale")
    assert c.peek("k", 0.0) == (None, None)                                 # fuera del margen: se descarta
    c.ttl = 0
    c.set("k", 2)
    assert c.peek("k", 5) == (None, None)                                   # caché apagada: nunca «stale»


def test_stale_value_is_served_at_once_and_only_one_background_refresh_runs(monkeypatch):
    cache = TTLCache(0.05)
    cache.set(("s", 1), {"v": "viejo"})
    time.sleep(0.08)
    calls, gate = [], threading.Event()

    def slow():
        calls.append(1)
        gate.wait(5)
        return {"v": "nuevo"}

    async def burst():
        t0 = time.perf_counter()
        got = await asyncio.gather(*[forms_public._cached_async(cache, ("s", 1), slow) for _ in range(30)])
        return got, time.perf_counter() - t0

    got, took = asyncio.run(burst())
    assert all(g == {"v": "viejo"} for g in got) and took < 1                # nadie esperó la recarga (que sigue bloqueada)
    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.01)
    assert len(calls) == 1                                                  # UNA recarga para 30 peticiones
    gate.set()
    deadline = time.time() + 2
    while cache.peek(("s", 1))[0] != {"v": "nuevo"} and time.time() < deadline:
        time.sleep(0.01)
    assert cache.peek(("s", 1)) == ({"v": "nuevo"}, "fresh") and not forms_public._refreshing


def test_a_failed_background_refresh_keeps_serving_the_old_value():
    cache = TTLCache(0.05)
    cache.set(("s", 2), {"v": "viejo"})
    time.sleep(0.08)

    def boom():
        raise RuntimeError("base caída")

    assert asyncio.run(forms_public._cached_async(cache, ("s", 2), boom)) == {"v": "viejo"}
    time.sleep(0.2)
    assert cache.peek(("s", 2), 5)[0] == {"v": "viejo"} and not forms_public._refreshing


def test_concurrent_misses_share_one_load_without_a_lock_inside_the_pool():
    cache, calls = TTLCache(60), []

    def load():
        calls.append(1)
        time.sleep(0.2)
        return {"v": 1}

    async def burst():
        return await asyncio.gather(*[forms_public._cached_async(cache, ("m", 1), load) for _ in range(20)])

    assert all(r == {"v": 1} for r in asyncio.run(burst())) and len(calls) == 1


# ------------------------------------------------------------------ B) submit sin Depends(get_db): una sola espera de hilo
def test_submit_has_no_db_dependency_and_hops_to_a_thread_once(client, factory, monkeypatch):
    assert "db" not in inspect.signature(forms_public.submit).parameters
    ev, f = _open_form(client, factory)
    hops = []
    real = timing.run

    async def counting(fn, *a, **k):
        hops.append(getattr(fn, "__name__", str(fn)))
        return await real(fn, *a, **k)

    monkeypatch.setattr(forms_public.timing, "run", counting)
    r = client.post(f"{_url(ev, f)}/submit", json={"values": {"cedula": "1098000111", "nombres": "A", "apellidos": "B", "correo": "a@example.com", "tel": "3001234567"}, "sid": "sidB1"})
    assert r.status_code == 200, r.text
    assert hops == ["_submit_sync"]                                         # antes: una espera para crear la sesión + otra para el envío


# ------------------------------------------------------------------ C) Server-Timing y log de esperas: solo con variable y token
def _mini_app():
    async def ok(request):
        timing.add("pool", 40)
        timing.add("db", 5, count=2)
        return PlainTextResponse("ok")

    return timing.TimingMiddleware(Starlette(routes=[Route("/x/{n}", ok)]))


def test_server_timing_only_with_the_variable_and_the_right_token(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "token-de-prueba")
    monkeypatch.setenv("SERVER_TIMING", "1")
    c = StarletteClient(_mini_app())
    tok = timing.token()
    assert tok and tok == timing_token()                                    # la misma fórmula en app/timing.py y scripts/load_cfg.py
    assert "server-timing" not in c.get("/x/1").headers                     # sin token
    assert "server-timing" not in c.get("/x/1", headers={"X-Timing-Token": "otro"}).headers
    h = c.get("/x/1", headers={"X-Timing-Token": tok}).headers["server-timing"]
    assert h.startswith("app;dur=") and "pool;dur=40.0" in h and 'queries;desc="2"' in h and "threads;desc=" in h
    monkeypatch.setenv("SERVER_TIMING", "0")                                # apagado: aunque el token sea correcto
    assert "server-timing" not in StarletteClient(_mini_app()).get("/x/1", headers={"X-Timing-Token": tok}).headers


def test_server_timing_never_comes_out_without_ops_token(monkeypatch):
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    monkeypatch.setenv("SERVER_TIMING", "1")
    assert timing.token() == "" and timing_token() == ""
    assert "server-timing" not in StarletteClient(_mini_app()).get("/x/1", headers={"X-Timing-Token": ""}).headers


def test_slow_wait_log_only_above_the_threshold_and_with_a_masked_path(monkeypatch, caplog):
    monkeypatch.setenv("SERVER_TIMING", "0")
    monkeypatch.setenv("LOG_SLOW_WAITS_MS", "30")
    with caplog.at_level(logging.WARNING, logger="golden.timing"):
        StarletteClient(_mini_app()).get("/x/1098000111")                   # espera de conexión de 40 ms ≥ 30
    lines = [r.getMessage() for r in caplog.records if r.name == "golden.timing"]
    assert len(lines) == 1 and "espera lenta" in lines[0] and "pool=40ms" in lines[0] and "1098000111" not in lines[0]
    caplog.clear()
    monkeypatch.setenv("LOG_SLOW_WAITS_MS", "500")
    with caplog.at_level(logging.WARNING, logger="golden.timing"):
        StarletteClient(_mini_app()).get("/x/1")
    assert not [r for r in caplog.records if r.name == "golden.timing"]


def test_diagnostics_are_off_by_default(monkeypatch):
    monkeypatch.delenv("SERVER_TIMING", raising=False)
    monkeypatch.delenv("LOG_SLOW_WAITS_MS", raising=False)
    assert not timing.active()


def test_locust_parses_server_timing_and_the_outside_the_app_share():
    import pathlib
    src = (pathlib.Path(__file__).parent / "load" / "locustfile.py").read_text(encoding="utf8")
    ns: dict = {}
    start = src.index("def _server_app_ms")
    exec(src[start:src.index("@events.request.add_listener")], ns)         # solo la función pura
    f = ns["_server_app_ms"]
    assert f('app;dur=12.5, thread;dur=1.0, queries;desc="2"') == 12.5 and f("") is None and f("thread;dur=3") is None and f("app;dur=x") is None


# ------------------------------------------------------------------ D) s-maxage público SOLO en el estado anónimo
def _state_url(ev, f):
    return f"{_url(ev, f)}/state"


def test_anonymous_state_gets_s_maxage_only_when_enabled_and_carries_nothing_per_user(client, factory, monkeypatch):
    ev, f = _open_form(client, factory)
    monkeypatch.setattr(formsvc.public_cache, "ttl", 60)
    client.cookies.clear()
    monkeypatch.delenv("FORM_STATE_CDN_SECONDS", raising=False)
    r = client.get(_state_url(ev, f))
    assert r.status_code == 200 and "s-maxage" not in r.headers.get("cache-control", "")          # apagado por defecto
    monkeypatch.setenv("FORM_STATE_CDN_SECONDS", "4")
    r = client.get(_state_url(ev, f))
    assert r.headers["cache-control"] == "public, max-age=0, s-maxage=4" and r.json()["stage"] == "form"
    assert "set-cookie" not in r.headers and "vary" not in r.headers or "cookie" not in r.headers["vary"].lower()
    d = r.json()
    assert d["prefill"] == {} and d["readonly"] == [] and d["is_test"] is False                     # nada de una persona concreta
    other = client.get(_state_url(ev, f), headers={"X-Forwarded-For": "9.9.9.9", "User-Agent": "otro"})
    assert other.json() == d                                                                        # el mismo cuerpo para cualquiera
    monkeypatch.setenv("FORM_STATE_CDN_SECONDS", "99")
    assert client.get(_state_url(ev, f)).headers["cache-control"].endswith("s-maxage=10")          # tope de 10 s
    monkeypatch.setenv("FORM_STATE_CDN_SECONDS", "abc")
    assert "s-maxage" not in client.get(_state_url(ev, f)).headers.get("cache-control", "")


@pytest.mark.parametrize("params,headers", [
    ({"k": "x"}, {}), ({"i": "x"}, {}), ({"t": "x"}, {}), ({"utm": "1"}, {}),                       # parámetros de cualquier tipo
    ({}, {"Cookie": "__session=abc"}), ({}, {"Authorization": "Bearer x"}),                         # sesión / credenciales
])
def test_state_with_params_cookie_or_session_is_never_publicly_cached(client, factory, monkeypatch, params, headers):
    ev, f = _open_form(client, factory)
    monkeypatch.setattr(formsvc.public_cache, "ttl", 60)
    monkeypatch.setenv("FORM_STATE_CDN_SECONDS", "4")
    client.cookies.clear()
    r = client.get(_state_url(ev, f), params=params, headers=headers)
    assert "s-maxage" not in r.headers.get("cache-control", "") and "public" not in r.headers.get("cache-control", "")


def test_logged_in_session_state_is_not_publicly_cached(client, factory, monkeypatch):
    ev, f = _open_form(client, factory)                                    # el cliente de pruebas queda con la cookie de sesión tras el login previo
    monkeypatch.setenv("FORM_STATE_CDN_SECONDS", "4")
    monkeypatch.setattr(formsvc.public_cache, "ttl", 60)
    client.cookies.set("__session", "cualquiera")
    assert "s-maxage" not in client.get(_state_url(ev, f)).headers.get("cache-control", "")
