"""Convierte el VOLCADO de SuiteCRM en los archivos por tipo que sube el importador del CRM (accounts.csv, contacts.csv, opportunities.csv).
Uso:  python scripts/crm_dump_to_csv.py <volcado.csv> <carpeta_de_salida>
Escribe SOLO en la carpeta de salida (que debe estar FUERA del repositorio: tiene datos personales) e imprime únicamente conteos."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.crm.importer import convert  # noqa: E402


def main(argv: list) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, out_dir = argv[1], os.path.abspath(argv[2])
    repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if out_dir == repo or out_dir.startswith(repo + os.sep):
        print("La carpeta de salida no puede estar dentro del repositorio (llevaría datos personales).")
        return 2
    os.makedirs(out_dir, exist_ok=True)
    with open(src, newline="", encoding="utf-8") as fh:
        tables = convert.load_tables(fh)
    files, report = convert.convert(tables)
    for kind, (header, rows) in files.items():
        raw = convert.to_csv(header, rows)
        with open(os.path.join(out_dir, kind + ".csv"), "wb") as fh:
            fh.write(raw)
        report.setdefault(kind, {})["bytes"] = len(raw)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
