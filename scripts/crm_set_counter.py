"""Fija (o sube) el número inicial de un contador del CRM y lo deja LISTO (docs/crm/CODIGOS.md).

    python scripts/crm_set_counter.py --name account --floor 21500            # SIMULACRO: solo muestra qué haría (por defecto)
    python scripts/crm_set_counter.py --name account --floor 21500 --apply    # lo aplica

Nunca baja un contador (usa el mayor entre el actual y --floor). El número que se fija es el ÚLTIMO ya usado: el siguiente que se entregue será floor + 1. Debe ser mayor o igual al
código más alto de SuiteCRM y de la plataforma. En producción solo se corre con autorización explícita de Juan David y con respaldo de Neon hecho antes. Conexión: DATABASE_URL
(o DIRECT_DATABASE_URL si existe). No imprime datos personales.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, choices=("account", "event"))
    ap.add_argument("--floor", required=True, type=int, help="último número ya usado (el siguiente será este + 1)")
    ap.add_argument("--apply", action="store_true", help="aplica el cambio (sin esto es un simulacro)")
    args = ap.parse_args(argv)
    if args.floor < 0:
        print("El número inicial no puede ser negativo.")
        return 2
    from app.crm.codes import bump_floor, counter_state
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        before = counter_state(db, args.name)
        target = max(args.floor, before["value"] or 0)
        print(f"Contador «{args.name}»: actual={before['value']} listo={before['ready']} → quedaría en {target} (el siguiente número entregado sería {target + 1}) y listo=True")
        if not args.apply:
            print("SIMULACRO: no se cambió nada. Agrega --apply para aplicarlo.")
            return 0
        after = bump_floor(db, args.name, args.floor)
        db.commit()
        print(f"Aplicado: contador «{args.name}» = {after}, listo.")
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"No se pudo: {type(exc).__name__}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
