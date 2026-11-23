"""POST /api/public/quote-request: recibe el formulario «Pide tu cotización» del sitio web corporativo (golden-eventos.com) y lo manda por correo.

Pública a propósito (sin sesión ni cookies). Lo llama el sitio estático por una reescritura de Firebase Hosting hacia `golden-publico`. Sin tabla: el correo es el registro.
Variables: QUOTE_TO_EMAIL (destinatario, obligatoria para enviar), QUOTE_ALLOWED_ORIGINS (orígenes del sitio, separados por comas; vacía = solo mismo origen)."""
import logging
import os

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import jobs, quote_core
from app.database import get_db
from app.security import client_ip
from app.ttlcache import SlidingLimiter

router = APIRouter()
log = logging.getLogger("quote")
_limiter = SlidingLimiter()


def _max(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _reply(request: Request, body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=quote_core.cors_headers(request.headers.get("origin")))


@router.options("/api/public/quote-request")
def quote_preflight(request: Request):
    return JSONResponse({}, status_code=204 if quote_core.origin_allowed(request.headers.get("origin")) else 403, headers=quote_core.cors_headers(request.headers.get("origin")))


@router.post("/api/public/quote-request")
def quote_request(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    if payload.get("website"):          # campo trampa: un robot lo llena; se responde igual que si todo saliera bien y no se hace nada
        return _reply(request, {"ok": True})
    ip = client_ip(request)
    if not _limiter.hit(("ip", ip), _max("QUOTE_IP_MAX_PER_10MIN", 5), 600.0) or not _limiter.hit("all", _max("QUOTE_MAX_PER_HOUR", 200), 3600.0):
        return _reply(request, {"detail": quote_core.MSG_TOO_MANY}, 429)
    clean, errors = quote_core.validate(payload)
    if errors:
        return _reply(request, {"detail": "Revise los datos del formulario", "errors": errors}, 400)
    if not (os.getenv("QUOTE_TO_EMAIL") or "").strip():
        log.error("QUOTE_TO_EMAIL sin configurar")
        return _reply(request, {"detail": quote_core.MSG_UNAVAILABLE}, 503)
    jobs.enqueue(db, quote_core.MAIL_KIND, {"quote": quote_core.build_mail(clean)}, max_attempts=4)
    db.commit()
    jobs.kick()
    return _reply(request, {"ok": True})
