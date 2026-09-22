"""Escarapela digital (reunión 2026-09-21, ítem 17): validación del contacto, enlace secreto por persona
y envío automático — correo por Microsoft 365 corporativo (SMTP, ver app/mailer.py) o WhatsApp por
Meta Business (WhatsApp Cloud API) si el contacto es un celular.

Sin proveedor configurado NADA sale al exterior: el mensaje queda como archivo en `data/outbox/` (igual que
el correo del informe final). Variables opcionales: PUBLIC_BASE_URL (dominio público para armar el enlace,
p.ej. https://golden.juandajuzga.com; por defecto el de la petición), WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID /
WHATSAPP_TEMPLATE_NAME / WHATSAPP_TEMPLATE_LANG (WhatsApp Cloud API) — ver .env.example para el detalle de cada una."""
import json
import os
import re
import secrets
import time
import urllib.error
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


# Texto sugerido para el template que hay que dar de alta y mandar a aprobar en Meta Business Manager
# (WhatsApp Manager > Plantillas de mensajes) antes de que esto pueda enviar nada — WhatsApp Cloud API
# exige una plantilla PRE-APROBADA para cualquier mensaje que la empresa inicia (no es una respuesta a
# algo que la persona escribió). Categoría: Utility. 3 variables en el cuerpo, en este orden:
#   {{1}} = nombre de la persona, {{2}} = nombre del evento, {{3}} = enlace (lo arma send_digital_badge).
# Cuerpo sugerido:
#   "Hola {{1}}, tu escarapela digital para el evento {{2}} ya está lista. Ábrela aquí: {{3}}"
# El nombre exacto que le pongas a la plantilla al crearla va en WHATSAPP_TEMPLATE_NAME (.env).
def _send_whatsapp(phone: str, person_name: str, event_name: str, link: str) -> dict:
    token, phone_id = os.getenv("WHATSAPP_TOKEN"), os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    template = os.getenv("WHATSAPP_TEMPLATE_NAME")
    if not (token and phone_id and template):
        os.makedirs(os.path.join("data", "outbox"), exist_ok=True)
        path = os.path.join("data", "outbox", f"{int(time.time())}_whatsapp_{phone.lstrip('+')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Para: {phone}\n\nHola {person_name}, tu escarapela digital para {event_name}: {link}\n")
        return {"sent": False, "detail": f"WhatsApp no configurado — el mensaje quedó guardado en {path}"}
    body = {
        "messaging_product": "whatsapp", "to": phone.lstrip("+"), "type": "template",
        "template": {
            "name": template, "language": {"code": os.getenv("WHATSAPP_TEMPLATE_LANG", "es")},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": person_name}, {"type": "text", "text": event_name}, {"type": "text", "text": link},
            ]}],
        },
    }
    try:
        req = urllib.request.Request(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.load(resp)
        return {"sent": True, "detail": f"WhatsApp enviado a {phone}"}
    except urllib.error.HTTPError as e:
        return {"sent": False, "detail": f"No se pudo enviar el WhatsApp: {e.read().decode(errors='replace')[:300]}"}
    except Exception as e:
        return {"sent": False, "detail": f"No se pudo enviar el WhatsApp: {e}"}


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
        result = _send_whatsapp(contact, person_name, event.name, link)
    attendee.digital_sent_at = datetime.utcnow()
    db.flush()
    return result
