"""Cola de trabajos en segundo plano — detrás de una interfaz pequeña para poder cambiar la implementación sin tocar a quien la usa.

La tabla `jobs` de Postgres es SIEMPRE la fuente de verdad (encolar dentro de la transacción, reintentos, «Estado del sistema»). Lo que
cambia según `JOBS_BACKEND` es quién la despierta:
  * `db` (por defecto, VM): un hilo dentro del proceso web (`JOBS_WORKER`) o `python -m app.worker` aparte, que sondea la tabla.
  * `cloudtasks` (Cloud Run, donde un hilo en segundo plano se queda sin CPU al terminar la petición): `kick()` crea una tarea de Cloud
    Tasks que llama a `POST /internal/jobs/run` (routers/ops.py) y ese endpoint ejecuta la cola dentro de su propia petición. Una tarea
    por segundo como máximo (nombre `kick-<segundo>`, programada al segundo siguiente: mil envíos en el mismo segundo = una tarea). Un
    reintento programa su propia tarea para cuando vence. Variables: `CLOUD_TASKS_QUEUE` (ruta completa de la cola),
    `CLOUD_TASKS_URL` (URL del endpoint, también es la audiencia del token OIDC) y `JOBS_INVOKER_SA` (cuenta de servicio del token).
    Si crear la tarea falla, el trabajo sigue en la tabla y lo toma el siguiente aviso o el barrido programado (Cloud Scheduler).

Reglas de diseño:
  * `enqueue(db, ...)` solo AGREGA la fila a la sesión del que llama: se confirma junto con su transacción (si la inscripción se deshace,
    el trabajo también). Después de confirmar, `kick()` despierta al worker local.
  * Cada trabajo se reclama con `FOR UPDATE SKIP LOCKED` (varios workers/procesos sin pisarse; compatible con PgBouncer en modo transacción:
    ni locks de sesión ni LISTEN/NOTIFY) y con un ARRIENDO (`locked_until`): si el proceso muere a mitad, el trabajo vuelve a la cola solo.
  * Reintentos con espera creciente; al agotarse pasa a `failed` y queda visible en «Estado del sistema».
  * Los manejadores deben ser IDEMPOTENTES (pueden correr dos veces si el proceso murió justo antes de marcarlos).
  * Apagado ordenado: `Worker.stop()` deja de reclamar, termina el trabajo en curso y sale."""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job

log = logging.getLogger("golden.jobs")

LEASE = timedelta(seconds=int(os.getenv("JOB_LEASE_SECONDS", "120")))
POLL_SECONDS = float(os.getenv("JOB_POLL_SECONDS", "5"))
BACKOFF_SECONDS = (15, 60, 300, 900, 3600)

_handlers: Dict[str, Callable[[dict], None]] = {}
_wake = threading.Event()


def handler(kind: str):
    """Registra la función que ejecuta los trabajos de ese tipo: `fn(payload: dict) -> None` (abre su propia sesión)."""
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


def enqueue(db: Session, kind: str, payload: dict, *, run_at: Optional[datetime] = None, dedupe_key: Optional[str] = None, max_attempts: int = 5) -> None:
    """Agrega un trabajo a la transacción de `db` (no confirma). Con `dedupe_key`, un segundo trabajo igual del mismo tipo se ignora."""
    if dedupe_key and db.query(Job.id).filter(Job.kind == kind, Job.dedupe_key == dedupe_key).first():
        return
    now = datetime.utcnow()
    db.add(Job(kind=kind, payload_json=json.dumps(payload), dedupe_key=dedupe_key, run_at=run_at or now, max_attempts=max_attempts, created_at=now))


def uses_cloud_tasks() -> bool:
    return os.getenv("JOBS_BACKEND", "db") == "cloudtasks"


_tasks_client = None


def _cloud_task(at: datetime) -> None:
    """Pide a Cloud Tasks que llame a /internal/jobs/run en el segundo siguiente a `at` (UTC). Nombre por segundo = sin tareas repetidas."""
    global _tasks_client
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2
    if _tasks_client is None:
        _tasks_client = tasks_v2.CloudTasksClient()
    queue, url = os.environ["CLOUD_TASKS_QUEUE"], os.environ["CLOUD_TASKS_URL"]
    second = int(at.replace(tzinfo=timezone.utc).timestamp()) + 1
    task = {"name": f"{queue}/tasks/kick-{second}", "schedule_time": datetime.fromtimestamp(second, timezone.utc),
            "http_request": {"http_method": tasks_v2.HttpMethod.POST, "url": url,
                             "oidc_token": {"service_account_email": os.environ["JOBS_INVOKER_SA"], "audience": url}}}
    try:
        _tasks_client.create_task(parent=queue, task=task)
    except AlreadyExists:
        pass


def kick(at: Optional[datetime] = None) -> None:
    """Avisa que hay trabajo (nuevo, o que vence en `at`): al hilo local, o con una tarea de Cloud Tasks."""
    if not uses_cloud_tasks():
        _wake.set()
        return
    try:
        _cloud_task(at or datetime.utcnow())
    except Exception:  # noqa: BLE001 — el trabajo ya está a salvo en la tabla; no se tumba la petición de quien encoló
        log.error("no se pudo crear la tarea de Cloud Tasks; la tomará el siguiente aviso o el barrido programado", exc_info=True)


