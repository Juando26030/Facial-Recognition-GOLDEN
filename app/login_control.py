"""Ingreso controlado de los digitadores (decisión de Juan David, 6-nov-2026; hallazgo S1 de la revisión de seguridad).

Las cuentas digitador entran con su cédula como usuario y contraseña. Para que conocer una cédula no baste:
  (a) solo se acepta el ingreso si la cuenta está asignada a por lo menos un evento EN PROCESO; si no, el mismo error genérico del login;
  (b) 3 contraseñas malas seguidas BLOQUEAN la cuenta (`staff_users.locked_at`) hasta que la desbloquee quien administra las cuentas temporales del evento;
  (c) cada ingreso con la contraseña correcta queda EN ESPERA: el coordinador lo permite o no desde «Usuarios del evento». El navegador que lo pidió guarda el token
      en su cookie firmada (`session["login_req"]`); en la base solo queda su SHA-256. Vence a los 5 minutos y se usa una sola vez.
(a) y (c) se pueden apagar con DIGITADOR_LOGIN_CONTROL=0 (solo para las pruebas antiguas); (b) siempre aplica. Las demás cuentas y los puestos de impresión no cambian."""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Event, EventStaffAuthorization, StaffUser
from app.timeutil import utcnow

MAX_FAILS = 3
REQUEST_TTL = timedelta(minutes=5)
POLL_SECONDS = 3
SESSION_KEY = "login_req"
LOCKED_MSG = "Tu cuenta está bloqueada. Pídele al coordinador que la desbloquee."
WAIT_MSG = "Esperando que el coordinador autorice tu ingreso…"
DENIED_MSG = "El coordinador no autorizó el ingreso."
EXPIRED_MSG = "La solicitud de ingreso venció. Vuelve a ingresar."
PENDING, APPROVED, DENIED = "pending", "approved", "denied"


def enabled() -> bool:
    return os.getenv("DIGITADOR_LOGIN_CONTROL", "1").strip().lower() not in ("0", "false", "no", "off")


def applies(staff: Optional[StaffUser]) -> bool:
    """¿Esta cuenta sigue el ingreso controlado? Solo las de rol digitador."""
    return staff is not None and staff.role == "digitador"


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def has_event_in_progress(db: Session, staff: StaffUser) -> bool:
    return db.query(EventStaffAuthorization.id).join(Event, Event.id == EventStaffAuthorization.event_id).filter(
        EventStaffAuthorization.staff_user_id == staff.id, Event.status == "en_proceso").first() is not None


def is_locked(staff: Optional[StaffUser]) -> bool:
    return staff is not None and staff.locked_at is not None


def register_fail(db: Session, staff: StaffUser) -> bool:
    """Un intento con la contraseña mala sobre una cuenta digitador. Suma de forma atómica (UPDATE … SET n = n + 1) y bloquea al llegar a MAX_FAILS.
    Devuelve True si la cuenta quedó (o ya estaba) bloqueada. Confirma la transacción."""
    db.query(StaffUser).filter(StaffUser.id == staff.id).update({StaffUser.failed_logins: StaffUser.failed_logins + 1}, synchronize_session=False)
    db.query(StaffUser).filter(StaffUser.id == staff.id, StaffUser.failed_logins >= MAX_FAILS, StaffUser.locked_at.is_(None)).update(
        {StaffUser.locked_at: utcnow()}, synchronize_session=False)
    db.commit()
    db.refresh(staff)
    return staff.locked_at is not None


def reset_fails(staff: StaffUser) -> None:
    staff.failed_logins = 0


def unlock(staff: StaffUser) -> None:
    staff.failed_logins = 0
    staff.locked_at = None


def new_request(staff: StaffUser) -> str:
    """Crea (o reemplaza) la solicitud de ingreso de la cuenta. Devuelve el token en claro: va SOLO a la cookie firmada de ese navegador. El que llama confirma."""
    token = secrets.token_urlsafe(32)
    staff.login_req_hash, staff.login_req_at, staff.login_req_status = token_hash(token), utcnow(), PENDING
    return token


def clear_request(staff: StaffUser) -> None:
    staff.login_req_hash = staff.login_req_at = staff.login_req_status = None


def request_alive(staff: StaffUser, now=None) -> bool:
    return bool(staff.login_req_hash and staff.login_req_at and (now or utcnow()) - staff.login_req_at <= REQUEST_TTL)


def pending(staff: StaffUser, now=None) -> bool:
    """¿Hay alguien esperando que se le autorice el ingreso a esta cuenta (y la solicitud no venció)?"""
    return staff.login_req_status == PENDING and request_alive(staff, now)


def seconds_left(staff: StaffUser, now=None) -> int:
    if not staff.login_req_at:
        return 0
    return max(0, int((staff.login_req_at + REQUEST_TTL - (now or utcnow())).total_seconds()))


def matches(staff: StaffUser, token: Optional[str]) -> bool:
    """¿El token que trae ESTE navegador es el de la solicitud vigente de la cuenta? (comparación en tiempo constante)."""
    return bool(token and staff.login_req_hash and hmac.compare_digest(token_hash(token), staff.login_req_hash))


def consume_approved(db: Session, staff: StaffUser, token: str) -> bool:
    """Usa la autorización UNA sola vez: borra la solicitud solo si sigue aprobada y con este mismo hash (UPDATE condicional; dos sondeos a la vez no entran dos veces). Confirma."""
    n = db.query(StaffUser).filter(StaffUser.id == staff.id, StaffUser.login_req_hash == token_hash(token), StaffUser.login_req_status == APPROVED).update(
        {StaffUser.login_req_hash: None, StaffUser.login_req_at: None, StaffUser.login_req_status: None}, synchronize_session=False)
    db.commit()
    db.refresh(staff)
    return n == 1
