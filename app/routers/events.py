from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.auth import hash_password, require_role

router = APIRouter()


class TempUserIn(BaseModel):
    username: str  # cédula
    password: str
    full_name: Optional[str] = None


def _serialize_staff(s: StaffUser) -> dict:
    return {"id": s.id, "username": s.username, "full_name": s.full_name, "is_active": s.is_active}


class EventIn(BaseModel):
    """Todos los campos operativos son obligatorios al crear un evento — 'notes' es la única
    excepción real (es explícitamente un campo de observaciones, opcional por naturaleza)."""
    tenant_id: str
    event_code: str
    name: str
    location: str
    address: str
    country: str
    city: str
    start_date: datetime
    end_date: datetime
    setup_date: datetime
    event_time_start: str
    event_time_end: str
    setup_time_start: str
    setup_time_end: str
    coordinator_staff_id: int
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
    event_time_start: Optional[str] = None
    event_time_end: Optional[str] = None
    setup_time_start: Optional[str] = None
    setup_time_end: Optional[str] = None
    coordinator_staff_id: Optional[int] = None
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
        "event_time_start": e.event_time_start, "event_time_end": e.event_time_end,
        "setup_time_start": e.setup_time_start, "setup_time_end": e.setup_time_end,
        "notes": e.notes,
        "coordinator_staff_id": e.coordinator_staff_id,
        "coordinator_name": (e.coordinator.full_name or e.coordinator.username) if e.coordinator else None,
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


@router.get("/events/search")
async def search_events(
    q: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """Búsqueda libre entre todos los clientes/eventos: por código, nombre, país o ciudad del
    evento, o por nombre del cliente (tenant)."""
    like = f"%{q}%"
    events = (
        db.query(Event)
        .join(Tenant, Tenant.id == Event.tenant_id)
        .filter(or_(
            Event.name.ilike(like), Event.event_code.ilike(like),
            Event.country.ilike(like), Event.city.ilike(like), Tenant.name.ilike(like),
        ))
        .order_by(Event.created_at.desc())
        .all()
    )
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
    coordinator = db.query(StaffUser).filter(
        StaffUser.id == data.coordinator_staff_id, StaffUser.role == "coordinador"
    ).first()
    if not coordinator:
        raise HTTPException(status_code=400, detail="El coordinador asignado no es válido")

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


@router.get("/events/{event_id}/temp-users")
async def list_temp_users(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """Digitadores autorizados para ESTE evento (creados aquí o reautorizados desde /admin/staff)."""
    staff_list = (
        db.query(StaffUser)
        .join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
        .filter(EventStaffAuthorization.event_id == event_id, StaffUser.role == "digitador")
        .all()
    )
    return [_serialize_staff(s) for s in staff_list]


@router.post("/events/{event_id}/temp-users")
async def create_temp_user(
    event_id: int, data: TempUserIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    """Crea un usuario digitador (temporal) y lo autoriza para ESTE evento en un solo paso —
    no queda visible en /admin/staff como cuenta 'suelta' sin asociar."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con esa cédula/usuario")

    temp_user = StaffUser(
        username=data.username, password_hash=hash_password(data.password),
        full_name=data.full_name, role="digitador", tenant_id=event.tenant_id, created_by_id=staff.id,
    )
    db.add(temp_user)
    db.flush()  # para obtener temp_user.id antes de commitear
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=temp_user.id, authorized_by_id=staff.id))
    db.commit()
    return _serialize_staff(temp_user)


@router.delete("/events/{event_id}/temp-users/{staff_id}")
async def revoke_temp_user(
    event_id: int, staff_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    db.query(EventStaffAuthorization).filter_by(event_id=event_id, staff_user_id=staff_id).delete()
    db.commit()
    return {"message": "Acceso a este evento revocado"}


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
