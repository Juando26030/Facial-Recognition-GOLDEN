"""Fase 1B · reimpresión con permisos (docs/1B_reimpresion_permisos.md).

Regla: con `events.reprint_disabled` encendido, reimprimir a quien YA se imprimió exige un permiso de UN solo uso que aprueba el coordinador asignado a ESE evento (o, si no tiene, un admin).
  - El digitador pide el permiso (`create_request`): sale en la PANTALLA del coordinador (tarjeta con Aprobar/Negar) y, de respaldo, por CORREO con un enlace de un solo uso.
  - Respaldo por correo, con dos trabajos diferidos en la cola de siempre (app/jobs.py): a los 25 s si la pantalla del coordinador no la mostró (no tiene sesión activa o está inactiva) y a los
    2 min si sigue pendiente. La reserva del envío es un UPDATE atómico de `email_sent_at`: no sale dos veces aunque corran los dos trabajos.
  - Aprobar vale UNA reimpresión y vence (REPRINT_APPROVAL_MINUTES, 15 por defecto). `consume` es un UPDATE atómico (status='approved' AND used_at IS NULL AND expires_at > ahora): dos equipos no la usan dos veces.
  - Enlace del correo: token aleatorio de 256 bits, guardado SOLO como hash SHA-256, ligado a una solicitud y a un destinatario. El GET solo muestra; la decisión es un POST. Tras usarse (o al decidirse la solicitud) queda muerto.
  - Cada hecho queda en `reprint_audit` (quién, cuándo, canal). Nada de esto escribe datos personales en el log."""
import hashlib
import logging
import os
import secrets
from datetime import timedelta
from html import escape
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app import jobs, publicurl
from app.auth import effective_roles
from app.database import SessionLocal
from app.mailer import send_mail
from app.models import Event, EventAttendee, PrintJob, PrintLog, ReprintAudit, ReprintLink, ReprintRequest, StaffUser, User
from app.timeutil import to_local, utcnow

log = logging.getLogger("golden.reprint")

SCREEN_GRACE_SECONDS = 25        # si la pantalla del coordinador no la mostró en este tiempo, no tiene sesión activa: correo ya
EMAIL_AFTER_SECONDS = 120        # sin respuesta en 2 minutos: correo
MAX_PENDING = 3                  # solicitudes pendientes o aprobadas sin usar por persona del personal y evento
MIN_GAP_SECONDS = 5              # ritmo: entre una solicitud y la siguiente de la misma persona del personal en un evento
MAX_PER_HOUR = 12
ADMIN_ROLES = {"admin", "super_admin"}


def _int_env(name: str, default: int, lo: int = 1, hi: int = 24 * 60) -> int:
    try:
        return max(lo, min(int(os.getenv(name, "").strip() or default), hi))
    except ValueError:
        return default


def approval_minutes() -> int:
    """Vigencia del permiso una vez aprobado (REPRINT_APPROVAL_MINUTES, 15 por defecto)."""
    return _int_env("REPRINT_APPROVAL_MINUTES", 15)


def request_minutes() -> int:
    """Cuánto espera una solicitud sin respuesta antes de vencer (REPRINT_REQUEST_MINUTES, 10 por defecto)."""
    return _int_env("REPRINT_REQUEST_MINUTES", 10)


def iso(dt) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ quién puede qué
def can_decide(event: Event, staff: StaffUser) -> bool:
    """Decide (y no necesita permiso para reimprimir): admin o super_admin, o el coordinador ASIGNADO a este evento. Un coordinador de otro evento no."""
    roles = effective_roles(staff)
    return bool(ADMIN_ROLES & roles) or (event.coordinator_staff_id is not None and staff.id == event.coordinator_staff_id and "coordinador" in roles)


def is_locked_for(event: Event, staff: StaffUser) -> bool:
    return bool(event.reprint_disabled) and not can_decide(event, staff)


