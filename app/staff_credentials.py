"""Entrega de credenciales del personal por CORREO (Fase 4). Decisión del dueño: los digitadores temporales ingresan SOLO con su cédula y el coordinador los autoriza (no hay contraseña que
entregar); no hay WhatsApp ni SMS. Además existe la hoja impresa (templates/kiosk_usuarios_hoja.html).

Reglas de seguridad:
  * El correo NUNCA lleva una contraseña. Cuentas que no son de digitador: «tu contraseña inicial es tu número de documento» (si lo es) o «te la comunicó quien creó tu cuenta», y el aviso de que el
    sistema pedirá cambiarla en el primer ingreso. Digitadores: «ingresa con tu cédula; el coordinador del evento te autorizará al llegar».
  * Sin enlaces con tokens ni sesión: solo la pantalla de ingreso (`PUBLIC_BASE_URL`), siempre https (salvo localhost en desarrollo).
  * Asunto por `mailer.clean_subject` (la propia `send_mail` también lo limpia), todo texto de personas escapado en el HTML.
  * Nada de datos personales en logs ni en el trabajo en cola (solo ids y banderas); el trabajo es idempotente (`dedupe_key`) y se encola en la MISMA transacción de la acción.
  * Reenviar: máximo `RESEND_PER_DAY` por persona cada 24 h, contado en `audit_actions` (solo INSERT, sin datos personales).
"""
import html
import logging
import re
from datetime import timedelta
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app import jobs, publicurl
from app.database import SessionLocal
from app.mailer import clean_subject, send_mail
from app.models import AuditAction, Event, EventStaffAuthorization, StaffUser
from app.timeutil import utcnow

log = logging.getLogger("golden.staffcred")

KIND = "staff_credentials"
RESEND_PER_DAY = 3
RESEND_WINDOW = timedelta(hours=24)
RESEND_ACTION = "resend_credentials"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-']{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,}$")          # sin comas, punto y coma, comillas ni espacios (un solo destinatario)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "testserver")

ROLE_LABELS = {"digitador": "digitador", "coordinador": "coordinador", "dir_coordinadores": "director de coordinadores", "comercial": "comercial", "admin": "administrador", "super_admin": "superadministrador", "cliente": "cliente"}
ROLE_INSTRUCTIONS = {
    "digitador": "Con tu cuenta registras y acreditas a las personas en la puerta del evento.",
    "dir_coordinadores": "Con tu cuenta administras los eventos como coordinador, asignas coordinadores a los eventos y revisas las legalizaciones.",
    "coordinador": "Con tu cuenta administras los eventos que te asignen: personal temporal, parámetros, registro y reportes.",
    "comercial": "Con tu cuenta gestionas clientes y eventos, y recibes los informes finales.",
    "admin": "Con tu cuenta administras la plataforma de tu cuenta de cliente: eventos, personal y configuración.",
    "super_admin": "Con tu cuenta administras toda la plataforma.",
    "cliente": "Con tu cuenta consultas la información que se te haya compartido.",
}
MODES = ("created", "reset", "resend", "assigned")
SUBJECTS = {"created": "Tu cuenta de GoldenWeb 2.0", "assigned": "Fuiste asignado a un evento en GoldenWeb 2.0",
            "reset": "Restablecimos tu acceso a GoldenWeb 2.0", "resend": "Tus datos de ingreso a GoldenWeb 2.0"}


def valid_email(value) -> str:
    """Correo normalizado en minúsculas o '' si no tiene forma de correo."""
    v = (value or "").strip()
    return v.lower() if _EMAIL.match(v) else ""


def login_url(request_base: str = "") -> str:
    """Pantalla de ingreso del entorno (`PUBLIC_BASE_URL`), siempre https (salvo localhost en desarrollo). Vacío si el entorno no tiene dirección pública."""
    base = publicurl.base(request_base)
    if not base:
        return ""
    parts = urlsplit(base)
    if parts.scheme == "http" and (parts.hostname or "") not in _LOCAL_HOSTS:
        base = "https://" + base[len("http://"):]
    return base + "/login"


def password_mode(staff: StaffUser, plain: Optional[str] = None) -> str:
    """'cedula' si la contraseña inicial es el número de documento (usuario); 'given' si la entregó quien creó la cuenta. `plain` solo se compara, nunca se guarda ni se envía."""
    if staff.role == "digitador":
        return "cedula"
    if plain is not None:
        return "cedula" if plain == staff.username else "given"
    from app.auth import verify_password
    return "cedula" if verify_password(staff.username, staff.password_hash) else "given"


# ------------------------------------------------------------------ contenido (sin I/O: se prueba con datos)
def _password_line(role: str, pw: str, must_change: bool) -> str:
    if role == "digitador":
        return "No necesitas contraseña que recordar: ingresa con tu cédula. El coordinador del evento te autorizará al llegar."
    base = ("Tu contraseña inicial es tu número de documento." if pw == "cedula"
            else "Tu contraseña inicial te la comunicó quien creó tu cuenta (por tu seguridad no va en este correo).")
    return base + (" El sistema te pedirá cambiarla en tu primer ingreso." if must_change else "")


