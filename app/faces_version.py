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


def _with_face(session: Session, wanted: dict) -> Set[tuple]:
    """{(cliente, cédula)} de las personas pedidas que tienen rostro guardado: UNA consulta por cada 2.000 cédulas de un cliente."""
    found: Set[tuple] = set()
    for tenant, ids in wanted.items():
        ordered = sorted(ids)
        for i in range(0, len(ordered), 2000):
            rows = session.execute(text("SELECT id FROM users WHERE tenant_id = :t AND id = ANY(:ids) AND face_encoding IS NOT NULL"), {"t": tenant, "ids": ordered[i:i + 2000]})
            found.update((tenant, r[0]) for r in rows)
    return found


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
    # Una persona con rostro que entra o sale de un evento sube la versión de ESE evento. Antes: una consulta a la base POR inscripción («¿tiene rostro?»); con 8.000 inscripciones eran 8.000
    # viajes. Ahora: lo pendiente en la sesión se resuelve en memoria y lo demás con UNA consulta por cada 2.000 cédulas (misma regla: tiene `face_encoding`).
    skip = session.info.get("faces_no_bump", ())          # «solo agregar»: personas que se inscriben sin aceptación en el evento (no entran a la matriz): la versión no sube, el quiosco no la reconstruye
    attendees = [o for o in list(session.new) + list(session.deleted) if isinstance(o, EventAttendee) and o.tenant_id not in tenants and o.event_id is not None
                 and (o.tenant_id, o.user_id) not in skip]
    if attendees:
        pending = {(u.tenant_id, u.id): u for u in session.new if isinstance(u, User)}
        to_ask: dict = {}
        for obj in attendees:
            user = pending.get((obj.tenant_id, obj.user_id))
            if user is None:
                to_ask.setdefault(obj.tenant_id, set()).add(obj.user_id)
        with_face = _with_face(session, to_ask)
        for obj in attendees:
            user = pending.get((obj.tenant_id, obj.user_id))
            if (user is not None and user.face_encoding) or (user is None and (obj.tenant_id, obj.user_id) in with_face):
                events.add(obj.event_id)
    session.info["faces_bump"] = (tenants, events)


@event.listens_for(Session, "after_flush")
def _apply(session: Session, flush_context) -> None:
    tenants, events = session.info.pop("faces_bump", (set(), set()))
    for tenant in tenants:
        bump(session, tenant_id=tenant)
    if events:
        bump(session, event_ids=events)
