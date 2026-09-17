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


def effective_roles(staff: StaffUser) -> set:
    """Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden
    ser comerciales" — StaffUser.secondary_role permite exactamente ESE doble rol (coordinador+
    comercial, en cualquier orden), asignado por admin+. Todo el resto de auth.py razona sobre
    este CONJUNTO de roles en vez de un solo `staff.role`, para que alguien con doble rol reciba
    la UNIÓN de permisos de ambos — en particular, para que las exclusiones de Fase 6 (comercial
    no puede Escarapelas/Adjuntar BD/Parámetros) NO le apliquen a quien también es coordinador de
    verdad, no una comercial pura."""
    roles = {staff.role}
    if staff.secondary_role:
        roles.add(staff.secondary_role)
    return roles


def require_role(minimum_role: str):
    """Exige que el staff logueado tenga al menos este rol (jerarquía en STAFF_ROLES) — considera
    el rol secundario si tiene uno (ver effective_roles)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) < minimum_level:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_role_excluding(minimum_role: str, excluded_roles: tuple):
    """Como require_role, pero además bloquea roles puntuales aunque cumplan la jerarquía — Sprint
    2.4 Fase 6 (2026-09-16, pedido explícito): 'comercial' queda por ENCIMA de 'coordinador' en
    STAFF_ROLES (hereda su acceso operativo por diseño, ver Fase 0), pero el usuario pidió que
    puntualmente NO tenga Adjuntar Base de Datos, Escarapelas ni Parámetros del Evento — un
    require_role('coordinador') simple no puede excluir un rol que está POR ENCIMA del mínimo.
    Con doble rol (Fase 15): solo bloquea si TODOS sus roles efectivos están en excluded_roles —
    una comercial pura queda bloqueada, pero alguien coordinador+comercial no (porque también es
    coordinador de verdad, no solo comercial con la jerarquía prestada)."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        roles = effective_roles(staff)
        if roles.issubset(set(excluded_roles)):
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        if max(ROLE_HIERARCHY[r] for r in roles) < minimum_level:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
        return staff

    return checker


def require_role_or_client(minimum_role: str):
    """Como require_role, pero además deja pasar siempre a 'cliente' aunque quede por debajo del
    mínimo en STAFF_ROLES — pensado para vistas de solo lectura (Estadísticas, 2026-09-16,
    pedido explícito: el cliente asignado a un evento debe poder ver sus estadísticas) donde
    'cliente' sí debe entrar pero 'digitador' (que en la jerarquía queda POR ENCIMA de 'cliente')
    sigue sin poder, porque no le corresponde ver reportes. 'cliente' nunca tiene rol secundario
    (el doble rol solo aplica a coordinador/comercial), así que effective_roles no cambia este caso."""
    minimum_level = ROLE_HIERARCHY[minimum_role]

    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if staff.role == "cliente" or max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) >= minimum_level:
            return staff
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")

    return checker


def require_super_admin(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Solo el Super Admin puede hacer esto")
    return staff


def get_event_for_staff(event_id: int, db: Session, staff: StaffUser) -> Event:
    """Resuelve el evento y valida acceso. coordinador+ tiene alcance de tenant (acceso a
    cualquier evento); digitador/cliente necesitan una EventStaffAuthorization para ESE evento
    puntual, y el evento debe estar en estado 'en_proceso' (ver EVENT_STATUSES en models.py)."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    if staff.role in ("digitador", "cliente"):
        authorized = db.query(EventStaffAuthorization).filter_by(
            event_id=event_id, staff_user_id=staff.id
        ).first()
        if not authorized:
            raise HTTPException(status_code=403, detail="No estás autorizado para este evento")
        if event.status != "en_proceso":
            label = "todavía no ha comenzado" if event.status == "creado" else "ya está finalizado"
            raise HTTPException(status_code=403, detail=f"Este evento {label}")

    return event


def require_event_in_progress(event: Event) -> None:
    """Gate aparte de get_event_for_staff, para las acciones de REGISTRAR en sí
    (recognize/register/bulk_register) — a diferencia del acceso general al evento, esto aplica a
    TODOS los roles por igual, incluido admin/super_admin: si el evento no está 'en_proceso', nadie
    registra, solo se puede ver/editar el evento y gestionar sus usuarios."""
    if event.status != "en_proceso":
        label = "todavía no ha comenzado" if event.status == "creado" else "ya está finalizado"
        raise HTTPException(status_code=403, detail=f"No se puede registrar: este evento {label}")
