"""Enlaces de solo lectura a las estadísticas (evento o formulario). Ver app/routers/stats_links.py.

- El token es aleatorio de 256 bits (`secrets.token_urlsafe(32)`); en la base solo queda su SHA-256. Se muestra UNA vez, al crearlo.
- Vence a los `days` elegidos (1 a 30, por defecto 7) y se puede revocar antes. Un enlace vencido o revocado responde igual que uno que no existe.
- Da acceso SOLO a agregados (conteos y gráficos): ninguna persona, ninguna descarga, ninguna acción.
"""
import hashlib
import re
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import StatsLink
from app.timeutil import utcnow

MAX_DAYS = 30
DEFAULT_DAYS = 7
MAX_ACTIVE_PER_EVENT = 30
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,64}$")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clamp_days(days) -> int:
    try:
        d = int(days)
    except (TypeError, ValueError):
        d = DEFAULT_DAYS
    return max(1, min(MAX_DAYS, d))


def create(db: Session, *, scope: str, event, form, staff, days, label: str = "") -> tuple:
    """Devuelve (token en claro, fila). El token en claro no se guarda en ningún lado."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    link = StatsLink(token_hash=hash_token(token), scope=scope, event_id=event.id, form_id=form.id if form is not None else None, tenant_id=event.tenant_id,
                     label=(label or "").strip()[:80] or None, created_by_staff_id=staff.id, created_at=now, expires_at=now + timedelta(days=clamp_days(days)))
    db.add(link)
    db.flush()
    return token, link


def resolve(db: Session, token: str, scope: str) -> Optional[StatsLink]:
    """El enlace vigente de ese alcance, o None (no existe, venció o se revocó: todo se ve igual)."""
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    link = db.query(StatsLink).filter(StatsLink.token_hash == hash_token(token), StatsLink.scope == scope).first()
    if link is None or link.revoked_at is not None or link.expires_at <= utcnow():
        return None
    return link


def active_for_event(db: Session, event_id: int) -> list:
    now = utcnow()
    return db.query(StatsLink).filter(StatsLink.event_id == event_id, StatsLink.revoked_at.is_(None), StatsLink.expires_at > now).order_by(StatsLink.id.desc()).all()


def revoke(db: Session, link: StatsLink) -> None:
    if link.revoked_at is None:
        link.revoked_at = utcnow()
