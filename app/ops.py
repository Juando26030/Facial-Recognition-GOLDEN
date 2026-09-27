"""Chequeos de salud y estado del sistema (docs/observabilidad.md). Cada chequeo devuelve un dict con `level` (green|yellow|red), `value`
(lo que se mide), `reason` (por qué ese color) y `action` (qué hacer), en español, para la pantalla «Estado del sistema»; `/readyz` usa
los mismos chequeos de infraestructura, pero solo pide que estén en verde/amarillo para dar «listo».

Ningún chequeo debe lanzar: si no puede medir algo, lo dice (amarillo/rojo con el motivo) en vez de romper la pantalla."""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import jobs
from app.database import SessionLocal, engine
from app.models import BulkJob, Event, FormPayment, SystemEvent, WebForm
from app.storage import get_storage
from app.timeutil import local_to_utc

log = logging.getLogger("golden.ops")
_last_5xx_write = 0.0
_skipped_5xx = 0
LEVELS = {"green": 0, "yellow": 1, "red": 2}
READY_TIMEOUT = float(os.getenv("READYZ_TIMEOUT_SECONDS", "2"))
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ops")


def item(id_: str, title: str, level: str, value: str, reason: str = "", action: str = "", **data) -> dict:
    return {"id": id_, "title": title, "level": level, "value": value, "reason": reason, "action": action, "data": data}


def _worst(levels: List[str]) -> str:
    return max(levels, key=lambda lv: LEVELS[lv]) if levels else "green"


# ------------------------------------------------------------------ registro de hechos del sistema
def record_system_event(kind: str, ref: Optional[str] = None, detail: Optional[str] = None) -> None:
    """Guarda un hecho para «Estado del sistema». Nunca lanza (si la base está caída no debe empeorar la caída) pero SÍ deja constancia en el log.
    `ref`/`detail` no deben llevar datos personales (se enmascaran de todas formas)."""
    from app.obs import mask_pii
    db = SessionLocal()
    try:
        db.add(SystemEvent(kind=kind, ref=(ref or "")[:80] or None, detail=mask_pii(detail)[:500] if detail else None, at=datetime.utcnow()))
        db.commit()
    except Exception:  # noqa: BLE001 — ver docstring
        log.error("no se pudo registrar el hecho %s del sistema", kind, exc_info=True)
    finally:
        db.close()


def record_5xx(request_id: str, method: str, path: str, status: int) -> None:
    """Cuenta un error 5xx (máximo uno por segundo por proceso: en plena caída no hay que escribir miles de filas; el resto se suma al siguiente)."""
    global _last_5xx_write, _skipped_5xx
    now = time.monotonic()
    if now - _last_5xx_write < 1.0:
        _skipped_5xx += 1
        return
    extra, _skipped_5xx, _last_5xx_write = _skipped_5xx, 0, now
    record_system_event("error_5xx", request_id, f"{method} {path} -> {status}" + (f" (+{extra} más en el último segundo)" if extra else ""))


# ------------------------------------------------------------------ versión
def build_info() -> dict:
    """Commit y fecha de la versión desplegada: variables APP_COMMIT/APP_BUILD_DATE (Cloud Run) o el archivo `.build_info` que escribe el despliegue."""
    commit, date = os.getenv("APP_COMMIT"), os.getenv("APP_BUILD_DATE")
    if not commit:
        try:
            with open(os.getenv("BUILD_INFO_FILE", ".build_info"), encoding="utf8") as fh:
                info = json.load(fh)
            commit, date = info.get("commit"), info.get("date")
        except (OSError, ValueError):
            pass
    return {"commit": (commit or "desconocida")[:12], "date": date or "desconocida"}


def check_version() -> dict:
    info = build_info()
    if info["commit"] == "desconocida":
        return item("version", "Versión desplegada", "yellow", "desconocida", "El despliegue no dejó el commit (APP_COMMIT o .build_info).",
                    "Revisa el paso «Registrar versión» del despliegue.", **info)
    return item("version", "Versión desplegada", "green", f"{info['commit']} · {info['date']}", **info)


# ------------------------------------------------------------------ base de datos
def _db_probe() -> float:
    db = SessionLocal()
    try:
        t0 = time.perf_counter()
        db.execute(text("SELECT 1"))
        return (time.perf_counter() - t0) * 1000
    finally:
        db.close()


