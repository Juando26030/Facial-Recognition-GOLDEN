"""Pantalla de ingreso para TV (Fase 8, pieza 1): lo que se proyecta en un televisor durante el evento. SOLO lectura y SOLO agregados + los últimos ingresos con
nombre y empresa (nunca cédula, correo, teléfono ni foto); la persona de prueba no cuenta. El resultado se guarda `CACHE_S` segundos en memoria: con N pantallas y N
sondeos el costo en la base es UNA consulta por evento cada pocos segundos (nada frecuente toca la base sin caché)."""
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app import testperson
from app.models import AccessLog, Event, EventAttendee, User
from app.timeutil import to_local, utcnow
from app.ttlcache import TTLCache

CACHE_S = 5
RECENT_N = 12
_cache = TTLCache(CACHE_S)


def short_name(first, last) -> str:
    """«Juan P.»: nombre y la inicial del apellido (no se proyecta el nombre completo de nadie en una pantalla pública)."""
    f = " ".join(str(first or "").split())
    la = " ".join(str(last or "").split())
    return (f + (" " + la[0].upper() + "." if la else "")).strip() or "Asistente"


def _real(query):
    return query.filter(func.upper(AccessLog.user_id) != testperson.TEST_ID)


def compute(db: Session, event: Event) -> dict:
    base = _real(db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado"))
    registered = base.with_entities(func.count(distinct(AccessLog.user_id))).scalar() or 0
    attendees = db.query(func.count(EventAttendee.id)).filter(EventAttendee.event_id == event.id, func.upper(EventAttendee.user_id) != testperson.TEST_ID).scalar() or 0
    expected = max(int(attendees), int(registered))
    rows = (base.join(User, (User.id == AccessLog.user_id) & (User.tenant_id == AccessLog.tenant_id))
            .with_entities(AccessLog.user_id, AccessLog.timestamp, User.first_name, User.last_name, User.entity)
            .order_by(AccessLog.timestamp.desc(), AccessLog.id.desc()).limit(RECENT_N * 4).all())
    recent, seen = [], set()
    for uid, ts, first, last, entity in rows:
        if uid in seen:
            continue
        seen.add(uid)
        recent.append({"name": short_name(first, last), "entity": " ".join(str(entity or "").split())[:60], "at": to_local(ts).strftime("%I:%M %p").lstrip("0") if ts else ""})
        if len(recent) >= RECENT_N:
            break
    pct = int(round(100 * registered / expected)) if expected else 0
    return {"event_name": event.name, "registered": int(registered), "expected": expected, "percent": min(pct, 100), "recent": recent,
            "updated_at": to_local(utcnow()).strftime("%I:%M:%S %p").lstrip("0")}


def snapshot(db: Session, event: Event) -> dict:
    return _cache.get_or_set(event.id, lambda: compute(db, event))
