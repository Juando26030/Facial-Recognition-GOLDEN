"""Unificación de los dos inventarios (Fase 5, decisión de Juan David del 9-nov-2026).

Antes había dos: el CAMPO «Inventario» de la plantilla de evento (líneas tipo/cantidad/referencia guardadas en `events.extra_json`) y el CATÁLOGO nuevo (productos por categoría y sus cantidades por evento en
`event_inventory_items`). Desde ahora el único inventario es el catálogo. Este módulo pasa lo viejo al catálogo, SIN perder nada y SIN pisar lo que ya exista en el catálogo:

  1. Cada tipo definido en un campo «inventario» de la plantilla pasa a ser un producto del catálogo (categoría «Inventario anterior»; si ya hay un producto con ese nombre, se usa ese).
  2. Las líneas guardadas en cada evento se suman por producto en `qty_assigned` (lo que pidió el evento); las referencias quedan en las notas. Si el evento ya tiene esa línea en el catálogo, no se toca.
  3. El campo viejo queda «retirado» en la plantilla (nunca se borra nada: sus valores siguen en `extra_json` como respaldo).

Es idempotente (correrlo dos veces no duplica nada) y solo usa SQL del núcleo de SQLAlchemy con una conexión, para servir igual a la migración 0109 y a las pruebas. Parte pura: `aggregate_lines`.
"""
import json
from typing import Optional

import sqlalchemy as sa

CATEGORY_NAME = "Inventario anterior"
MAX_NOTES = 250


def inventory_field_keys(fields) -> list:
    """Claves de los campos tipo «inventory» (activos o retirados) de una lista de campos de plantilla."""
    return [f["key"] for f in (fields or []) if isinstance(f, dict) and f.get("type") == "inventory" and isinstance(f.get("key"), str)]


def aggregate_lines(lines, labels: dict) -> dict:
    """{nombre del producto: {"qty": suma, "refs": [referencias sin repetir]}} a partir de las líneas viejas [{type, qty, ref}] y las etiquetas {clave de tipo: nombre}. Ignora lo ilegible."""
    out = {}
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        name = labels.get(line.get("type")) or (line.get("type") if isinstance(line.get("type"), str) else None)
        try:
            qty = int(line.get("qty"))
        except (TypeError, ValueError):
            continue
        if not name or qty < 1:
            continue
        slot = out.setdefault(name.strip(), {"qty": 0, "refs": []})
        slot["qty"] += qty
        ref = line.get("ref")
        if isinstance(ref, str) and ref.strip() and ref.strip() not in slot["refs"]:
            slot["refs"].append(ref.strip())
    return out


def _notes(refs: list) -> Optional[str]:
    if not refs:
        return None
    text = "Referencias del inventario anterior: " + ", ".join(refs)
    return text[:MAX_NOTES]


def _ensure_category(conn) -> int:
    row = conn.execute(sa.text("SELECT id FROM inventory_categories WHERE lower(name) = lower(:n) ORDER BY id LIMIT 1"), {"n": CATEGORY_NAME}).first()
    if row:
        return row[0]
    pos = conn.execute(sa.text("SELECT COALESCE(MAX(position), 0) + 1 FROM inventory_categories")).scalar()
    return conn.execute(sa.text("INSERT INTO inventory_categories (name, position, created_at) VALUES (:n, :p, CURRENT_TIMESTAMP) RETURNING id"), {"n": CATEGORY_NAME, "p": pos}).scalar()


def _ensure_product(conn, name: str, cache: dict) -> int:
    key = name.lower()
    if key in cache:
        return cache[key]
    row = conn.execute(sa.text("SELECT id FROM inventory_products WHERE lower(name) = lower(:n) ORDER BY (archived_at IS NOT NULL), id LIMIT 1"), {"n": name}).first()
    if row:
        cache[key] = row[0]
        return row[0]
    cat = _ensure_category(conn)
    pos = conn.execute(sa.text("SELECT COALESCE(MAX(position), 0) + 1 FROM inventory_products")).scalar()
    pid = conn.execute(sa.text("INSERT INTO inventory_products (category_id, name, unit, position, created_at) VALUES (:c, :n, 'unidad', :p, CURRENT_TIMESTAMP) RETURNING id"), {"c": cat, "n": name[:120], "p": pos}).scalar()
    cache[key] = pid
    return pid


def migrate(conn) -> dict:
    """Pasa el inventario viejo al catálogo. Devuelve conteos AGREGADOS: {"fields", "products", "events", "lines", "skipped"} (nunca datos de personas)."""
    stats = {"fields": 0, "products": 0, "events": 0, "lines": 0, "skipped": 0}
    tpl = conn.execute(sa.text("SELECT id, fields_json FROM event_templates")).fetchall()
    cache, field_labels = {}, {}          # {clave de campo: {clave de tipo: nombre}}
    before = conn.execute(sa.text("SELECT COUNT(*) FROM inventory_products")).scalar()
    for tid, raw in tpl:
        try:
            fields = json.loads(raw)
        except (TypeError, ValueError):
            continue
        changed = False
        for f in fields if isinstance(fields, list) else []:
            if not (isinstance(f, dict) and f.get("type") == "inventory" and isinstance(f.get("key"), str)):
                continue
            labels = {t["key"]: t.get("label") for t in ((f.get("config") or {}).get("inventory_types") or []) if isinstance(t, dict) and t.get("key") and t.get("label")}
            field_labels[f["key"]] = labels
            for label in labels.values():
                _ensure_product(conn, str(label), cache)
            if not f.get("retired"):
                f["retired"] = True
                f["required"] = False
                changed = True
            stats["fields"] += 1
        if changed:
            conn.execute(sa.text("UPDATE event_templates SET fields_json = :j WHERE id = :i"), {"j": json.dumps(fields, ensure_ascii=False), "i": tid})
    if not field_labels:
        return stats
    seen_events = set()
    for eid, extra in conn.execute(sa.text("SELECT id, extra_json FROM events WHERE extra_json IS NOT NULL")).fetchall():
        try:
            data = json.loads(extra)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        merged = {}
        for key, labels in field_labels.items():
            for name, slot in aggregate_lines(data.get(key), labels).items():
                m = merged.setdefault(name, {"qty": 0, "refs": []})
                m["qty"] += slot["qty"]
                m["refs"] += [r for r in slot["refs"] if r not in m["refs"]]
        for name, slot in merged.items():
            pid = _ensure_product(conn, name, cache)
            if conn.execute(sa.text("SELECT 1 FROM event_inventory_items WHERE event_id = :e AND product_id = :p"), {"e": eid, "p": pid}).first():
                stats["skipped"] += 1          # ya hay una línea en el catálogo: no se pisa
                continue
            conn.execute(sa.text("INSERT INTO event_inventory_items (event_id, product_id, qty_assigned, qty_out, qty_returned, qty_consumed, notes, updated_at) "
                                 "VALUES (:e, :p, :q, 0, 0, 0, :n, CURRENT_TIMESTAMP)"), {"e": eid, "p": pid, "q": slot["qty"], "n": _notes(slot["refs"])})
            stats["lines"] += 1
            seen_events.add(eid)
    stats["events"] = len(seen_events)
    stats["products"] = conn.execute(sa.text("SELECT COUNT(*) FROM inventory_products")).scalar() - before
    return stats
