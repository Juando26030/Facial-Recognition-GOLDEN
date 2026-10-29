"""Importa un paquete de evento (docs/18_EXPORTAR_EVENTOS.md) creando un evento NUEVO. Usa el MISMO código que la interfaz (app/event_transfer.py).

    python scripts/event_import.py evento_EV123.zip --new-code EV123-COPIA --new-name "Copia" --dry-run     # simulacro: no escribe nada
    python scripts/event_import.py evento_EV123.zip --new-code EV123-COPIA --new-name "Copia"              # importa de verdad

Nunca sobrescribe un evento. No envía correos, no llama a Wompi ni encola trabajos. Un evento «en proceso» queda en espera hasta `--confirm <número de importación>`."""
import argparse
import json
import sys

sys.path.insert(0, ".")
from app import event_transfer                      # noqa: E402
from app.database import SessionLocal                # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("package", nargs="?", help="archivo .zip del paquete")
    ap.add_argument("--new-code", help="código del evento nuevo (obligatorio si ya existe uno igual)")
    ap.add_argument("--new-name", help="nombre del evento nuevo")
    ap.add_argument("--keep-original-state", action="store_true", help="conservar el estado original de los formularios (se aplica al confirmar)")
    ap.add_argument("--dry-run", action="store_true", help="simulacro: lista qué entraría y los conflictos, sin escribir nada")
    ap.add_argument("--confirm", type=int, metavar="N", help="aplica el estado original de la importación en espera N")
    ap.add_argument("--user", default="cli", help="nombre con el que queda en la bitácora")
    args = ap.parse_args(argv)
    db = SessionLocal()
    try:
        if args.confirm:
            out = event_transfer.confirm_import(db, args.confirm, args.user)
            print(json.dumps(out, ensure_ascii=False))
            return 0
        if not args.package:
            ap.error("falta el archivo del paquete")
        with open(args.package, "rb") as f:
            data = f.read()
        report = event_transfer.import_package(db, data, staff_username=args.user, new_event_code=args.new_code, new_name=args.new_name,
                                               keep_original_state=args.keep_original_state, dry_run=args.dry_run)
    except event_transfer.TransferError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
