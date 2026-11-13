"""Manejador de la cola para el importador de SuiteCRM (`crm_import`). Idempotente: una corrida terminada o cancelada no se repite."""
from app import jobs
from app.crm.importer import runner
from app.database import SessionLocal


@jobs.handler("crm_import")
def _crm_import_job(payload: dict) -> None:
    db = SessionLocal()
    try:
        runner.run(db, int(payload["run_id"]))
    finally:
        db.close()
