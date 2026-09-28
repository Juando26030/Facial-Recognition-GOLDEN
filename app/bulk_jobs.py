"""Cargas masivas en segundo plano con progreso (Sprint 5).

`bulk_register` con `background=true` ya no procesa dentro de la petición: crea una fila `bulk_jobs`, lanza un hilo
que hace el trabajo (con su propia sesión de base de datos) y responde de inmediato con el `job_id`. El navegador
consulta `GET /api/bulk_jobs/{id}` y dibuja la barra con el porcentaje y el tiempo estimado. Ventajas: se ve el
avance, un proceso de horas ya no depende de que la conexión HTTP aguante, y la app no queda congelada para los
demás usuarios mientras se codifican fotos.

El estado vive en Postgres (no en memoria). Dónde corre el trabajo lo decide `BULK_BACKEND`:
  * `thread` (por defecto; VM y desarrollo): un hilo en el proceso que recibió la petición. Si ese proceso se reinicia a mitad de
    camino, la tarea queda sin latidos y se marca como interrumpida al consultarla.
  * `cloudrun` (Cloud Run): en Cloud Run un hilo se queda sin CPU apenas se responde, y una carga de miles de fotos tarda horas.
    La petición guarda en la fila qué procesar (`spec_json`: tokens de los archivos YA subidos al bucket, no su contenido — el servicio
    web ni siquiera los descarga) y lanza una ejecución del Cloud Run Job `BULK_JOB_NAME` con el id como argumento; el Job
    (`python -m app.bulk_runner <id>`, misma imagen) corre el mismo código y reporta el avance en la misma fila. La barra no cambia.
"""
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BulkJob

log = logging.getLogger("golden.bulk")

_active = set()      # ids de las cargas que ESTE proceso está ejecutando (para marcarlas si se apaga a mitad)

PHOTO_WEIGHT = 20   # una foto (encoding facial) pesa ~20 veces más que guardar una fila
ROW_WEIGHT = 1
STALE_AFTER = timedelta(minutes=10)


def uses_cloud_run() -> bool:
    return os.getenv("BULK_BACKEND", "thread") == "cloudrun"


def create_job(db: Session, event_id: int, staff_id: int, spec: dict = None) -> str:
    job = BulkJob(id=uuid.uuid4().hex, event_id=event_id, staff_user_id=staff_id, status="queued", stage="En cola",
                  spec_json=json.dumps(spec) if spec is not None else None)
    db.add(job)
    db.commit()
    return job.id


def active_job(db: Session, event_id: int):
    """Tarea en curso de este evento (y con latido reciente), para no procesar dos cargas a la vez."""
    since = datetime.utcnow() - STALE_AFTER
    return db.query(BulkJob).filter(
        BulkJob.event_id == event_id, BulkJob.status.in_(("queued", "running")), BulkJob.updated_at > since,
    ).first()


class Reporter:
    """Callable `progress(stage, done, total)` que actualiza la fila de la tarea (con su propia sesión, para no
    mezclarse con la transacción de la carga) como máximo una vez por segundo."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.db = SessionLocal()
        self.last = 0.0

    def __call__(self, stage: str, done: int, total: int, force: bool = False):
        now = time.time()
        if not force and now - self.last < 1.0:
            return
        self.last = now
        self.db.query(BulkJob).filter(BulkJob.id == self.job_id).update(
            {"status": "running", "stage": stage, "done": done, "total": total, "updated_at": datetime.utcnow()}
        )
        self.db.commit()

    def close(self):
        self.db.close()


def _finish(job_id: str, result=None, error_status=None, error_detail=None):
    db = SessionLocal()
    try:
        values = {"finished_at": datetime.utcnow(), "updated_at": datetime.utcnow()}
        if error_status is not None:
            values.update(status="error", error_status=error_status, error_detail=str(error_detail), stage="Error")
        else:
            values.update(status="done", result_json=json.dumps(result), stage="Listo")
            job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
            if job and job.total:
                values["done"] = job.total
        db.query(BulkJob).filter(BulkJob.id == job_id).update(values)
        db.commit()
    finally:
        db.close()


def run(job_id: str, work) -> None:
    """Ejecuta `work(db, reporter)` y deja el resultado en la tarea. `work` devuelve el resultado (dict) o lanza HTTPException /
    cualquier error — que quedan guardados en la tarea para que el navegador los muestre como antes."""
    from fastapi import HTTPException

    db = SessionLocal()
    reporter = Reporter(job_id)
    _active.add(job_id)
    try:
        reporter("Preparando", 0, 0, force=True)
        _finish(job_id, result=work(db, reporter))
    except HTTPException as e:
        db.rollback()
        _finish(job_id, error_status=e.status_code, error_detail=e.detail)
    except Exception as e:  # noqa: BLE001 — cualquier fallo se le muestra al usuario, no se pierde en el hilo
        log.error("la carga %s falló", job_id, exc_info=True)
        db.rollback()
        _finish(job_id, error_status=500, error_detail=f"Error inesperado: {e}")
    finally:
        _active.discard(job_id)
        reporter.close()
        db.close()


def start(job_id: str, work) -> None:
    """Modo `thread`: `run` en un hilo aparte."""
    threading.Thread(target=run, args=(job_id, work), daemon=True, name=f"bulk-{job_id[:8]}").start()


def launch_cloud_run(job_id: str) -> None:
    """Modo `cloudrun`: una ejecución del Job `BULK_JOB_NAME` (projects/<p>/locations/<r>/jobs/<nombre>) con el id como argumento.
    Por la API REST de Cloud Run con las credenciales del servicio (necesita run.jobs.runWithOverrides sobre ese Job)."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    resp = AuthorizedSession(creds).post(
        f"https://run.googleapis.com/v2/{os.environ['BULK_JOB_NAME']}:run",
        json={"overrides": {"containerOverrides": [{"args": ["-m", "app.bulk_runner", job_id]}]}}, timeout=30)
    resp.raise_for_status()


def mark_interrupted() -> int:
    """Apagado ordenado (SIGTERM): las cargas que este proceso tenía en curso se marcan YA como interrumpidas, para que quien las lanzó lo vea al instante y
    pueda repetirlas — en vez de quedar «en proceso» hasta que se venza el latido (10 min). Devuelve cuántas marcó."""
    ids = list(_active)
    for job_id in ids:
        _finish(job_id, error_status=503, error_detail="La carga se interrumpió porque el servidor se reinició. Vuelve a subirla.")
    return len(ids)


def serialize(job: BulkJob, db: Session) -> dict:
    """Estado para el navegador. Una tarea 'running' sin latidos hace más de 10 min se da por interrumpida."""
    if job.status in ("queued", "running") and job.updated_at < datetime.utcnow() - STALE_AFTER:
        job.status, job.error_status, job.stage = "error", 500, "Interrumpida"
        job.error_detail = "La carga se interrumpió (el servidor se reinició). Vuelve a intentarlo."
        job.finished_at = datetime.utcnow()
        db.commit()
    out = {"id": job.id, "status": job.status, "stage": job.stage, "done": job.done, "total": job.total,
           "elapsed": ((job.finished_at or datetime.utcnow()) - job.created_at).total_seconds()}
    if job.status == "done":
        out["result"] = json.loads(job.result_json)
    if job.status == "error":
        out["error"] = {"status": job.error_status, "detail": job.error_detail}
    return out
