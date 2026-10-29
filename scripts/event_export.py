"""Exporta un evento COMPLETO a un paquete .zip (docs/18_EXPORTAR_EVENTOS.md). Usa el MISMO código que la interfaz (app/event_transfer.py): sirve para el servidor local y para Cloud Run Jobs.

    python scripts/event_export.py --event-code EV123 --out evento_EV123.zip
    python scripts/event_export.py --event-id 20 --out evento_20.zip

El paquete contiene DATOS PERSONALES: guárdalo con cuidado y bórralo al terminar. Sin biometría (F3). Solo lee la base; escribe una línea en la bitácora de transferencias."""
import argparse
import sys

sys.path.insert(0, ".")
from app import event_transfer                      # noqa: E402
from app.database import SessionLocal                # noqa: E402
from app.models import Event                         # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--event-id", type=int)
    g.add_argument("--event-code")
    ap.add_argument("--out", required=True, help="archivo .zip de salida")
    ap.add_argument("--user", default="cli", help="nombre con el que queda en la bitácora")
    args = ap.parse_args(argv)
    db = SessionLocal()
    try:
        q = db.query(Event)
        event = q.filter(Event.id == args.event_id).first() if args.event_id else q.filter(Event.event_code == args.event_code).first()
        if not event:
            print("No existe ese evento.", file=sys.stderr)
            return 2
        data, manifest = event_transfer.export_event(db, event, staff_username=args.user)
    except event_transfer.TransferError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        db.close()
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Paquete escrito: {args.out} ({len(data)} bytes). Filas por tabla:")
    for name, info in manifest["tables"].items():
        print(f"  {name:24s} {info['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
