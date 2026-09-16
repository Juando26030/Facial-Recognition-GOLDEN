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

from app.auth import require_role
from app.database import get_db
from app.models import CalendarNote, Event, StaffUser
from app.routers.events import _serialize

router = APIRouter()


@router.get("/events/calendar")
async def calendar_events(
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
    if commercial_staff_id is not None:
        query = query.filter(Event.commercial_staff_id == commercial_staff_id)
    if coordinator_staff_id is not None:
        query = query.filter(Event.coordinator_staff_id == coordinator_staff_id)
    return [_serialize(e) for e in query.order_by(Event.start_date).all()]


class CalendarNoteIn(BaseModel):
    date: date
    text: str


def _serialize_note(n: CalendarNote) -> dict:
    return {
        "id": n.id, "date": n.date.isoformat(), "text": n.text,
        "created_by_id": n.created_by_id,
        "created_by_name": (n.created_by.full_name or n.created_by.username) if n.created_by else None,
    }


@router.get("/calendar/notes")
async def list_calendar_notes(
    start: date, end: date, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    notes = db.query(CalendarNote).filter(CalendarNote.date >= start, CalendarNote.date <= end).order_by(CalendarNote.date).all()
    return [_serialize_note(n) for n in notes]


@router.post("/calendar/notes")
async def create_calendar_note(
    data: CalendarNoteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="El recordatorio no puede estar vacío")
    note = CalendarNote(date=data.date, text=text, created_by_id=staff.id)
    db.add(note)
    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@router.delete("/calendar/notes/{note_id}")
async def delete_calendar_note(
    note_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Solo el autor del recordatorio o admin+ puede borrarlo — es un tablero compartido, pero no
    cualquiera debería poder borrar la nota de otra persona."""
    note = db.query(CalendarNote).filter(CalendarNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    if note.created_by_id != staff.id and staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo quien lo creó (o un Admin) puede borrar este recordatorio")
    db.delete(note)
    db.commit()
    return {"message": "Recordatorio eliminado"}