def render(mode: str, *, name: str, username: str, role: str, pw: str, must_change: bool, url: str, event: Optional[dict] = None) -> dict:
    """{subject, text, html}. `event`: {name, date, place, coordinator} (solo para digitadores asignados)."""
    nombre = (name or "").strip()
    saludo = f"Hola {nombre}:" if nombre else "Hola:"
    rol = ROLE_LABELS.get(role, role)
    intro = {"created": f"Se creó tu cuenta de {rol} en GoldenWeb 2.0, la plataforma de acreditación de Golden Eventos y Logística.",
             "assigned": "Te asignaron a un evento en GoldenWeb 2.0, la plataforma de acreditación de Golden Eventos y Logística.",
             "reset": f"Restablecimos el acceso de tu cuenta de {rol} en GoldenWeb 2.0.",
             "resend": f"Te reenviamos los datos para ingresar a tu cuenta de {rol} en GoldenWeb 2.0."}[mode]
    lines = [("Usuario", username)]
    if event:
        lines = [("Evento", event.get("name") or ""), ("Fecha", event.get("date") or ""), ("Lugar", event.get("place") or ""), ("Coordinador", event.get("coordinator") or "")] + lines
    lines = [(k, v) for k, v in lines if v]
    dest = url or "la dirección web de GoldenWeb que te indique tu coordinador"
    steps = [f"Entra a {dest}.", f"Escribe tu usuario: {username}.",
             _password_line(role, pw, must_change)]
    if role == "digitador":
        steps.append("Cuando el coordinador autorice tu ingreso, ya puedes registrar personas.")
    aviso = ROLE_INSTRUCTIONS.get(role, "")
    cierre = "Si no esperabas este correo, ignóralo o avísale a tu coordinador. Nunca compartas tu usuario con otras personas."
    text = "\n".join([saludo, "", intro, aviso, ""] + [f"- {k}: {v}" for k, v in lines] + ["", "Cómo ingresar:"] + [f"{i}. {s}" for i, s in enumerate(steps, 1)] + ["", cierre])
    e = html.escape
    li = "".join(f"<li><b>{e(k)}:</b> {e(v)}</li>" for k, v in lines)
    ol = "".join(f"<li>{e(s)}</li>" for s in steps[1:])
    entrar = f"<a href=\"{e(url)}\">{e(url)}</a>" if url else e(dest)
    html_body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\">"
                 f"<p>{e(saludo)}</p><p>{e(intro)} {e(aviso)}</p><ul style=\"padding-left:18px\">{li}</ul>"
                 f"<h3 style=\"margin:18px 0 6px\">Cómo ingresar</h3><ol style=\"padding-left:18px\"><li>Entra a {entrar}.</li>{ol}</ol>"
                 f"<p style=\"font-size:13px;color:#555\">{e(cierre)}</p></div>")
    return {"subject": clean_subject(SUBJECTS[mode]), "text": text, "html": html_body}


# ------------------------------------------------------------------ encolar (misma transacción de la acción; el que llama confirma y luego hace jobs.kick())
def enqueue(db: Session, target: StaffUser, mode: str, *, event: Optional[Event] = None, pw: Optional[str] = None, nonce: str = "") -> bool:
    """Encola el correo de credenciales. False (y no encola) si la cuenta no tiene un correo válido. Un mismo (cuenta, modo, evento, nonce) no se repite."""
    if mode not in MODES or not valid_email(target.email):
        return False
    event_id = int(event.id) if event is not None else 0
    jobs.enqueue(db, KIND, {"staff_id": int(target.id), "mode": mode, "event_id": event_id, "pw": pw or password_mode(target)}, max_attempts=4,
                 dedupe_key=f"{KIND}:{mode}:{target.id}:{event_id}:{nonce}")
    return True


def enqueue_for_event(db: Session, target: StaffUser, mode: str, event: Event, *, nonce: str = "") -> bool:
    """Alta/asignación de un digitador a un evento: respeta el interruptor del evento («Correos a los digitadores»)."""
    if not event.staff_mail_enabled:
        return False
    return enqueue(db, target, mode, event=event, nonce=nonce)


def resends_today(db: Session, target_id: int) -> int:
    since = utcnow() - RESEND_WINDOW
    return db.query(AuditAction).filter(AuditAction.action == RESEND_ACTION, AuditAction.entity == "staff_user", AuditAction.entity_id == str(target_id), AuditAction.at >= since).count()


def event_info(db: Session, event: Event) -> dict:
    coord = db.get(StaffUser, event.coordinator_staff_id) if event.coordinator_staff_id else None
    return {"name": event.name, "date": event.start_date.strftime("%d/%m/%Y") if event.start_date else "",
            "place": ", ".join(x for x in ((event.location or "").strip(), (event.city or "").strip()) if x),
            "coordinator": ((coord.full_name or "").strip() if coord is not None else "")}


@jobs.handler("staff_credentials")
def run_mail(payload: dict) -> None:
    sid, mode, event_id = int(payload["staff_id"]), payload.get("mode"), int(payload.get("event_id") or 0)
    if mode not in MODES:
        return
    with SessionLocal() as db:
        target = db.get(StaffUser, sid)
        to = valid_email(target.email) if target is not None else ""
        if target is None or not to or not target.is_active or target.archived_at is not None:
            return                                           # la cuenta ya no existe, está archivada o no tiene correo: no es un error
        ev = None
        if event_id:
            event = db.get(Event, event_id)
            if event is None or (mode != "resend" and not event.staff_mail_enabled) or not db.query(EventStaffAuthorization.id).filter_by(event_id=event_id, staff_user_id=sid).first():
                return                                       # se apagó el interruptor o ya no está asignado: no se avisa
            ev = event_info(db, event)
        mail = render(mode, name=target.full_name or "", username=target.username, role=target.role, pw=str(payload.get("pw") or "given"),
                      must_change=bool(target.must_change_password), url=login_url(), event=ev)
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("credenciales: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el correo de credenciales")          # se reintenta con espera creciente
