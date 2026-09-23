"""Seguridad de cuentas (Sprint 4): límite de intentos, política de contraseña y tokens de restablecimiento.

Todo el estado vive en Postgres (`rate_limit_events`, `password_reset_tokens`), no en memoria, para que valga con
varios procesos/workers y sobreviva a un reinicio."""
import hashlib
import math
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.models import PasswordResetToken, RateLimitEvent

LOGIN_MAX_FAILS = 5          # intentos fallidos por usuario dentro de la ventana
LOGIN_MAX_FAILS_PER_IP = 20  # tope por IP (cubre a quien prueba muchos usuarios distintos)
LOGIN_WINDOW = timedelta(minutes=15)
RESET_MAX_REQUESTS = 5       # solicitudes de "olvidé mi contraseña" por usuario / por IP en la ventana
RESET_WINDOW = timedelta(hours=1)
RESET_TOKEN_TTL = timedelta(minutes=60)
MIN_PASSWORD_LENGTH = 8


def client_ip(request: Request) -> str:
    """IP real del visitante detrás de Cloudflare/Nginx (cabeceras que ellos ponen)."""
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


def record_event(db: Session, kind: str, key: str, ip: Optional[str]) -> None:
    db.add(RateLimitEvent(kind=kind, key=key.lower(), ip=ip))
    # Limpieza oportunista: nada de esto se necesita pasado un día.
    db.query(RateLimitEvent).filter(RateLimitEvent.created_at < datetime.utcnow() - timedelta(days=1)).delete()
    db.commit()


def clear_events(db: Session, kind: str, key: str) -> None:
    db.query(RateLimitEvent).filter(RateLimitEvent.kind == kind, RateLimitEvent.key == key.lower()).delete()
    db.commit()


def minutes_locked(db: Session, kind: str, key: Optional[str], ip: Optional[str], max_by_key: int, max_by_ip: int, window: timedelta) -> int:
    """Minutos que faltan para poder volver a intentar (0 = no está bloqueado). Bloquea si `key` acumuló
    `max_by_key` eventos dentro de la ventana, o si `ip` acumuló `max_by_ip`."""
    since = datetime.utcnow() - window
    locks = []
    for value, column, limit in ((key.lower() if key else None, RateLimitEvent.key, max_by_key), (ip, RateLimitEvent.ip, max_by_ip)):
        if not value:
            continue
        times = [r.created_at for r in db.query(RateLimitEvent.created_at).filter(
            RateLimitEvent.kind == kind, column == value, RateLimitEvent.created_at > since,
        ).order_by(RateLimitEvent.created_at.desc()).limit(limit)]
        if len(times) >= limit:
            # Se libera cuando el evento más viejo de los últimos `limit` sale de la ventana.
            locks.append((times[-1] + window) - datetime.utcnow())
    if not locks:
        return 0
    return max(1, math.ceil(max(locks).total_seconds() / 60))


def login_minutes_locked(db: Session, username: str, ip: str) -> int:
    return minutes_locked(db, "login_fail", username, ip, LOGIN_MAX_FAILS, LOGIN_MAX_FAILS_PER_IP, LOGIN_WINDOW)


def enforce_public_limit(db: Session, request: Request, kind: str, key: str, max_hits: int, window: timedelta) -> None:
    """Para endpoints públicos (ej. consulta de certificados): registra la consulta y responde 429 si esa IP
    ya hizo `max_hits` para esa clave dentro de la ventana."""
    ip = client_ip(request)
    if _public_locked(db, kind, key, ip, max_hits, window):
        raise HTTPException(status_code=429, detail="Demasiadas consultas seguidas — espera unos minutos e intenta de nuevo.")
    record_event(db, kind, key, ip)


def _public_locked(db: Session, kind: str, key: str, ip: str, max_hits: int, window: timedelta) -> bool:
    since = datetime.utcnow() - window
    hits = db.query(RateLimitEvent).filter(
        RateLimitEvent.kind == kind, RateLimitEvent.key == key.lower(), RateLimitEvent.ip == ip, RateLimitEvent.created_at > since,
    ).count()
    return hits >= max_hits


def password_problem(password: str) -> Optional[str]:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(db: Session, staff_id: int) -> str:
    """Crea un enlace nuevo e invalida los anteriores sin usar de esa cuenta. Devuelve el token en claro
    (solo se envía por correo; en la base queda el hash)."""
    now = datetime.utcnow()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.staff_user_id == staff_id, PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now})
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(staff_user_id=staff_id, token_hash=_hash_token(token), expires_at=now + RESET_TOKEN_TTL))
    db.commit()
    return token


def find_valid_reset_token(db: Session, token: str) -> Optional[PasswordResetToken]:
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == _hash_token(token)).first()
    if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
        return None
    return row
