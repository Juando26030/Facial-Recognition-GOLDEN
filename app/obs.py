"""Observabilidad: logs estructurados en JSON (formato que Cloud Logging entiende), identificador por petición y manejo global de errores.

  * Cada línea de log es un JSON en stdout con `severity`, `message`, `time`, `request_id`, y —en las líneas de petición— `httpRequest` y
    `logging.googleapis.com/trace` (si llega `X-Cloud-Trace-Context`).
  * `X-Request-ID`: se respeta el que llegue (si es razonable) o se genera; siempre vuelve en la respuesta y en cada log de esa petición.
  * PROHIBIDO registrar datos personales. Se aplica en DOS capas: (1) el middleware nunca registra cuerpos, cabeceras ni cookies, y enmascara
    tokens/cédulas dentro de la ruta; (2) el formateador pasa TODO mensaje y traza por `mask_pii`, venga de donde venga (uvicorn, librerías,
    excepciones): correos, teléfonos, números largos (cédulas), tokens y vectores de encodings quedan enmascarados. Los NOMBRES no se pueden
    reconocer con una expresión regular: por eso el código de la aplicación no debe incluirlos en los mensajes (regla en docs/observabilidad.md)."""
import contextvars
import json
import logging
import os
import re
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
trace_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_FLOAT_VECTOR = re.compile(r"\[\s*-?\d+\.\d+(\s*,\s*-?\d+\.\d+){7,}\s*\]")       # un encoding facial (128 decimales)
_LONG_NUMBER = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{5,}\d(?![\w])")            # cédulas, teléfonos
_TOKEN = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{28,}(?![\w-])")                    # tokens de enlaces, hashes, llaves
_SENSITIVE_QUERY = re.compile(r"([?&](?:t|i|k|d|code|token|key|access_token|password)=)[^&\s]*", re.I)
_PATH_TOKEN = re.compile(r"(/(?:b|c|r)/)[^/\s?]+")
_PATH_ID = re.compile(r"(?<=/)\d{5,}(?=/|\?|$)")


def mask_pii(text: Any) -> str:
    """Enmascara correos, vectores de encodings, números largos (cédulas/teléfonos) y tokens dentro de un texto."""
    s = str(text)
    s = _FLOAT_VECTOR.sub("[encoding]", s)
    s = _EMAIL.sub(lambda m: m.group(0)[0] + "***@***", s)
    s = _LONG_NUMBER.sub(_mask_number, s)
    return _TOKEN.sub("[token]", s)


def _mask_number(match: "re.Match") -> str:
    """Enmascara cédulas y teléfonos (6+ dígitos) dejando las últimas 2 cifras; no toca fechas ISO ni números cortos como «HTTP/1.1 302»."""
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) or len(digits) < 6 or (len(digits) < 7 and re.search(r"\D", raw)):
        return raw
    return "***" + digits[-2:]


def mask_url(url: str) -> str:
    """Ruta + query sin tokens ni cédulas: `/b/<token>` -> `/b/[token]`, `?t=...` -> `?t=[x]`, `/api/users/1016100329` -> `/api/users/***`."""
    url = _SENSITIVE_QUERY.sub(r"\1[x]", url)
    url = _PATH_TOKEN.sub(r"\1[token]", url)
    return _PATH_ID.sub("***", url)


def mask_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    if ":" in ip:
        return ip.rsplit(":", 1)[0] + ":*"
    return ip.rsplit(".", 1)[0] + ".*"


class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro, con los nombres de campo que Cloud Logging reconoce."""

    _LEVELS = {"WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "CRITICAL", "INFO": "INFO", "DEBUG": "DEBUG"}

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "severity": self._LEVELS.get(record.levelname, "DEFAULT"),
            "message": mask_pii(record.getMessage()),
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        trace = trace_var.get()
        if trace:
            entry["logging.googleapis.com/trace"] = trace
        http = getattr(record, "http_request", None)
        if http:
            entry["httpRequest"] = http
        if record.exc_info:
            entry["stack_trace"] = mask_pii("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> None:
    """Deja el log en JSON a stdout para toda la app (y para uvicorn/gunicorn). Idempotente."""
    root = logging.getLogger()
    if any(getattr(h, "_golden_json", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._golden_json = True          # type: ignore[attr-defined]
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    for name in ("uvicorn", "uvicorn.error", "gunicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False        # el log de peticiones lo escribe RequestLogMiddleware (ya enmascarado)
    logging.getLogger("uvicorn.access").disabled = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def _clean_request_id(raw: Optional[str]) -> str:
    return raw if raw and re.fullmatch(r"[A-Za-z0-9._-]{6,64}", raw) else new_request_id()


def _trace_from(header: Optional[str]) -> Optional[str]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if header and project:
        return f"projects/{project}/traces/{header.split('/')[0]}"
    return None


class RequestLogMiddleware:
    """Middleware ASGI puro (sin BaseHTTPMiddleware: no crea tareas extra ni interfiere con los hilos). Pone el `X-Request-ID`, mide la
    latencia y escribe UNA línea de log por petición. No registra cuerpos, cabeceras ni cookies. Las peticiones a /health y /healthz no se registran."""

    def __init__(self, app: ASGIApp, on_5xx=None) -> None:
        self.app, self.on_5xx = app, on_5xx
        self.log = logging.getLogger("golden.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        rid = _clean_request_id(headers.get("x-request-id"))
        tokens = (request_id_var.set(rid), trace_var.set(_trace_from(headers.get("x-cloud-trace-context"))))
        scope.setdefault("state", {})["request_id"] = rid
        start, status, backpressure = time.perf_counter(), 500, False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, backpressure
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = rid
                # «ocupado, reintenta» (forms_public._busy_response, marca interna X-Golden-Busy): contrapresión esperada, no un error. NO basta con `Retry-After`: el 503 de «base de datos
                # caída» (main.py) también lo lleva y ese SÍ es un error real.
                backpressure = status == 503 and out.get("x-golden-busy") == "1"
                if "x-golden-busy" in out:
                    del out["x-golden-busy"]                         # la marca es solo para este middleware: no sale al cliente
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in ("/health", "/healthz"):
                query = scope.get("query_string", b"").decode("latin-1")
                client = scope.get("client")
                http = {"requestMethod": scope.get("method"), "requestUrl": mask_url(path + ("?" + query if query else "")), "status": status,
                        "latency": f"{time.perf_counter() - start:.3f}s", "remoteIp": mask_ip(headers.get("cf-connecting-ip") or (client[0] if client else None))}
                real_5xx = status >= 500 and not backpressure
                self.log.log(logging.ERROR if real_5xx else logging.INFO, "%s %s -> %s", http["requestMethod"], http["requestUrl"], status, extra={"http_request": http})
                if real_5xx and self.on_5xx:                 # la contrapresión (503 + Retry-After) ni va como ERROR ni enciende «Estado del sistema»
                    self.on_5xx(rid, http["requestMethod"], mask_url(path), status)
            request_id_var.reset(tokens[0])
            trace_var.reset(tokens[1])
