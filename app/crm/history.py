"""Registro de cambios del CRM, con la forma de `app/person_history.py`: una fila por campo cambiado en `crm_change_log` (campo, valor anterior, valor nuevo, quién, cuándo, origen).

Uso (siempre el mismo patrón, sin commit propio):
    before = history.snapshot(account, "account")                         # ANTES de tocar nada
    ... se cambian los campos ...
    history.record(db, account, "account", before, staff_id=staff.id)       # después
Una cuenta/contacto recién creado no deja historial (eso es el alta, no un cambio). Los valores viven solo en la base, nunca en los logs. Es pura la comparación (`diff`).
"""
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models import CrmChangeLog
from app.person_history import MAX_VALUE, _norm
from app.timeutil import utcnow

ACCOUNT_FIELDS = ("name", "status", "nit", "email", "phone", "billing_address", "billing_city", "billing_state", "billing_country", "shipping_address", "shipping_city", "shipping_country",
                  "billing_contact_name", "billing_contact_phone", "payment_term", "payment_days", "billing_close", "agency_percent", "owner_staff_id", "description", "archived_at")
CONTACT_FIELDS = ("first_name", "last_name", "job_title", "email", "phone", "mobile", "is_primary", "notes", "archived_at")
FIELDS = {"account": ACCOUNT_FIELDS, "contact": CONTACT_FIELDS}
SOURCES = ("edit", "import", "system")


def snapshot(obj, entity: str) -> dict:
    """Los campos de la cuenta/contacto tal como están ahora, en texto normalizado (para comparar antes/después)."""
    return {f: _norm(getattr(obj, f, None)) for f in FIELDS[entity]}


def diff(before: dict, after: dict, fields: Optional[Iterable[str]] = None) -> list:
    """[(campo, valor anterior, valor nuevo)] de lo que cambió. Pura: no toca la base."""
    out = []
    for f in (fields or before.keys()):
        b, a = before.get(f, ""), after.get(f, "")
        if b != a:
            out.append((f, b, a))
    return out


def record(db: Session, obj, entity: str, before: dict, *, staff_id: Optional[int] = None, source: str = "edit") -> int:
    """Guarda una fila por campo cambiado entre `before` y el estado actual de `obj`. Devuelve cuántas. Sin commit."""
    if source not in SOURCES:
        raise ValueError(f"Origen de cambio no válido: {source}")
    changes = diff(before, snapshot(obj, entity), FIELDS[entity])
    now = utcnow()
    for f, old, new in changes:
        db.add(CrmChangeLog(entity=entity, entity_id=obj.id, field_key=f, old_value=(old or None) and old[:MAX_VALUE], new_value=(new or None) and new[:MAX_VALUE],
                            changed_by_id=staff_id, source=source, changed_at=now))
    return len(changes)
