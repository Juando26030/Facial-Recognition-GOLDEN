"""Envío masivo del enlace personal de autorización (entrega 1 del piloto) y exportación de los enlaces.

Reglas (pedidas por Juan David y la auditora):
  * SOLO eventos propios de Golden (`controller_mode == 'golden'`), con el reconocimiento facial y la aceptación por enlace activados y sin candado biométrico.
  * SOLO personas adultas con correo válido que no se inscribieron por un formulario abierto (ese correo lo escribió quien se inscribió: su enlace NO es confiable y ya lo cubre `formsvc`).
  * Nunca dos veces a la misma persona: el envío se RESERVA con un UPDATE atómico de `accept_sent_at` (solo si estaba vacío) ANTES de llamar al correo. Si el correo falla se libera la reserva;
    si el proceso se cae a medias queda «reservado» y NO se reenvía solo (preferimos no mandar a mandar dos veces; se ve en el registro).
  * Máximo 25 por minuto: un correo por tarea, la siguiente a `SPACING` segundos (2,4 s ⇒ ≤ 25/min) y, además, un tope duro contando el registro del último minuto.
  * Detener y reanudar: `events.accept_mail_run` guarda el id de la tanda en curso. Detener lo vacía; las tareas ya encoladas de esa tanda se descartan solas al ver que ya no coincide.
  * El texto del correo es el aprobado por la auditora (`acceptlink.render_link_email`), sin cambios. Registro en `accept_mail_log`: cédula, fecha y hora y resultado; sin IP ni User-Agent, sin direcciones de correo."""
import csv
import io
import logging
import re
import secrets
import uuid
from collections import Counter
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app import acceptlink, company, consent, jobs, minors
from app.database import SessionLocal
from app.mailer import send_mail
from app.ops import record_system_event
from app.models import AcceptMailLog, Event, EventAttendee, FormSubmission, User
from app.timeutil import utcnow

log = logging.getLogger(__name__)

SPACING = 2.4              # segundos entre un correo y el siguiente: 60 / 2,4 = 25 por minuto
PER_MINUTE = 25            # tope duro (se cuenta en el registro, por si hubiera dos tandas a la vez)
LOG_RETENTION_DAYS = 60    # días calendario desde la fecha de CADA envío (Habeas Data: 15 días hábiles + margen). Única constante del plazo
STALE_AFTER = 300          # segundos: un envío «reservado» más viejo que esto se da por cortado (sin confirmar)
MAX_FAIL_STREAK = 3        # tres fallos seguidos detienen la tanda (correo mal configurado): no se insiste
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
REASONS = {"sin_correo": "no tiene correo", "correo_invalido": "el correo no es válido", "menor": "es menor de edad (sin biometría)", "ya_enviado": "ya se le envió el enlace",
           "ya_respondio": "ya respondió (aceptó o rechazó)", "formulario": "se inscribió por formulario (su correo no es del listado de Golden)", "fallo": "el envío falló en esta tanda"}


def blocked_reason(event: Event) -> Optional[str]:
    """Por qué NO se puede enviar en este evento (None = sí se puede)."""
    if event.controller_mode != "golden":
        return "Solo se envía en eventos propios de Golden."
    if event.biometrics_locked:
        return "El evento tiene el candado biométrico puesto."
    if not (event.facial_enabled and event.aceptar_enabled):
        return "Activa el reconocimiento facial y «Permitir aceptar desde el celular» en los parámetros del evento."
    return None


