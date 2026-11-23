"""Manejador de la cola para el importador de SuiteCRM (`crm_import`). Idempotente: una corrida terminada o cancelada no se repite.

En Cloud Run (`BULK_BACKEND=cloudrun`) la corrida se entrega al Cloud Run Job de la carga masiva (`python -m app.crm.import_runner <id>`):
una petición de la cola se corta a los ~60 s y una carga real de decenas de miles de filas tarda más (carga #5 de staging, 14-nov-2026:
quedó a medias y sin error visible). En local (hilo) se corre aquí mismo."""
import logging
import os

from app import jobs
from app.crm.importer import runner
from app.database import SessionLocal
from app.models import CrmImportRun
from app.timeutil import utcnow

log = logging.getLogger("golden.crm_import")


def launch_cloud_run(run_id: int) -> None:
    from app import cloudrun
    cloudrun.run_job(os.environ["BULK_JOB_NAME"], ["-m", "app.crm.import_runner", str(run_id)])


def _fail(db, run_id: int, message: str) -> None:
    row = db.get(CrmImportRun, run_id)
    if row is not None and row.status == "queued":
        row.status, row.error, row.finished_at = "failed", message[:500], utcnow()
        db.commit()


@jobs.handler("crm_import")
def _crm_import_job(payload: dict) -> None:
    run_id = int(payload["run_id"])
    db = SessionLocal()
    try:
        from app import bulk_jobs
        if bulk_jobs.uses_cloud_run():
            row = db.get(CrmImportRun, run_id)
            if row is None or row.status != "queued":
                return                                           # ya la tomó el Job (o terminó): no se lanza otra
            try:
                launch_cloud_run(run_id)
            except Exception:
                log.error("no se pudo lanzar el Cloud Run Job de la importación %s", run_id, exc_info=True)
                db.rollback()
                _fail(db, run_id, "No se pudo iniciar el proceso de importación. Intenta de nuevo.")
            return
        runner.run(db, run_id)
    finally:
        db.close()
