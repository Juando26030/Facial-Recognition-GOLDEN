"""Entrega al cliente de un evento FACTURADO (Fase 5, B): enlace público `/entrega/<token>` → encuesta de satisfacción → descarga de la base final. Ver docs/FASE_5_ENTREGA_ENCUESTA.md.

Reglas (todas se validan SIEMPRE en el servidor, en cada petición):
  * El evento sigue «Facturado» (`is_billed`), no está archivado y existe la base final subida por el coordinador (`final_db`).
  * El enlace existe y no está revocado. Un enlace desconocido, revocado o de un evento que ya no está facturado responden lo mismo (no se confirma nada a quien lo adivina).
  * La descarga exige la encuesta enviada (una por evento: regenerar el enlace no obliga a contestarla otra vez) y tiene un límite por enlace y hora.
  * El token no se guarda: se DERIVA con HMAC (SECRET_KEY) del `nonce` de la fila; en la base solo queda su SHA-256. Así el personal puede volver a ver el enlace; revocar o regenerar lo mata.
  * La encuesta no guarda datos personales: solo un hash TRUNCADO de la IP (antiabuso). Las respuestas viven en `survey_responses`/`survey_answers`, fuera de `form_submissions` y de la purga biométrica.

Dependencia con la rama del estado «Facturado» y de la base final (otro agente): aquí solo se LEEN, de forma defensiva (`getattr` con valor por defecto), sin crear esas columnas."""
import base64
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import event_rules, jobs, publicurl, survey_def
from app.database import SessionLocal
from app.mailer import clean_subject, send_mail
from app.models import AuditAction, Event, EventDeliveryLink, EventStaffAuthorization, StaffUser, SurveyAnswer, SurveyResponse, Tenant
from app.secretkey import secret_key
from app.staff_credentials import valid_email
from app.timeutil import utcnow

log = logging.getLogger("golden.delivery")

KIND = "delivery_mail"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,64}$")
DOWNLOADS_PER_HOUR = int(os.getenv("DELIVERY_DOWNLOADS_PER_HOUR", "5"))
MAIL_COOLDOWN = timedelta(hours=1)
ACTION_DOWNLOAD, ACTION_MAIL, ACTION_LINK = "delivery_download", "delivery_mail", "delivery_link"

MSG_UNAVAILABLE = "Este enlace ya no está disponible. Pida uno nuevo a su asesor comercial de Golden."
MSG_NOT_BILLED = "La entrega de este evento todavía no está habilitada. Su asesor comercial de Golden le avisará cuando lo esté."
MSG_NO_DB = "La base de datos final de este evento todavía no está disponible. Su asesor comercial de Golden se la hará llegar en cuanto esté lista."
MSG_NEEDS_SURVEY = "Para descargar la base de datos, primero diligencie la encuesta de satisfacción."
MSG_ALREADY = "Ya recibimos la encuesta de este evento. ¡Gracias por su opinión!"
MSG_DOWNLOAD_LIMIT = "Se alcanzó el máximo de descargas por hora de este enlace. Intente de nuevo en un rato."


# ------------------------------------------------------------------ lectura defensiva de lo que construye la otra rama
def is_billed(event: Event) -> bool:
    """¿La entrega al cliente está habilitada? Con la regla de estado `client_delivery` (rama del estado Facturado) manda ella; sin la regla, base «finalizado» + `billed_at`.
    Un evento archivado (o con la base archivada, L7) no se entrega."""
    if event is None or getattr(event, "archived_at", None) is not None or getattr(event, "data_archived_at", None) is not None:
        return False
    if "client_delivery" in event_rules.RULES:
        return bool(event_rules.allowed(event, "client_delivery"))
    return event.status == "finalizado" and getattr(event, "billed_at", None) is not None


def final_db(event: Event) -> Optional[tuple]:
    """(clave en el almacenamiento, nombre del archivo) de la base final, o None si el coordinador aún no la subió."""
    key = getattr(event, "final_db_key", None)
    if not key:
        return None
    return key, (getattr(event, "final_db_name", None) or "base_de_datos_final")


