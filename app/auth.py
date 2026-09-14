import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, EventStaffAuthorization, StaffUser, STAFF_ROLES

ROLE_HIERARCHY = {role: i for i, role in enumerate(STAFF_ROLES)}


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def get_current_staff(request: Request, db: Session = Depends(get_db)) -> StaffUser:
    staff_id = request.session.get("staff_user_id")
    if not staff_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    staff = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.is_active == True).first()
    if not staff:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sesión inválida o usuario desactivado")
    return staff


def require_role(minimum_role: str):
    """Exige que el staff logueado tenga al menos este rol (jerarquía en STAFF_ROLES)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if ROLE_HIERARCHY[staff.role] < minimum_level:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_super_admin(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede hacer esto")
    return staff


def get_event_for_staff(event_id: int, db: Session, staff: StaffUser) -> Event:
    """Resuelve el evento y valida acceso. coordinador+ tiene alcance de tenant (acceso a
    cualquier evento); digitador necesita una EventStaffAuthorization activa para ESE evento
    puntual, y el evento debe seguir 'activo'."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    if staff.role == "digitador":
        authorized = db.query(EventStaffAuthorization).filter_by(
            event_id=event_id, staff_user_id=staff.id
        ).first()
        if not authorized:
            raise HTTPException(status_code=403, detail="No estás autorizado para este evento")
        if event.status != "activo":
            raise HTTPException(status_code=403, detail="Este evento ya está cerrado")

    return event
