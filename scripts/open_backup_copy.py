"""Abre una copia semanal cifrada (.gwbk) bajada de OneDrive y deja el respaldo normal (.sql.gz) listo para restaurar.

Uso (en cualquier computador con Python y `pip install cryptography`; NO necesita la base ni la nube):
    python scripts/open_backup_copy.py golden_db_20261108_0300.gwbk golden_db_20261108_0300.sql.gz
La llave se lee de la variable de entorno BACKUP_COPY_ENCRYPTION_KEY (nunca como argumento, para que no quede en el historial del terminal);
si no está, se pide por el teclado sin mostrarla. Si el archivo está truncado, alterado o la llave es otra, se detiene y no deja un archivo a medias.
Luego se restaura como cualquier respaldo: gunzip -c golden_db_….sql.gz | psql "$DATABASE_URL" (ver docs/recuperacion_desastre.md).
"""
from __future__ import annotations

import getpass
import os
import sys


def main(argv: list) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src_path, dst_path = argv[1], argv[2]
    if os.path.exists(dst_path):
        print(f"{dst_path} ya existe; elige otro nombre para no pisarlo.")
        return 2
    key = os.environ.get("BACKUP_COPY_ENCRYPTION_KEY", "").strip() or getpass.getpass("Llave BACKUP_COPY_ENCRYPTION_KEY: ").strip()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from app.offsite_copy import decrypt_stream
    tmp = dst_path + ".parcial"
    try:
        with open(src_path, "rb") as src, open(tmp, "wb") as out:
            n = 0
            for part in decrypt_stream(src, key):
                out.write(part)
                n += len(part)
        os.replace(tmp, dst_path)
    except (ValueError, OSError) as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"No se pudo abrir la copia: {e}")
        return 1
    print(f"Listo: {dst_path} ({n} bytes). Comprueba con: gunzip -t {dst_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
