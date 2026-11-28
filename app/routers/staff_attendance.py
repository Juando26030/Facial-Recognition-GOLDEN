"""Llamado de asistencia del personal temporal de un evento (28-nov-2026, Juan David): segunda pestaña de «Usuarios del evento».

  GET /api/events/{id}/staff-attendance                 las cuentas del evento (digitadores y coordinadores temporales) con su marca: «a tiempo», «tarde», «no llegó» o sin marcar,
                                                         y de dónde salió cada una (formulario del compromiso o creada a mano / Excel)
  PUT /api/events/{id}/staff-attendance/{staff_id}      {"status": "on_time"|"late"|"absent"|null}   null = quitar la marca (queda «sin marcar»)

Una marca por cuenta y evento (tabla `event_staff_attendance`; sin fila = sin marcar). Coordinador en adelante, salvo la comercial pura (como el resto de la gestión de cuentas del evento).
Queda en la auditoría quién marcó a quién (sin cédulas) y el evento debe estar abierto a cambios. Sin datos personales en el log."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import audit_actions, event_archive
from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import EventStaffAttendance, EventStaffAuthorization, EventStaffPledge, StaffUser
from app.timeutil import utcnow

router = APIRouter()
ATTENDANCE_ROLE = require_role_excluding("coordinador", ("comercial",))
STATUSES = ("on_time", "late", "absent")
LABELS = {"on_time": "Llegó a tiempo", "late": "Llegó tarde", "absent": "No llegó"}


class MarkIn(BaseModel):
    status: Optional[str] = None


def _json(data) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


def _team(db: Session, event_id: int) -> list:
    """Las cuentas que trabajan el evento: digitadores y coordinadores temporales (no los clientes), activas y no archivadas."""
    return (db.query(StaffUser).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
            .filter(EventStaffAuthorization.event_id == event_id, StaffUser.archived_at.is_(None),
                    or_(StaffUser.role == "digitador", StaffUser.event_only.is_(True)), StaffUser.client_temp.isnot(True))
            .order_by(StaffUser.full_name, StaffUser.username).all())


@router.get("/events/{event_id}/staff-attendance")
def get_attendance(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ATTENDANCE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    team = _team(db, event.id)
    marks = {m.staff_user_id: m for m in db.query(EventStaffAttendance).filter(EventStaffAttendance.event_id == event.id)}
    from_form = {sid for (sid,) in db.query(EventStaffPledge.staff_id).filter(EventStaffPledge.event_id == event.id, EventStaffPledge.source == "link", EventStaffPledge.staff_id.isnot(None))}
    rows = [{"staff_id": s.id, "name": s.full_name or "", "username": s.username, "origin": "form" if s.id in from_form else "manual", "status": (marks[s.id].status if s.id in marks else None)} for s in team]
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUSES}
    counts["unmarked"] = sum(1 for r in rows if r["status"] is None)
    return _json({"rows": rows, "counts": counts, "total": len(rows)})


@router.put("/events/{event_id}/staff-attendance/{staff_id}")
def mark_attendance(event_id: int, staff_id: int, body: MarkIn, db: Session = Depends(get_db), staff: StaffUser = Depends(ATTENDANCE_ROLE)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    status = body.status or None
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail="La marca debe ser «llegó a tiempo», «llegó tarde» o «no llegó».")
    target = next((s for s in _team(db, event.id) if s.id == staff_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Esa persona no está en el personal de este evento.")
    row = db.query(EventStaffAttendance).filter_by(event_id=event.id, staff_user_id=staff_id).with_for_update().first()
    if status is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(EventStaffAttendance(event_id=event.id, staff_user_id=staff_id, status=status, marked_by_id=staff.id, marked_at=utcnow()))
    else:
        row.status, row.marked_by_id, row.marked_at = status, staff.id, utcnow()
    audit_actions.record(db, staff, "attendance", "event_staff", staff_id, target.full_name or target.username, f"evento {event.id} · {LABELS.get(status, 'sin marcar')}")
    db.commit()
    return _json({"result": "OK", "staff_id": staff_id, "status": status})