def plan(db: Session, event: Event, run_id: Optional[str] = None, for_export: bool = False) -> dict:
    """{"eligible": [(asistente, persona, correo)], "omitted": Counter(razón → cuántas)}. Con `for_export=True` (descarga de enlaces) también entran quienes no tienen correo o ya recibieron el enlace."""
    accepted = consent.accepted_user_ids(db, event.tenant_id, event.id)
    denied = consent.denied_user_ids(db, event.tenant_id, event.id)
    from_form = {r[0] for r in db.query(FormSubmission.person_id).filter(FormSubmission.event_id == event.id, FormSubmission.is_test == False, FormSubmission.person_id.isnot(None)).distinct()}  # noqa: E712
    failed = {r[0] for r in db.query(AcceptMailLog.user_id).filter(AcceptMailLog.run_id == run_id, AcceptMailLog.kind == "bulk", AcceptMailLog.result == "failed")} if run_id else set()
    eligible, omitted, minor_ids = [], Counter(), []
    rows = (db.query(EventAttendee, User).join(User, (User.id == EventAttendee.user_id) & (User.tenant_id == EventAttendee.tenant_id))
            .filter(EventAttendee.event_id == event.id).order_by(EventAttendee.id).all())
    for att, user in rows:
        to = (user.email or "").strip()
        if minors.is_minor(user.birth_date):
            reason = "menor"
            minor_ids.append(user.id)
        elif user.id in from_form:
            reason = "formulario"
        elif user.id in accepted or user.id in denied:
            reason = "ya_respondio"
        elif att.accept_sent_at and not for_export:
            reason = "ya_enviado"
        elif user.id in failed:
            reason = "fallo"
        elif not to and not for_export:
            reason = "sin_correo"
        elif to and not EMAIL_RE.match(to):
            reason = None if for_export else "correo_invalido"
        else:
            reason = None
        if reason:
            omitted[reason] += 1
        else:
            eligible.append((att, user, to))
    return {"eligible": eligible, "omitted": omitted, "minor_ids": minor_ids, "no_birth": sum(1 for _a, u, _t in eligible if u.birth_date is None)}


def pending_rows(db: Session, event: Event) -> list:
    """Personas «sin confirmar»: su último intento quedó `unknown` o `reserving` hace más de STALE_AFTER segundos (no se sabe si el correo salió). Es la lista para reenviar a mano."""
    latest = {}
    for r in db.query(AcceptMailLog).filter(AcceptMailLog.event_id == event.id, AcceptMailLog.kind.in_(("bulk", "resend")), AcceptMailLog.user_id.isnot(None)).order_by(AcceptMailLog.id):
        latest[r.user_id] = r
    cut = utcnow() - timedelta(seconds=STALE_AFTER)
    return [r for r in latest.values() if r.result == "unknown" or (r.result == "reserving" and r.at < cut)]


def _counts(db: Session, event: Event) -> dict:
    rows = dict(db.query(AcceptMailLog.result, func.count(func.distinct(AcceptMailLog.user_id))).filter(AcceptMailLog.event_id == event.id, AcceptMailLog.kind == "bulk").group_by(AcceptMailLog.result).all())
    return {"sent": rows.get("sent", 0), "failed": rows.get("failed", 0), "unknown": len(pending_rows(db, event)), "omitted_minor": omitted_minor(db, event)}


def omitted_minor(db: Session, event: Event) -> int:
    """Cuántas personas quedaron registradas como «omitido: menor de edad» en los envíos de este evento."""
    return db.query(func.count(func.distinct(AcceptMailLog.user_id))).filter(AcceptMailLog.event_id == event.id, AcceptMailLog.kind == "bulk", AcceptMailLog.result == "omitido").scalar() or 0


def preview(db: Session, event: Event) -> dict:
    """Vista previa y estado: cuántas personas recibirían el correo, cuántas se omiten y por qué, y cómo va la tanda."""
    blocked = blocked_reason(event)
    p = plan(db, event, event.accept_mail_run) if not blocked else {"eligible": [], "omitted": Counter(), "no_birth": 0}
    n = len(p["eligible"])
    return {"blocked": blocked, "will_send": n, "omitted": [{"reason": REASONS[k], "count": c} for k, c in p["omitted"].most_common()], "omitted_total": sum(p["omitted"].values()), "no_birth_date": p["no_birth"],
            "running": bool(event.accept_mail_run), "minutes": round(n * SPACING / 60 + 0.4), **_counts(db, event), "per_minute": PER_MINUTE}


def _log(db: Session, event: Event, kind: str, result: str, user_id: Optional[str] = None, staff_id: Optional[int] = None, run_id: Optional[str] = None, detail: Optional[str] = None) -> AcceptMailLog:
    row = AcceptMailLog(tenant_id=event.tenant_id, event_id=event.id, user_id=user_id, staff_user_id=staff_id, kind=kind, result=result, run_id=run_id, detail=detail)
    db.add(row)
    return row


