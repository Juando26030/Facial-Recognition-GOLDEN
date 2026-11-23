"""«Código» opcional por evento (0140): un serial aparte de la cédula que identifica a la persona al escanear su QR.

Reglas (pedido de Juan David, 12-nov-2026):
- El evento decide si lo usa (`Event.code_enabled`) y si es obligatorio al registrar (`Event.code_required`).
- El código vive en `EventAttendee.code` (por persona y evento). Es único dentro del evento SIN distinguir mayúsculas y NUNCA puede ser igual a una identificación
  (ni la de una persona del cliente, ni la de una de este evento); y a la inversa, no se puede registrar una identificación igual a un código ya usado en el evento.
- Al escanear se busca primero por identificación y, si no está y el evento usa código, por código. Un código que no existe se trata igual que una cédula que no existe.

Solo lógica de datos: no hace commit (lo hace quien llama) y no escribe en logs (ni cédulas ni códigos).
"""
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Event, EventAttendee, User

MAX_CODE_LENGTH = 64


class CodeError(ValueError):
    """El código no es válido; el mensaje se muestra tal cual al usuario (español, sin datos personales)."""


def normalize(value) -> str:
    """Código limpio: sin espacios en los extremos. Vacío = sin código."""
    return str(value or "").strip()


def _holder(db: Session, event: Event, code: str) -> Optional[EventAttendee]:
    return db.query(EventAttendee).filter(EventAttendee.event_id == event.id, func.lower(EventAttendee.code) == code.lower()).first()


def validate(db: Session, event: Event, code, user_id: Optional[str] = None) -> str:
    """Devuelve el código limpio o lanza `CodeError`. `user_id` = la persona que lo recibe (puede conservar el suyo). Código vacío = '' (sin código)."""
    code = normalize(code)
    if not code:
        return ""
    if len(code) > MAX_CODE_LENGTH:
        raise CodeError(f"El código es demasiado largo (máximo {MAX_CODE_LENGTH} caracteres)")
    if user_id is not None and code.lower() == str(user_id).strip().lower():
        raise CodeError("El código no puede ser igual a la identificación de la persona")
    taken_by_id = db.query(User.id).filter(User.tenant_id == event.tenant_id, func.lower(User.id) == code.lower()).first()
    if taken_by_id:
        raise CodeError("Ese código es igual a una identificación ya registrada: usa otro")
    holder = _holder(db, event, code)
    if holder and (user_id is None or holder.user_id != user_id):
        raise CodeError("Ese código ya está asignado a otra persona de este evento")
    return code


def id_collides_with_code(db: Session, event: Event, user_id) -> bool:
    """¿La identificación que se va a registrar es igual a un código ya usado en el evento? (con el código apagado nunca choca)."""
    if not event.code_enabled:
        return False
    user_id = str(user_id or "").strip()
    return bool(user_id) and _holder(db, event, user_id) is not None


def require_free_id(db: Session, event: Event, user_id) -> None:
    if id_collides_with_code(db, event, user_id):
        raise CodeError("Esa identificación es igual a un código ya asignado en este evento: revisa el número")


def set_code(db: Session, event: Event, user_id: str, code, *, required: Optional[bool] = None) -> Optional[str]:
    """Fija (o borra, con vacío) el código de la persona en el evento. Con `required` (por defecto el del evento) y el código activo, no se puede dejar vacío al ASIGNAR por primera vez.
    Devuelve el código guardado (None = sin código). La persona debe estar en el evento (`EventAttendee`)."""
    if not event.code_enabled:
        raise CodeError("Este evento no usa código")
    row = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user_id).first()
    if row is None:
        raise CodeError("La persona no está en este evento")
    clean = validate(db, event, code, user_id)
    must = event.code_required if required is None else required
    if must and not clean:
        raise CodeError("En este evento el código es obligatorio")
    row.code = clean or None
    db.flush()
    return row.code


def find_user(db: Session, event: Event, value) -> Tuple[Optional[User], str]:
    """Busca a la persona por lo que trae el escaneo o lo digitado. Devuelve (User | None, vía) con vía = 'id' | 'code' | ''.
    Primero identificación (cualquier persona del cliente); si no está y el evento usa código, el código dentro del evento."""
    value = normalize(value)
    if not value:
        return None, ""
    user = db.query(User).filter(User.id == value, User.tenant_id == event.tenant_id).first()
    if user:
        return user, "id"
    if event.code_enabled:
        row = _holder(db, event, value)
        if row:
            user = db.query(User).filter(User.id == row.user_id, User.tenant_id == event.tenant_id).first()
            if user:
                return user, "code"
    return None, ""


def code_of(db: Session, event: Event, user_id: str) -> Optional[str]:
    row = db.query(EventAttendee.code).filter(EventAttendee.event_id == event.id, EventAttendee.user_id == user_id).first()
    return row[0] if row else None
