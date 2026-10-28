"""Correo de constancia de la autorización (B2b). Texto APROBADO por la auditora (versión optimizada, 8-oct-2026, ver docs/legal/RESPUESTAS_AUDITORA_2026-10-08.md).

Se envía cuando la persona ACEPTA (por su enlace personal, el portal web, el QR del cartel o en la puerta), como tarea en segundo plano: la puerta nunca espera. No lleva la foto. Estructura:
saludo, escarapela virtual (si el evento la tiene), detalles de la constancia, cómo revocar (sin fricción) y, AL FINAL como anexo, el texto literal que la persona aceptó, tomado del archivo de la
auditora (`app/legal_texts_data.py`) sin reescribirlo; solo se incluye si su huella coincide con la registrada en `audit_consent_logs` (si el texto cambió desde entonces, el anexo dice que está
disponible a solicitud). Las respuestas llegan a PRIVACY_EMAIL (buzón atendido). Solo eventos propios de Golden: para el de un tercero el Responsable es el organizador y falta su redacción aprobada."""
import html
import logging
import re
from datetime import timezone

from app import company, digital_badge, jobs, legal_texts
from app.database import SessionLocal
from app.mailer import send_mail
from app.models import AuditConsentLog, Event, EventAttendee, User
from app.timeutil import to_local

log = logging.getLogger("golden.receipt")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# Cuatro frases fijas (definidas por la dueña del producto con la auditora): ninguna descripción técnica
CHANNELS = {
    "link": "Enlace único enviado a este correo",
    "web": "Portal web del evento",
    "qr": "Escaneo de código QR en la entrada",
    "door": "En la puerta, con el personal de acreditación",
}
WEB_CHANNELS = ("link", "web", "qr")


def channel_of(device: str) -> str:
    """Canal a partir de la etiqueta de dispositivo del registro (`web-link`, `web-qr`, `web-portal`...); lo demás (quiosco, personal) es la puerta."""
    d = (device or "").lower()
    if d.startswith("web-link"):
        return "link"
    if d.startswith("web-qr"):
        return "qr"
    if d.startswith("web"):
        return "web"
    return "door"


def enqueue(db, entry_id: str, tenant_id: str, event_id: int, user_id: str, channel: str) -> None:
    """Encola la constancia (una por registro de aceptación; repetirlo no duplica). No hace commit."""
    jobs.enqueue(db, "consent_receipt", {"entry_id": entry_id, "tenant_id": tenant_id, "event_id": int(event_id), "user_id": str(user_id), "channel": channel},
                 dedupe_key=f"receipt:{entry_id}", max_attempts=4)


def _paragraphs(consent_text: dict) -> list:
    return [consent_text["title"]] + list(consent_text["body"])


