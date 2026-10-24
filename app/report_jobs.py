"""Reporte Excel de la base del evento, en SEGUNDO PLANO y con progreso (orden del 23-oct-2026: el reporte directo de 3.000 personas se cortaba a los 60 s de Firebase Hosting).

Flujo (todo cabe holgado en los 60 s por petición, con miles de personas):
  1. `POST /api/report/start {event_id}`: crea una tarea (la misma tabla y el mismo seguimiento que la carga masiva, `bulk_jobs`) y la arma en un hilo; espera como mucho
     `REPORT_START_WAIT` s a que termine (lo normal con unos miles de personas) y responde SIEMPRE con el estado de la tarea (`running` o `done`).
  2. `GET /api/report/status/{id}`: etapa, porcentaje y, al terminar, `ready`.
  3. `GET /api/report/download/{id}`: entrega el archivo YA guardado en el almacenamiento (no genera nada: pesa lo que el Excel y dura segundos).
El archivo (lleva datos personales) solo lo ve quien lo pidió, se llama «<evento> - <código> - Reporte final.xlsx» (el nombre del evento, no datos de personas), vence a la hora (`REPORT_TTL_MINUTES`) y se borra: al
vencer, en cada nuevo reporte y en la tarea horaria de operaciones. Cada descarga queda en la bitácora (log `golden.report`: tarea, evento y usuario; sin datos personales). No incluye biometría.

Un reporte tarda unos segundos: corre en un hilo del propio servicio (no en un Cloud Run Job, cuyo arranque en frío costaría más que el reporte). Mientras alguien consulta el avance, la
instancia tiene CPU; si el hilo no alcanza a terminar, la tarea queda en `error` (por el vencimiento de latido de `bulk_jobs`) y se puede pedir de nuevo.
El reporte directo `GET /api/report` sigue existiendo, ya sin consultas por persona a Cloud Storage."""
import json
import logging
import os
import tempfile
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import bulk_jobs, heavy
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import BulkJob, StaffUser
from app.reports import ReportManager
from app.storage import get_storage, key_of
from app.timeutil import utcnow

log = logging.getLogger("golden.report")
router = APIRouter()
ROLE = require_role("coordinador")            # misma regla que el reporte de siempre (cliente no exporta la base)
TTL = timedelta(minutes=int(os.getenv("REPORT_TTL_MINUTES", "60")))
START_WAIT = float(os.getenv("REPORT_START_WAIT", "8"))
REPORT_KIND = "Reporte final"
KIND = json.dumps({"kind": "report"})


def _storage_key(tenant_id: str, job_id: str) -> str:
    return key_of(tenant_id, "report_exports", f"{job_id}.xlsx")


def purge_expired(db: Session) -> int:
    """Borra del almacenamiento los reportes vencidos (y marca la tarea). Barato: una consulta por las tareas de reporte ya terminadas hace más de TTL."""
    cut = utcnow() - TTL
    n = 0
    for job in db.query(BulkJob).filter(BulkJob.spec_json == KIND, BulkJob.status == "done", BulkJob.finished_at < cut, BulkJob.result_json.isnot(None)).all():
        result = json.loads(job.result_json or "{}")
        if result.get("key"):
            try:
                get_storage().delete(result["key"])
            except Exception:  # noqa: BLE001 — se reintenta en la siguiente pasada
                log.warning("no se pudo borrar un reporte vencido", exc_info=True)
                continue
            job.result_json = json.dumps({"expired": True})
            n += 1
    if n:
        db.commit()
    return n


def _work(event_id: int, tenant_id: str, job_id: str):
    def work(job_db, reporter):
        with heavy.heavy_slot(), tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "reporte.xlsx")
            ReportManager.generate_excel_report(job_db, event_id, tenant_id, path, progress=reporter)
            reporter("Guardando el archivo", 97, 100, force=True)
            with open(path, "rb") as fh:
                data = fh.read()
        key = _storage_key(tenant_id, job_id)
        get_storage().put(key, data)
        return {"key": key, "bytes": len(data), "expires_at": (utcnow() + TTL).isoformat() + "Z"}
    return work


def _out(job: BulkJob) -> dict:
    result = json.loads(job.result_json) if job.result_json else {}
    total = job.total or 0
    percent = 100 if job.status == "done" else (int(min(99, job.done * 100 / total)) if total else 0)
    return {"job_id": job.id, "status": job.status, "stage": job.stage or "", "percent": percent, "ready": job.status == "done" and bool(result.get("key")),
            "expired": bool(result.get("expired")), "expires_at": result.get("expires_at"),
            "error": job.error_detail if job.status == "error" else None, "bytes": result.get("bytes")}


def _mine(db: Session, job_id: str, staff: StaffUser) -> BulkJob:
    """Solo quien pidió el reporte (y con acceso al evento) lo ve; cualquier otro caso es 404."""
    job = db.query(BulkJob).filter(BulkJob.id == job_id, BulkJob.spec_json == KIND).first()
    if job is None or job.staff_user_id != staff.id:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    get_event_for_staff(job.event_id, db, staff)
    return job


@router.post("/report/start")
def start_report(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ROLE)):
    try:
        event_id = int(data.get("event_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Falta el evento")
    event = get_event_for_staff(event_id, db, staff)
    purge_expired(db)
    active = bulk_jobs.active_job(db, event.id)
    if active is not None:
        if active.spec_json == KIND and active.staff_user_id == staff.id:      # el mismo usuario pidió otra vez: se le da el mismo reporte en curso
            job = active
        else:
            raise HTTPException(status_code=409, detail="Hay una carga o un reporte en curso para este evento: espera a que termine y vuelve a pedirlo.")
    else:
        job_id = bulk_jobs.create_job(db, event.id, staff.id, {"kind": "report"})
        bulk_jobs.start(job_id, _work(event.id, event.tenant_id, job_id))
        job = db.get(BulkJob, job_id)
    deadline = time.time() + START_WAIT
    while time.time() < deadline and job.status in ("queued", "running"):
        time.sleep(0.25)
        db.expire_all()
        job = db.get(BulkJob, job.id)
    return _out(job)


@router.get("/report/status/{job_id}")
def report_status(job_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(ROLE)):
    return _out(_mine(db, job_id, staff))


@router.get("/report/download/{job_id}")
def report_download(job_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(ROLE)):
    job = _mine(db, job_id, staff)
    out = _out(job)
    if out["expired"] or (job.status == "done" and job.finished_at and utcnow() - job.finished_at > TTL):
        raise HTTPException(status_code=410, detail="Este reporte ya venció (dura una hora). Genera uno nuevo.")
    if not out["ready"]:
        raise HTTPException(status_code=409, detail="El reporte todavía no está listo.")
    key = json.loads(job.result_json)["key"]
    if not get_storage().exists(key):
        raise HTTPException(status_code=410, detail="Este reporte ya no está disponible. Genera uno nuevo.")
    log.info("reporte descargado: tarea %s, evento %s, usuario %s", job.id, job.event_id, staff.id)
    event = get_event_for_staff(job.event_id, db, staff)
    return get_storage().response(key, media_type=heavy.XLSX, headers={"Cache-Control": "no-store", "Content-Disposition": heavy.content_disposition(heavy.event_report_filename(event, REPORT_KIND))})
