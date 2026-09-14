from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccessLog, Event, EventStaffAuthorization, STAFF_ROLES, StaffUser
from app.auth import hash_password, require_role

router = APIRouter()

# Roles creables desde /admin/staff. "digitador" NO está aquí a propósito: los usuarios
# temporales se crean desde dentro de un evento (ver app/routers/events.py, POST
# /events/{id}/temp-users), donde quedan asociados a ese evento en el mismo paso.
ROLES_CREATABLE_BY_ADMIN = ("coordinador", "cliente")

# Qué roles puede BORRAR PERMANENTEMENTE cada rol (siempre "todo lo que está por debajo de mí").
# coordinador es el caso especial: solo temporales (digitador), nada más.
DELETABLE_ROLES_BY = {
    "coordinador": ("digitador",),
    "admin": ("coordinador", "digitador", "cliente"),
    "super_admin": ("admin", "coordinador", "digitador", "cliente"),
}


class StaffIn(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    role: str


def _serialize(s: StaffUser) -> dict:
    return {
        "id": s.id, "username": s.username, "full_name": s.full_name,
        "role": s.role, "is_active": s.is_active,
    }


@router.get("/staff/coordinators")
async def list_coordinators(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Liviano y accesible desde coordinador+ (a diferencia de /staff, que es admin+) — para
    poblar el selector de 'coordinador asignado' al crear/editar un evento."""
    coords = db.query(StaffUser).filter(StaffUser.role == "coordinador", StaffUser.is_active == True).all()
    return [{"id": c.id, "username": c.username, "full_name": c.full_name} for c in coords]


@router.get("/staff/assignable")
async def list_assignable_staff(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """digitador + cliente activos, para el desplegable de 'autorizar/reautorizar para un evento'
    en /admin/staff — independiente del filtro de ROLES_CREATABLE_BY_ADMIN de /staff (que oculta
    digitador/cliente de la tabla general a propósito, pero aquí sí hacen falta)."""
    staff_list = db.query(StaffUser).filter(
        StaffUser.role.in_(("digitador", "cliente")), StaffUser.is_active == True
    ).all()
    return [_serialize(s) for s in staff_list]


@router.get("/staff")
async def list_staff(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    query = db.query(StaffUser)
    if staff.role != "super_admin":
        query = query.filter(StaffUser.role.in_(ROLES_CREATABLE_BY_ADMIN))
    return [_serialize(s) for s in query.order_by(StaffUser.created_at.desc()).all()]


@router.post("/staff")
async def create_staff(
    data: StaffIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    if data.role not in STAFF_ROLES:
        raise HTTPException(status_code=400, detail="Rol inválido")
    if data.role == "super_admin":
        raise HTTPException(status_code=403, detail="No se puede crear otro Super Admin desde la app")
    if data.role == "digitador":
        raise HTTPException(
            status_code=400,
            detail="Los usuarios temporales (digitador) se crean desde dentro de un evento, no aquí",
        )
    if data.role == "admin" and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede crear cuentas Admin")
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ese usuario ya existe")

    new_staff = StaffUser(
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        tenant_id=staff.tenant_id,
        created_by_id=staff.id,
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)
    return _serialize(new_staff)


@router.patch("/staff/{staff_id}/deactivate")
async def deactivate_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.role in ("admin", "super_admin") and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    target.is_active = False
    db.commit()
    return {"message": f"{target.username} desactivado"}


@router.patch("/staff/{staff_id}/activate")
async def activate_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.role in ("admin", "super_admin") and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    target.is_active = True
    db.commit()
    return {"message": f"{target.username} reactivado"}


@router.delete("/staff/{staff_id}")
async def delete_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """Borrado PERMANENTE (no desactivación) — cada rol solo puede borrar lo que tiene
    directamente debajo en DELETABLE_ROLES_BY. No borra Eventos ni AccessLogs asociados (son
    datos de negocio reales, no cuentas de staff): las referencias a este staff se desvinculan
    (quedan en NULL) en vez de arrastrar un borrado en cascada."""
    if staff.role not in DELETABLE_ROLES_BY:
        raise HTTPException(status_code=403, detail="No autorizado")

    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes borrar tu propia cuenta")
    if target.role not in DELETABLE_ROLES_BY[staff.role]:
        raise HTTPException(status_code=403, detail=f"Un {staff.role} no puede borrar cuentas de rol '{target.role}'")

    db.query(EventStaffAuthorization).filter(EventStaffAuthorization.staff_user_id == target.id).delete()
    db.query(EventStaffAuthorization).filter(EventStaffAuthorization.authorized_by_id == target.id).update({"authorized_by_id": None})
    db.query(Event).filter(Event.coordinator_staff_id == target.id).update({"coordinator_staff_id": None})
    db.query(Event).filter(Event.created_by_id == target.id).update({"created_by_id": None})
    db.query(AccessLog).filter(AccessLog.registered_by_staff_id == target.id).update({"registered_by_staff_id": None})
    db.query(StaffUser).filter(StaffUser.created_by_id == target.id).update({"created_by_id": None})

    username = target.username
    db.delete(target)
    db.commit()
    return {"message": f"{username} eliminado permanentemente de la base de datos"}


@router.post("/staff/{staff_id}/authorize-event/{event_id}")
async def authorize_for_event(
    staff_id: int, event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    """Autoriza a un digitador o cliente (ambos requieren EventStaffAuthorization, ver
    app/auth.get_event_for_staff) a acceder a un evento puntual. Para digitador normalmente se usa
    en cambio POST /api/events/{id}/temp-users (crea + autoriza en un paso); este endpoint es para
    reautorizar uno ya existente en otro evento, o para asignar un usuario cliente."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    event = db.query(Event).filter(Event.id == event_id).first()
    if not target or not event:
        raise HTTPException(status_code=404, detail="Usuario o evento no encontrado")
    existing = db.query(EventStaffAuthorization).filter_by(staff_user_id=staff_id, event_id=event_id).first()
    if existing:
        return {"message": "Ya estaba autorizado"}
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=staff_id, authorized_by_id=staff.id))
    db.commit()
    return {"message": f"{target.username} autorizado para '{event.name}'"}


@router.delete("/staff/{staff_id}/authorize-event/{event_id}")
async def revoke_event_authorization(
    staff_id: int, event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    db.query(EventStaffAuthorization).filter_by(staff_user_id=staff_id, event_id=event_id).delete()
    db.commit()
    return {"message": "Autorización revocada"}