# ------------------------------------------------------------------ enlace
def _token_for(nonce: str) -> str:
    mac = hmac.new(secret_key().encode(), b"delivery-link|" + nonce.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_of(link: EventDeliveryLink) -> str:
    return _token_for(link.nonce)


def url_for_link(link: EventDeliveryLink, request_base: str = "") -> str:
    base = publicurl.base(request_base)
    return f"{base}/entrega/{token_of(link)}" if base else ""


def active_link(db: Session, event_id: int) -> Optional[EventDeliveryLink]:
    return (db.query(EventDeliveryLink).filter(EventDeliveryLink.event_id == event_id, EventDeliveryLink.revoked_at.is_(None))
            .order_by(EventDeliveryLink.id.desc()).first())


def ensure_link(db: Session, event: Event, staff: Optional[StaffUser], *, regenerate: bool = False) -> EventDeliveryLink:
    """El enlace vigente del evento (lo crea si no hay). `regenerate`: revoca el vigente y crea otro. No confirma (lo hace quien llama). La fila del evento se bloquea para que dos clics no creen dos enlaces."""
    db.query(Event.id).filter(Event.id == event.id).with_for_update().first()
    current = active_link(db, event.id)
    if current is not None and not regenerate:
        return current
    now = utcnow()
    if current is not None:
        db.query(EventDeliveryLink).filter(EventDeliveryLink.event_id == event.id, EventDeliveryLink.revoked_at.is_(None)).update({"revoked_at": now}, synchronize_session=False)
    nonce = secrets.token_hex(16)
    link = EventDeliveryLink(event_id=event.id, token_hash=hash_token(_token_for(nonce)), nonce=nonce, created_at=now, created_by_id=getattr(staff, "id", None))
    db.add(link)
    db.flush()
    _audit(db, staff, ACTION_LINK, link, event, "regenerado" if current is not None else "creado")
    return link


def revoke_link(db: Session, event: Event, staff: Optional[StaffUser]) -> int:
    n = db.query(EventDeliveryLink).filter(EventDeliveryLink.event_id == event.id, EventDeliveryLink.revoked_at.is_(None)).update({"revoked_at": utcnow()}, synchronize_session=False)
    return n


def resolve(db: Session, token: str) -> Optional[EventDeliveryLink]:
    """El enlace vigente de ese token, o None (no existe o se revocó: todo se ve igual)."""
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        return None
    link = db.query(EventDeliveryLink).filter(EventDeliveryLink.token_hash == hash_token(token)).first()
    if link is None or link.revoked_at is not None or not hmac.compare_digest(token_of(link), token):
        return None
    return link


def touch(db: Session, link: EventDeliveryLink) -> None:
    if link.last_opened_at is None or utcnow() - link.last_opened_at > timedelta(minutes=10):
        link.last_opened_at = utcnow()
        db.commit()


def _audit(db: Session, staff, action: str, link: EventDeliveryLink, event: Event, detail: str) -> None:
    """Solo ids, nombre del evento y conteos (nunca correos ni datos de personas). Dentro de la misma transacción que la acción."""
    from app import audit_actions
    audit_actions.record(db, staff, action, "delivery_link", link.id, event.name, detail)


# ------------------------------------------------------------------ encuesta y descarga
def response_for(db: Session, event_id: int) -> Optional[SurveyResponse]:
    return db.query(SurveyResponse).filter(SurveyResponse.event_id == event_id).first()


def survey_done(db: Session, event_id: int) -> bool:
    return db.query(SurveyResponse.id).filter(SurveyResponse.event_id == event_id).first() is not None


class AlreadySubmitted(Exception):
    pass


def ip_hash(ip: Optional[str]) -> Optional[str]:
    """Hash TRUNCADO (16 hex) de la IP con SECRET_KEY: sirve para detectar abuso, no para saber quién fue."""
    if not ip:
        return None
    return hashlib.sha256((secret_key() + "|survey-ip|" + ip).encode()).hexdigest()[:16]


def submit_survey(db: Session, link: EventDeliveryLink, event: Event, payload: dict, ip: Optional[str] = None) -> SurveyResponse:
    """Valida y guarda la encuesta (una por evento). Lanza `survey_def.SurveyError` (respuesta inválida) o `AlreadySubmitted`. Confirma la transacción."""
    rows = survey_def.validate(payload)
    if survey_done(db, event.id):
        raise AlreadySubmitted()
    now = utcnow()
    summary = survey_def.summarize(rows)
    resp = SurveyResponse(event_id=event.id, tenant_id=event.tenant_id, survey_version=survey_def.SURVEY_VERSION, submitted_at=now, delivery_link_id=link.id, ip_hash=ip_hash(ip), **summary)
    resp.answers = [SurveyAnswer(event_id=event.id, tenant_id=event.tenant_id, submitted_at=now, survey_version=survey_def.SURVEY_VERSION, **r) for r in rows]
    db.add(resp)
    queued_next = wants_next_event(rows) and enqueue_next_event_notice(db, event)       # plan §12: interés en otro evento → correo a la comercial (misma transacción)
    try:
        db.commit()
    except IntegrityError:                          # dos envíos a la vez: gana uno solo (índice único por evento)
        db.rollback()
        raise AlreadySubmitted() from None
    resp.next_event_queued = bool(queued_next)        # atributo solo en memoria: el router despierta la cola si hay correo
    return resp


# ------------------------------------------------------------------------------------------------ «¿próximo evento?» → aviso a la comercial
NEXT_KIND = "next_event_mail"
NEXT_QUESTION = "q8_next_event"


def wants_next_event(rows: list) -> bool:
    """True si la encuesta validada respondió «Sí» a la pregunta del próximo evento."""
    return any(r.get("question_id") == NEXT_QUESTION and (r.get("choice_text") or "").strip().lower() in ("sí", "si") for r in rows)


def enqueue_next_event_notice(db: Session, event: Event) -> bool:
    """Encola el aviso a la comercial del evento (sin datos en la cola: solo el id). False si el evento no tiene comercial con correo válido."""
    commercial = getattr(event, "commercial", None)
    if commercial is None or not valid_email(commercial.email):
        return False
    jobs.enqueue(db, NEXT_KIND, {"event_id": int(event.id)}, max_attempts=4, dedupe_key=f"{NEXT_KIND}:{event.id}")
    return True


def render_next_event_mail(*, event_name: str, client_name: str, commercial_name: str, comment: Optional[str], link: str) -> dict:
    nombre = (commercial_name or "").strip()
    saludo = f"Hola {nombre}:" if nombre else "Hola:"
    frase = (f"El cliente {client_name} respondió en la encuesta de satisfacción del evento «{event_name}» que tiene un próximo evento "
             "(la encuesta le ofrece un 2 % de descuento si lo programa con nosotros). Contáctalo pronto.")
    lines = [saludo, "", frase]
    if comment:
        lines += ["", f"Comentario del cliente: {comment}"]
    if link:
        lines += ["", f"Abre el evento: {link}"]
    e = html.escape
    body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\"><p>{e(saludo)}</p><p>{e(frase)}</p>"
            + (f"<p><strong>Comentario del cliente:</strong> {e(comment)}</p>" if comment else "")
            + (f"<p><a href=\"{e(link)}\">Abrir el evento</a></p>" if link else "") + "</div>")
    return {"subject": clean_subject(f"Oportunidad: el cliente de «{event_name}» tiene un próximo evento"), "text": "\n".join(lines), "html": body}