def ping_database(timeout: float = READY_TIMEOUT) -> float:
    """Milisegundos de un `SELECT 1`, con tiempo límite (si el pool está agotado o la base no responde, levanta TimeoutError)."""
    try:
        return _pool.submit(_db_probe).result(timeout=timeout)
    except FutureTimeout as exc:
        raise TimeoutError(f"la base no respondió en {timeout:g} s") from exc


def check_database() -> dict:
    try:
        ms = ping_database(timeout=5)
    except Exception as exc:  # noqa: BLE001 — se informa el motivo en pantalla
        return item("database", "Base de datos", "red", "sin respuesta", f"No se pudo consultar la base: {type(exc).__name__}.",
                    "Revisa que Postgres/Neon esté arriba y que DATABASE_URL sea correcta; mira los logs de errores.")
    level = "green" if ms < 100 else "yellow" if ms < 500 else "red"
    reason = {"green": "", "yellow": "La base responde lento.", "red": "La base responde muy lento."}[level]
    action = "" if level == "green" else "Mira las conexiones y consultas lentas; si es Neon, revisa que el cómputo no se esté reactivando."
    return item("database", "Base de datos", level, f"{ms:.0f} ms", reason, action, latency_ms=round(ms, 1))


def check_connections(db: Session) -> dict:
    pool = engine.pool
    used, size = getattr(pool, "checkedout", lambda: 0)(), (getattr(pool, "size", lambda: 0)() + getattr(pool, "_max_overflow", 0)) or 1
    try:
        total = db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar() or 0
        limit = int(db.execute(text("SELECT current_setting('max_connections')")).scalar() or 0) or 100
    except Exception as exc:  # noqa: BLE001
        return item("connections", "Conexiones a la base", "yellow", "no medido", f"No se pudieron leer las conexiones: {type(exc).__name__}.")
    ratio = max(total / limit, used / size)
    level = "green" if ratio < 0.6 else "yellow" if ratio < 0.85 else "red"
    return item("connections", "Conexiones a la base", level, f"{total} de {limit} (este proceso usa {used} de {size})",
                "" if level == "green" else "Quedan pocas conexiones libres.",
                "" if level == "green" else "Si es en plena carga, baja DB_POOL_SIZE/WEB_CONCURRENCY o usa el pooler de Neon; no reinicies durante un evento.",
                total=total, limit=limit, used=used, pool=size)


# ------------------------------------------------------------------ cola, correos, cargas
def check_queue(db: Session) -> dict:
    s = jobs.stats(db)
    level = "green"
    reasons = []
    if s["failed"]:
        level = "red" if s["failed"] >= 10 else "yellow"
        reasons.append(f"{s['failed']} trabajo(s) fallaron")
    if s["oldest_pending_seconds"] > 600:
        level = "red"
        reasons.append("hay trabajos esperando hace más de 10 minutos")
    elif s["oldest_pending_seconds"] > 60:
        level = _worst([level, "yellow"])
        reasons.append("hay trabajos esperando más de 1 minuto")
    return item("queue", "Cola de trabajos", level, f"{s['pending']} pendientes · {s['running']} en curso · {s['failed']} fallidos" +
                (f" · la más antigua {s['oldest_pending_seconds']} s" if s["pending"] else ""), "; ".join(reasons).capitalize() + "." if reasons else "",
                "" if level == "green" else "Comprueba que el worker esté corriendo (JOBS_WORKER) y mira el último error del trabajo en la tabla jobs.", **s)


def check_emails(db: Session) -> dict:
    kinds = ("email", "form_feed")
    pending = db.query(func.count(jobs.Job.id)).filter(jobs.Job.kind.in_(kinds), jobs.Job.status == "queued").scalar() or 0
    failed = db.query(func.count(jobs.Job.id)).filter(jobs.Job.kind.in_(kinds), jobs.Job.status == "failed").scalar() or 0
    level = "red" if failed >= 5 else "yellow" if failed or pending > 200 else "green"
    return item("emails", "Correos y cargas de inscripciones", level, f"{pending} pendientes · {failed} fallidos",
                "" if level == "green" else "Hay envíos que no salieron o se están acumulando.",
                "" if level == "green" else "Revisa las credenciales de correo (Graph/SMTP) y reintenta los trabajos fallidos.", pending=pending, failed=failed)


