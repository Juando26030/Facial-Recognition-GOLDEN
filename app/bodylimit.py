"""Tope de tamaño del cuerpo en las rutas PÚBLICAS (C3 y R3-07, Fase 3).

Starlette lee `request.form()` / `request.body()` entero (y los multipart se copian a disco) ANTES de que corra cualquier comprobación de la ruta: sin tope, una sola
petición anónima de cientos de MB agota memoria o disco. Este middleware ASGI puro (no consume el cuerpo):
  1. rechaza con 413 por `Content-Length` antes de leer nada;
  2. si no hay `Content-Length` (chunked) o miente, cuenta los bytes que va entregando el servidor y corta con 413 al pasarse (`BodyTooLarge`, que main.py convierte en respuesta).
Solo mira métodos que cambian estado y las rutas públicas de `limit_for`; el panel y la carga masiva (autenticados) no se tocan. Nginx / Cloud Run son la primera defensa."""
import os
from typing import Optional

KB, MB = 1024, 1024 * 1024
MSG = "El envío es demasiado grande"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class BodyTooLarge(Exception):
    """El cuerpo pasó el tope de su ruta (se convierte en 413)."""


def limit_for(method: str, path: str) -> Optional[int]:
    """Bytes máximos del cuerpo para esa petición, o None si la ruta no se limita aquí."""
    if method not in _MUTATING:
        return None
    small = _env_int("MAX_BODY_SMALL_BYTES", 64 * KB)
    if path == "/api/public/quote-request":
        return 8 * KB          # «Pide tu cotización» del sitio web: siete campos de texto
    if path.startswith("/f/"):
        return _env_int("MAX_BODY_PUBLIC_BYTES", 36 * MB) if path.endswith("/submit") else _env_int("MAX_BODY_FORM_JSON_BYTES", 256 * KB)
    if path.startswith("/webhooks/"):
        return _env_int("MAX_BODY_WEBHOOK_BYTES", 256 * KB)
    if path.startswith("/api/aceptar/"):
        return small if path.endswith("/check") else _env_int("MAX_BODY_ACEPTAR_BYTES", 10 * MB)      # la selfie pesa hasta 8 MB
    if path.startswith(("/login", "/olvide-contrasena", "/restablecer/")):
        return small
    return None


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = limit_for(scope.get("method", "GET"), scope.get("path", ""))
        if limit is None:
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers") or []:
            if k == b"content-length":
                if v.isdigit() and int(v) > limit:
                    return await self._reject(send)
                break
        seen = 0

        async def counting_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body") or b"")
                if seen > limit:
                    raise BodyTooLarge()
            return msg

        await self.app(scope, counting_receive, send)

    @staticmethod
    async def _reject(send):
        body = ('{"detail":"%s"}' % MSG).encode("utf-8")
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
