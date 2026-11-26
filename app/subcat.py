"""Subcategorías de zonas e inventario (0140): una zona o ítem «principal» con subcategorías dentro (Salón A › Entrada A, B, C; Comida › Hamburguesa, Perro…).

Reglas (pedido de Juan David, 12-nov-2026):
- Un solo nivel: una subcategoría no tiene subcategorías.
- Un grupo (principal con subcategorías) no recibe movimientos ni entregas por sí mismo: se elige una subcategoría.
- `max_per_person` del GRUPO manda sobre el de sus subcategorías (cuenta lo de todas juntas); la subcategoría puede tener además el suyo. NULL = sin límite.
- Cada subcategoría y su grupo pueden generar estadística (`stats_enabled`); las del grupo suman las de sus subcategorías.

Solo lógica de datos; no hace commit. Sin datos personales en lo que devuelve (solo conteos).
"""
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import testperson
from app.models import AreaMovement, EventArea, InventoryDelivery, InventoryItem

SEP = " › "


class SubcatError(ValueError):
    """Regla de subcategorías incumplida; el mensaje se muestra tal cual (español)."""


def clean_limit(value) -> Optional[int]:
    """Límite por persona: vacío / None = sin límite; si no, entero de 1 en adelante."""
    if value is None or str(value).strip() == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise SubcatError("El límite por persona debe ser un número entero")
    if n < 1:
        raise SubcatError("El límite por persona debe ser 1 o más (déjalo vacío para no limitar)")
    return n


def validate_parent(db: Session, model, event_id: int, parent_id, self_row=None):
    """Devuelve la fila padre (o None si `parent_id` viene vacío) o lanza SubcatError. `self_row` = la fila que se edita (None al crear)."""
    if parent_id is None or str(parent_id).strip() == "":
        return None
    try:
        parent_id = int(parent_id)
    except (TypeError, ValueError):
        raise SubcatError("La categoría principal no es válida")
    parent = db.query(model).filter(model.id == parent_id, model.event_id == event_id).first()
    if parent is None:
        raise SubcatError("La categoría principal no existe en este evento")
    if parent.archived_at is not None:
        raise SubcatError("La categoría principal está archivada: restáurala primero")
    if parent.parent_id is not None:
        raise SubcatError("Solo hay un nivel de subcategorías: una subcategoría no puede tener otras dentro")
    if self_row is not None:
        if parent.id == self_row.id:
            raise SubcatError("Una categoría no puede ser subcategoría de sí misma")
        if db.query(model.id).filter(model.parent_id == self_row.id).first():
            raise SubcatError("Esta categoría ya tiene subcategorías: no puede pasar a ser subcategoría de otra")
    return parent


def active_children(db: Session, model, parent_id: int) -> list:
    return db.query(model).filter(model.parent_id == parent_id, model.archived_at.is_(None)).order_by(model.id).all()


def has_children(db: Session, model, row_id: int) -> bool:
    return db.query(model.id).filter(model.parent_id == row_id).first() is not None


def group_ids(db: Session, model, row) -> List[int]:
    """Ids de TODO el grupo al que pertenece `row`: el principal y todas sus subcategorías (si `row` es principal sin hijas, solo él)."""
    root_id = row.parent_id or row.id
    ids = [root_id] + [i for (i,) in db.query(model.id).filter(model.parent_id == root_id)]
    return ids


def label_of(rows_by_id: Dict[int, object], row) -> str:
    """«Salón A › Entrada A» para una subcategoría; el nombre solo para el resto."""
    if row.parent_id and row.parent_id in rows_by_id:
        return f"{rows_by_id[row.parent_id].name}{SEP}{row.name}"
    return row.name


def lock_rows(db: Session, model, ids: List[int]) -> dict:
    """Bloquea (FOR UPDATE, en orden de id para no cruzar bloqueos entre quioscos) las filas del grupo: dos puestos que registran a la misma persona a la vez se turnan."""
    rows = db.query(model).filter(model.id.in_(sorted(set(ids)))).order_by(model.id).with_for_update().all()
    return {r.id: r for r in rows}


# ------------------------------------------------------------------------------------------------ Zonas

def entries_of(db: Session, area_ids: List[int], user_id: str) -> int:
    """Cuántas ENTRADAS ('in') tiene la persona en esas zonas (varias entradas al mismo salón suman)."""
    return int(db.query(func.count(AreaMovement.id)).filter(AreaMovement.area_id.in_(area_ids), AreaMovement.user_id == user_id, AreaMovement.direction == "in").scalar() or 0)


def area_limit_problem(db: Session, area: EventArea, locked: Dict[int, EventArea], user_id: str) -> Optional[str]:
    """Mensaje si la persona ya agotó su límite de entradas (el del grupo manda sobre el de la subcategoría); None si puede entrar."""
    parent = locked.get(area.parent_id) if area.parent_id else None
    if parent is not None and parent.max_per_person is not None:
        used = entries_of(db, [parent.id] + [a.id for a in locked.values() if a.parent_id == parent.id], user_id)
        if used >= parent.max_per_person:
            return f"ya tiene {used} entrada(s) a «{parent.name}» y el máximo es {parent.max_per_person}"
    if area.max_per_person is not None:
        used = entries_of(db, [area.id], user_id)
        if used >= area.max_per_person:
            return f"ya tiene {used} entrada(s) a «{area.name}» y el máximo es {area.max_per_person}"
    return None


