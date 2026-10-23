"""Impresión compartida de escarapelas (orden del 22-oct-2026, evento sin rostro de ~3000 personas). APAGADA por defecto, por evento.

Equipos Android con Chrome. Algunos (los «Y») tienen una Brother QL-800 por USB; otros (los «X») registran y su escarapela sale en la impresora de un Y.
  - Cada equipo que abre el Registro reporta cada pocos segundos su plataforma, navegador y si tiene la impresora conectada (`heartbeat`). Sin IP ni datos de personas.
  - En Parámetros se elige, para cada usuario X, «en su propio equipo» o «en el equipo de Y» (sin tope: con más de WARN_PER_PRINTER usuarios en una impresora, Parámetros avisa que puede haber espera).
  - Cuando X registra con impresión automática, su equipo pide un trabajo (`POST print-jobs`, con un `request_id` propio: un reintento no duplica).
  - El equipo Y pregunta cada 1-2 s por su siguiente trabajo (`GET print-jobs/next`): el servidor lo RESERVA de forma atómica (queued → sent, FOR UPDATE SKIP
    LOCKED), Y imprime por USB y confirma (`result`: printed | failed). Un trabajo reservado no se vuelve a entregar: nunca se imprime dos veces solo.
  - Lo que no se imprimió en PRINT_JOB_TTL queda «expired» (visible para reimprimir a mano); nunca se imprime después por su cuenta.
Carga: solo pregunta el equipo que de verdad atiende a alguien (≤ 1 consulta indexada cada 1,5 s por impresora) y el resto reporta cada 10 s."""
import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import AccessLog, Event, EventAttendee, EventStaffAuthorization, PrintDevice, PrintJob, PrintLog, PrintRoute, StaffUser, User
from app.timeutil import utcnow

log = logging.getLogger("golden.shared_print")
router = APIRouter()

PRINT_JOB_TTL = timedelta(minutes=5)
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


class JobIn(BaseModel):
    user_id: str
    request_id: str


class ResultIn(BaseModel):
    ok: bool
    error: Optional[str] = None


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
    n = (db.query(PrintJob).filter(PrintJob.event_id == event_id, PrintJob.status.in_(("queued", "sent")), PrintJob.created_at < cut)
         .update({PrintJob.status: "expired", PrintJob.done_at: utcnow()}, synchronize_session=False))
    if n:
        db.commit()
        log.warning("impresión compartida: %s trabajo(s) caducaron sin imprimirse en el evento %s", n, event_id)


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
    return {"id": job.id, "status": job.status, "printer_name": _name(printer), "error": job.error,
            "created_at": job.created_at.isoformat() + "Z", "done_at": job.done_at.isoformat() + "Z" if job.done_at else None}


