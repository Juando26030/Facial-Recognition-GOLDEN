"""Punto de entrada del Cloud Run Job de la carga masiva: `python -m app.bulk_runner <id de la tarea>` (ver app/bulk_jobs.py).

Corre UNA carga con el mismo código y el mismo reporte de avance que el modo hilo. Sale con código 0 aunque la carga termine en error
(el error ya quedó en la tarea y lo ve el navegador): reintentar el Job no arreglaría un archivo mal formado y volvería a procesar fotos."""
import logging
import sys

from app import bulk_jobs
from app.database import SessionLocal
from app.models import BulkJob
from app.obs import configure_logging


def main(job_id: str) -> int:
    db = SessionLocal()
    try:
        job = db.get(BulkJob, job_id)
        if not job or not job.spec_json or job.status not in ("queued", "running"):
            logging.getLogger("golden.bulk").error("la tarea %s no existe, no es de un Job o ya terminó", job_id)
            return 1
    finally:
        db.close()
    from app.routers.api import run_bulk_spec
    bulk_jobs.run(job_id, lambda job_db, reporter: run_bulk_spec(job_db, job_db.get(BulkJob, job_id), reporter))
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(main(sys.argv[1]))
