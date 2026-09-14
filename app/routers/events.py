from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.auth import require_role

router = APIRouter()


class EventIn(BaseModel):
    tenant_id: str
    event_code: Optional[str] = None
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    setup_date: Optional[datetime] = None
    event_schedule: Optional[str] = None
    setup_schedule: Optional[str] = None
    notes: Optional[str] = None


class EventUpdate(BaseModel):
    event_code: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    setup_date: Optional[datetime] = None
    event_schedule: Optional[str] = None
    setup_schedule: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


def _serialize(e: Event) -> dict:
    return {
        "id": e.id, "tenant_id": e.tenant_id, "tenant_name": e.tenant.name if e.tenant else None,
        "event_code": e.event_code, "name": e.name, "location": e.location, "address": e.address,
        "country": e.country, "city": e.city, "status": e.status,
        "start_date": e.start_date.isoformat() if e.start_date else None,
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "setup_date": e.setup_date.isoformat() if e.setup_date else None,
        "event_schedule": e.event_schedule, "setup_schedule": e.setup_schedule, "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/my-events")
async def my_events(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """Para el dashboard: eventos a los que este staff puede entrar directo a registrar.
    digitador -> solo eventos activos con autorización explícita. coordinador+ -> todos los activos."""
    query = db.query(Event).filter(Event.status == "activo")
    if staff.role == "digitador":
        query = query.join(
            EventStaffAuthorization, EventStaffAuthorization.event_id == Event.id
        ).filter(EventStaffAuthorization.staff_user_id == staff.id)
    events = query.order_by(Event.created_at.desc()).all()
    return [_serialize(e) for e in events]


@router.get("/events")
async def list_events(
    tenant_id: Optional[str] = None, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    query = db.query(Event)
    if tenant_id:
        query = query.filter(Event.tenant_id == tenant_id)
    return [_serialize(e) for e in query.order_by(Event.created_at.desc()).all()]


@router.post("/events")
async def create_event(
    data: EventIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    if not db.query(Tenant).filter(Tenant.id == data.tenant_id).first():
        raise HTTPException(status_code=404, detail="Cliente (tenant) no encontrado")
    event = Event(**data.dict(), created_by_id=staff.id)
    db.add(event)
    db.commit()
    db.refresh(event)
    return _serialize(event)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: int, data: EventUpdate, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = db.query(Event).filter(Event.id == event_id).first()
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
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    db.delete(event)
    db.commit()
    return {"message": "Evento eliminado permanentemente"}
