"""Impresión compartida de escarapelas (orden del 22-oct-2026, evento sin rostro de ~3000 personas). APAGADA por defecto, por evento.

Equipos Android con Chrome. Algunos (los «Y») tienen una Brother QL-800 por USB; otros (los «X») registran y su escarapela sale en la impresora de un Y.
  - Cada equipo que abre el Registro reporta cada pocos segundos su plataforma, navegador y si tiene la impresora conectada (`heartbeat`). Sin IP ni datos de personas.
  - En Parámetros se elige, para cada usuario X, «en su propio equipo» o «en el equipo de Y» (sin tope: con más de WARN_PER_PRINTER usuarios en una impresora, Parámetros avisa que puede haber espera).
  - Cuando X registra con impresión automática, su equipo pide un trabajo (`POST print-jobs`, con un `request_id` propio: un reintento no duplica).
  - El equipo Y pregunta cada 1-2 s por su siguiente trabajo (`GET print-jobs/next`): el servidor lo RESERVA de forma atómica (queued → sent, FOR UPDATE SKIP
    LOCKED), Y imprime por USB y confirma (`result`: printed | failed). Un trabajo reservado no se vuelve a entregar: nunca se imprime dos veces solo.
  - Lo que no se imprimió en PRINT_JOB_TTL queda «expired» (visible para reimprimir a mano); nunca se imprime después por su cuenta.
Carga: solo pregunta el equipo que de verdad atiende a alguien (≤ 1 consulta indexada cada 1,5 s por impresora) y el resto reporta cada 10 s."""
import json
import logging
import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import reprint
from app.auth import get_event_for_staff, require_role_excluding
from app.routers import print_settings
from app.routers.print_stations import read_station
from app.database import get_db
from app.models import AccessLog, Event, EventAttendee, EventStaffAuthorization, PrintDevice, PrintJob, PrintLog, PrintRoute, StaffUser, User
from app.timeutil import utcnow

log = logging.getLogger("golden.shared_print")
router = APIRouter()

PRINT_JOB_TTL = timedelta(minutes=5)
CLAIM_LEASE = timedelta(seconds=int(os.getenv("PRINT_CLAIM_LEASE_SECONDS", "60")))    # un trabajo reclamado que no termina en este tiempo vuelve a la cola
DEDUPE_WINDOW = timedelta(seconds=int(os.getenv("PRINT_DEDUPE_SECONDS", "30")))      # una persona = una impresión por ventana (salvo reimpresión explícita)
BATCH_MAX = 50                                 # «Imprimir pendientes»: hasta 50 escarapelas por tanda (una sola ventana de impresión); si hay más, una segunda tanda
BATCH_LEASE = timedelta(minutes=4)             # un lote reclamado tiene más tiempo que uno solo (la persona está frente al cuadro de impresión de varias hojas); si no confirma, vuelve a la cola
ONLINE_WINDOW = timedelta(seconds=30)          # sin señal en 30 s = desconectado
WARN_PER_PRINTER = 6                           # orden del 22-oct-2026: sin tope duro; con más de 6 usuarios en una impresora, aviso suave en Parámetros
OPERATOR = require_role_excluding("digitador", ("comercial",))       # quien registra (mismo mínimo que imprimir hoy)
CONFIG = require_role_excluding("coordinador", ("comercial",))       # quien configura Parámetros


class HeartbeatIn(BaseModel):
    device_id: str
    platform: Optional[str] = None
    browser: Optional[str] = None
    printer_connected: Optional[bool] = None    # None = esta pestaña no es la dueña de la impresora (otra pestaña del mismo equipo la tiene): no cambia lo que hay
    printer_name: Optional[str] = None
    print_mode: Optional[str] = None            # «dialog»: este equipo imprime con la ventana de Chrome (lo declara la persona en la barra); sin impresora ni esto = «none»


class JobIn(BaseModel):
    user_id: str
    request_id: str
    reprint: bool = False          # reimpresión EXPLÍCITA (Cola o confirmada): la única forma de pedir otra escarapela de la misma persona dentro de la ventana
    prefs: Optional[dict] = None   # parámetros de impresión YA resueltos del equipo que pide (24-oct-2026): el equipo con la impresora imprime con estos, no con los suyos


