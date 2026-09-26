"""Sube `events.faces_version` cada vez que cambia lo que el reconocimiento facial de un evento debe ver (ver app/faces.py).

Se engancha al `flush` de cualquier sesión, así que cubre por igual las rutas de la API, los scripts y las pruebas sin tener que acordarse
de llamar nada en cada sitio:
  * un rostro nuevo, cambiado o borrado en `users.face_encoding`  -> sube la versión de TODOS los eventos de ese cliente;
  * una persona con rostro que entra o sale de un evento (`event_attendees`) -> sube la de ESE evento.
Las operaciones masivas que no pasan por la sesión (`query.delete()`/`update()`) deben llamar a `bump()` a mano: ver `delete_user_from_event`."""
from typing import Iterable, Optional, Set

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from app.models import EventAttendee, User


def bump(connection_or_session, tenant_id: Optional[str] = None, event_ids: Iterable[int] = ()) -> None:
    """`UPDATE events SET faces_version = faces_version + 1` para el cliente y/o los eventos indicados (dentro de la transacción en curso)."""
    execute = connection_or_session.execute
    if tenant_id:
        execute(text("UPDATE events SET faces_version = faces_version + 1 WHERE tenant_id = :t"), {"t": tenant_id})
    ids = sorted(set(event_ids))
    if ids:
        execute(text("UPDATE events SET faces_version = faces_version + 1 WHERE id = ANY(:ids)"), {"ids": ids})


def _face_changed(user: User) -> bool:
    return inspect(user).attrs.face_encoding.history.has_changes()


def _has_face(session: Session, user_id: str, tenant_id: str) -> bool:
    return session.execute(text("SELECT 1 FROM users WHERE id = :i AND tenant_id = :t AND face_encoding IS NOT NULL"), {"i": user_id, "t": tenant_id}).first() is not None


@event.listens_for(Session, "before_flush")
def _collect(session: Session, flush_context, instances) -> None:
    tenants: Set[str] = set()
    events: Set[int] = set()
    for obj in session.new:
        if isinstance(obj, User) and obj.face_encoding:
            tenants.add(obj.tenant_id)
    for obj in session.dirty:
        if isinstance(obj, User) and _face_changed(obj):
            tenants.add(obj.tenant_id)
    for obj in session.deleted:
        if isinstance(obj, User):
            tenants.add(obj.tenant_id)
    for obj in list(session.new) + list(session.deleted):
        if isinstance(obj, EventAttendee) and obj.tenant_id not in tenants and obj.event_id is not None:
            pending = next((u for u in session.new if isinstance(u, User) and u.id == obj.user_id and u.tenant_id == obj.tenant_id), None)
            if (pending is not None and pending.face_encoding) or (pending is None and _has_face(session, obj.user_id, obj.tenant_id)):
                events.add(obj.event_id)
    session.info["faces_bump"] = (tenants, events)


@event.listens_for(Session, "after_flush")
def _apply(session: Session, flush_context) -> None:
    tenants, events = session.info.pop("faces_bump", (set(), set()))
    for tenant in tenants:
        bump(session, tenant_id=tenant)
    if events:
        bump(session, event_ids=events)