def recipients(db: Session, event: Event) -> list:
    """A quién le llega: SOLO el coordinador asignado al evento; si no tiene (o está inactivo), los admin/super_admin activos del cliente (o globales)."""
    if event.coordinator_staff_id:
        coord = db.get(StaffUser, event.coordinator_staff_id)
        if coord is not None and coord.is_active:
            return [coord]
    admins = db.query(StaffUser).filter(StaffUser.is_active == True, StaffUser.role.in_(tuple(ADMIN_ROLES))).all()      # noqa: E712
    return [a for a in admins if a.tenant_id in (None, event.tenant_id)]


def already_printed(db: Session, event: Event, user_id: str) -> bool:
    """¿A esta persona ya se le imprimió la escarapela en este evento? (el conteo de siempre, o un trabajo compartido impreso)."""
    if db.query(PrintLog.id).filter(PrintLog.event_id == event.id, PrintLog.user_id == user_id, PrintLog.tenant_id == event.tenant_id).first():
        return True
    att = db.query(EventAttendee.id).filter_by(event_id=event.id, user_id=user_id).first()
    return bool(att and db.query(PrintJob.id).filter(PrintJob.event_id == event.id, PrintJob.attendee_id == att[0], PrintJob.status == "printed").first())


# ------------------------------------------------------------------------------------------------ auditoría y vencimiento
def audit(db: Session, request_id: int, kind: str, staff_id: Optional[int] = None, channel: Optional[str] = None) -> None:
    db.add(ReprintAudit(request_id=request_id, at=utcnow(), kind=kind, staff_id=staff_id, channel=channel))


def expire_due(db: Session, event_id: Optional[int] = None) -> int:
    """Marca como vencidas las solicitudes pendientes o aprobadas cuyo plazo pasó (y deja el hecho en la auditoría). Atómico por fila: dos procesos no lo anotan dos veces."""
    now = utcnow()
    q = db.query(ReprintRequest.id).filter(ReprintRequest.status.in_(("pending", "approved")), ReprintRequest.expires_at <= now)
    if event_id is not None:
        q = q.filter(ReprintRequest.event_id == event_id)
    n = 0
    for (rid,) in q.limit(200).all():
        done = db.execute(update(ReprintRequest).where(ReprintRequest.id == rid, ReprintRequest.status.in_(("pending", "approved")), ReprintRequest.expires_at <= now)
                          .values(status="expired")).rowcount
        if done:
            audit(db, rid, "expired")
            _kill_links(db, rid)
            n += 1
    return n


def _kill_links(db: Session, request_id: int) -> None:
    db.execute(update(ReprintLink).where(ReprintLink.request_id == request_id, ReprintLink.used_at.is_(None)).values(used_at=utcnow()))


def active_request(db: Session, event_id: int, staff_id: int, user_id: str) -> Optional[ReprintRequest]:
    """La solicitud viva (pendiente, o aprobada sin usar y vigente) de ESTA persona del personal para esa persona; si no hay, la última negada o vencida de los últimos 2 minutos (para mostrar el estado)."""
    now = utcnow()
    base = db.query(ReprintRequest).filter(ReprintRequest.event_id == event_id, ReprintRequest.requested_by_staff_id == staff_id, ReprintRequest.user_id == user_id)
    live = base.filter(ReprintRequest.status.in_(("pending", "approved")), ReprintRequest.expires_at > now).order_by(ReprintRequest.id.desc()).first()
    if live is not None:
        return live
    return base.filter(ReprintRequest.status.in_(("denied", "expired")), or_(ReprintRequest.decided_at > now - timedelta(minutes=2), ReprintRequest.expires_at > now - timedelta(minutes=2))).order_by(ReprintRequest.id.desc()).first()


def view(req: ReprintRequest) -> dict:
    return {"id": req.id, "status": req.status, "expires_at": iso(req.expires_at), "requested_at": iso(req.requested_at), "decided_at": iso(req.decided_at)}