def start(db: Session, event: Event, staff_id: int) -> dict:
    blocked = blocked_reason(event)
    if blocked:
        return {"ok": False, "detail": blocked}
    if event.accept_mail_run:
        return {"ok": False, "detail": "Ya hay un envío en curso."}
    p = plan(db, event)
    n = len(p["eligible"])
    if not n and not p["minor_ids"]:
        return {"ok": False, "detail": "No hay personas a quienes enviar."}
    run = uuid.uuid4().hex
    _log_minors(db, event, p["minor_ids"], run)           # a los menores (por la fecha de la base) no se les envía nada: queda «omitido: menor de edad», sin más datos
    if not n:                                             # solo había menores: se registran como omitidos y no arranca ninguna tanda
        db.commit()
        return {"ok": False, "detail": "No hay personas a quienes enviar (los menores de edad quedaron omitidos)."}
    event.accept_mail_run = run
    _log(db, event, "control", "start", staff_id=staff_id, run_id=run, detail=f"{n} por enviar")
    jobs.enqueue(db, "accept_mail", {"event_id": event.id, "run": run})
    db.commit()
    jobs.kick()
    return {"ok": True, "will_send": n}


def _log_minors(db: Session, event: Event, ids: list, run: str) -> None:
    done = {r[0] for r in db.query(AcceptMailLog.user_id).filter(AcceptMailLog.event_id == event.id, AcceptMailLog.kind == "bulk", AcceptMailLog.result == "omitido")}
    for uid in ids:
        if uid not in done:
            _log(db, event, "bulk", "omitido", user_id=uid, run_id=run, detail="menor de edad")


def stop(db: Session, event: Event, staff_id: int) -> dict:
    if not event.accept_mail_run:
        return {"ok": False, "detail": "No hay un envío en curso."}
    _log(db, event, "control", "stop", staff_id=staff_id, run_id=event.accept_mail_run)
    event.accept_mail_run = None
    db.commit()
    return {"ok": True}


def send_test(db: Session, event: Event, to: str, staff_id: int) -> dict:
    """Envío de prueba: el MISMO correo aprobado, solo a la dirección indicada, con un enlace de ejemplo que no sirve y «[PRUEBA]» en el asunto. No toca a ninguna persona."""
    to = (to or "").strip()
    if not EMAIL_RE.match(to):
        return {"ok": False, "detail": "Escribe un correo válido."}
    blocked = blocked_reason(event)
    if blocked:
        return {"ok": False, "detail": blocked}
    link = acceptlink.url(event, "ENLACE-DE-PRUEBA-NO-FUNCIONA")
    if not link:
        return {"ok": False, "detail": "Falta PUBLIC_BASE_URL: no se puede armar el enlace."}
    subject, body = acceptlink.render_link_email(event, "Persona de prueba", link)
    result = send_mail(to, "[PRUEBA] " + subject, body, reply_to=company.get("PRIVACY_EMAIL"))
    sent = bool(result.get("sent"))
    _log(db, event, "test", "sent" if sent else "failed", staff_id=staff_id)
    db.commit()
    return {"ok": sent, "detail": "Enviado." if sent else "No se pudo enviar (¿el correo está configurado?)."}


def purge_log(db: Session, now=None) -> int:
    """Retención del registro de envíos (decisión de la auditora, 2026-10-09): cada fila se borra LOG_RETENTION_DAYS días calendario después de su fecha, sin importar el evento. Lo llama el paso `purge`
    del Job horario. NO toca la constancia de aceptación (`audit_consent_logs`, `web_acceptances`): esa se conserva como prueba de consentimiento."""
    from sqlalchemy import delete
    n = db.execute(delete(AcceptMailLog).where(AcceptMailLog.at <= (now or utcnow()) - timedelta(days=LOG_RETENTION_DAYS))).rowcount
    db.commit()
    return n


