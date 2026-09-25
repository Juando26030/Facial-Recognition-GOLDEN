"""Aplica la política de retención de datos biométricos: borra el rostro (encoding + foto) de las personas de eventos FINALIZADOS hace más de
`BIOMETRIC_RETENTION_DAYS` días (180 = 6 meses por defecto; `0` apaga el borrado automático). Debe coincidir con la Política de Privacidad publicada.

    0 4 * * * cd /home/juando02603/Facial-Recognition && venv/bin/python scripts/purge_biometrics.py >> ~/backups/purge.log 2>&1

`--dry-run` solo cuenta lo que se borraría. Las personas que siguen en otro evento NO finalizado del mismo cliente se conservan.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from app import privacy  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Event  # noqa: E402


def main() -> int:
    days = privacy.retention_days()
    if not days:
        print("BIOMETRIC_RETENTION_DAYS=0: el borrado automático está apagado, no se borra nada.")
        return 0
    db = SessionLocal()
    try:
        if "--dry-run" in sys.argv:
            from datetime import date, timedelta
            limit = date.today() - timedelta(days=days)
            events = db.query(Event).filter(Event.status == "finalizado", Event.end_date < limit, Event.biometrics_purged_at.is_(None)).all()
            print(f"Se purgarían {len(events)} evento(s): " + ", ".join(f"{e.event_code}" for e in events))
            return 0
        print(privacy.purge_expired(db, days))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
