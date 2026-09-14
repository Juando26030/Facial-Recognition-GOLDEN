import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, Tenant
from app.auth import get_current_staff, hash_password, require_role
from app.cities_data import COUNTRY_CITIES

router = APIRouter()


@router.get("/cities")
async def list_cities(country: str, staff: StaffUser = Depends(require_role("coordinador"))):
    """Sugerencias de ciudad para el país dado (dataset GeoNames, ver app/cities_data.py),
    ordenadas por población — se recorta a las primeras 300 para no mandar un <datalist> gigante
    al navegador en países con miles de ciudades. El campo de ciudad siempre acepta texto libre
    también, por si la ciudad buscada no queda entre esas 300."""
    return COUNTRY_CITIES.get(country, [])[:300]


class EventStaffIn(BaseModel):
    username: str  # cédula, para digitador
    password: str
    full_name: Optional[str] = None
    role: str = "digitador"  # "digitador" (coordinador+) o "cliente" (admin+ únicamente)


class AssignExistingIn(BaseModel):
    staff_id: int


def _serialize_staff(s: StaffUser) -> dict:
    return {"id": s.id, "username": s.username, "full_name": s.full_name, "role": s.role, "is_active": s.is_active}


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
    start_date: date
    end_date: date
    setup_date: date
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
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    setup_date: Optional[date] = None
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
async def my_events(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """Para el dashboard: eventos a los que este staff puede entrar directo. digitador/cliente ->
    solo eventos activos con autorización explícita. coordinador+ -> todos los activos."""
    query = db.query(Event).filter(Event.status == "activo")
    if staff.role in ("digitador", "cliente"):
        query = query.join(
            EventStaffAuthorization, EventStaffAuthorization.event_id == Event.id
        ).filter(EventStaffAuthorization.staff_user_id == staff.id)
    events = query.order_by(Event.created_at.desc()).all()
    return [_serialize(e) for e in events]


def _words(text: Optional[str]) -> list:
    return re.findall(r"\w+", (text or "").lower())


def _matches_by_word_prefix(haystack: str, query: str) -> bool:
    """True si CADA palabra de `query` es prefijo de ALGUNA palabra de `haystack`
    (ej. 'c' o 'cor' matchean 'Corferias', pero 'ferias' no) — como cualquier buscador
    "empieza por", no una coincidencia de substring en cualquier posición."""
    query_words = _words(query)
    if not query_words:
        return False
    haystack_words = _words(haystack)
    return all(any(hw.startswith(qw) for hw in haystack_words) for qw in query_words)


@router.get("/events/search")
async def search_events(
    q: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """Búsqueda libre entre todos los clientes/eventos: por código, nombre, país o ciudad del
    evento, o por nombre del cliente (tenant). Filtrado en Python (no SQL LIKE) para que la
    coincidencia sea por inicio de palabra y no por substring en medio de una palabra."""
    all_events = db.query(Event).order_by(Event.created_at.desc()).all()
    matches = []
    for e in all_events:
        haystack = " ".join(filter(None, [
            e.name, e.event_code, e.country, e.city, e.tenant.name if e.tenant else None,
        ]))
        if _matches_by_word_prefix(haystack, q):
            matches.append(e)
    return [_serialize(e) for e in matches]


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


@router.get("/events/{event_id}/staff-users")
async def list_event_staff(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """digitador + cliente autorizados para ESTE evento."""
    staff_list = (
        db.query(StaffUser)
        .join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
        .filter(EventStaffAuthorization.event_id == event_id, StaffUser.role.in_(("digitador", "cliente")))
        .all()
    )
    return [_serialize_staff(s) for s in staff_list]


@router.post("/events/{event_id}/staff-users")
async def create_event_staff(
    event_id: int, data: EventStaffIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    """Crea una cuenta digitador o cliente y la autoriza para ESTE evento en un solo paso — no
    queda visible en /admin/staff como cuenta 'suelta' sin asociar. 'cliente' exige admin+
    (un coordinador solo puede crear digitador)."""
    if data.role not in ("digitador", "cliente"):
        raise HTTPException(status_code=400, detail="Rol inválido (debe ser 'digitador' o 'cliente')")
    if data.role == "cliente" and staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo un Admin puede crear cuentas cliente")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese usuario")

    new_user = StaffUser(
        username=data.username, password_hash=hash_password(data.password),
        full_name=data.full_name, role=data.role, tenant_id=event.tenant_id, created_by_id=staff.id,
    )
    db.add(new_user)
    db.flush()  # para obtener new_user.id antes de commitear
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=new_user.id, authorized_by_id=staff.id))
    db.commit()
    return _serialize_staff(new_user)


@router.post("/events/{event_id}/staff-users/assign-existing")
async def assign_existing_staff(
    event_id: int, data: AssignExistingIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("admin")),
):
    """Autoriza una cuenta digitador/cliente YA existente (de otro evento) para ESTE evento —
    admin+ únicamente. Para crear una cuenta nueva usar POST .../staff-users en su lugar."""
    target = db.query(StaffUser).filter(
        StaffUser.id == data.staff_id, StaffUser.role.in_(("digitador", "cliente"))
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    existing = db.query(EventStaffAuthorization).filter_by(staff_user_id=target.id, event_id=event_id).first()
    if existing:
        return {"message": "Ya estaba autorizado para este evento"}
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=target.id, authorized_by_id=staff.id))
    db.commit()
    return _serialize_staff(target)


@router.delete("/events/{event_id}/staff-users/{staff_id}")
async def revoke_event_staff(
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