def _claim(limit: int) -> list:
    """Reclama hasta `limit` trabajos vencidos y los marca en curso. Devuelve [(id, kind, payload)]."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = (db.query(Job)
                .filter(((Job.status == "queued") & (Job.run_at <= now)) | ((Job.status == "running") & (Job.locked_until < now)))
                .order_by(Job.run_at, Job.id).limit(limit).with_for_update(skip_locked=True).all())
        claimed = []
        for job in rows:
            job.status, job.locked_until, job.attempts = "running", now + LEASE, (job.attempts or 0) + 1
            claimed.append((job.id, job.kind, json.loads(job.payload_json), job.attempts, job.max_attempts))
        db.commit()
        return claimed
    finally:
        db.close()


def _finish(job_id: int, error: Optional[str], attempts: int, max_attempts: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        now = datetime.utcnow()
        job.locked_until = None
        if error is None:
            job.status, job.finished_at, job.last_error = "done", now, None
        elif attempts >= max_attempts:
            job.status, job.finished_at, job.last_error = "failed", now, error[:2000]
        else:
            job.status, job.last_error = "queued", error[:2000]
            job.run_at = now + timedelta(seconds=BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)])
        retry_at = job.run_at if job.status == "queued" else None
        db.commit()
    finally:
        db.close()
    if retry_at and uses_cloud_tasks():           # con el hilo local no hace falta: el sondeo lo encuentra solo
        kick(retry_at)


def run_once(limit: int = 10) -> int:
    """Ejecuta un lote de trabajos vencidos. Devuelve cuántos ejecutó (los tests y `python -m app.worker --once` lo usan)."""
    claimed = _claim(limit)
    for job_id, kind, payload, attempts, max_attempts in claimed:
        fn = _handlers.get(kind)
        try:
            if fn is None:
                raise LookupError(f"no hay manejador para el trabajo «{kind}»")
            fn(payload)
            _finish(job_id, None, attempts, max_attempts)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo de un trabajo se registra y se reintenta; no debe tumbar al worker
            log.error("trabajo %s (%s) falló en el intento %s: %s", job_id, kind, attempts, exc, exc_info=True)
            _finish(job_id, f"{type(exc).__name__}: {exc}", attempts, max_attempts)
    return len(claimed)


def drain(max_rounds: int = 50, budget_seconds: Optional[float] = None) -> int:
    """Ejecuta trabajos hasta que no quede ninguno vencido, EN el hilo de quien llama (nunca en segundo plano).

    `budget_seconds`: deja de reclamar lotes nuevos al pasar ese tiempo (el endpoint de Cloud Tasks lo usa para responder antes del
    timeout de la petición); con presupuesto los lotes son chicos para no dejar trabajos reclamados sin ejecutar. Si se corta con
    trabajo pendiente, programa otra tarea para seguir."""
    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    total = n = 0
    for _ in range(max_rounds):
        if deadline is not None and time.monotonic() >= deadline:
            kick()
            break
        n = run_once(5 if deadline is not None else 50)
        total += n
        if not n:
            break
    else:
        if n:
            kick()
    return total


class Worker(threading.Thread):
    """Hilo que sondea la cola. Se detiene con `stop()` sin cortar el trabajo en curso."""

    def __init__(self) -> None:
        super().__init__(name="golden-jobs", daemon=True)
        self._stop_flag = threading.Event()

    def run(self) -> None:
        log.info("worker de trabajos iniciado")
        while not self._stop_flag.is_set():
            try:
                did = run_once(10)
            except Exception:  # noqa: BLE001 — la base pudo caerse un momento: se reintenta en el siguiente ciclo
                log.error("el worker no pudo leer la cola", exc_info=True)
                did = 0
            if not did:
                _wake.wait(POLL_SECONDS)
                _wake.clear()
        log.info("worker de trabajos detenido")

    def stop(self, timeout: float = 8.0) -> None:
        self._stop_flag.set()
        _wake.set()
        self.join(timeout)


def stats(db: Session) -> dict:
    """Para «Estado del sistema»: pendientes, la más antigua, en curso y fallidas."""
    from sqlalchemy import func
    now = datetime.utcnow()
    pending = db.query(func.count(Job.id), func.min(Job.run_at)).filter(Job.status == "queued").first()
    due = db.query(func.min(Job.run_at)).filter(Job.status == "queued", Job.run_at <= now).scalar()      # los que esperan un reintento futuro no cuentan como atrasados
    return {
        "pending": pending[0] or 0,
        "oldest_pending_seconds": int((now - due).total_seconds()) if due else 0,
        "running": db.query(func.count(Job.id)).filter(Job.status == "running").scalar() or 0,
        "failed": db.query(func.count(Job.id)).filter(Job.status == "failed").scalar() or 0,
    }
