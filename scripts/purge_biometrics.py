"""Aplica la retención biométrica (app/privacy.py): borra foto y vector del rostro de quien tiene TODOS sus eventos finalizados hace más de
`BIOMETRIC_RETENTION_DAYS_AFTER_EVENT` días (7) o lleva más de `BIOMETRIC_MAX_DAYS` (180) desde la captura. En la nube lo corre solo el Job de
operaciones (paso `purge`, cada hora); este script es para la VM o para correrlo a mano. Solo imprime conteos.

    0 4 * * * cd /home/juando02603/Facial-Recognition && venv/bin/python scripts/purge_biometrics.py >> ~/backups/purge.log 2>&1

`--dry-run` solo cuenta lo que se borraría (sin tocar nada).
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from app import privacy  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        if "--dry-run" in sys.argv:
            r = privacy.purge_expired(db, dry_run=True)
            print(f"Se borrarían {r['people']} persona(s) y {r['objects']} foto(s) (por tope de días: {r['by_cap']}).")
            return 0
        print(privacy.purge_expired(db))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
