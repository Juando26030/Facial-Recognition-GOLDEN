"""Crea una cuenta de staff (típicamente el primer Super Admin, para arrancar el sistema).

Uso:
    python scripts/create_staff_user.py --username juando --role super_admin --full-name "Juan David"

Pide la contraseña de forma interactiva (no queda en el historial de la shell). Requiere que las
migraciones ya estén aplicadas (`alembic upgrade head`) y que exista `.env` con DATABASE_URL.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal  # noqa: E402
from app.models import STAFF_ROLES, StaffUser  # noqa: E402
from app.auth import hash_password  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=STAFF_ROLES)
    parser.add_argument("--full-name", default=None)
    parser.add_argument("--tenant-id", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if db.query(StaffUser).filter(StaffUser.username == args.username).first():
            print(f"Ya existe un usuario '{args.username}'.")
            sys.exit(1)

        password = getpass.getpass("Contraseña: ")
        confirm = getpass.getpass("Confirmar contraseña: ")
        if password != confirm:
            print("Las contraseñas no coinciden.")
            sys.exit(1)
        if len(password) < 8:
            print("La contraseña debe tener al menos 8 caracteres.")
            sys.exit(1)

        staff = StaffUser(
            username=args.username,
            password_hash=hash_password(password),
            full_name=args.full_name,
            role=args.role,
            tenant_id=args.tenant_id,
        )
        db.add(staff)
        db.commit()
        print(f"Creado: {args.username} ({args.role})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