@jobs.handler("next_event_mail")
def run_next_event_mail(payload: dict) -> None:
    from app import final_db                                   # import perezoso: reusa el enlace a la edición del evento
    with SessionLocal() as db:
        event = db.get(Event, int(payload["event_id"]))
        if event is None:
            return
        commercial = getattr(event, "commercial", None)
        to = valid_email(commercial.email) if commercial is not None else ""
        if not to or not commercial.is_active:
            return                                             # sin comercial activa con correo: no es un error
        answer = db.query(SurveyAnswer).filter(SurveyAnswer.event_id == event.id, SurveyAnswer.question_id == NEXT_QUESTION).order_by(SurveyAnswer.id.desc()).first()
        tenant = db.get(Tenant, event.tenant_id) if event.tenant_id else None
        mail = render_next_event_mail(event_name=event.name, client_name=(tenant.name if tenant else "del evento"), commercial_name=commercial.full_name or "",
                                      comment=(answer.comment if answer else None), link=final_db.event_link(event))
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("próximo evento: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el aviso de próximo evento")


def downloads_last_hour(db: Session, link_id: int) -> int:
    return db.query(AuditAction.id).filter(AuditAction.action == ACTION_DOWNLOAD, AuditAction.entity == "delivery_link", AuditAction.entity_id == str(link_id),
                                           AuditAction.at >= utcnow() - timedelta(hours=1)).count()


def record_download(db: Session, link: EventDeliveryLink, event: Event) -> None:
    n = db.query(AuditAction.id).filter(AuditAction.action == ACTION_DOWNLOAD, AuditAction.entity == "delivery_link", AuditAction.entity_id == str(link.id)).count() + 1
    _audit(db, None, ACTION_DOWNLOAD, link, event, f"descarga {n}")


def check_state(db: Session, link: EventDeliveryLink, event: Optional[Event]) -> dict:
    """Estado que ve la página pública: {ok, code, message, survey_done, can_download}. `ok` False = ya no se puede usar el enlace para nada (se muestra `message`)."""
    if event is None or link.revoked_at is not None:
        return {"ok": False, "code": "gone", "message": MSG_UNAVAILABLE, "survey_done": False, "can_download": False}
    if not is_billed(event):
        return {"ok": False, "code": "not_billed", "message": MSG_NOT_BILLED, "survey_done": False, "can_download": False}
    done = survey_done(db, event.id)
    has_db = final_db(event) is not None
    return {"ok": True, "code": "ok", "message": "", "survey_done": done, "can_download": done and has_db, "has_db": has_db}


