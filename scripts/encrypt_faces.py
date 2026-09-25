"""Cifra el dato biométrico que todavía esté en claro (encodings de la base y fotos de data/<cliente>/known_people/). Idempotente: lo ya cifrado no se toca.
Requiere FACE_ENCRYPTION_KEY en el `.env`. Haz un respaldo antes (scripts/backup_db.sh).

    python scripts/encrypt_faces.py --dry-run     # solo cuenta
    python scripts/encrypt_faces.py               # cifra
"""
import glob
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text, update  # noqa: E402

from app import crypto  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not crypto.enabled():
        print("FACE_ENCRYPTION_KEY no está definida: no hay con qué cifrar. Genera una con scripts/gen_face_key.py y agrégala al .env.")
        return 1
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT id, tenant_id, face_encoding FROM users WHERE face_encoding IS NOT NULL AND face_encoding NOT LIKE :p"),
                          {"p": crypto.TEXT_PREFIX + "%"}).fetchall()
        files = []
        for path in glob.glob(os.path.join("data", "*", "known_people", "*.jpg")):
            with open(path, "rb") as fh:
                if fh.read(len(crypto.FILE_MAGIC)) != crypto.FILE_MAGIC:
                    files.append(path)
        print(f"En claro: {len(rows)} encoding(s) y {len(files)} foto(s).")
        if dry:
            return 0
        for uid, tenant, enc in rows:
            db.execute(update(User).where(User.id == uid, User.tenant_id == tenant).values(face_encoding=enc))      # pasa por el tipo cifrado
        db.commit()
        for path in files:
            with open(path, "rb") as fh:
                data = fh.read()
            with open(path, "wb") as fh:
                fh.write(crypto.encrypt_bytes(data))
        print("Listo: todo el dato biométrico quedó cifrado.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
