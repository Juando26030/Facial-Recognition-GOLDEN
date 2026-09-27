"""Concilia con Wompi los pagos que siguen «pendientes» (por si se perdió un webhook). Cron sugerido, cada 5 minutos:

    */5 * * * * cd ~/Facial-Recognition && venv/bin/python scripts/reconcile_payments.py >> ~/backups/reconcile.log 2>&1

Ver app/reconcile.py y docs/observabilidad.md."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.reconcile import reconcile_pending  # noqa: E402

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(json.dumps(reconcile_pending(db)))
    finally:
        db.close()