# ------------------------------------------------------------------------------------------------ pedir
def create_request(db: Session, event: Event, staff: StaffUser, user_id: str) -> tuple:
    """(solicitud, creada). Si ya hay una viva de la misma persona para la misma persona, devuelve esa. Límites: pendientes por persona/evento y ritmo (429)."""
    now = utcnow()
    expire_due(db, event.id)
    live = active_request(db, event.id, staff.id, user_id)
    if live is not None and live.status in ("pending", "approved"):
        return live, False
    mine = db.query(ReprintRequest).filter(ReprintRequest.event_id == event.id, ReprintRequest.requested_by_staff_id == staff.id)
    if mine.filter(ReprintRequest.status.in_(("pending", "approved")), ReprintRequest.expires_at > now).count() >= MAX_PENDING:
        raise HTTPException(status_code=429, detail="Ya tienes varias solicitudes esperando respuesta. Espera a que el coordinador responda.")
    if mine.filter(ReprintRequest.requested_at > now - timedelta(seconds=MIN_GAP_SECONDS)).first() or mine.filter(ReprintRequest.requested_at > now - timedelta(hours=1)).count() >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Estás pidiendo permisos muy seguido. Espera un momento.")
    approver = recipients(db, event)[:1]
    req = ReprintRequest(event_id=event.id, tenant_id=event.tenant_id, user_id=user_id, requested_by_staff_id=staff.id,
                         approver_staff_id=approver[0].id if approver and approver[0].id == event.coordinator_staff_id else None,
                         status="pending", requested_at=now, expires_at=now + timedelta(minutes=request_minutes()))
    db.add(req)
    db.flush()
    audit(db, req.id, "requested", staff.id, "screen")
    at_screen, at_mail = now + timedelta(seconds=SCREEN_GRACE_SECONDS), now + timedelta(seconds=EMAIL_AFTER_SECONDS)
    jobs.enqueue(db, "reprint_notify", {"request_id": req.id, "stage": "presence"}, run_at=at_screen, dedupe_key=f"reprint_notify:{req.id}:presence")
    jobs.enqueue(db, "reprint_notify", {"request_id": req.id, "stage": "timeout"}, run_at=at_mail, dedupe_key=f"reprint_notify:{req.id}:timeout")
    return req, True


def kick_notify(req: ReprintRequest) -> None:
    """Después de confirmar la transacción: avisa a la cola (los dos trabajos diferidos, a su hora)."""
    now = utcnow()
    jobs.kick(now + timedelta(seconds=SCREEN_GRACE_SECONDS))
    jobs.kick(now + timedelta(seconds=EMAIL_AFTER_SECONDS))


# ------------------------------------------------------------------------------------------------ decidir
def decide(db: Session, request_id: int, staff_id: Optional[int], approve: bool, channel: str) -> bool:
    """Aprueba o niega UNA vez (UPDATE atómico condicionado a «pendiente y vigente»). True si esta llamada fue la que decidió."""
    now = utcnow()
    values = {"status": "approved" if approve else "denied", "decided_at": now, "decided_by_staff_id": staff_id, "decided_channel": channel}
    if approve:
        values["expires_at"] = now + timedelta(minutes=approval_minutes())
    done = db.execute(update(ReprintRequest).where(ReprintRequest.id == request_id, ReprintRequest.status == "pending", ReprintRequest.expires_at > now).values(**values)).rowcount
    if not done:
        return False
    audit(db, request_id, "approved" if approve else "denied", staff_id, channel)
    _kill_links(db, request_id)                         # decidida: ningún enlace de correo sirve ya
    return True


# ------------------------------------------------------------------------------------------------ usar (la puerta del servidor)
def consume(db: Session, event: Event, staff: StaffUser, user_id: str, channel: str) -> bool:
    """Gasta el permiso aprobado de ESTA persona del personal para esa persona. UPDATE atómico: si dos equipos lo intentan a la vez, solo uno gana. No confirma: va en la transacción de quien imprime."""
    now = utcnow()
    for (rid,) in db.query(ReprintRequest.id).filter(ReprintRequest.event_id == event.id, ReprintRequest.requested_by_staff_id == staff.id, ReprintRequest.user_id == user_id,
                                                      ReprintRequest.status == "approved", ReprintRequest.used_at.is_(None), ReprintRequest.expires_at > now).order_by(ReprintRequest.id).limit(3).all():
        done = db.execute(update(ReprintRequest).where(ReprintRequest.id == rid, ReprintRequest.status == "approved", ReprintRequest.used_at.is_(None), ReprintRequest.expires_at > now)
                          .values(status="used", used_at=now, used_channel=channel)).rowcount
        if done:
            audit(db, rid, "used", staff.id, channel)
            return True
    return False


