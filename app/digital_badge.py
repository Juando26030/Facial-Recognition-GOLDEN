"""Escarapela digital (reunión 2026-09-21, ítem 17): validación del contacto, enlace secreto por persona
y envío automático por correo (Microsoft Graph / SMTP, ver app/mailer.py).

Decisión 2026-09-21: se descartó WhatsApp (Meta cobra por conversación iniciada por la empresa) — solo
correo, y por eso el campo pasa a ser obligatorio (ver Parámetros del Evento: `set_digital_badge_enabled`
en app/routers/parametros.py deja el campo marcado `required` por defecto al activar el módulo).

Sin correo configurado (ver app/mailer.py) NADA sale al exterior: el mensaje queda como archivo en
`data/outbox/`. Variable opcional: PUBLIC_BASE_URL (dominio público para armar el enlace, confirmado
como https://app.golden-eventos.com; por defecto el de la petición)."""
import os
import re
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app import email_template
from app.mailer import send_mail
from app.models import EventAttendee

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_contact(raw: str) -> Optional[str]:
    """Devuelve el correo limpio; None si viene vacío; lanza ValueError si tiene contenido pero no es un
    correo válido (2026-09-21: ya no se acepta teléfono — la escarapela digital solo se envía por correo)."""
    value = (raw or "").strip()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        raise ValueError("Escribe un correo corporativo válido para la escarapela digital")
    return value.lower()


def ensure_token(db: Session, attendee: EventAttendee) -> str:
    if not attendee.digital_token:
        attendee.digital_token = secrets.token_urlsafe(18)
        db.flush()
    return attendee.digital_token


DEFAULT_BASE_URL = "https://app.golden-eventos.com"      # último recurso: un enlace relativo («/b/…») no sirve en un correo


def send_digital_badge(db: Session, event, attendee: EventAttendee, person_name: str, base_url: str, last_name: str = "") -> dict:
    """Envía el enlace de la escarapela digital al correo guardado y marca el envío. Devuelve
    {"sent": bool, "detail": str} — nunca lanza (el alta de la persona no debe fallar por el envío)."""
    contact = attendee.digital_contact
    if not contact:
        return {"sent": False, "detail": "Sin correo para enviar"}
    link = f"{(os.getenv('PUBLIC_BASE_URL') or base_url or DEFAULT_BASE_URL).rstrip('/')}/b/{ensure_token(db, attendee)}"
    subject, html_body, text_body = email_template.render(event, person_name, last_name, link)
    result = send_mail(contact, subject, text_body, html=html_body)
    attendee.digital_sent_at = datetime.utcnow()
    db.flush()
    return result