class ResultIn(BaseModel):
    ok: bool
    error: Optional[str] = None
    applied: Optional[str] = None   # parámetros con los que el equipo que imprime armó la etiqueta (se muestran en la Cola)


class BatchResultIn(BaseModel):
    results: list                  # [{"id": n, "ok": true|false, "error": "...", "applied": "..."}]: el resultado de cada trabajo de la tanda, después de que la ventana terminó


class ReleaseIn(BaseModel):
    ids: list                      # trabajos reclamados que NO se imprimieron (la persona cerró o canceló la ventana): vuelven a la cola, nunca se pierden ni se reimprimen solos


class RouteIn(BaseModel):
    staff_user_id: int
    printer_staff_id: Optional[int] = None


def _clip(value: Optional[str], n: int) -> Optional[str]:
    v = (value or "").strip()
    return v[:n] or None


def _online(device: Optional[PrintDevice], now=None) -> bool:
    return bool(device and device.last_seen_at and device.last_seen_at >= (now or utcnow()) - ONLINE_WINDOW)


def _printer_ready(device: Optional[PrintDevice], now=None) -> bool:
    return bool(_online(device, now) and device.printer_connected)


def _mode(device: Optional[PrintDevice]) -> str:
    """Cómo imprime este equipo: «usb» (impresora abierta por WebUSB), «dialog» (con la ventana de Chrome; lo declara la persona) o «none». Un latido viejo (sin print_mode) con la impresora conectada cuenta como usb."""
    if device is None:
        return "none"
    if device.printer_connected:
        return "usb"
    return "dialog" if device.print_mode == "dialog" else "none"


def _can_host(device: Optional[PrintDevice], now=None) -> bool:
    """¿Puede elegirse como anfitrión de otros equipos? Que esté activo (abierto en el Registro) Y que sepa imprimir: con la impresora USB lista, o declarando que imprime con la ventana de Chrome
    (atiende con «Imprimir pendientes»). Un equipo sin impresora («none») NO puede ser anfitrión (29-oct-2026)."""
    return _online(device, now) and _mode(device) in ("usb", "dialog")


def _ineligible_reason(device: Optional[PrintDevice], now=None) -> Optional[str]:
    """Por qué un equipo NO se puede elegir como anfitrión (para mostrarlo en Parámetros); None si sí se puede."""
    if device is None:
        return "Todavía no abrió el Registro con la impresión compartida."
    if not _online(device, now):
        return "Está desconectado (sin señal)."
    if _mode(device) == "none":
        return "No tiene impresora: conéctala por USB o marca «Este equipo imprime con la ventana de Chrome» en su barra de impresión."
    return None


def _enabled_event(event_id: int, db: Session, staff: StaffUser) -> Event:
    event = get_event_for_staff(event_id, db, staff)
    if not event.shared_print_enabled:
        raise HTTPException(status_code=409, detail="La impresión compartida no está activada en este evento.")
    return event


def _name(staff: Optional[StaffUser]) -> str:
    return (staff.full_name or staff.username) if staff else ""


def _expire(db: Session, event_id: int) -> None:
    """Lo que no se imprimió a tiempo queda «expired» (nunca se imprime después por su cuenta)."""
    cut = utcnow() - PRINT_JOB_TTL
    back = (db.query(PrintJob).filter(PrintJob.event_id == event_id, PrintJob.status == "sent", PrintJob.sent_at < utcnow() - CLAIM_LEASE, PrintJob.created_at >= cut)
            .update({PrintJob.status: "queued", PrintJob.sent_at: None}, synchronize_session=False))       # arrendamiento vencido: el equipo que lo reclamó no terminó (se cerró, se colgó el cuadro...)
    if back:
        db.commit()
        log.warning("impresión compartida: %s trabajo(s) reclamados volvieron a la cola en el evento %s", back, event_id)
    n = (db.query(PrintJob).filter(PrintJob.event_id == event_id, PrintJob.status.in_(("queued", "sent")), PrintJob.created_at < cut)
         .update({PrintJob.status: "expired", PrintJob.done_at: utcnow()}, synchronize_session=False))
    if n:
        db.commit()
        log.warning("impresión compartida: %s trabajo(s) caducaron sin imprimirse en el evento %s", n, event_id)