DENIED_DETAIL = "No se puede reimprimir: esta escarapela ya se imprimió y la reimpresión está deshabilitada en este evento. Pide permiso al coordinador."


def gate(db: Session, event: Event, staff: StaffUser, user_id: str, channel: str) -> None:
    """La puerta del SERVIDOR. Sin error si: la reimpresión está habilitada, quien imprime decide en este evento, la persona aún no se imprimió, o hay un permiso aprobado vigente (que se gasta aquí). 403 si no."""
    if not event.reprint_disabled or can_decide(event, staff):
        return
    expire_due(db, event.id)
    if not already_printed(db, event, user_id):
        return
    if consume(db, event, staff, user_id, channel):
        return
    db.commit()                                         # deja el vencimiento anotado aunque se rechace
    raise HTTPException(status_code=403, detail=DENIED_DETAIL)


def state_for(db: Session, event: Event, staff: StaffUser, user_id: str) -> dict:
    """Lo que la pantalla necesita saber antes de imprimir: ¿está bloqueada la reimpresión para esta persona del personal?, ¿hay permiso?, ¿cómo va la solicitud?"""
    locked = is_locked_for(event, staff)
    out = {"reprint_locked": locked, "permit": False, "request": None}
    if not locked:
        return out
    expire_due(db, event.id)
    req = active_request(db, event.id, staff.id, user_id)
    if req is not None:
        out["request"] = view(req)
        out["permit"] = req.status == "approved"
    return out


# ------------------------------------------------------------------------------------------------ correo de respaldo
def person_name(db: Session, tenant_id: str, user_id: str) -> str:
    u = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    return (f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "") or "la persona"


def staff_name(staff: Optional[StaffUser]) -> str:
    return ((staff.full_name or staff.username) if staff else "") or "un digitador"


def hhmm(dt) -> str:
    return to_local(dt).strftime("%H:%M")


def render_email(*, to_name: str, requester: str, person: str, event_name: str, requested_at, expires_at, url: str) -> dict:
    subject = f"Permiso de reimpresión pedido en {event_name}"
    text = (f"Hola {to_name},\n\n"
            f"{requester} pidió permiso para reimprimir la escarapela de {person} en el evento «{event_name}» (pedido a las {hhmm(requested_at)}).\n"
            f"En este evento la reimpresión está deshabilitada y esa persona ya tiene su escarapela impresa.\n\n"
            f"Para responder abre este enlace. Sirve una sola vez y vence a las {hhmm(expires_at)}:\n{url}\n\n"
            f"Al abrirlo verás los datos y dos botones: Aprobar o Negar. Abrir el enlace no aprueba nada.\n"
            f"Si no esperabas este correo, ignóralo: sin tu respuesta no se imprime nada.\n\n"
            f"Golden Eventos y Logística")
    e = escape
    html = (f"<div style=\"font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#1b1d2a;max-width:560px\">"
            f"<p>Hola {e(to_name)},</p>"
            f"<p><b>{e(requester)}</b> pidió permiso para reimprimir la escarapela de <b>{e(person)}</b> en el evento «{e(event_name)}» (pedido a las {hhmm(requested_at)}).</p>"
            f"<p>En este evento la reimpresión está deshabilitada y esa persona ya tiene su escarapela impresa.</p>"
            f"<p><a href=\"{e(url)}\" style=\"display:inline-block;background:#0a0e2e;color:#ffffff;padding:14px 22px;border-radius:10px;text-decoration:none;font-weight:700\">Ver la solicitud y responder</a></p>"
            f"<p style=\"font-size:14px\">El enlace sirve una sola vez y vence a las {hhmm(expires_at)}. Al abrirlo verás los datos y dos botones: Aprobar o Negar. Abrir el enlace no aprueba nada.</p>"
            f"<p style=\"font-size:14px\">Si no esperabas este correo, ignóralo: sin tu respuesta no se imprime nada.</p>"
            f"<p style=\"font-size:14px;color:#4a4d5c\">Golden Eventos y Logística</p></div>")
    return {"subject": subject, "text": text, "html": html}


