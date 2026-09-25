"""Borra TODOS los datos de la base (clientes, eventos, personas, formularios, pagos, cuentas de staff…) y las
carpetas de archivos de cada cliente en `data/`, dejando el esquema (tablas y migraciones) intacto.

Es IRREVERSIBLE. Antes: tomar un backup fresco (`scripts/backup_db.sh`). Después de correrlo no queda ninguna cuenta:
crear el Super Admin con `scripts/create_staff_user.py`.

Uso (desde la carpeta del proyecto, con el .env cargado):
    python scripts/wipe_all_data.py
Muestra qué base es y cuántos registros hay, y exige escribir el NOMBRE de la base para continuar.
"""
import os
import shutil
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.database import engine  # noqa: E402
from app.models import Base  # noqa: E402

KEEP = {"alembic_version"}


def main():
    db_name = make_url(str(engine.url)).database
    tables = [t.name for t in Base.metadata.sorted_tables if t.name not in KEEP]
    print(f"Base de datos: {db_name}  ({engine.url.host})")
    with engine.connect() as conn:
        counts = {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tables}
    for t, n in counts.items():
        if n:
            print(f"  {t}: {n}")
    print(f"Total de filas a borrar: {sum(counts.values())} en {sum(1 for n in counts.values() if n)} tablas.")
    print("También se borran las carpetas de data/ de cada cliente (fotos, firmas, logos, documentos, archivos de formularios) y data/outbox.")
    typed = input(f"\nEscribe el nombre de la base ({db_name}) para BORRAR TODO, o Enter para cancelar: ").strip()
    if typed != db_name:
        print("Cancelado: no se borró nada.")
        sys.exit(1)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    removed = []
    if os.path.isdir("data"):
        for name in os.listdir("data"):
            path = os.path.join("data", name)
            if os.path.isdir(path) and name != "backups":
                shutil.rmtree(path, ignore_errors=True)
                removed.append(name)
    print(f"Listo. Base vaciada; carpetas de data/ borradas: {', '.join(removed) or 'ninguna'}.")
    print("Ahora crea el Super Admin:  python scripts/create_staff_user.py --username <usuario> --role super_admin --full-name \"Tu nombre\" --email tu@correo --phone +57...")


if __name__ == "__main__":
    main()