def check_bulk_jobs(db: Session) -> dict:
    running = db.query(BulkJob).filter(BulkJob.status.in_(("queued", "running"))).all()
    stuck = [j for j in running if j.updated_at and j.updated_at < datetime.utcnow() - timedelta(minutes=10)]
    if stuck:
        return item("bulk_jobs", "Cargas masivas", "red", f"{len(running)} en curso, {len(stuck)} sin avanzar", "Una carga lleva más de 10 minutos sin avanzar.",
                    "Avisa a quien la lanzó; si el servidor se reinició, debe volver a subir la carga.", running=len(running), stuck=len(stuck))
    return item("bulk_jobs", "Cargas masivas", "yellow" if running else "green", f"{len(running)} en curso",
                "Hay cargas en proceso: no reinicies el servidor." if running else "", "", running=len(running))


# ------------------------------------------------------------------ respaldos
def check_backup() -> dict:
    folder = os.getenv("BACKUP_DIR")
    max_age = float(os.getenv("BACKUP_MAX_AGE_HOURS", "26"))
    if not folder or not os.path.isdir(folder):
        return item("backup", "Último respaldo", "yellow", "no configurado", "El sistema no sabe dónde buscar los respaldos (BACKUP_DIR).",
                    "Define BACKUP_DIR con la carpeta de los volcados o verifica el respaldo directamente en el bucket.")
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith((".sql.gz", ".dump", ".sql"))]
    if not files:
        return item("backup", "Último respaldo", "red", "ninguno", f"No hay volcados en {os.path.basename(folder)}.", "Corre scripts/backup_db.sh y revisa el cron.")
    newest = max(files, key=os.path.getmtime)
    age_h = (time.time() - os.path.getmtime(newest)) / 3600
    level = "green" if age_h <= max_age else "yellow" if age_h <= max_age * 2 else "red"
    return item("backup", "Último respaldo", level, f"hace {age_h:.0f} h", "" if level == "green" else "El respaldo más reciente es más viejo de lo esperado.",
                "" if level == "green" else "Revisa el cron del respaldo (backup.log) y corre scripts/backup_db.sh a mano.", age_hours=round(age_h, 1))