# ------------------------------------------------------------------------------------------------ Inventario

def units_of(db: Session, event_id: int, item_ids: List[int], user_id: str) -> int:
    return int(db.query(func.coalesce(func.sum(InventoryDelivery.qty), 0)).filter(
        InventoryDelivery.event_id == event_id, InventoryDelivery.item_id.in_(item_ids), InventoryDelivery.user_id == user_id).scalar() or 0)


def inventory_limit_problem(db: Session, event_id: int, item: InventoryItem, qty: int, locked: Dict[int, InventoryItem], user_id: str, pending_by_item: Dict[int, int]) -> Optional[str]:
    """Mensaje si entregar `qty` de `item` pasa el límite por persona del grupo (manda) o de la subcategoría; `pending_by_item` = lo que esta misma entrega ya suma a otros ítems del grupo."""
    parent = locked.get(item.parent_id) if item.parent_id else None
    if parent is not None and parent.max_per_person is not None:
        members = [parent.id] + [i.id for i in locked.values() if i.parent_id == parent.id]
        used = units_of(db, event_id, members, user_id) + sum(q for iid, q in pending_by_item.items() if iid in members and iid != item.id)
        if used + qty > parent.max_per_person:
            return limit_message(db, event_id, parent.name, parent.max_per_person, members, user_id, used)
    if item.max_per_person is not None:
        used = units_of(db, event_id, [item.id], user_id)
        if used + qty > item.max_per_person:
            return limit_message(db, event_id, item.name, item.max_per_person, [item.id], user_id, used)
    return None


def received_names(db: Session, event_id: int, item_ids: List[int], user_id: str) -> List[str]:
    """Lo que la persona ya recibió de esos ítems: «Mazorcada Corferias» o «2 × Lechona» (en el orden en que se entregó)."""
    rows = (db.query(InventoryItem.name, func.sum(InventoryDelivery.qty), func.min(InventoryDelivery.delivered_at))
            .join(InventoryItem, InventoryItem.id == InventoryDelivery.item_id)
            .filter(InventoryDelivery.event_id == event_id, InventoryDelivery.item_id.in_(item_ids), InventoryDelivery.user_id == user_id)
            .group_by(InventoryItem.name).order_by(func.min(InventoryDelivery.delivered_at)).all())
    return [(f"{int(q)} × {n}" if int(q or 0) > 1 else n) for n, q, _t in rows]


def limit_message(db: Session, event_id: int, name: str, limit: int, item_ids: List[int], user_id: str, used: int) -> str:
    """Hotfix 26-nov-2026 (Juan David): el motivo real y QUÉ recibió. Grupo: «Esta persona ya recibió Alimentación: Mazorcada Corferias. Solo se permite 1 por persona.»;
    ítem suelto: «Esta persona ya recibió Postre Muffin. Solo se permite 1 por persona.»"""
    got = received_names(db, event_id, item_ids, user_id)
    single = len(item_ids) == 1
    if not got:
        what = f"«{name}»"
    elif single:
        what = f"«{got[0]}»" if got[0] != name else f"«{name}»"
    else:
        what = f"«{name}»: " + ", ".join(got)
    if used <= 0:
        return f"«{name}» solo permite {limit} por persona."
    return f"Esta persona ya recibió {what}. Solo se permite {limit} por persona."


# ------------------------------------------------------------------------------------------------ Estadísticas (solo conteos)

def _real(ids):
    return [i for i in ids if not testperson.is_test(i)]


def _area_counts(db: Session, event_id: int) -> Dict[int, dict]:
    """Por zona: entradas y personas únicas ('in'), sin la persona de prueba."""
    stats: Dict[int, dict] = {}
    seen: Dict[int, set] = {}
    for area_id, user_id in db.query(AreaMovement.area_id, AreaMovement.user_id).filter(AreaMovement.event_id == event_id, AreaMovement.direction == "in"):
        if testperson.is_test(user_id):
            continue
        s = stats.setdefault(area_id, {"entries": 0, "people": 0})
        s["entries"] += 1
        seen.setdefault(area_id, set()).add(user_id)
    for area_id, people in seen.items():
        stats[area_id]["people"] = len(people)
    return stats