def pending_list(db: Session, event: Event) -> list:
    out = []
    for r in pending_rows(db, event):
        u = db.query(User).filter(User.id == r.user_id, User.tenant_id == event.tenant_id).first()
        out.append({"user_id": r.user_id, "name": f"{u.first_name or ''} {u.last_name or ''}".strip() if u else "", "at": r.at.strftime("%Y-%m-%d %H:%M:%S")})
    return out


def resend(db: Session, event: Event, user_id: str, staff_id: int) -> dict:
    """Reenvío a mano, de UNA persona «sin confirmar». El cambio de `accept_sent_at` es atómico (solo si sigue igual): dos clics o dos coordinadores a la vez no duplican.
    El enlace se renueva: si el primer correo sí había llegado, su enlace viejo deja de servir y vale el nuevo. Si el correo no sale, la persona sigue en la lista."""
    blocked = blocked_reason(event)
    if blocked:
        return {"ok": False, "detail": blocked}
    if str(user_id) not in {r.user_id for r in pending_rows(db, event)}:
        return {"ok": False, "detail": "Esa persona no está en la lista de «sin confirmar»."}
    att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=str(user_id), tenant_id=event.tenant_id).first()
    user = db.query(User).filter(User.id == str(user_id), User.tenant_id == event.tenant_id).first()
    to = (user.email or "").strip() if user else ""
    if user is not None and minors.is_minor(user.birth_date):
        return {"ok": False, "detail": "La persona es menor de edad: no se le envía el enlace."}
    if att is None or att.accept_sent_at is None or not EMAIL_RE.match(to):
        return {"ok": False, "detail": "La persona ya no tiene correo válido o fue retirada del evento."}
    old = att.accept_sent_at
    if db.execute(update(EventAttendee).where(EventAttendee.id == att.id, EventAttendee.accept_sent_at == old).values(accept_sent_at=utcnow())).rowcount != 1:
        db.rollback()
        return {"ok": False, "detail": "Otro envío se le adelantó. Actualiza la lista."}
    att.accept_token, att.accept_trusted = secrets.token_urlsafe(18), True
    entry = _log(db, event, "resend", "reserving", user_id=user.id, staff_id=staff_id)
    db.commit()
    link = acceptlink.url(event, att.accept_token)
    result = {"sent": False}
    try:
        if link:
            subject, body = acceptlink.render_link_email(event, user.first_name or "", link)
            result = send_mail(to, subject, body, reply_to=company.get("PRIVACY_EMAIL"))
    except Exception:     # noqa: BLE001 — no se sabe si salió: sigue «sin confirmar»
        log.error("reenvío de enlace: excepción al enviar (evento %s)", event.id, exc_info=True)
    if result.get("sent"):
        entry.result = "sent"
    else:
        db.execute(update(EventAttendee).where(EventAttendee.id == att.id).values(accept_sent_at=old))
        entry.result, entry.detail = "unknown", "el correo no salió"
    db.commit()
    return {"ok": bool(result.get("sent")), "detail": "Reenviado." if result.get("sent") else "No se pudo enviar; sigue en la lista."}


