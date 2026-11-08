"""Calendario (Sprint 2.4 Fase 8, 2026-09-16, pedido explícito) — vista mensual/semanal/diaria de
eventos por rango de fechas, con los mismos filtros de pertenencia que /eventos
(commercial_staff_id/coordinator_staff_id, ver events.py), más recordatorios libres sobre un día
cualquiera (CalendarNote) para dejar anotaciones de equipo ("llamar al cliente X") sin tener que
atarlas a un evento en particular."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_role, scope_events_query
from app.database import get_db
from app.models import CalendarNote, Event, StaffUser
from app.routers.events import _serialize
from app.tenant_scope import assert_same_tenant, staff_tenant_enforced

router = APIRouter()

# Sprint 2.4 Fase 14 (2026-09-17, pedido explícito): "esto no aplica para usuarios temporales o
# para clientes" — solo estos 4 roles pueden ser destinatarios de un recordatorio, mismos roles
# que ya tienen acceso al Calendario (coordinador+).
NOTIFIABLE_ROLES = ("coordinador", "comercial", "admin", "super_admin")


@router.get("/calendar/notifiable-staff")
def list_notifiable_staff(
    q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Para el buscador de destinatarios al crear un recordatorio — lista desplegable que también
    filtra escribiendo. `q` (opcional) filtra por nombre o usuario, substring insensible a
    mayúsculas (no hace falta el criterio de prefijo por palabra de otras búsquedas, esta lista es
    corta)."""
    query = db.query(StaffUser).filter(StaffUser.role.in_(NOTIFIABLE_ROLES), StaffUser.is_active == True)
    if staff_tenant_enforced(staff):          # ENFORCE_STAFF_TENANT: solo ofrece compañeros de su mismo cliente
        query = query.filter(StaffUser.tenant_id == staff.tenant_id)
    people = query.all()
    if q:
        q_lower = q.lower()
        people = [p for p in people if q_lower in (p.full_name or "").lower() or q_lower in p.username.lower()]
    return [{"id": p.id, "username": p.username, "full_name": p.full_name, "role": p.role} for p in people]


@router.get("/events/calendar")
def calendar_events(
    start: date, end: date,
    commercial_staff_id: Optional[int] = None, coordinator_staff_id: Optional[int] = None,
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Eventos cuyo rango [start_date, end_date] se solapa con [start, end] — un evento de varios
    días aparece en cada día que le corresponde, no solo en start_date. Mismos filtros de
    pertenencia que GET /api/events/search (ver events.py), para reusar el mismo toggle "Mis
    eventos"/"Todos" (comercial) y los selectores de admin+ también en el Calendario."""
    query = db.query(Event).filter(
        Event.start_date <= end,
        (Event.end_date >= start) | (Event.end_date.is_(None)),
    )
    query = query.filter(Event.archived_at.is_(None))          # Fase 3: los archivados no salen en el calendario
    query = scope_events_query(query, staff)          # P5: el mismo recorte por cliente y pertenencia que /api/events y /api/events/search
    if commercial_staff_id is not None:
        query = query.filter(Event.commercial_staff_id == commercial_staff_id)
    if coordinator_staff_id is not None:
        query = query.filter(Event.coordinator_staff_id == coordinator_staff_id)
    return [_serialize(e) for e in query.order_by(Event.start_date).all()]


class CalendarNoteIn(BaseModel):
    date: date
    text: str
    target_staff_ids: list = []


def _serialize_note(n: CalendarNote) -> dict:
    targets = n.get_targets()
    return {
        "id": n.id, "date": n.date.isoformat(), "text": n.text,
        "created_by_id": n.created_by_id,
        "created_by_name": (n.created_by.full_name or n.created_by.username) if n.created_by else None,
        "target_staff_ids": targets,
    }


def _note_tenant(n: CalendarNote):
    """Cliente de la nota = cliente de quien la creó (None = personal global de Golden)."""
    return n.created_by.tenant_id if n.created_by is not None else None


@router.get("/calendar/notes")
def list_calendar_notes(
    start: date, end: date, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Solo trae los recordatorios que le corresponden a quien pregunta (Fase 14, 2026-09-17,
    pedido explícito): sin destinatarios elegidos = para todo el equipo (comportamiento original);
    con destinatarios = solo para esas personas + quien lo creó."""
    notes = db.query(CalendarNote).filter(CalendarNote.date >= start, CalendarNote.date <= end).order_by(CalendarNote.date).all()
    visible = [n for n in notes if not n.get_targets() or staff.id in n.get_targets() or n.created_by_id == staff.id]
    if staff_tenant_enforced(staff):
        # Las notas no tienen cliente propio (sin migración): pertenecen al cliente de quien las creó. Con ENFORCE_STAFF_TENANT cada quien ve las de su cliente
        # y las que otra persona le dirigió a él expresamente.
        visible = [n for n in visible if staff.id in n.get_targets() or _note_tenant(n) == staff.tenant_id]
    return [_serialize_note(n) for n in visible]


@router.post("/calendar/notes")
def create_calendar_note(
    data: CalendarNoteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El recordatorio no puede estar vacío")

    target_ids = [int(i) for i in (data.target_staff_ids or [])]
    if target_ids:
        valid = db.query(StaffUser).filter(
            StaffUser.id.in_(target_ids), StaffUser.role.in_(NOTIFIABLE_ROLES), StaffUser.is_active == True
        ).all()
        if len(valid) != len(set(target_ids)):
            raise HTTPException(status_code=400, detail="Uno o más destinatarios no son válidos (cliente/digitador no pueden recibir recordatorios)")
        if staff_tenant_enforced(staff) and any(v.tenant_id != staff.tenant_id for v in valid):
            raise HTTPException(status_code=400, detail="Uno o más destinatarios no son válidos (cliente/digitador no pueden recibir recordatorios)")      # mismo mensaje: no confirma que existen en otro cliente

    note = CalendarNote(date=data.date, text=text, created_by_id=staff.id)
    note.set_targets(target_ids)
    db.add(note)
    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@router.delete("/calendar/notes/{note_id}")
def delete_calendar_note(
    note_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Solo el autor del recordatorio o admin+ puede borrarlo — es un tablero compartido, pero no
    cualquiera debería poder borrar la nota de otra persona."""
    note = db.query(CalendarNote).filter(CalendarNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    assert_same_tenant(staff, _note_tenant(note), "Recordatorio no encontrado")
    if note.created_by_id != staff.id and staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo quien lo creó (o un Admin) puede borrar este recordatorio")
    db.delete(note)
    db.commit()
    return {"message": "Recordatorio eliminado"}