# ------------------------------------------------------------------ eventos y formularios
def _next_form_openings(db: Session, hours: int = 24) -> List[dict]:
    """Formularios con calendario cuyo próximo tramo «activo» empieza en las próximas `hours` horas (hora local del calendario)."""
    from app import formsvc
    now, out = formsvc.now_local(), []
    for form in db.query(WebForm).filter(WebForm.use_schedule == True).all():  # noqa: E712
        for seg in formsvc.get_schedule(form):
            try:
                start = datetime.fromisoformat(seg["from"])
            except (KeyError, ValueError):
                continue
            if seg.get("status") == "activo" and now <= start <= now + timedelta(hours=hours):
                out.append({"form_id": form.id, "event_id": form.event_id, "opens_in_minutes": int((start - now).total_seconds() // 60)})
    return out


def check_events(db: Session) -> dict:
    running = db.query(func.count(Event.id)).filter(Event.status == "en_proceso").scalar() or 0
    openings = _next_form_openings(db)
    return item("events", "Eventos y formularios", "yellow" if running or openings else "green",
                f"{running} evento(s) en curso · {len(openings)} formulario(s) abren en las próximas 24 h",
                "Hay actividad que no debe interrumpirse." if running or openings else "",
                "No despliegues ni reinicies el servidor mientras haya eventos en curso." if running or openings else "", running=running, openings=openings)


def deploy_allowed(db: Session, hours: Optional[int] = None) -> dict:
    """¿Se puede desplegar ahora? No si hay un evento en curso, o uno/un formulario por abrir en las próximas N horas (DEPLOY_FREEZE_HOURS, 3 por defecto)."""
    hours = hours if hours is not None else int(os.getenv("DEPLOY_FREEZE_HOURS", "3"))
    reasons = []
    running = db.query(Event.event_code).filter(Event.status == "en_proceso").all()
    if running:
        reasons.append(f"Hay {len(running)} evento(s) en curso ({', '.join(r[0] for r in running[:5])}).")
    horizon = datetime.utcnow() + timedelta(hours=hours)
    for ev in db.query(Event).filter(Event.status == "creado", Event.start_date != None).all():  # noqa: E711
        start = local_to_utc(datetime.combine(ev.start_date, datetime.strptime(ev.event_time_start or "00:00", "%H:%M").time()))
        if datetime.utcnow() <= start <= horizon:
            reasons.append(f"El evento {ev.event_code} abre en menos de {hours} h.")
    reasons += [f"Un formulario del evento {o['event_id']} abre en {o['opens_in_minutes']} min." for o in _next_form_openings(db, hours)]
    return {"allowed": not reasons, "hours": hours, "reasons": reasons}


# ------------------------------------------------------------------ pagos, errores
def check_payments(db: Session) -> dict:
    last = db.query(func.max(SystemEvent.at)).filter(SystemEvent.kind == "wompi_webhook").scalar()
    stale = db.query(func.count(FormPayment.id)).filter(FormPayment.status == "pending", FormPayment.is_test == False,  # noqa: E712
                                                         FormPayment.created_at < datetime.utcnow() - timedelta(minutes=15)).scalar() or 0
    level = "red" if stale >= 5 else "yellow" if stale else "green"
    when = f"hace {int((datetime.utcnow() - last).total_seconds() // 60)} min" if last else "ninguno registrado"
    return item("payments", "Pagos (Wompi)", level, f"último webhook: {when} · {stale} pago(s) sin conciliar",
                "" if level == "green" else "Hay pagos pendientes de hace más de 15 minutos: el webhook pudo perderse.",
                "" if level == "green" else "Corre scripts/reconcile_payments.py (consulta a Wompi por referencia) y verifica la URL del webhook en el panel de Wompi.",
                stale=stale, last_webhook=last.isoformat() if last else None)


def check_errors(db: Session) -> dict:
    n = db.query(func.count(SystemEvent.id)).filter(SystemEvent.kind == "error_5xx", SystemEvent.at > datetime.utcnow() - timedelta(minutes=15)).scalar() or 0
    level = "red" if n >= 10 else "yellow" if n else "green"
    return item("errors", "Errores (últimos 15 min)", level, f"{n} error(es) del servidor", "" if level == "green" else "El servidor devolvió errores 5xx recientemente.",
                "" if level == "green" else "Busca en los logs por severity=ERROR; el id de cada error aparece en la pantalla del usuario y en el log.", count=n)


# ------------------------------------------------------------------ estado completo / readiness
def system_status(db: Session) -> dict:
    checks: List[Callable[[], dict]] = [check_version, check_database, lambda: check_connections(db), lambda: check_queue(db), check_backup,
                                        lambda: check_bulk_jobs(db), lambda: check_events(db), lambda: check_emails(db), lambda: check_payments(db),
                                        lambda: check_errors(db)]
    results = []
    for fn in checks:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 — un chequeo roto no debe tumbar la pantalla: se muestra como rojo con el motivo
            log.error("falló un chequeo de estado", exc_info=True)
            results.append(item("check", "Chequeo", "red", "error", f"El chequeo falló: {type(exc).__name__}.", "Revisa los logs del servidor."))
    return {"level": _worst([r["level"] for r in results]), "checked_at": datetime.utcnow().isoformat() + "Z", "items": results}


def model_ready() -> None:
    """Levanta si el modelo facial (dlib) no está cargado/instalable — solo el punto de entrada de biometría lo pide."""
    from app import faces
    faces.warmup()


def readiness(require_model: bool = False) -> Dict[str, dict]:
    """{componente: {"ok": bool, "reason": str}} — /readyz responde 503 si alguno no está ok."""
    out: Dict[str, dict] = {}
    try:
        out["database"] = {"ok": True, "latency_ms": round(ping_database(), 1)}
    except Exception as exc:  # noqa: BLE001
        out["database"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        get_storage().ping()
        out["storage"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        out["storage"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if require_model:
        try:
            model_ready()
            out["biometrics_model"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            out["biometrics_model"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return out