def _station_counts(db: Session, event_id: int, staff_id: int) -> dict:
    """Lo que espera en el puesto de esta cuenta: pendientes (en cola) y reclamados (enviados a una ventana que aún no confirma)."""
    rows = db.query(PrintJob.status).filter(PrintJob.event_id == event_id, PrintJob.printer_staff_id == staff_id, PrintJob.status.in_(("queued", "sent")),
                                            PrintJob.created_at >= utcnow() - PRINT_JOB_TTL).all()
    return {"waiting": sum(1 for (st,) in rows if st == "queued"), "claimed": sum(1 for (st,) in rows if st == "sent")}


def _route(db: Session, event_id: int, staff_id: int) -> Optional[int]:
    row = db.query(PrintRoute).filter_by(event_id=event_id, staff_user_id=staff_id).first()
    return row.printer_staff_id if row else None


def _registered(db: Session, event_id: int, user_id: str) -> bool:
    """«Registrado» en ESTE evento = tiene al menos una acreditación real (misma regla que api._already_checked_in y que el estado del Directorio: «Actualizado» no cuenta)."""
    return db.query(AccessLog.id).filter(AccessLog.event_id == event_id, AccessLog.user_id == user_id, AccessLog.record_type != "Actualizado").first() is not None


def _not_registered_msg(db: Session, tenant_id: str, user_id: str) -> str:
    u = db.query(User.first_name, User.last_name).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    name = f"{u.first_name or ''} {u.last_name or ''}".strip() if u else ""
    return f"No se puede imprimir: {name or 'esta persona'} aún no está registrado. Acredítalo o guarda su registro primero."


def _job_out(db: Session, job: PrintJob) -> dict:
    printer = db.get(StaffUser, job.printer_staff_id) if job.printer_staff_id else None
    applied = None
    if job.prefs_json:
        try:
            applied = (json.loads(job.prefs_json) or {}).get("_applied")
        except (ValueError, AttributeError):
            applied = None
    return {"id": job.id, "status": job.status, "printer_name": _name(printer), "error": job.error, "applied": applied,
            "created_at": job.created_at.isoformat() + "Z", "done_at": job.done_at.isoformat() + "Z" if job.done_at else None}


# ------------------------------------------------------------------------------------------------ equipos (cualquiera que registre)
@router.post("/events/{event_id}/print-devices/heartbeat")
def heartbeat(event_id: int, data: HeartbeatIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """El equipo dice que sigue ahí y si tiene la impresora conectada. Responde dónde imprime este usuario y si debe preguntar por trabajos (si atiende a alguien)."""
    event = _enabled_event(event_id, db, staff)
    now = utcnow()
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff.id).first()
    device_id = _clip(data.device_id, 64) or "?"
    # Un equipo por cuenta (sin columnas nuevas): el que PUEDE IMPRIMIR SOLO manda. Otra sesión de la misma cuenta (p. ej. el celular del admin) que no tiene impresora NO pisa su estado ni su señal.
    mode_in = "usb" if data.printer_connected else ("dialog" if data.print_mode == "dialog" else "none")
    held = dev is not None and dev.device_id != device_id and _online(dev, now) and _mode(dev) in ("usb", "dialog") and mode_in == "none" and not data.printer_connected
    if not held:
        if dev is None:
            dev = PrintDevice(event_id=event.id, staff_user_id=staff.id, device_id=device_id, last_seen_at=now)
            db.add(dev)
        dev.device_id = device_id
        dev.platform, dev.browser = _clip(data.platform, 40), _clip(data.browser, 40)
        if data.printer_connected is not None or dev.printer_connected is None:
            dev.printer_connected, dev.printer_name = bool(data.printer_connected), _clip(data.printer_name, 80)
            dev.print_mode = mode_in
        dev.last_seen_at = now
    db.commit()
    printer_id = _route(db, event.id, staff.id)
    printer = db.get(StaffUser, printer_id) if printer_id else None
    printer_dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=printer_id).first() if printer_id else None
    serving = db.query(PrintRoute).filter(PrintRoute.event_id == event.id, PrintRoute.printer_staff_id == staff.id).count()
    return {"enabled": True, "mode": "shared" if printer_id else "self", "printer_name": _name(printer), "printer_ready": _printer_ready(printer_dev, now),
            "printer_mode": _mode(printer_dev) if printer_id else None, "printer_online": _online(printer_dev, now) if printer_id else None, "my_mode": _mode(dev),
            "serving": serving, "poll": bool(serving and dev.printer_connected and dev.device_id == device_id and not held),
            "holder": bool(dev.device_id == device_id and not held), **_station_counts(db, event.id, staff.id),
            "serving_names": [_name(db.get(StaffUser, r.staff_user_id)) for r in db.query(PrintRoute).filter(PrintRoute.event_id == event.id, PrintRoute.printer_staff_id == staff.id).limit(12)]}


