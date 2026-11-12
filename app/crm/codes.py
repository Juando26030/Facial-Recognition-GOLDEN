"""Códigos consecutivos del CRM (docs/crm/CODIGOS.md). Un contador por tipo en `crm_counters`: `account` (cuenta = código de cliente) y `event` (se usa desde la pieza C4).

* Una sola sentencia `UPDATE … RETURNING` con bloqueo de fila: compatible con el pooler de Neon en modo transacción (sin advisory locks, sin SET de sesión, sin tablas temporales).
* SIN HUECOS: si la transacción de quien pidió el número se revierte, el contador también (una secuencia de Postgres sí dejaría huecos).
* El contador nace NO LISTO (`ready` falso): `next_code` se niega hasta que alguien fije el número inicial con `bump_floor` (scripts/crm_set_counter.py).
* Salta los números ya ocupados: códigos de cliente (hexadecimales de solo dígitos incluidos), alias viejos, cuentas del CRM y códigos de evento solo numéricos.
* El llamador mantiene corta su transacción: pedir número, insertar la fila, commit.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.timeutil import utcnow

COUNTERS = ("account", "event", "quote", "proforma")
MAX_ATTEMPTS = 1000


class CodeCounterNotReady(Exception):
    """El contador no existe o no se ha fijado su número inicial."""


# Una consulta por tipo: devuelve una fila si el número ya está ocupado. :n = número, :s = su texto.
_TAKEN = {
    "account": "SELECT 1 FROM tenants WHERE client_code = :s OR legacy_client_code = :s UNION ALL SELECT 1 FROM crm_accounts WHERE code = :n LIMIT 1",
    "event": "SELECT 1 FROM events WHERE lower(btrim(event_code)) = :s LIMIT 1",
    "quote": "SELECT 1 FROM crm_quotes WHERE number = :n LIMIT 1",
    "proforma": "SELECT 1 FROM crm_proformas WHERE number = :n LIMIT 1",
}


def next_code(db: Session, name: str) -> int:
    if name not in COUNTERS:
        raise ValueError(f"Contador desconocido: {name}")
    for _ in range(MAX_ATTEMPTS):
        row = db.execute(text("UPDATE crm_counters SET value = value + 1, updated_at = :now WHERE name = :name AND ready RETURNING value"), {"now": utcnow(), "name": name}).first()
        if row is None:
            raise CodeCounterNotReady(f"El contador «{name}» no está listo: falta fijar el número inicial (scripts/crm_set_counter.py).")
        n = int(row[0])
        if db.execute(text(_TAKEN[name]), {"n": n, "s": str(n)}).first() is None:
            return n
    raise RuntimeError(f"No se encontró un número libre para «{name}» tras {MAX_ATTEMPTS} intentos.")


def bump_floor(db: Session, name: str, floor: int) -> int:
    """Sube el contador al menos hasta `floor` (nunca lo baja) y lo deja LISTO. Crea la fila si falta. Devuelve el valor resultante. Lo usan el script de ajuste y, en C1c, el importador."""
    if name not in COUNTERS:
        raise ValueError(f"Contador desconocido: {name}")
    if int(floor) < 0:
        raise ValueError("El número inicial no puede ser negativo.")
    row = db.execute(text(
        "INSERT INTO crm_counters (name, value, ready, updated_at) VALUES (:name, :floor, true, :now) "
        "ON CONFLICT (name) DO UPDATE SET value = GREATEST(crm_counters.value, EXCLUDED.value), ready = true, updated_at = EXCLUDED.updated_at RETURNING value"),
        {"name": name, "floor": int(floor), "now": utcnow()}).first()
    return int(row[0])


def counter_state(db: Session, name: str) -> dict:
    row = db.execute(text("SELECT value, ready FROM crm_counters WHERE name = :name"), {"name": name}).first()
    return {"exists": row is not None, "value": int(row[0]) if row else None, "ready": bool(row[1]) if row else False}