def render(event: Event, user: User, entry: AuditConsentLog, channel: str, badge_link: str = "") -> dict:
    """{subject, text, html}. Sin I/O: se prueba con datos."""
    nombre = (user.first_name or "").strip()
    titular = f"{user.first_name or ''} {user.last_name or ''}".strip() or str(user.id)
    last3 = str(user.id)[-3:]
    fecha_evento = event.start_date.strftime("%d/%m/%Y") if event.start_date else ""
    evento_fecha = f"{event.name} - {fecha_evento}" if fecha_evento else event.name
    ts = entry.consent_timestamp_utc
    cuando = to_local(ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts).strftime("%d/%m/%Y %H:%M")
    empresa = f"{company.get('COMPANY_NAME')}, NIT {company.get('COMPANY_NIT')}"
    privacy_mail = company.get("PRIVACY_EMAIL")
    policy = company.policy_url()
    current = legal_texts.render(event, web=channel in WEB_CHANNELS)
    same = current["hash"] == entry.legal_text_hash
    short = entry.legal_text_hash[:12]
    subject = f"Tu autorización para entrar con reconocimiento facial — {event.name}"

    details = [
        ("Titular", f"{titular}, documento terminado en ***{last3}"),
        ("Evento", evento_fecha),
        ("Canal de autorización", CHANNELS[channel]),
        ("Fecha y hora", f"{cuando} (Hora de Colombia)"),
        ("Responsable del tratamiento", empresa),
        ("Propósito y retención", "Identificarte ágilmente en la puerta. Tu fotografía y vector facial serán eliminados de nuestros servidores 7 días después de finalizado el evento. "
                                  "Este correo no incluye tu foto por seguridad."),
    ]
    revoke = (f"¿Cambiaste de opinión? Puedes revocar este permiso en cualquier momento escribiendo a {privacy_mail} o notificándolo directamente al personal de logística en la puerta. "
              "Revocarlo no afecta tu acceso; simplemente seguirás entrando con tu cédula o el código QR de tu escarapela.")
    policy_line = f"Consulta nuestra Política de privacidad completa aquí: {policy}"
    anexo_title = f"Anexo: Texto literal que aprobaste (Versión: {entry.consent_version} | Identificador de seguridad: {short})"
    paragraphs = _paragraphs(current) if same else []
    anexo_missing = f"El texto de esa versión ({entry.consent_version}) ya no es el vigente; está disponible a solicitud en {privacy_mail}."
    badge_line = f"🎫 Tu escarapela virtual: {badge_link} (Puedes usar este enlace en cualquier momento para ver tu código de acceso)." if badge_link else ""

    t = [f"Hola {nombre}:", "", f"Recibimos tu autorización para usar tu rostro como método de ingreso rápido a {event.name}.", ""]
    if badge_line:
        t += [badge_line, ""]
    t += ["Detalles de tu autorización (Constancia de Habeas Data)"] + [f"- {k}: {v}" for k, v in details] + ["", revoke, policy_line, "", "-" * 40, anexo_title, ""]
    t += paragraphs if same else [anexo_missing]
    text = "\n".join(t)

    e = html.escape
    li = "".join(f"<li><b>{e(k)}:</b> {e(v)}</li>" for k, v in details)
    anexo_html = "".join(f"<p style=\"margin:0 0 8px\">{e(p)}</p>" for p in paragraphs) if same else f"<p>{e(anexo_missing)}</p>"
    badge_html = f"<p>🎫 Tu escarapela virtual: <a href=\"{e(badge_link)}\">{e(badge_link)}</a><br><span style=\"color:#666\">Puedes usar este enlace en cualquier momento para ver tu código de acceso.</span></p>" if badge_link else ""
    html_body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\">"
                 f"<p>Hola {e(nombre)}:</p><p>Recibimos tu autorización para usar tu rostro como método de ingreso rápido a <b>{e(event.name)}</b>.</p>{badge_html}"
                 f"<h3 style=\"margin:18px 0 6px\">Detalles de tu autorización (Constancia de Habeas Data)</h3><ul style=\"padding-left:18px\">{li}</ul>"
                 f"<p>{e(revoke)}</p><p>Consulta nuestra Política de privacidad completa <a href=\"{e(policy)}\">aquí</a>.</p>"
                 f"<hr style=\"border:none;border-top:1px solid #ccc;margin:22px 0\"><div style=\"font-size:12px;color:#555\"><p style=\"margin:0 0 8px\"><b>{e(anexo_title)}</b></p>{anexo_html}</div></div>")
    return {"subject": subject, "text": text, "html": html_body}


def _recipient(att: EventAttendee, user: User) -> str:
    for candidate in (att.digital_contact if att else None, user.email):
        c = (candidate or "").strip()
        if _EMAIL.match(c):
            return c.lower()
    return ""


@jobs.handler("consent_receipt")
def run_receipt(payload: dict) -> None:
    tenant, uid, event_id, entry_id, channel = payload["tenant_id"], str(payload["user_id"]), int(payload["event_id"]), payload["entry_id"], payload.get("channel", "door")
    with SessionLocal() as db:
        event = db.get(Event, event_id)
        user = db.query(User).filter(User.id == uid, User.tenant_id == tenant).first()
        entry = db.get(AuditConsentLog, entry_id)
        if event is None or user is None or entry is None or entry.reason != "consent" or not entry.accepted_biometric:
            return                                           # la persona ya no existe (supresión) o ese registro no es una aceptación
        if event.controller_mode != "golden" or channel not in CHANNELS:
            return                                           # eventos de terceros: falta la redacción aprobada del Responsable
        att = db.query(EventAttendee).filter_by(event_id=event_id, user_id=uid).first()
        to = _recipient(att, user)
        if not to:
            return                                           # sin correo no hay constancia (no es un error)
        badge_link = ""
        if att is not None and event.digital_badge_enabled:
            base = (company.policy_url().rsplit("/privacidad", 1)[0])
            badge_link = f"{base}/b/{digital_badge.ensure_token(db, att)}"
            db.commit()
        mail = render(event, user, entry, channel, badge_link)
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"], reply_to=company.get("PRIVACY_EMAIL"))
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("constancia: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar la constancia")          # el trabajo se reintenta con espera creciente
