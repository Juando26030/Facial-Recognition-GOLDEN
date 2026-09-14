from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, StaffUser
from app.auth import require_role

router = APIRouter()

# Mismo tenant fijo que app/routers/api.py (ver CLAUDE.md: multi-tenant no explotado todavía)
CURRENT_TENANT = "golden_hq"


class EventIn(BaseModel):
    name: str
    location: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class EventUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


def _serialize(e: Event) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "location": e.location,
        "status": e.status,
        "start_date": e.start_date.isoformat() if e.start_date else None,
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/events")
async def list_events(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    events = db.query(Event).filter(Event.tenant_id == CURRENT_TENANT).order_by(Event.created_at.desc()).all()
    return [_serialize(e) for e in events]


@router.post("/events")
async def create_event(
    data: EventIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    event = Event(
        tenant_id=CURRENT_TENANT, name=data.name, location=data.location,
        start_date=data.start_date, end_date=data.end_date, created_by_id=staff.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _serialize(event)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: int, data: EventUpdate, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = db.query(Event).filter(Event.id == event_id, Event.tenant_id == CURRENT_TENANT).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    for field, value in data.dict(exclude_unset=True).items():
        setattr(event, field, value)
    db.commit()
    return _serialize(event)


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    """Borrado permanente — solo admin+ (coordinador puede cerrar un evento vía PATCH status='cerrado')."""
    event = db.query(Event).filter(Event.id == event_id, Event.tenant_id == CURRENT_TENANT).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    db.delete(event)
    db.commit()
    return {"message": "Evento eliminado permanentemente"}
