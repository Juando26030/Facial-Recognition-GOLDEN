"""Enlace personal de autorización (B2a): `/aceptar/<código del evento>/<token>`, uno por persona y evento.

El token (`event_attendees.accept_token`, aleatorio, guardado) identifica a la persona, pero la página SIEMPRE pide también su cédula y su fecha de nacimiento (las de ESA persona) antes de abrir la cámara (menores, B2e); 5 fallos en 15 minutos pausan el enlace. Quien ya aceptó ve de inmediato su estado.
`accept_trusted` dice de dónde salió el enlace:
  * del listado que cargó el organizador (correo propio de cada persona): abrirlo y aceptar verifica la aceptación (el dueño del correo es la persona) y entra directo a la matriz facial;
  * de un formulario abierto (el correo lo escribió quien se inscribió): la aceptación sigue «por verificar» hasta que el personal confirme la identidad en puerta.
Volver a generar el enlace (`regenerate`) revoca el anterior."""
import os
import secrets
from typing import Optional

from app import company, publicurl
from app.mailer import send_mail
from app.models import Event, EventAttendee, User
from app.timeutil import utcnow


def issue(db, attendee: EventAttendee, trusted: bool = False) -> str:
    """Token del enlace de esta persona (lo crea si falta). `trusted` solo sube: un enlace confiable no baja a «por verificar» porque el formulario lo vuelva a emitir. No hace commit."""
    if not attendee.accept_token:
        attendee.accept_token = secrets.token_urlsafe(18)
    attendee.accept_trusted = bool(attendee.accept_trusted or trusted)
    db.flush()
    return attendee.accept_token


def regenerate(db, attendee: EventAttendee) -> str:
    """Revoca el enlace anterior y crea uno nuevo (el trust se conserva)."""
    attendee.accept_token = secrets.token_urlsafe(18)
    attendee.accept_sent_at = None
    db.flush()
    return attendee.accept_token


def base_url(request_base: str = "") -> str:
    return publicurl.base(request_base)


def url(event: Event, token: str, request_base: str = "") -> Optional[str]:
    base = base_url(request_base)
    return f"{base}/aceptar/{event.event_code}/{token}" if base else None


def render_link_email(event: Event, first_name: str, link: str) -> tuple:
    """(asunto, texto) del correo con el enlace. Lleva «voluntario» y «sin restricción»: es una invitación, no la autorización (esa es la pantalla)."""
    name = company.get("COMPANY_NAME")
    subject = f"Entra más rápido a {event.name}: autoriza el uso de tu rostro (opcional)"
    body = (f"Hola {first_name or ''}:\n\nPara entrar más rápido a {event.name} puedes autorizar el uso de tu rostro. Es totalmente voluntario: si no lo haces, entras con tu cédula "
            f"o con el código QR de tu escarapela, sin ninguna restricción.\n\nAbre tu enlace personal:\n{link}\n\nEs personal y solo sirve para ti: no lo compartas.\n\n{name}")
    return subject, body


def send_link(db, event: Event, user: User, attendee: EventAttendee, to: str, trusted: bool, request_base: str = "") -> dict:
    """Envía el enlace personal por correo. Nunca lanza. Devuelve {"sent": bool, "detail": str}."""
    token = issue(db, attendee, trusted)
    link = url(event, token, request_base)
    if not link:
        return {"sent": False, "detail": "Falta PUBLIC_BASE_URL: no se puede armar el enlace"}
    subject, body = render_link_email(event, user.first_name or "", link)
    result = send_mail(to, subject, body, reply_to=company.get("PRIVACY_EMAIL"))
    if result.get("sent"):
        attendee.accept_sent_at = utcnow()
        db.flush()
    return result