# ------------------------------------------------------------------ correo al cliente
def client_contact(db: Session, event: Event) -> Optional[dict]:
    """{email, name, source} de quien recibe la entrega: el correo de contacto de la cuenta (cliente) del evento; si no tiene, una cuenta de tipo «cliente» autorizada al evento. None si no hay ninguno válido."""
    tenant = db.get(Tenant, event.tenant_id)
    mail = valid_email(tenant.contact_email) if tenant is not None else ""
    if mail:
        return {"email": mail, "name": (tenant.contact_name or "").strip(), "source": "tenant"}
    row = (db.query(StaffUser).join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
           .filter(EventStaffAuthorization.event_id == event.id, StaffUser.role == "cliente", StaffUser.is_active.is_(True), StaffUser.archived_at.is_(None), StaffUser.email.isnot(None))
           .order_by(StaffUser.id).all())
    for acct in row:
        mail = valid_email(acct.email)
        if mail:
            return {"email": mail, "name": (acct.full_name or "").strip(), "source": "client_account"}
    return None


def mail_sent_recently(db: Session, link_id: int) -> bool:
    return db.query(AuditAction.id).filter(AuditAction.action == ACTION_MAIL, AuditAction.entity == "delivery_link", AuditAction.entity_id == str(link_id),
                                           AuditAction.at >= utcnow() - MAIL_COOLDOWN).first() is not None


def render_mail(*, event_name: str, contact_name: str, url: str) -> dict:
    """{subject, text, html}. Sin contraseñas ni datos personales de los asistentes; solo el enlace de la encuesta."""
    saludo = f"Hola {contact_name}:" if contact_name else "Hola:"
    p1 = f"El evento «{event_name}» finalizó. Gracias por confiar en Golden Eventos y Logística para el registro de sus asistentes."
    p2 = "Su opinión nos ayuda a mejorar cada evento: le pedimos que diligencie esta breve encuesta (toma menos de 3 minutos). Al completarla podrá descargar la base de datos final de su evento."
    p3 = "Este correo no incluye contraseñas ni datos personales de los asistentes: la base se descarga únicamente desde el enlace, después de enviar la encuesta."
    cierre = "Si no esperaba este correo, puede ignorarlo o escribirle a su asesor comercial de Golden. Por favor no reenvíe este enlace a personas ajenas a su organización."
    text = "\n".join([saludo, "", p1, "", p2, "", f"Encuesta y descarga: {url}", "", p3, "", cierre, "", "Golden Eventos y Logística S.A.S."])
    e = html.escape
    html_body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\">"
                 f"<p>{e(saludo)}</p><p>{e(p1)}</p><p>{e(p2)}</p>"
                 f"<p style=\"margin:22px 0\"><a href=\"{e(url)}\" style=\"background:#D4AF37;color:#1a1200;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:24px;display:inline-block\">Diligenciar la encuesta</a></p>"
                 f"<p style=\"font-size:13px;color:#555\">Si el botón no abre, copie este enlace en su navegador:<br><a href=\"{e(url)}\">{e(url)}</a></p>"
                 f"<p>{e(p3)}</p><p style=\"font-size:13px;color:#555\">{e(cierre)}</p><p>Golden Eventos y Logística S.A.S.</p></div>")
    return {"subject": clean_subject(f"Su evento «{event_name}» finalizó: comparta su opinión y descargue su base de datos"), "text": text, "html": html_body}


def enqueue_mail(db: Session, event: Event, link: EventDeliveryLink, base: str, staff: Optional[StaffUser]) -> None:
    """Encola el correo (misma transacción; quien llama confirma y luego hace jobs.kick()). Sin datos personales en la cola: el destinatario se lee al enviar."""
    hour = utcnow().strftime("%Y%m%d%H")
    jobs.enqueue(db, KIND, {"event_id": int(event.id), "link_id": int(link.id), "base": base}, max_attempts=4, dedupe_key=f"{KIND}:{link.id}:{hour}")
    _audit(db, staff, ACTION_MAIL, link, event, "correo encolado")


@jobs.handler("delivery_mail")
def run_mail(payload: dict) -> None:
    with SessionLocal() as db:
        event, link = db.get(Event, int(payload["event_id"])), db.get(EventDeliveryLink, int(payload["link_id"]))
        if event is None or link is None or link.revoked_at is not None or not is_billed(event):
            return                                           # el enlace se revocó/regeneró o el evento dejó de estar facturado: no se manda un enlace muerto
        contact = client_contact(db, event)
        base = (str(payload.get("base") or "")).rstrip("/")
        if contact is None or not base:
            log.warning("entrega: sin destinatario o sin dirección pública para el evento %s; no se envió", event.id)
            return
        mail = render_mail(event_name=event.name, contact_name=contact["name"], url=f"{base}/entrega/{token_of(link)}")
        result = send_mail(contact["email"], mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("entrega: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el correo de entrega")          # se reintenta con espera creciente