@jobs.handler("reprint_notify")
def run_notify(payload: dict) -> None:
    """Respaldo por correo. `presence`: a los 25 s, si la pantalla del coordinador no la mostró. `timeout`: a los 2 min, si sigue pendiente. Idempotente: la reserva de `email_sent_at` es atómica."""
    rid, stage = int(payload["request_id"]), payload.get("stage")
    with SessionLocal() as db:
        now = utcnow()
        req = db.get(ReprintRequest, rid)
        if req is None or req.status != "pending" or req.expires_at <= now:
            expire_due(db)
            db.commit()
            return
        if stage == "presence" and req.screen_seen_at is not None:
            return                                                   # el coordinador la está viendo en su pantalla: espera la hora límite
        claimed = db.execute(update(ReprintRequest).where(ReprintRequest.id == rid, ReprintRequest.status == "pending", ReprintRequest.expires_at > now, ReprintRequest.email_sent_at.is_(None))
                             .values(email_sent_at=now)).rowcount
        if not claimed:
            return
        event = db.get(Event, req.event_id)
        valid = [s for s in recipients(db, event) if (s.email or "").strip()] if event is not None else []
        if event is not None and event.coordinator_staff_id and not any(s.id == event.coordinator_staff_id for s in valid):
            valid = [s for s in db.query(StaffUser).filter(StaffUser.is_active == True, StaffUser.role.in_(tuple(ADMIN_ROLES))).all()      # noqa: E712
                     if (s.email or "").strip() and s.tenant_id in (None, event.tenant_id)]                                                    # el coordinador no tiene correo: lo recibe un admin
        if not valid:
            audit(db, rid, "email_none", None, "email")
            db.commit()
            log.warning("reimpresión %s: sin destinatario con correo", rid)
            return
        for s in valid:
            jobs.enqueue(db, "reprint_mail", {"request_id": rid, "staff_id": s.id}, dedupe_key=f"reprint_mail:{rid}:{s.id}")
        db.commit()
    jobs.kick()


@jobs.handler("reprint_mail")
def run_mail(payload: dict) -> None:
    rid, sid = int(payload["request_id"]), int(payload["staff_id"])
    with SessionLocal() as db:
        now = utcnow()
        req = db.get(ReprintRequest, rid)
        staff = db.get(StaffUser, sid)
        event = db.get(Event, req.event_id) if req is not None else None
        to = ((staff.email or "").strip() if staff is not None else "")
        if req is None or event is None or not to or req.status != "pending" or req.expires_at <= now:
            return                                                   # ya se decidió, venció o no hay a quién escribir
        if db.query(ReprintAudit.id).filter_by(request_id=rid, staff_id=sid, kind="email").first():
            return                                                   # ya salió (reintento tras éxito): no se repite
        token = secrets.token_urlsafe(32)
        db.add(ReprintLink(request_id=rid, staff_id=sid, token_hash=hash_token(token), created_at=now))
        db.commit()
        base = publicurl.base()
        url = f"{base}/reimpresion/{token}" if base else f"/reimpresion/{token}"
        mail = render_email(to_name=staff.full_name or staff.username, requester=staff_name(db.get(StaffUser, req.requested_by_staff_id)), person=person_name(db, req.tenant_id, req.user_id),
                            event_name=event.name, requested_at=req.requested_at, expires_at=req.expires_at, url=url)
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent") and "quedó guardado" not in str(result.get("detail")):
            raise RuntimeError("no se pudo enviar el correo de reimpresión")          # se reintenta con espera creciente
        audit(db, rid, "email", sid, "email")
        db.commit()
        log.info("reimpresión %s: correo de respaldo enviado", rid)
