"""Cliente de FORMULARIO: una cuenta con rol «cliente» que solo ve las estadísticas (agregados, sin datos personales) de UN formulario.

Cómo se aísla (sin tocar `get_event_for_staff`): la cuenta se crea SIN `EventStaffAuthorization`, así que `get_event_for_staff` le responde 403 en cualquier ruta de cualquier evento, y su
único permiso es la fila de `form_client_users` (formulario + vencimiento). Los clientes de EVENTO no cambian: no tienen fila aquí, y el cliente de formulario no tiene autorización de evento."""
import secrets
import string
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import assert_event_tenant
from app.models import Event, FormClientUser, StaffUser, WebForm
from app.timeutil import utcnow

DEFAULT_DAYS = 30
MAX_DAYS = 180


def grant_for(db: Session, staff: StaffUser) -> Optional[FormClientUser]:
    if staff.role != "cliente":
        return None
    return db.query(FormClientUser).filter(FormClientUser.staff_user_id == staff.id).first()


def is_form_client(db: Session, staff: StaffUser) -> bool:
    return grant_for(db, staff) is not None


def resolve(db: Session, staff: StaffUser) -> tuple:
    """(grant, formulario, evento) del cliente de formulario, o 403/404/410. El formulario sale SIEMPRE de la fila de la cuenta, nunca de un parámetro del cliente."""
    grant = grant_for(db, staff)
    if not grant:
        raise HTTPException(status_code=403, detail="Esta cuenta no tiene un formulario asignado")
    if grant.expires_at <= utcnow():
        raise HTTPException(status_code=403, detail="Tu acceso a las estadísticas venció. Pide uno nuevo a tu contacto de Golden.")
    form = db.query(WebForm).filter(WebForm.id == grant.form_id).first()
    event = db.query(Event).filter(Event.id == form.event_id).first() if form else None
    if not form or not event:
        raise HTTPException(status_code=404, detail="El formulario ya no existe")
    assert_event_tenant(event, staff)
    return grant, form, event


def new_password() -> str:
    """Contraseña temporal segura (14 caracteres, sin los que se confunden al leerlos: 0/O, 1/l/I), con mayúsculas, minúsculas y números."""
    letters = "".join(c for c in string.ascii_letters if c not in "lIO")
    digits = "23456789"
    alphabet = letters + digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and sum(c in digits for c in pw) >= 2:
            return pw


def new_username(db: Session, form: WebForm) -> str:
    while True:
        name = f"cliente-f{form.id}-{secrets.token_hex(2)}"
        if not db.query(StaffUser.id).filter(StaffUser.username == name).first():
            return name


def expiry(days: int):
    return utcnow() + timedelta(days=max(1, min(int(days), MAX_DAYS)))
