"""Diagnóstico de esperas (D2.3): dónde se pierde el tiempo de una petición — cola del pool de hilos, cola del pool de conexiones, tiempo en la base, o fuera de la app.

APAGADO por defecto y sin costo cuando está apagado. Dos interruptores independientes (variables de entorno):
  SERVER_TIMING=1      la respuesta lleva la cabecera `Server-Timing` (app, thread, pool, db, queries, estado del pool de hilos) SOLO si la petición trae `X-Timing-Token`
                       con el token derivado de OPS_TOKEN (`token()`): el generador de carga lo calcula igual; nadie más ve estos números.
  LOG_SLOW_WAITS_MS=N  una línea de log (`golden.timing`) cuando una petición esperó ≥ N ms por un hilo o por una conexión.
Nada de esto guarda ni muestra datos de personas: solo milisegundos, contadores y la ruta enmascarada (app/obs.py)."""
import hashlib
import hmac
import logging
import os
import time
from contextvars import ContextVar
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders

log = logging.getLogger("golden.timing")
_stats: ContextVar[Optional[dict]] = ContextVar("golden_timing", default=None)


def enabled() -> bool:
    return os.getenv("SERVER_TIMING") == "1"


def slow_ms() -> float:
    try:
        return float(os.getenv("LOG_SLOW_WAITS_MS") or 0)
    except ValueError:
        return 0.0


def active() -> bool:
    return enabled() or slow_ms() > 0


def token() -> str:
    """Token de la cabecera `X-Timing-Token`: derivado de OPS_TOKEN (sin OPS_TOKEN no hay token y la cabecera nunca sale). Misma fórmula en scripts/load_cfg.py."""
    secret = os.getenv("OPS_TOKEN", "")
    return hmac.new(secret.encode(), b"golden-server-timing", hashlib.sha256).hexdigest()[:20] if secret else ""


def add(name: str, ms: float, count: int = 0) -> None:
    d = _stats.get()
    if d is not None:
        d[name] = d.get(name, 0.0) + ms
        if count:
            d["queries"] = d.get("queries", 0) + count


async def run(fn, *args, **kwargs):
    """Como `run_in_threadpool`, midiendo cuánto ESPERÓ el turno de un hilo (cola del pool de hilos). Sin diagnóstico activo es exactamente `run_in_threadpool`."""
    if _stats.get() is None:
        return await run_in_threadpool(fn, *args, **kwargs)
    t0 = time.perf_counter()

    def inner():
        add("thread", (time.perf_counter() - t0) * 1000)
        return fn(*args, **kwargs)

    return await run_in_threadpool(inner)


def install_db(engine) -> None:
    """Mide la espera de conexión del pool y el tiempo/número de consultas (solo si el diagnóstico está activo)."""
    from sqlalchemy import event
    pool, original = engine.pool, engine.pool.connect

    def timed_connect():
        t0 = time.perf_counter()
        try:
            return original()
        finally:
            add("pool", (time.perf_counter() - t0) * 1000)

    pool.connect = timed_connect

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info["_t0"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        add("db", (time.perf_counter() - conn.info.pop("_t0", time.perf_counter())) * 1000, count=1)


def _gauge() -> str:
    try:
        import anyio.to_thread
        s = anyio.to_thread.current_default_thread_limiter().statistics()
        return f"borrowed={s.borrowed_tokens}/{int(s.total_tokens)} waiting={s.tasks_waiting}"
    except Exception:  # noqa: BLE001
        return "n/a"


def header_value(stats: dict) -> str:
    return (f'app;dur={stats.get("app", 0):.1f}, thread;dur={stats.get("thread", 0):.1f}, pool;dur={stats.get("pool", 0):.1f}, db;dur={stats.get("db", 0):.1f}, '
            f'queries;desc="{stats.get("queries", 0)}", threads;desc="{_gauge()}"')


class TimingMiddleware:
    """ASGI puro: reparte las esperas de cada petición (contextvar), agrega `Server-Timing` (con token) y registra las esperas lentas. Solo se monta si `active()`."""

    def __init__(self, app):
        self.app = app
        self.emit = enabled()
        self.slow = slow_ms()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        stats: dict = {}
        marker = _stats.set(stats)
        t0 = time.perf_counter()
        status = {"code": 0}
        want = False
        if self.emit:
            secret = token()
            want = bool(secret) and hmac.compare_digest(Headers(scope=scope).get("x-timing-token", ""), secret)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                stats["app"] = (time.perf_counter() - t0) * 1000
                if want:
                    MutableHeaders(scope=message)["Server-Timing"] = header_value(stats)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _stats.reset(marker)
            waited = max(stats.get("thread", 0.0), stats.get("pool", 0.0))
            if self.slow and waited >= self.slow:
                from app.obs import mask_url
                log.warning("espera lenta %s %s -> %s app=%.0fms thread=%.0fms pool=%.0fms db=%.0fms q=%s hilos[%s]", scope.get("method"), mask_url(scope.get("path", "")),
                            status["code"], stats.get("app", (time.perf_counter() - t0) * 1000), stats.get("thread", 0), stats.get("pool", 0), stats.get("db", 0),
                            stats.get("queries", 0), _gauge())
