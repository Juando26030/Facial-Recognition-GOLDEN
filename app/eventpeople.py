"""Una sola regla de «esta persona es de ESTE evento» (inscrita o con algún registro aquí).

La cédula sola no basta: los datos de `User` se comparten entre los eventos del mismo cliente, así que un digitador autorizado al evento A no puede leer, imprimir ni acreditar a alguien que solo
es del evento B (Fase 3, B2 y R2-1). Módulo sin dependencias de routers para poder importarlo desde cualquiera sin ciclos.
"""
from typing import Iterable, Optional, Set

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AccessLog, Event, EventAttendee, User

NOT_FOUND_MSG = "Persona no encontrada"


def person_of_event(db: Session, event: Event, user_id: str) -> Optional[User]:
    """La persona `user_id` SOLO si es de ESTE evento (inscrita o con algún registro aquí); si no, None."""
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if user is None:
        return None
    if db.query(EventAttendee.id).filter_by(event_id=event.id, user_id=user.id).first() or db.query(AccessLog.id).filter_by(event_id=event.id, user_id=user.id).first():
        return user
    return None


def require_person_of_event(db: Session, event: Event, user_id: str) -> User:
    """Como `person_of_event`, pero 404 con el MISMO texto exista la persona en otro evento o no (no confirma nada)."""
    user = person_of_event(db, event, str(user_id or "").strip())
    if user is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
    return user


def member_ids(db: Session, event: Event, ids: Iterable[str]) -> Set[str]:
    """Subconjunto de `ids` que pertenece al evento (para lotes: dos consultas, no una por persona)."""
    wanted = {i for i in ids if i}
    if not wanted:
        return set()
    attendees = {u for (u,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(wanted))}
    logged = {u for (u,) in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.user_id.in_(wanted))}
    return attendees | logged
