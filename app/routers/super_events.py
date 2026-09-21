"""Superevento (reunión 2026-09-21, ítem 19): agrupa eventos independientes de un mismo cliente bajo
un "padre". Cada hijo se maneja totalmente separado (parámetros, registro, reportes) — lo único que
cruza es el aviso de que una persona ya asistió a un evento hermano."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import AccessLog, Event, StaffUser, SuperEvent, User

router = APIRouter()


@router.get("/super-events")
async def list_super_events(tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    rows = db.query(SuperEvent).filter(SuperEvent.tenant_id == tenant_id).order_by(SuperEvent.name).all()
    return [{"id": s.id, "name": s.name, "tenant_id": s.tenant_id, "events": len(s.events)} for s in rows]


@router.post("/super-events")
async def create_super_event(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    name = str(data.get("name") or "").strip()
    tenant_id = str(data.get("tenant_id") or "").strip()
    if not name or not tenant_id:
        raise HTTPException(status_code=400, detail="El superevento necesita un nombre y un cliente")
    if db.query(SuperEvent).filter(SuperEvent.tenant_id == tenant_id, SuperEvent.name == name).first():
        raise HTTPException(status_code=400, detail="Ya existe un superevento con ese nombre para este cliente")
    sup = SuperEvent(tenant_id=tenant_id, name=name, created_by_id=staff.id, created_at=datetime.utcnow())
    db.add(sup)
    db.commit()
    return {"id": sup.id, "name": sup.name, "tenant_id": sup.tenant_id, "events": 0}


def sibling_attendance(db: Session, event: Event, user_id: str) -> list:
    """Eventos HERMANOS (mismo superevento, distinto evento) a los que esta persona ya asistió —
    o sea, con al menos una acreditación real (no las ediciones de perfil, 'Actualizado')."""
    if not event.super_event_id:
        return []
    siblings = db.query(Event).filter(Event.super_event_id == event.super_event_id, Event.id != event.id).all()
    attended = []
    for sib in siblings:
        real = db.query(AccessLog).filter(
            AccessLog.event_id == sib.id, AccessLog.user_id == user_id, AccessLog.record_type != "Actualizado"
        ).first()
        if real:
            attended.append({"event_id": sib.id, "event_name": sib.name, "event_code": sib.event_code})
    return attended


@router.get("/users/{user_id}/sibling-check")
async def sibling_check(
    user_id: str, event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """¿Esta persona ya asistió a un evento hermano de este (mismo superevento)? Si sí, devuelve sus
    datos guardados para poder solo vincularla a este evento en vez de capturarlos de nuevo."""
    event = get_event_for_staff(event_id, db, staff)
    attended = sibling_attendance(db, event, user_id)
    if not attended:
        return {"siblings": []}
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    return {
        "siblings": attended,
        "super_event_name": event.super_event.name if event.super_event else "",
        "user": {"id": user.id, "first_name": user.first_name, "last_name": user.last_name} if user else None,
    }
