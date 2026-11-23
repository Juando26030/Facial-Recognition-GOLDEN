"""Punto de entrada del Cloud Run Job de la importación de SuiteCRM: `python -m app.crm.import_runner <id de la corrida>`.

Mismo código que el modo hilo (`runner.run`); el error queda en la corrida y se ve en la pantalla, así que sale con 0 (reintentar no arregla un dato malo)."""
import logging
import sys

from app.crm.importer import runner
from app.database import SessionLocal
from app.obs import configure_logging


def main(run_id: str) -> int:
    db = SessionLocal()
    try:
        runner.run(db, int(run_id))
    except Exception:
        logging.getLogger("golden.crm_import").error("la importación %s terminó con error", run_id, exc_info=True)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(main(sys.argv[1]))
