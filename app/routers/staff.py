from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AccessLog, Event, EventStaffAuthorization, STAFF_ROLES, StaffUser
from app.auth import effective_roles, hash_password, require_role

router = APIRouter()

# Roles creables/visibles desde /admin/staff. "digitador" y "cliente" NO están aquí a propósito:
# ambos se crean desde dentro de un evento (ver app/routers/events.py, POST
# /events/{id}/staff-users), donde quedan asociados a ese evento en el mismo paso.
# "comercial" (Sprint 2.4, 2026-09-16): mismo flujo que coordinador, admin+ lo crea desde acá.
ROLES_CREATABLE_BY_ADMIN = ("coordinador", "comercial")

# Qué roles puede BORRAR PERMANENTEMENTE cada rol (siempre "todo lo que está por debajo de mí").
# coordinador es el caso especial: solo temporales (digitador), nada más. "comercial" no borra a
# nadie por ahora (no fue parte del pedido) — solo admin+ puede borrar cuentas comercial.
DELETABLE_ROLES_BY = {
    "coordinador": ("digitador",),
    "admin": ("comercial", "coordinador", "digitador", "cliente"),
    "super_admin": ("admin", "comercial", "coordinador", "digitador", "cliente"),
}


class StaffIn(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    role: str
    phone: Optional[str] = None  # Sprint 2.4: notificaciones por WhatsApp más adelante


def _serialize(s: StaffUser) -> dict:
    return {
        "id": s.id, "username": s.username, "full_name": s.full_name,
        "role": s.role, "secondary_role": s.secondary_role, "is_active": s.is_active, "phone": s.phone,
    }


# Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "el único doble rol permitido es coordinador
# comercial" — ambos deben estar entre coordinador/comercial, y distintos entre sí.
DUAL_ROLE_PAIR = {"coordinador", "comercial"}


@router.get("/staff/coordinators")
async def list_coordinators(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Liviano y accesible desde coordinador+ (a diferencia de /staff, que es admin+) — para
    poblar el selector de 'coordinador asignado' al crear/editar un evento. Incluye a quien tenga
    'coordinador' como rol PRIMARIO o SECUNDARIO (Fase 15: doble rol coordinador+comercial)."""
    coords = db.query(StaffUser).filter(
        or_(StaffUser.role == "coordinador", StaffUser.secondary_role == "coordinador"),
        StaffUser.is_active == True,
    ).all()
    return [{"id": c.id, "username": c.username, "full_name": c.full_name} for c in coords]


@router.get("/staff/commercials")
async def list_commercials(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("comercial"))):
    """Sprint 2.4 Fase 5 (2026-09-16): mismo patrón que /staff/coordinators — poblar el selector
    de 'comercial asignada' al crear/editar un evento y el filtro de admin+ en /eventos. Incluye a
    quien tenga 'comercial' como rol PRIMARIO o SECUNDARIO (Fase 15)."""
    commercials = db.query(StaffUser).filter(
        or_(StaffUser.role == "comercial", StaffUser.secondary_role == "comercial"),
        StaffUser.is_active == True,
    ).all()
    return [{"id": c.id, "username": c.username, "full_name": c.full_name} for c in commercials]


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
    if data.role in ("digitador", "cliente"):
        raise HTTPException(
            status_code=400,
            detail=f"Las cuentas '{data.role}' se crean desde dentro de un evento (pestaña Usuarios del Evento), no aquí",
        )
    if data.role == "admin" and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede crear cuentas Admin")
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ese usuario ya existe")
    # Sprint 2.4 Fase 4 (2026-09-16, pedido explícito): el teléfono es obligatorio y único para
    # todas las cuentas que se crean por acá (coordinador/comercial/admin) — digitador/cliente,
    # las dos excepciones, no pasan por este endpoint (ver create_event_staff en events.py).
    phone = (data.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="El teléfono es obligatorio para esta cuenta")
    if db.query(StaffUser).filter(StaffUser.phone == phone).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese teléfono")

    new_staff = StaffUser(
        username=data.username,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
        tenant_id=staff.tenant_id,
        created_by_id=staff.id,
        phone=phone,
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)
    return _serialize(new_staff)


@router.patch("/staff/{staff_id}/secondary-role")
async def assign_secondary_role(
    staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin")),
):
    """Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden
    ser comerciales, esos son los únicos usuarios que pueden tener doble rol... lo hace el
    administrador". `data: {"secondary_role": "comercial"|"coordinador"|null}` — null quita el rol
    secundario. El rol primario del objetivo y el secundario elegido deben ser, entre los dos,
    exactamente el par {coordinador, comercial} — no se admite ninguna otra combinación (ej. un
    admin no puede ganar un rol secundario, ni comercial+comercial)."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    secondary = data.get("secondary_role")
    if secondary is None:
        target.secondary_role = None
        db.commit()
        return _serialize(target)

    if target.role not in DUAL_ROLE_PAIR:
        raise HTTPException(status_code=400, detail="Solo cuentas coordinador o comercial pueden tener un rol secundario")
    if secondary not in DUAL_ROLE_PAIR or secondary == target.role:
        raise HTTPException(status_code=400, detail="El rol secundario debe ser el otro de coordinador/comercial")

    target.secondary_role = secondary
    db.commit()
    return _serialize(target)


@router.patch("/staff/{staff_id}/deactivate")
async def deactivate_staff(
    staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))
):
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.role == "super_admin":
        raise HTTPException(status_code=403, detail="Un Super Admin no se puede desactivar")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta")
    if target.role == "admin" and staff.role != "super_admin":
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
    directamente debajo en DELETABLE_ROLES_BY (Fase 15: la unión de lo que permite CADA uno de sus
    roles efectivos, por si tiene doble rol coordinador+comercial en cualquier orden). No borra
    Eventos ni AccessLogs asociados (son datos de negocio reales, no cuentas de staff): las
    referencias a este staff se desvinculan (quedan en NULL) en vez de arrastrar un borrado en
    cascada."""
    deletable_roles = set()
    for r in effective_roles(staff):
        deletable_roles |= set(DELETABLE_ROLES_BY.get(r, ()))
    if not deletable_roles:
        raise HTTPException(status_code=403, detail="No autorizado")

    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes borrar tu propia cuenta")
    if target.role not in deletable_roles:
        raise HTTPException(status_code=403, detail=f"No puedes borrar cuentas de rol '{target.role}'")

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



# Nota: la autorización de un digitador/cliente EXISTENTE a un evento ya no vive aquí — se movió
# a app/routers/events.py (POST/DELETE /events/{id}/staff-users, /assign-existing), porque todo
# lo relacionado a "quién puede operar en este evento" se gestiona desde dentro del evento.
