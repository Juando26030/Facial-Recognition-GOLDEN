"""C3 / R3-07 (Fase 3): tope de cuerpo en las rutas públicas. ASGI puro: no necesita base de datos ni la app completa."""
import asyncio
from pathlib import Path

from app import bodylimit

ROOT = Path(__file__).resolve().parent.parent


def test_limit_for_rules():
    f = bodylimit.limit_for
    assert f("GET", "/f/1/x/submit") is None                       # solo métodos que cambian estado
    assert f("POST", "/api/users") is None                         # el panel autenticado no se limita aquí
    assert f("POST", "/f/1/x/submit") == 36 * 1024 * 1024
    assert f("POST", "/f/1/x/gate") == 256 * 1024 and f("POST", "/f/1/x/pay/confirm") == 256 * 1024
    assert f("POST", "/webhooks/wompi") == 256 * 1024
    assert f("POST", "/api/aceptar/abc") == 10 * 1024 * 1024 and f("POST", "/api/aceptar/abc/check") == 64 * 1024
    assert f("POST", "/login") == f("POST", "/olvide-contrasena") == f("POST", "/restablecer/tok") == 64 * 1024


def _run(headers, chunks, path="/f/1/x/submit", method="POST"):
    """Devuelve (estado de la respuesta, ¿llegó la app a leer todo el cuerpo?)."""
    sent, state = [], {"read": 0}

    async def app(scope, receive, send):
        try:
            while True:
                m = await receive()
                state["read"] += len(m.get("body") or b"")
                if not m.get("more_body"):
                    break
        except bodylimit.BodyTooLarge:
            await send({"type": "http.response.start", "status": 413, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    queue = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)] or [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return queue.pop(0)

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": method, "path": path, "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(bodylimit.BodyLimitMiddleware(app)(scope, receive, send))
    return sent[0]["status"], state["read"]


def test_content_length_over_limit_is_413_without_reading():
    assert _run({"content-length": str(40 * 1024 * 1024)}, [b"x"]) == (413, 0)
    assert _run({"content-length": str(300 * 1024)}, [b"x"], path="/f/1/x/gate")[0] == 413
    assert _run({"content-length": "70000"}, [b"x"], path="/login")[0] == 413
    assert _run({"content-length": "300000"}, [b"x"], path="/webhooks/wompi")[0] == 413


def test_normal_bodies_and_other_routes_pass():
    assert _run({"content-length": "100"}, [b"x" * 100], path="/f/1/x/gate") == (200, 100)
    assert _run({"content-length": str(40 * 1024 * 1024)}, [b"x"], path="/api/bulk") [0] == 200      # ruta autenticada: sin tope aquí
    assert _run({}, [b"x"], method="GET")[0] == 200


def test_chunked_or_lying_content_length_is_cut_while_reading():
    chunks = [b"x" * 40000] * 3                                    # 120 kB sin Content-Length en una ruta de 64 kB
    assert _run({}, chunks, path="/login")[0] == 413
    assert _run({"content-length": "10"}, chunks, path="/login")[0] == 413      # miente
    assert _run({}, [b"x" * 1000], path="/login")[0] == 200


def test_main_wires_the_middleware_and_nginx_has_public_limit():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "app.add_middleware(bodylimit.BodyLimitMiddleware)" in main and "exception_handler(bodylimit.BodyTooLarge)" in main
    ng = (ROOT / "deploy/nginx-golden.conf").read_text(encoding="utf-8")
    assert "client_max_body_size 40M" in ng and "f/|webhooks/" in ng