@jobs.handler("accept_mail")
def run_tick(payload: dict) -> None:
    with SessionLocal() as db:
        event = db.get(Event, int(payload["event_id"]))
        run = payload["run"]
        if event is None or event.accept_mail_run != run or blocked_reason(event):
            return                                            # detenida (o reemplazada por otra tanda): esta tarea sobra
        now = utcnow()
        recent = db.query(AcceptMailLog.at).filter(AcceptMailLog.kind == "bulk", AcceptMailLog.at > now - timedelta(seconds=60)).order_by(AcceptMailLog.at).all()
        if len(recent) >= PER_MINUTE:                         # tope duro: esperar a que salga del minuto el más antiguo
            return _next(db, event, run, recent[0][0] + timedelta(seconds=61))
        eligible = plan(db, event, run)["eligible"]
        if not eligible:
            _log(db, event, "control", "done", run_id=run)
            event.accept_mail_run = None
            db.commit()
            return
        att, user, to = eligible[0]
        claimed = db.execute(update(EventAttendee).where(EventAttendee.id == att.id, EventAttendee.accept_sent_at.is_(None)).values(accept_sent_at=now)).rowcount
        if claimed != 1:
            db.rollback()
            return _next(db, event, run, now)                 # otra tarea se le adelantó: sigue con la siguiente persona
        entry = _log(db, event, "bulk", "reserving", user_id=user.id, run_id=run)
        db.commit()                                           # la reserva queda firme ANTES de tocar el correo
        db.refresh(att)
        token = acceptlink.issue(db, att, trusted=True)
        db.commit()                                           # el enlace tiene que existir en la base antes de salir por correo
        link = acceptlink.url(event, token)
        result = {"sent": False}
        try:
            if link:
                subject, body = acceptlink.render_link_email(event, user.first_name or "", link)
                result = send_mail(to, subject, body, reply_to=company.get("PRIVACY_EMAIL"))
        except Exception:     # noqa: BLE001 — no se sabe si salió: queda «unknown» y NO se reenvía
            log.error("envío masivo de enlaces: excepción al enviar (evento %s)", event.id, exc_info=True)
            entry.result = "unknown"
            db.commit()
            return _next(db, event, run, now + timedelta(seconds=SPACING))
        if result.get("sent"):
            entry.result = "sent"
        else:
            db.execute(update(EventAttendee).where(EventAttendee.id == att.id).values(accept_sent_at=None))      # no salió nada: se libera la reserva
            entry.result, entry.detail = "failed", "el correo no salió"
            log.warning("envío masivo de enlaces: un correo no salió (evento %s)", event.id)
        db.commit()
        last = [r[0] for r in db.query(AcceptMailLog.result).filter(AcceptMailLog.run_id == run, AcceptMailLog.kind == "bulk").order_by(AcceptMailLog.id.desc()).limit(MAX_FAIL_STREAK)]
        if len(last) == MAX_FAIL_STREAK and all(r == "failed" for r in last):
            _log(db, event, "control", "stop", run_id=run, detail="detenida sola: tres fallos seguidos")
            event.accept_mail_run = None
            db.commit()
            return
        _next(db, event, run, now + timedelta(seconds=SPACING))


def _next(db: Session, event: Event, run: str, at) -> None:
    jobs.enqueue(db, "accept_mail", {"event_id": event.id, "run": run}, run_at=at)
    db.commit()
    jobs.kick(at)


# ------------------------------------------------------------------------------------------------------------------------------------ exportación y registro
def _safe(v) -> str:
    v = str(v or "")
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v      # que Excel no ejecute una celda como fórmula


def export_links(db: Session, event: Event, staff_id: int) -> Optional[str]:
    """CSV (cédula, nombre, correo, enlace, enviado) con el enlace personal CONFIABLE de cada adulto del listado de Golden (también quien no tiene correo). Emite los enlaces que falten.
    Devuelve None si el evento no admite el envío."""
    if blocked_reason(event):
        return None
    sent_ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.accept_sent_at.isnot(None))}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["cedula", "nombre", "correo", "enlace", "enlace_enviado_por_correo"])
    n = 0
    for att, user, to in plan(db, event, for_export=True)["eligible"]:
        link = acceptlink.url(event, acceptlink.issue(db, att, trusted=True))
        w.writerow([_safe(user.id), _safe(f"{user.first_name or ''} {user.last_name or ''}".strip()), _safe(to), link or "", "sí" if user.id in sent_ids else "no"])
        n += 1
    _log(db, event, "export", "done", staff_id=staff_id, detail=f"{n} enlaces")
    db.commit()
    record_system_event("accept_links_export", ref=event.event_code, detail=f"{n} enlaces personales descargados por el personal #{staff_id}")
    return out.getvalue()


def log_csv(db: Session, event: Event) -> str:
    """Registro de envíos: cédula, fecha y hora (UTC) y resultado. Sin IP ni User-Agent."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["cedula", "fecha_hora_utc", "tipo", "resultado"])
    for r in db.query(AcceptMailLog).filter(AcceptMailLog.event_id == event.id).order_by(AcceptMailLog.id):
        w.writerow([_safe(r.user_id), r.at.strftime("%Y-%m-%d %H:%M:%S"), r.kind, f"{r.result}: {r.detail}" if r.result == "omitido" else r.result])
    return out.getvalue()