# ------------------------------------------------------------------------------------------------ equipos (cualquiera que registre)
@router.post("/events/{event_id}/print-devices/heartbeat")
def heartbeat(event_id: int, data: HeartbeatIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """El equipo dice que sigue ahí y si tiene la impresora conectada. Responde dónde imprime este usuario y si debe preguntar por trabajos (si atiende a alguien)."""
    event = _enabled_event(event_id, db, staff)
    now = utcnow()
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff.id).first()
    if dev is None:
        dev = PrintDevice(event_id=event.id, staff_user_id=staff.id, device_id=_clip(data.device_id, 64) or "?", last_seen_at=now)
        db.add(dev)
    dev.device_id = _clip(data.device_id, 64) or dev.device_id
    dev.platform, dev.browser = _clip(data.platform, 40), _clip(data.browser, 40)
    if data.printer_connected is not None or dev.printer_connected is None:
        dev.printer_connected, dev.printer_name = bool(data.printer_connected), _clip(data.printer_name, 80)
    dev.last_seen_at = now
    db.commit()
    printer_id = _route(db, event.id, staff.id)
    printer = db.get(StaffUser, printer_id) if printer_id else None
    printer_dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=printer_id).first() if printer_id else None
    serving = db.query(PrintRoute).filter(PrintRoute.event_id == event.id, PrintRoute.printer_staff_id == staff.id).count()
    return {"enabled": True, "mode": "shared" if printer_id else "self", "printer_name": _name(printer), "printer_ready": _printer_ready(printer_dev, now),
            "serving": serving, "poll": bool(serving and dev.printer_connected)}


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
    job = PrintJob(event_id=event.id, attendee_id=attendee.id, requested_by_staff_id=staff.id, printer_staff_id=printer_id, request_id=request_id,
                   status="queued", created_at=utcnow())
    db.add(job)
    db.commit()
    dev = db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=printer_id).first()
    ready = _printer_ready(dev)
    log.info("impresión compartida: trabajo %s en cola (evento %s)", job.id, event.id)
    out = {**_job_out(db, job), "duplicate": False, "printer_ready": ready}
    if not ready:
        out["warning"] = (f"El equipo de {out['printer_name']} no está conectado o no tiene la impresora: la escarapela quedó en cola "
                          f"({int(PRINT_JOB_TTL.total_seconds() // 60)} min) y podrás reimprimirla.")
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
def my_jobs(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """La cola visible de quien pidió: lo que no se imprimió en las últimas 4 horas (en cola, enviado, fallido o caducado), con la persona para reimprimir."""
    event = _enabled_event(event_id, db, staff)
    _expire(db, event.id)
    rows = (db.query(PrintJob, EventAttendee).join(EventAttendee, EventAttendee.id == PrintJob.attendee_id)
            .filter(PrintJob.event_id == event.id, PrintJob.requested_by_staff_id == staff.id, PrintJob.status != "printed",
                    PrintJob.created_at >= utcnow() - timedelta(hours=4))
            .order_by(PrintJob.id.desc()).limit(50).all())
    printed_later = {a for (a,) in db.query(PrintJob.attendee_id).filter(PrintJob.event_id == event.id, PrintJob.status == "printed",
                                                                        PrintJob.attendee_id.in_([a.id for _j, a in rows] or [0]))}
    return {"jobs": [{**_job_out(db, j), "user_id": a.user_id, "printed_later": a.id in printed_later} for j, a in rows]}


# ------------------------------------------------------------------------------------------------ Y: recibir e imprimir
@router.get("/events/{event_id}/print-jobs-next")
def next_job(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    """El siguiente trabajo para el equipo de este usuario: se RESERVA de forma atómica (queued → sent). Un trabajo reservado no se vuelve a entregar."""
    event = _enabled_event(event_id, db, staff)
    now = utcnow()
    db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff.id).update({PrintDevice.last_seen_at: now}, synchronize_session=False)
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
    return {"job": {"id": job.id, "user_id": attendee.user_id if attendee else None, "requested_by": _name(requester)}}


@router.post("/events/{event_id}/print-jobs/{job_id}/result")
def job_result(event_id: int, job_id: int, data: ResultIn, db: Session = Depends(get_db), staff: StaffUser = Depends(OPERATOR)):
    event = _enabled_event(event_id, db, staff)
    job = db.query(PrintJob).filter(PrintJob.id == job_id, PrintJob.event_id == event.id).with_for_update().first()
    if job is None or job.printer_staff_id != staff.id:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
    if job.status != "sent":                                   # ya confirmado (o caducado): no cambia, idempotente
        db.commit()
        return _job_out(db, job)
    job.status = "printed" if data.ok else "failed"
    job.error = None if data.ok else _clip(data.error or "La impresora no respondió.", 200)
    job.done_at = utcnow()
    if data.ok:
        attendee = db.get(EventAttendee, job.attendee_id)
        if attendee is not None:                               # el conteo de impresiones de siempre (aviso de reimpresión), a nombre de quien lo pidió
            db.add(PrintLog(tenant_id=attendee.tenant_id, user_id=attendee.user_id, event_id=event.id, printed_by_staff_id=job.requested_by_staff_id))
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
                                                      "printer_name": d.printer_name, "online": _online(d, now),
                                                      "seconds_ago": int((now - d.last_seen_at).total_seconds())},
                    "printer_staff_id": routes.get(u.id), "eligible_printer": _printer_ready(d, now), "serving": serving.get(u.id, 0)})
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
    if not _printer_ready(db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=y.id).first()):
        raise HTTPException(status_code=409, detail="Ese equipo no está conectado con la impresora en este momento: no se puede elegir.")
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

