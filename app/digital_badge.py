"""Escarapela digital (reunión 2026-09-21, ítem 17): validación del contacto, enlace secreto por persona
y envío automático (correo por SMTP, o SMS por Twilio si está configurado).

Sin proveedor configurado NADA sale al exterior: el mensaje queda como archivo en `data/outbox/` (igual que
el correo del informe final). Variables opcionales: PUBLIC_BASE_URL (dominio público para armar el enlace;
por defecto el de la petición), TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM (SMS)."""
import base64
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.mailer import send_mail
from app.models import EventAttendee

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_contact(raw: str) -> Optional[str]:
    """Devuelve el contacto limpio si es un correo o un teléfono válidos; None si viene vacío;
    lanza ValueError si tiene contenido pero no es ninguno de los dos."""
    value = (raw or "").strip()
    if not value:
        return None
    if "@" in value:
        if not _EMAIL_RE.match(value):
            raise ValueError("El correo para la escarapela digital no es válido")
        return value.lower()
    digits = re.sub(r"\D", "", value)
    if not re.fullmatch(r"\+?[\d\s\-()]{7,20}", value) or not 7 <= len(digits) <= 15:
        raise ValueError("Escribe un correo o un teléfono válido para la escarapela digital (7 a 15 dígitos)")
    return ("+" if value.startswith("+") else "") + digits


def ensure_token(db: Session, attendee: EventAttendee) -> str:
    if not attendee.digital_token:
        attendee.digital_token = secrets.token_urlsafe(18)
        db.flush()
    return attendee.digital_token


def _send_sms(phone: str, text: str) -> dict:
    sid, token, sender = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"), os.getenv("TWILIO_FROM")
    if not (sid and token and sender):
        os.makedirs(os.path.join("data", "outbox"), exist_ok=True)
        path = os.path.join("data", "outbox", f"{int(time.time())}_sms_{phone.lstrip('+')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Para: {phone}\n\n{text}\n")
        return {"sent": False, "detail": f"SMS no configurado — el mensaje quedó guardado en {path}"}
    try:
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=urllib.parse.urlencode({"To": phone if phone.startswith("+") else "+" + phone, "From": sender, "Body": text}).encode(),
        )
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.load(resp)
        return {"sent": True, "detail": f"SMS enviado a {phone}"}
    except Exception as e:
        return {"sent": False, "detail": f"No se pudo enviar el SMS: {e}"}


def send_digital_badge(db: Session, event, attendee: EventAttendee, person_name: str, base_url: str) -> dict:
    """Envía el enlace de la escarapela digital al contacto guardado y marca el envío. Devuelve
    {"sent": bool, "detail": str} — nunca lanza (el alta de la persona no debe fallar por el envío)."""
    contact = attendee.digital_contact
    if not contact:
        return {"sent": False, "detail": "Sin contacto para enviar"}
    link = f"{(os.getenv('PUBLIC_BASE_URL') or base_url).rstrip('/')}/b/{ensure_token(db, attendee)}"
    if "@" in contact:
        result = send_mail(
            contact, f"Tu escarapela digital — {event.name}",
            f"Hola {person_name}, esta es tu escarapela digital para {event.name}. Ábrela desde tu celular el día del evento:\n\n{link}\n\n"
            "Es personal: no compartas el enlace ni capturas de pantalla (la escarapela muestra una animación y la hora en vivo).",
        )
    else:
        result = _send_sms(contact, f"Tu escarapela digital para {event.name}: {link}")
    attendee.digital_sent_at = datetime.utcnow()
    db.flush()
    return result
