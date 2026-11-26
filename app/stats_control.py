"""Resumen principal de Control de inventario y Control de zonas para Estadísticas (rediseño 26-nov-2026, pedido de Juan David).

Lo que el cliente necesita ver de un vistazo, debajo de las cifras del registro:
- Inventario: unidades entregadas y personas atendidas (en grande) y, por cada producto, «entregadas de las que hay en el
  inventario» con lo que queda y el porcentaje sobre ESE producto (no un reparto entre cosas distintas).
- Zonas: personas que entraron, cuántas siguen adentro y las entradas; por zona, personas únicas sobre los registrados.

Reglas: solo si el módulo está activo en el evento; solo lo no archivado y con «genera estadísticas»; la persona de prueba no
cuenta en lo entregado ni en las personas. «Quedan» es la existencia real (cantidad inicial menos TODO lo entregado), la
misma cifra de «disponibles» de la pantalla de entrega. Solo conteos: ningún dato de las personas.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app import testperson
from app.models import AreaMovement, EventArea, InventoryDelivery, InventoryItem


def pct(part: int, total: int) -> Optional[float]:
    """Porcentaje con un decimal (None si no hay sobre qué calcularlo)."""
    if not total:
        return None
    return round(100.0 * part / total, 1)


def _item_row(name: str, delivered: int, initial: int, all_delivered: int) -> dict:
    return {"name": name, "delivered": delivered, "initial": initial, "remaining": initial - all_delivered, "pct": pct(delivered, initial)}


def inventory_summary(db: Session, event) -> Optional[dict]:
    if not getattr(event, "inventory_enabled", False):
        return None
    items = db.query(InventoryItem).filter(InventoryItem.event_id == event.id, InventoryItem.archived_at.is_(None)).order_by(InventoryItem.id).all()
    if not items:
        return None
    units: Dict[int, int] = {}          # lo entregado a personas reales
    every: Dict[int, int] = {}          # todo lo entregado (para la existencia real)
    people: Dict[int, set] = {}
    for item_id, user_id, qty in db.query(InventoryDelivery.item_id, InventoryDelivery.user_id, InventoryDelivery.qty).filter(InventoryDelivery.event_id == event.id):
        q = int(qty or 0)
        every[item_id] = every.get(item_id, 0) + q
        if testperson.is_test(user_id):
            continue
        units[item_id] = units.get(item_id, 0) + q
        people.setdefault(item_id, set()).add(user_id)

    kids: Dict[int, List[InventoryItem]] = {}
    for i in items:
        if i.parent_id:
            kids.setdefault(i.parent_id, []).append(i)
    groups, singles, shown_ids = [], [], []
    for i in items:
        if i.parent_id or not i.stats_enabled:
            continue
        children = kids.get(i.id) or []
        if children:
            members = [i.id] + [c.id for c in children]
            shown_ids += members
            g_people = set().union(*[people.get(m, set()) for m in members])
            g_units = sum(units.get(m, 0) for m in members)
            g_initial = sum(c.initial_qty or 0 for c in children)
            g_every = sum(every.get(m, 0) for m in members)
            rows = [_item_row(c.name, units.get(c.id, 0), c.initial_qty or 0, every.get(c.id, 0)) for c in children if c.stats_enabled]
            groups.append({"name": i.name, "units": g_units, "people": len(g_people), "initial": g_initial, "remaining": g_initial - g_every,
                           "pct": pct(g_units, g_initial), "items": rows})
        else:
            shown_ids.append(i.id)
            row = _item_row(i.name, units.get(i.id, 0), i.initial_qty or 0, every.get(i.id, 0))
            row["people"] = len(people.get(i.id, set()))
            singles.append(row)
    if not groups and not singles:
        return None
    all_people = set().union(*[people.get(m, set()) for m in shown_ids]) if shown_ids else set()
    total_initial = sum(g["initial"] for g in groups) + sum(s["initial"] for s in singles)
    total_remaining = sum(g["remaining"] for g in groups) + sum(s["remaining"] for s in singles)
    return {"units": sum(units.get(m, 0) for m in shown_ids), "people": len(all_people), "initial": total_initial, "remaining": total_remaining,
            "groups": groups, "items": singles}


def zones_summary(db: Session, event, registered: int) -> Optional[dict]:
    if not getattr(event, "areas_enabled", False):
        return None
    areas = db.query(EventArea).filter(EventArea.event_id == event.id, EventArea.archived_at.is_(None)).order_by(EventArea.id).all()
    if not areas:
        return None
    last: Dict[tuple, str] = {}
    entries: Dict[int, int] = {}
    exits: Dict[int, int] = {}
    visitors: Dict[int, set] = {}
    q = (db.query(AreaMovement.area_id, AreaMovement.user_id, AreaMovement.direction)
         .filter(AreaMovement.event_id == event.id).order_by(AreaMovement.timestamp, AreaMovement.id))
    for area_id, user_id, direction in q:
        if testperson.is_test(user_id):
            continue
        last[(area_id, user_id)] = direction
        if direction == "in":
            entries[area_id] = entries.get(area_id, 0) + 1
            visitors.setdefault(area_id, set()).add(user_id)
        else:
            exits[area_id] = exits.get(area_id, 0) + 1

    def block(name: str, members: List[int]) -> dict:
        mset = set(members)
        who = set().union(*[visitors.get(m, set()) for m in members]) if members else set()
        inside = {u for (a, u), d in last.items() if a in mset and d == "in"}
        n = len(who)
        return {"name": name, "people": n, "inside": len(inside), "entries": sum(entries.get(m, 0) for m in members),
                "exits": sum(exits.get(m, 0) for m in members), "pct": pct(n, registered)}

    kids: Dict[int, List[EventArea]] = {}
    for a in areas:
        if a.parent_id:
            kids.setdefault(a.parent_id, []).append(a)
    zones, shown = [], []
    for a in areas:
        if a.parent_id or not a.stats_enabled:
            continue
        children = kids.get(a.id) or []
        members = [a.id] + [c.id for c in children]
        shown += members
        z = block(a.name, members)
        z["children"] = [block(c.name, [c.id]) for c in children if c.stats_enabled]
        zones.append(z)
    if not zones:
        return None
    total = block("", shown)
    return {"people": total["people"], "inside": total["inside"], "entries": total["entries"], "exits": total["exits"],
            "pct": total["pct"], "registered": registered, "zones": zones}


def build(db: Session, event, registered: int) -> dict:
    """{"inventory": {...} | None, "zones": {...} | None}."""
    return {"inventory": inventory_summary(db, event), "zones": zones_summary(db, event, registered)}