# ------------------------------------------------------------------------------------------------ X: pedir y seguir una impresión
@router.post("/events/{event_id}/print-jobs")
def create_job(event_id: int, data: JobIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    event = _enabled_event(event_id, db, staff)
    request_id = _clip(data.request_id, 64)
    if not request_id:
        raise HTTPException(status_code=400, detail="Falta el identificador de la solicitud.")
    existing = db.query(PrintJob).filter_by(request_id=request_id).first()
    if existing is not None:                                   # reintento de la misma solicitud: no se duplica
        if existing.event_id != event.id or existing.requested_by_staff_id != staff.id:
            raise HTTPException(status_code=409, detail="Solicitud repetida.")
        return {**_job_out(db, existing), "duplicate": True, "printer_ready": True}
    printer_id = _route(db, event.id, staff.id)
    if not printer_id:
        raise HTTPException(status_code=409, detail="Este usuario imprime en su propio equipo.")
    attendee = db.query(EventAttendee).filter_by(event_id=event.id, user_id=str(data.user_id).strip()).first()
    if attendee is None:
        raise HTTPException(status_code=404, detail="La persona no está inscrita en este evento.")
    if not _registered(db, event.id, attendee.user_id):              # orden del 22-oct-2026: solo se imprime a quien ya está Registrado (también la reimpresión de la Cola)
        raise HTTPException(status_code=409, detail=_not_registered_msg(db, event.tenant_id, attendee.user_id))
    # UNA impresión por persona (clave: evento + persona; la plantilla la decide la persona/categoría): con la fila de la inscripción BLOQUEADA, dos pedidos simultáneos (doble clic, dos pestañas,
    # dos equipos, un refresco) se serializan y el segundo recibe el trabajo que ya existe. Solo una REIMPRESIÓN explícita (`reprint`, desde la Cola o tras confirmar) crea otro, y queda en la bitácora.
    db.query(EventAttendee.id).filter(EventAttendee.id == attendee.id).with_for_update().first()
    if not data.reprint:
        recent = (db.query(PrintJob).filter(PrintJob.event_id == event.id, PrintJob.attendee_id == attendee.id, PrintJob.status.in_(("queued", "sent", "printed")),
                                            PrintJob.created_at >= utcnow() - DEDUPE_WINDOW).order_by(PrintJob.id.desc()).first())
        if recent is not None:
            log.info("impresión compartida: pedido repetido (trabajo %s, evento %s): no se crea otro", recent.id, event.id)
            dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=recent.printer_staff_id).first()
            return {**_job_out(db, recent), "duplicate": True, "printer_ready": _printer_ready(dev)}
    else:
        log.info("impresión compartida: REIMPRESIÓN explícita (evento %s, usuario %s)", event.id, staff.id)
    reprint.gate(db, event, staff, attendee.user_id, "shared")        # Fase 1B: con la reimpresión deshabilitada, una persona ya impresa exige permiso aprobado (se gasta aquí, de forma atómica; 403 si no)
    prefs = print_settings.job_prefs(data.prefs)
    job = PrintJob(event_id=event.id, attendee_id=attendee.id, requested_by_staff_id=staff.id, printer_staff_id=printer_id, request_id=request_id,
                   status="queued", created_at=utcnow(), prefs_json=json.dumps(prefs) if prefs else None)
    db.add(job)
    db.commit()
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=printer_id).first()
    ready = _printer_ready(dev)
    log.info("impresión compartida: trabajo %s en cola (evento %s)", job.id, event.id)
    out = {**_job_out(db, job), "duplicate": False, "printer_ready": ready, "printer_mode": _mode(dev)}
    if not ready:
        mins = int(PRINT_JOB_TTL.total_seconds() // 60)
        if _online(dev) and _mode(dev) == "dialog":
            out["warning"] = f"La escarapela quedó en cola: sale cuando el equipo de {out['printer_name']} toque «Imprimir pendientes» ({mins} min) y podrás reimprimirla."
        else:
            out["warning"] = (f"El equipo de {out['printer_name']} no está conectado o no tiene la impresora: la escarapela quedó en cola "
                              f"({mins} min) y podrás reimprimirla.")
    return out


@router.get("/events/{event_id}/print-check/{user_id}")
def print_check(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Antes de imprimir (local o compartida, manual, automática o desde la Cola): ¿la persona está Registrada en este evento? La pantalla no imprime si no."""
    event = _enabled_event(event_id, db, staff)
    uid = str(user_id).strip()
    if db.query(EventAttendee.id).filter_by(event_id=event.id, user_id=uid).first() is None and not _registered(db, event.id, uid):
        raise HTTPException(status_code=404, detail="La persona no está inscrita en este evento.")
    if _registered(db, event.id, uid):
        return {"registered": True}
    return {"registered": False, "detail": _not_registered_msg(db, event.tenant_id, uid)}


@router.get("/events/{event_id}/print-jobs/{job_id}")
def job_status(event_id: int, job_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    event = _enabled_event(event_id, db, staff)
    _expire(db, event.id)
    job = db.get(PrintJob, job_id)
    if job is None or job.event_id != event.id or staff.id not in (job.requested_by_staff_id, job.printer_staff_id):
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    return _job_out(db, job)


@router.get("/events/{event_id}/print-jobs")
def my_jobs(event_id: int, scope: str = "mine", db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """La cola visible de quien pidió: lo que no se imprimió en las últimas 4 horas (en cola, enviado, fallido o caducado), con la persona para reimprimir."""
    event = _enabled_event(event_id, db, staff)
    _expire(db, event.id)
    if scope == "station":                                     # la Cola del PUESTO: lo que espera aquí (en cola) o ya fue reclamado y no confirma
        srows = (db.query(PrintJob, EventAttendee).join(EventAttendee, EventAttendee.id == PrintJob.attendee_id)
                 .filter(PrintJob.event_id == event.id, PrintJob.printer_staff_id == staff.id, PrintJob.status.in_(("queued", "sent")), PrintJob.created_at >= utcnow() - PRINT_JOB_TTL)
                 .order_by(PrintJob.id).limit(50).all())
        return {"jobs": [{**_job_out(db, j), "user_id": a.user_id, "requested_by": _name(db.get(StaffUser, j.requested_by_staff_id)) if j.requested_by_staff_id else ""} for j, a in srows]}
    rows = (db.query(PrintJob, EventAttendee).join(EventAttendee, EventAttendee.id == PrintJob.attendee_id)
            .filter(PrintJob.event_id == event.id, PrintJob.requested_by_staff_id == staff.id, PrintJob.status != "printed",
                    PrintJob.created_at >= utcnow() - timedelta(hours=4))
            .order_by(PrintJob.id.desc()).limit(50).all())
    printed_later = {a for (a,) in db.query(PrintJob.attendee_id).filter(PrintJob.event_id == event.id, PrintJob.status == "printed",
                                                                        PrintJob.attendee_id.in_([a.id for _j, a in rows] or [0]))}
    return {"jobs": [{**_job_out(db, j), "user_id": a.user_id, "printed_later": a.id in printed_later} for j, a in rows]}


# ------------------------------------------------------------------------------------------------ Y: recibir e imprimir
def _require_page_fetch(request: Request) -> None:
    mode = (request.headers.get("sec-fetch-mode") or "").lower()
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if mode == "navigate" or site == "cross-site":
        raise HTTPException(status_code=403, detail="Esta acción solo se puede hacer desde la pantalla de impresión")


@router.get("/events/{event_id}/print-jobs-next")
def next_job(event_id: int, request: Request, device_id: Optional[str] = None, manual: bool = False, batch: int = 0, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """El siguiente trabajo para el equipo de este usuario: se RESERVA de forma atómica (queued → sent). Un trabajo reservado no se vuelve a entregar.
    `batch` (solo con `manual`, el toque de «Imprimir pendientes»): reserva hasta BATCH_MAX trabajos de una vez, con el mismo arrendamiento largo, para imprimirlos en UNA ventana.
    S9: es un GET que cambia estado, así que solo lo atiende un `fetch` de la propia página: una navegación (enlace desde otro sitio: la cookie Lax sí viaja) o una petición
    de otro sitio se rechazan con 403 (cabeceras Sec-Fetch-* que pone el navegador; la página manda además `X-Gw-Fetch: 1`)."""
    _require_page_fetch(request)
    event = _enabled_event(event_id, db, staff)
    now = utcnow()
    if batch:
        return _claim_batch(db, event, staff, device_id, manual, batch, now)
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff.id).first()
    # Solo reclama por sondeo la ventana que PUEDE IMPRIMIR SOLA (la dueña de la impresora USB, que el servidor tiene como su equipo). Una ventana sin impresora, o la sesión
    # del celular de la misma cuenta, NUNCA reclaman por sondeo: `manual` es el toque de «Imprimir pendientes» (la persona está ahí para confirmar la ventana de impresión).
    if not manual and (dev is None or not dev.printer_connected or (device_id and dev.device_id != _clip(device_id, 64))):
        _expire(db, event.id)
        db.commit()
        return {"job": None}
    if dev is not None and (manual or not device_id or dev.device_id == _clip(device_id, 64)):
        dev.last_seen_at = now
    _expire(db, event.id)
    job = (db.query(PrintJob).filter(PrintJob.event_id == event.id, PrintJob.printer_staff_id == staff.id, PrintJob.status == "queued",
                                     PrintJob.created_at >= now - PRINT_JOB_TTL)
           .order_by(PrintJob.id).with_for_update(skip_locked=True).first())
    if job is None:
        db.commit()
        return {"job": None}
    job.status, job.sent_at = "sent", now
    attendee = db.get(EventAttendee, job.attendee_id)
    requester = db.get(StaffUser, job.requested_by_staff_id) if job.requested_by_staff_id else None
    db.commit()
    try:
        prefs = json.loads(job.prefs_json) if job.prefs_json else None
    except ValueError:
        prefs = None
    # `prefs`: los del equipo que pidió; None (pedido viejo o sin parámetros) = el equipo con la impresora usa los del EVENTO, nunca los suyos
    return {"job": {"id": job.id, "user_id": attendee.user_id if attendee else None, "requested_by": _name(requester), "prefs": prefs}}


def _claim_batch(db: Session, event: Event, staff: StaffUser, device_id: Optional[str], manual: bool, batch: int, now) -> dict:
    """Reclamo por lote: los mismos trabajos «queued» de este puesto, en orden, reservados de forma atómica (FOR UPDATE SKIP LOCKED) y entregados UNA sola vez. Solo con el toque de la persona."""
    if not manual:
        return {"jobs": []}                                        # el sondeo automático sigue reclamando de a uno (solo la dueña de la impresora USB)
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff.id).first()
    if dev is not None and (not device_id or dev.device_id == _clip(device_id, 64)):
        dev.last_seen_at = now
    _expire(db, event.id)
    n = max(1, min(int(batch), BATCH_MAX))
    jobs = (db.query(PrintJob).filter(PrintJob.event_id == event.id, PrintJob.printer_staff_id == staff.id, PrintJob.status == "queued", PrintJob.created_at >= now - PRINT_JOB_TTL)
            .order_by(PrintJob.id).with_for_update(skip_locked=True).limit(n).all())
    out = []
    for job in jobs:
        job.status, job.sent_at = "sent", now + (BATCH_LEASE - CLAIM_LEASE)       # vence a los BATCH_LEASE (el chequeo de _expire compara contra CLAIM_LEASE)
        attendee = db.get(EventAttendee, job.attendee_id)
        requester = db.get(StaffUser, job.requested_by_staff_id) if job.requested_by_staff_id else None
        try:
            prefs = json.loads(job.prefs_json) if job.prefs_json else None
        except ValueError:
            prefs = None
        out.append({"id": job.id, "user_id": attendee.user_id if attendee else None, "requested_by": _name(requester), "prefs": prefs})
    db.commit()
    if out:
        log.info("impresión compartida: lote de %s trabajo(s) reclamado (evento %s)", len(out), event.id)
    return {"jobs": out}


def _apply_result(db: Session, event: Event, job: PrintJob, data: ResultIn) -> None:
    """El resultado de UN trabajo (lo usan el endpoint de uno y el de la tanda); idempotente: un trabajo ya confirmado no cambia."""
    if job.status not in ("sent", "queued"):                   # ya confirmado (o caducado)
        return
    job.status = "printed" if data.ok else "failed"
    job.error = None if data.ok else _clip(data.error or "La impresora no respondió.", 200)
    job.done_at = utcnow()
    applied = _clip(data.applied, 300)
    if applied:
        try:
            asked = json.loads(job.prefs_json) if job.prefs_json else {}
        except ValueError:
            asked = {}
        job.prefs_json = json.dumps({**(asked if isinstance(asked, dict) else {}), "_applied": applied})
    if data.ok:
        attendee = db.get(EventAttendee, job.attendee_id)
        if attendee is not None:                               # el conteo de impresiones de siempre (aviso de reimpresión), a nombre de quien lo pidió
            db.add(PrintLog(tenant_id=attendee.tenant_id, user_id=attendee.user_id, event_id=event.id, printed_by_staff_id=job.requested_by_staff_id))


@router.post("/events/{event_id}/print-jobs/result-batch")
def job_result_batch(event_id: int, data: BatchResultIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """Los resultados de una tanda, DESPUÉS de que la ventana de impresión terminó. Cada trabajo se confirma por separado (uno que no es de este puesto se ignora)."""
    event = _enabled_event(event_id, db, staff)
    done = 0
    for item in (data.results or [])[:BATCH_MAX]:
        try:
            jid, res = int(item.get("id")), ResultIn(ok=bool(item.get("ok")), error=item.get("error"), applied=item.get("applied"))
        except (TypeError, ValueError, AttributeError):
            continue
        job = db.query(PrintJob).filter(PrintJob.id == jid, PrintJob.event_id == event.id, PrintJob.printer_staff_id == staff.id).with_for_update().first()
        if job is not None:
            _apply_result(db, event, job, res)
            done += 1
    db.commit()
    log.info("impresión compartida: resultado de una tanda de %s trabajo(s) (evento %s)", done, event.id)
    return {"confirmed": done}


@router.post("/events/{event_id}/print-jobs/release")
def job_release(event_id: int, data: ReleaseIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """La persona cerró o canceló la ventana: los trabajos que seguían «enviados» a este puesto vuelven a la cola (nunca se pierden ni se reimprimen solos)."""
    event = _enabled_event(event_id, db, staff)
    ids = []
    for x in (data.ids or [])[:BATCH_MAX]:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    n = 0
    if ids:
        n = (db.query(PrintJob).filter(PrintJob.id.in_(ids), PrintJob.event_id == event.id, PrintJob.printer_staff_id == staff.id, PrintJob.status == "sent")
             .update({PrintJob.status: "queued", PrintJob.sent_at: None}, synchronize_session=False))
        db.commit()
    log.info("impresión compartida: %s trabajo(s) devueltos a la cola por una ventana cerrada (evento %s)", n, event.id)
    return {"released": n}


@router.post("/events/{event_id}/print-jobs/{job_id}/result")
def job_result(event_id: int, job_id: int, data: ResultIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    event = _enabled_event(event_id, db, staff)
    job = db.query(PrintJob).filter(PrintJob.id == job_id, PrintJob.event_id == event.id).with_for_update().first()
    if job is None or job.printer_staff_id != staff.id:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    _apply_result(db, event, job, data)                        # ya confirmado (o caducado): no cambia, idempotente. «queued» = el arrendamiento venció pero el equipo sí terminó: se acepta
    db.commit()
    log.info("impresión compartida: trabajo %s %s (evento %s)", job.id, job.status, event.id)
    return _job_out(db, job)


# ------------------------------------------------------------------------------------------------ Parámetros
@router.get("/events/{event_id}/shared-print")
def config(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG)):
    event = get_event_for_staff(event_id, db, staff)
    now = utcnow()
    devices = {d.staff_user_id: d for d in db.query(PrintDevice).filter_by(event_id=event.id)}
    routes = {r.staff_user_id: r.printer_staff_id for r in db.query(PrintRoute).filter_by(event_id=event.id)}
    ids = {a for (a,) in db.query(EventStaffAuthorization.staff_user_id).filter_by(event_id=event.id)} | set(devices) | set(routes)
    ids |= {i for i in (event.coordinator_staff_id,) if i}
    users = db.query(StaffUser).filter(StaffUser.id.in_(ids or [0]), StaffUser.is_active == True).order_by(StaffUser.full_name, StaffUser.username).all()  # noqa: E712
    serving = {}
    for x, y in routes.items():
        if y:
            serving[y] = serving.get(y, 0) + 1
    out = []
    for u in users:
        d = devices.get(u.id)
        out.append({"staff_id": u.id, "name": _name(u), "username": u.username, "role": u.role,
                    "device": None if d is None else {"platform": d.platform, "browser": d.browser, "printer_connected": d.printer_connected,
                                                      "printer_name": d.printer_name, "online": _online(d, now), "print_mode": _mode(d),
                                                      "seconds_ago": int((now - d.last_seen_at).total_seconds())},
                    "printer_staff_id": routes.get(u.id), "eligible_printer": _can_host(d, now), "ineligible_reason": _ineligible_reason(d, now), "serving": serving.get(u.id, 0),
                    "print_station": bool(u.print_station), "station": read_station(db, event.id, u.id)})
    return {"enabled": bool(event.shared_print_enabled), "warn_per_printer": WARN_PER_PRINTER, "users": out}


@router.put("/events/{event_id}/shared-print")
def set_enabled(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG)):
    event = get_event_for_staff(event_id, db, staff)
    event.shared_print_enabled = bool(data.get("enabled"))
    db.commit()
    return {"enabled": event.shared_print_enabled}


@router.put("/events/{event_id}/shared-print/route")
def set_route(event_id: int, data: RouteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(CONFIG)):
    event = get_event_for_staff(event_id, db, staff)
    x = db.get(StaffUser, data.staff_user_id)
    if x is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    get_event_for_staff(event.id, db, x)                       # X debe tener acceso a ESTE evento (mismo cliente)
    row = db.query(PrintRoute).filter_by(event_id=event.id, staff_user_id=x.id).first()
    if data.printer_staff_id is None:
        if row:
            db.delete(row)
        db.commit()
        return {"staff_user_id": x.id, "printer_staff_id": None}
    if data.printer_staff_id == x.id:
        raise HTTPException(status_code=400, detail="Para imprimir en su propio equipo elige «En su propio equipo».")
    y = db.get(StaffUser, data.printer_staff_id)
    if y is None or not y.is_active:
        raise HTTPException(status_code=404, detail="El equipo elegido no existe.")
    get_event_for_staff(event.id, db, y)                       # Y también debe ser de este evento
    ydev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=y.id).first()
    if not _can_host(ydev):                                    # solo con impresora USB lista, o un equipo que declara imprimir con la ventana de Chrome (atiende con «Imprimir pendientes»)
        raise HTTPException(status_code=409, detail="Ese equipo no se puede elegir como anfitrión. " + (_ineligible_reason(ydev) or "No está disponible."))
    if _route(db, event.id, y.id):
        raise HTTPException(status_code=409, detail="Ese usuario imprime en otro equipo: no puede atender a otros.")
    if db.query(PrintRoute).filter(PrintRoute.event_id == event.id, PrintRoute.printer_staff_id == x.id).first():
        raise HTTPException(status_code=409, detail="Este usuario ya atiende a otros: primero cámbiales el equipo.")
    if row is None:
        row = PrintRoute(event_id=event.id, staff_user_id=x.id)
        db.add(row)
    row.printer_staff_id = y.id
    db.commit()
    serving = db.query(PrintRoute).filter(PrintRoute.event_id == event.id, PrintRoute.printer_staff_id == y.id).count()
    out = {"staff_user_id": x.id, "printer_staff_id": y.id, "serving": serving}
    if serving > WARN_PER_PRINTER:
        out["warning"] = f"El equipo de {_name(y)} imprime para {serving} usuarios: puede haber espera de impresión."
    return out

