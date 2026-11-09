"""Entrega de credenciales del personal por correo (Fase 4; reglas en app/staff_credentials.py).

  POST  /api/events/{id}/staff-users/{staff_id}/resend-credentials   reenviar el correo a un digitador del evento (coordinador+; no la comercial pura); máximo 3 por persona cada 24 h
  PATCH /api/events/{id}/staff-users/{staff_id}/email                 completar/corregir el correo de un digitador del evento (coordinador+)
  PATCH /api/events/{id}/staff-mail                                   {"enabled": bool}: interruptor «correo a los digitadores asignados» del evento
  POST  /api/staff/{staff_id}/resend-credentials                      reenviar a una cuenta que NO es de digitador y aún no eligió su contraseña (quien puede administrarla)
Sin datos personales en el registro de auditoría ni en el log; mensajes en español."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_actions, jobs, staff_credentials as sc
from app.auth import effective_roles, get_event_for_staff, require_role
from app.database import get_db
from app.models import EventStaffAuthorization, StaffUser
from app.timeutil import utcnow
from app.routers.staff import _assert_can_manage, _manageable_roles

router = APIRouter()
NO_EMAIL = "Esta cuenta no tiene un correo registrado. Agrégalo o entrega la hoja impresa."
LIMIT_MSG = f"Ya se reenviaron {sc.RESEND_PER_DAY} correos a esta persona en las últimas 24 horas. Entrégale la hoja impresa o inténtalo más tarde."


def _can_manage_temp(staff: StaffUser) -> None:
    if effective_roles(staff).issubset({"comercial"}):
        raise HTTPException(status_code=403, detail="Un comercial no puede administrar cuentas digitador")


def _locked_target(db: Session, staff_id: int) -> StaffUser:
    """La cuenta bajo candado de fila: dos reenvíos simultáneos no se saltan el tope."""
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).with_for_update().first()
    if target is None or target.archived_at is not None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return target


def _resend(db: Session, actor: StaffUser, target: StaffUser, detail: str, event=None) -> dict:
    if not sc.valid_email(target.email):
        raise HTTPException(status_code=400, detail=NO_EMAIL)
    used = sc.resends_today(db, target.id)
    if used >= sc.RESEND_PER_DAY:
        raise HTTPException(status_code=429, detail=LIMIT_MSG)
    audit_actions.record(db, actor, sc.RESEND_ACTION, "staff_user", target.id, None, detail)          # sin nombre ni correo: solo ids
    sc.enqueue(db, target, "resend", event=event, nonce=f"{used + 1}:{utcnow().strftime('%Y%m%d')}")
    db.commit()
    jobs.kick()
    return {"message": "Correo en camino", "remaining_today": sc.RESEND_PER_DAY - used - 1}


@router.post("/events/{event_id}/staff-users/{staff_id}/resend-credentials")
def resend_event_staff(event_id: int, staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    _can_manage_temp(staff)
    event = get_event_for_staff(event_id, db, staff)          # solo sus eventos (tenant y pertenencia)
    target = _locked_target(db, staff_id)
    if target.role != "digitador" or not db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=target.id).first():
        raise HTTPException(status_code=404, detail="Esa persona no está en este evento")
    return _resend(db, staff, target, f"evento: {event.id}", event=event)


@router.patch("/events/{event_id}/staff-users/{staff_id}/email")
def set_event_staff_email(event_id: int, staff_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    _can_manage_temp(staff)
    event = get_event_for_staff(event_id, db, staff)
    target = db.query(StaffUser).filter(StaffUser.id == staff_id, StaffUser.role == "digitador").first()
    if target is None or not db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=target.id).first():
        raise HTTPException(status_code=404, detail="Esa persona no está en este evento")
    raw = str(data.get("email") or "").strip()
    if raw and not sc.valid_email(raw):
        raise HTTPException(status_code=400, detail="Correo con formato inválido")
    target.email = sc.valid_email(raw) or None
    db.commit()
    return {"has_email": bool(target.email)}


@router.patch("/events/{event_id}/staff-mail")
def set_event_staff_mail(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    _can_manage_temp(staff)
    event = get_event_for_staff(event_id, db, staff)
    enabled = bool(data.get("enabled"))
    if enabled != bool(event.staff_mail_enabled):
        audit_actions.record(db, staff, "update", "event_staff_mail_enabled", event.id, event.name, f"{bool(event.staff_mail_enabled)} -> {enabled}")
        event.staff_mail_enabled = enabled
        db.commit()
    return {"enabled": bool(event.staff_mail_enabled)}


@router.post("/staff/{staff_id}/resend-credentials")
def resend_account(staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    target = _locked_target(db, staff_id)
    if target.id == staff.id:
        raise HTTPException(status_code=400, detail="No puedes reenviarte tus propios datos")
    if target.role == "digitador" or target.role not in _manageable_roles(staff):
        raise HTTPException(status_code=403, detail=f"No puedes reenviar los datos de una cuenta '{target.role}'")
    _assert_can_manage(db, staff, target)
    if not target.must_change_password:
        raise HTTPException(status_code=400, detail="Esa persona ya eligió su propia contraseña. Si la olvidó, restablécela.")
    return _resend(db, staff, target, f"rol: {target.role}")
