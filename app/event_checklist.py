"""Checklist de inventario de un evento, para CONSULTAR en el quiosco (18-nov-2026): qué se alistó (asignado, salió, volvió, se consumió).

En la nube sale de `event_inventory_items`. En un servidor local esas tablas no viajan con el evento (el catálogo es de internet), así que al descargar el evento se guarda una
FOTO del checklist en `app_settings` (clave `evinv:<id del evento local>`, JSON) y se puede refrescar con internet. Solo lectura; sin datos de personas."""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppSetting, EventInventoryItem, InventoryProduct
from app.timeutil import utcnow


def snapshot_key(local_event_id: int) -> str:
    return f"evinv:{int(local_event_id)}"


def cloud_lines(db: Session, event_id: int) -> list:
    """Las líneas del evento con lo que importa para consultar: elemento, categoría, unidad y cantidades. Orden del catálogo."""
    rows = (db.query(EventInventoryItem).join(InventoryProduct, InventoryProduct.id == EventInventoryItem.product_id)
            .filter(EventInventoryItem.event_id == event_id).order_by(InventoryProduct.position, InventoryProduct.id).all())
    out = []
    for l in rows:
        p = l.product
        cat = p.category if p.category is not None and p.category.archived_at is None else None
        out.append({"name": p.name, "category": cat.name if cat else None, "unit": p.unit or "unidad", "assigned": l.qty_assigned or 0, "out": l.qty_out or 0,
                    "returned": l.qty_returned or 0, "consumed": l.qty_consumed or 0, "notes": l.notes or None})
    return [r for r in out if r["assigned"] or r["out"] or r["returned"] or r["consumed"]]


def save_snapshot(db: Session, local_event_id: int, lines: list) -> None:
    payload = json.dumps({"fetched_at": utcnow().isoformat(), "lines": lines}, ensure_ascii=False)
    key = snapshot_key(local_event_id)
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=payload, updated_at=utcnow()))
    else:
        row.value, row.updated_at = payload, utcnow()


def load_snapshot(db: Session, local_event_id: int) -> Optional[dict]:
    row = db.get(AppSetting, snapshot_key(local_event_id))
    try:
        data = json.loads(row.value) if row and row.value else None
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("lines"), list) else None