def area_variables(db: Session, event) -> List[dict]:
    """Rediseño 26-nov-2026: ya no se agregan solas en «Gráficos por variable» (lo principal sale arriba, en Control de zonas / inventario; app/stats_control.py); siguen en la lista para elegirlas.
    Variables de Estadísticas para las zonas con `stats_enabled`: `zona:<id>` (la principal con subcategorías: un grupo por subcategoría; la suelta: una sola barra)."""
    if not event.areas_enabled:
        return []
    areas = db.query(EventArea).filter(EventArea.event_id == event.id, EventArea.archived_at.is_(None)).order_by(EventArea.id).all()
    by_id = {a.id: a for a in areas}
    out = []
    for a in areas:
        if a.parent_id or not a.stats_enabled:
            continue
        out.append({"key": f"zona:{a.id}", "label": f"Zona: {a.name}", "default_stat_enabled": False, "default_chart_type": None})
    for a in areas:
        if a.parent_id and a.stats_enabled and a.parent_id in by_id:
            out.append({"key": f"zona:{a.id}", "label": f"Zona: {label_of(by_id, a)}", "default_stat_enabled": False, "default_chart_type": None})
    return out


def area_data(db: Session, event, area_id: int) -> Optional[dict]:
    area = db.query(EventArea).filter(EventArea.id == area_id, EventArea.event_id == event.id, EventArea.archived_at.is_(None)).first()
    if area is None or not area.stats_enabled:
        return None
    counts = _area_counts(db, event.id)
    children = db.query(EventArea).filter(EventArea.parent_id == area.id, EventArea.archived_at.is_(None)).order_by(EventArea.id).all()
    if children:
        # grupo: una barra por subcategoría (personas únicas) y el total del grupo (personas únicas y entradas) en las etiquetas; las personas únicas del grupo salen de TODAS sus entradas
        member_ids = [area.id] + [c.id for c in children]
        people, entries = set(), 0
        for uid, in db.query(AreaMovement.user_id).filter(AreaMovement.area_id.in_(member_ids), AreaMovement.direction == "in"):
            if not testperson.is_test(uid):
                people.add(uid)
                entries += 1
        buckets = [{"label": f"{c.name} (personas únicas)", "count": counts.get(c.id, {}).get("people", 0)} for c in children if c.stats_enabled]
        buckets.append({"label": f"TOTAL «{area.name}»: personas únicas", "count": len(people)})
        buckets.append({"label": f"TOTAL «{area.name}»: entradas", "count": entries})
        return {"type": "categorical", "buckets": buckets}
    c = counts.get(area.id, {"entries": 0, "people": 0})
    return {"type": "categorical", "buckets": [{"label": "Personas únicas", "count": c["people"]}, {"label": "Entradas", "count": c["entries"]}]}


def _item_counts(db: Session, event_id: int) -> Dict[int, dict]:
    stats: Dict[int, dict] = {}
    seen: Dict[int, set] = {}
    for item_id, user_id, qty in db.query(InventoryDelivery.item_id, InventoryDelivery.user_id, InventoryDelivery.qty).filter(InventoryDelivery.event_id == event_id):
        if testperson.is_test(user_id):
            continue
        s = stats.setdefault(item_id, {"units": 0, "people": 0})
        s["units"] += int(qty or 0)
        seen.setdefault(item_id, set()).add(user_id)
    for item_id, people in seen.items():
        stats[item_id]["people"] = len(people)
    return stats


def inventory_variables(db: Session, event) -> List[dict]:
    if not event.inventory_enabled:
        return []
    items = db.query(InventoryItem).filter(InventoryItem.event_id == event.id, InventoryItem.archived_at.is_(None)).order_by(InventoryItem.id).all()
    by_id = {i.id: i for i in items}
    out = []
    for i in items:
        if i.parent_id or not i.stats_enabled:
            continue
        out.append({"key": f"inv:{i.id}", "label": f"Inventario: {i.name}", "default_stat_enabled": False, "default_chart_type": None})
    for i in items:
        if i.parent_id and i.stats_enabled and i.parent_id in by_id:
            out.append({"key": f"inv:{i.id}", "label": f"Inventario: {label_of(by_id, i)}", "default_stat_enabled": False, "default_chart_type": None})
    return out


def inventory_data(db: Session, event, item_id: int) -> Optional[dict]:
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id, InventoryItem.event_id == event.id, InventoryItem.archived_at.is_(None)).first()
    if item is None or not item.stats_enabled:
        return None
    counts = _item_counts(db, event.id)
    children = db.query(InventoryItem).filter(InventoryItem.parent_id == item.id, InventoryItem.archived_at.is_(None)).order_by(InventoryItem.id).all()
    if children:
        member_ids = [item.id] + [c.id for c in children]
        people, units = set(), 0
        for uid, qty in db.query(InventoryDelivery.user_id, InventoryDelivery.qty).filter(InventoryDelivery.item_id.in_(member_ids)):
            if not testperson.is_test(uid):
                people.add(uid)
                units += int(qty or 0)
        buckets = [{"label": f"{c.name} (unidades entregadas)", "count": counts.get(c.id, {}).get("units", 0)} for c in children if c.stats_enabled]
        buckets.append({"label": f"TOTAL «{item.name}»: unidades", "count": units})
        buckets.append({"label": f"TOTAL «{item.name}»: personas atendidas", "count": len(people)})
        return {"type": "categorical", "buckets": buckets}
    c = counts.get(item.id, {"units": 0, "people": 0})
    return {"type": "categorical", "buckets": [{"label": "Unidades entregadas", "count": c["units"]}, {"label": "Personas atendidas", "count": c["people"]}]}
