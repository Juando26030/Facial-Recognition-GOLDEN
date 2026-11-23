"""Inventario «lo define la base» (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md).

En vez de que la persona elija, el archivo ya dice qué le toca a cada quien: un campo de la base de registro (el producto del TITULAR) y/o una columna de la base de
dependientes (el producto de cada dependiente). Cada valor distinto es un producto del inventario (se crea solo, con el stock igual a lo asignado; el stock se puede
editar, incluso por debajo de lo asignado: solo se avisa). En el puesto se escanea a la persona, se ve lo que le corresponde (no se puede cambiar) y se entrega por
partes o todo junto. Solo a quien está REGISTRADO.

Lo que le toca a cada persona se calcula EN VIVO desde la base (no se copia): si la base cambia, la entrega lo ve. La entrega guarda `assignment_key` ('h' el titular,
'd<uid>' la fila de un dependiente) para no entregar dos veces lo mismo. Las opciones de cada producto (máximo por persona, estadía, estadísticas) siguen como siempre;
los límites cuentan por la persona que recibe (el titular recibe lo de sus dependientes)."""
import json
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func

from app import dependents as deps_mod
from app import inv_assign_core as core
from app import testperson
from app.models import EventAttendee, EventDependent, InventoryDelivery, InventoryItem, User
from app.timeutil import utcnow

FIXED_HOLDER_FIELDS = (("role", "Cargo"), ("entity", "Entidad"), ("opt_1", "Tipo de Asistente"))
NOT_REGISTERED = "Esta persona aún no está registrada en el evento. Regístrala primero (Registro) para poder entregarle."
MODE_BLOCKS_CHOOSE = "En este evento lo que se entrega lo define la base de datos: escanea a la persona y entrega lo que le corresponde (no se elige)."


def mode(event) -> str:
    return core.MODE_ASSIGNED if (event.inventory_mode or "") == core.MODE_ASSIGNED else core.MODE_CHOOSE


def is_assigned(event) -> bool:
    return bool(event.inventory_enabled) and mode(event) == core.MODE_ASSIGNED


def get_config(event) -> dict:
    try:
        raw = json.loads(event.inventory_assign_json) if event.inventory_assign_json else {}
    except ValueError:
        raw = {}
    return {"mode": mode(event), **core.clean_assign_config(raw)}


def holder_fields(event) -> list:
    """Campos de la base de registro que pueden decir el producto o la cantidad del titular: Cargo, Entidad, Tipo de asistente y los campos opcionales del evento."""
    out = [{"key": k, "label": label} for k, label in FIXED_HOLDER_FIELDS]
    for key, label in sorted(event.get_optional_labels().items(), key=lambda kv: int(kv[0].split("_")[1])):
        out.append({"key": key, "label": label})
    return out


def dependent_columns(db, event) -> list:
    """Títulos de las columnas que trae la base de dependientes del evento (de las primeras 2.000 filas)."""
    seen = {}
    for (raw,) in db.query(EventDependent.data_json).filter(EventDependent.event_id == event.id, EventDependent.data_json.isnot(None)).order_by(EventDependent.id).limit(2000):
        try:
            for k in json.loads(raw or "{}"):
                seen.setdefault(core.norm(k), k)
        except ValueError:
            continue
    return [{"key": v, "label": v[:1].upper() + v[1:]} for v in seen.values()]


def set_config(db, event, data: dict) -> dict:
    """Guarda el modo y las columnas. En el modo «la base lo define» hace falta al menos una columna de producto (del titular o de los dependientes)."""
    new_mode = data.get("mode", mode(event))
    if new_mode not in core.MODES:
        raise HTTPException(status_code=400, detail="Elige «La persona elige» o «La base lo define»")
    cfg = core.clean_assign_config({k: data.get(k, get_config(event).get(k)) for k in core.ASSIGN_KEYS})
    valid_holder = {f["key"] for f in holder_fields(event)}
    for k in ("holder_product", "holder_qty"):
        if cfg[k] and cfg[k] not in valid_holder:
            raise HTTPException(status_code=400, detail="Ese campo no existe en la base de registro de este evento")
    if cfg["holder_qty"] and not cfg["holder_product"]:
        raise HTTPException(status_code=400, detail="Para usar un campo de cantidad del titular, elige primero el campo del producto")
    if cfg["dep_qty"] and not cfg["dep_product"]:
        raise HTTPException(status_code=400, detail="Para usar una columna de cantidad de los dependientes, elige primero la columna del producto")
    if cfg["holder_product"] and cfg["holder_product"] == cfg["holder_qty"]:
        raise HTTPException(status_code=400, detail="El producto y la cantidad no pueden ser el mismo campo")
    if cfg["dep_product"] and cfg["dep_qty"] and core.norm(cfg["dep_product"]) == core.norm(cfg["dep_qty"]):
        raise HTTPException(status_code=400, detail="El producto y la cantidad no pueden ser la misma columna")
    if new_mode == core.MODE_ASSIGNED and not (cfg["holder_product"] or cfg["dep_product"]):
        raise HTTPException(status_code=400, detail="Elige qué campo de la base dice el producto (del titular, de los dependientes o de ambos)")
    if new_mode == core.MODE_ASSIGNED and mode(event) != core.MODE_ASSIGNED:
        has_choice = db.query(InventoryDelivery.id).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.assignment_key.is_(None)).first()
        if has_choice:
            raise HTTPException(status_code=409, detail="Este evento ya tiene entregas hechas con «La persona elige». Cambiar el modo ahora mezclaría las dos formas de entregar: crea los productos en otro evento o pide a un administrador revisar.")
    event.inventory_mode = None if new_mode == core.MODE_CHOOSE else core.MODE_ASSIGNED
    event.inventory_assign_json = json.dumps(cfg) if any(cfg.values()) else None
    return get_config(event)


def _holder_value(user: User, key: str):
    if not key or user is None:
        return None
    if key.startswith("opcional_"):
        return user.get_extras().get(key)
    return getattr(user, key, None)


def _items_by_key(db, event) -> dict:
    """{valor normalizado: producto} — primero por el valor que lo creó (`source_value`), si no por su nombre."""
    out = {}
    items = db.query(InventoryItem).filter(InventoryItem.event_id == event.id, InventoryItem.archived_at.is_(None), InventoryItem.parent_id.is_(None)).order_by(InventoryItem.id).all()
    for i in items:
        out.setdefault(core.norm(i.name), i)
    for i in items:
        if i.source_value:
            out[i.source_value] = i
    return out


def _delivered_by_item(db, event_id: int) -> dict:
    rows = db.query(InventoryDelivery.item_id, func.sum(InventoryDelivery.qty)).filter(InventoryDelivery.event_id == event_id).group_by(InventoryDelivery.item_id).all()
    return {i: int(t or 0) for i, t in rows}


def _delivered_by_key(db, event, user_id: str, keys: list) -> dict:
    """Unidades ya entregadas de cada asignación. 'h' es la del titular (por persona); 'd<uid>' es única en el evento (la entregue quien la entregue)."""
    out = defaultdict(int)
    dep_keys = [k for k in keys if k != core.HOLDER_KEY]
    if core.HOLDER_KEY in keys:
        for (q,) in db.query(InventoryDelivery.qty).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.user_id == user_id, InventoryDelivery.assignment_key == core.HOLDER_KEY):
            out[core.HOLDER_KEY] += int(q or 0)
    if dep_keys:
        for k, q in db.query(InventoryDelivery.assignment_key, InventoryDelivery.qty).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.assignment_key.in_(dep_keys)):
            out[k] += int(q or 0)
    return out


def raw_lines(db, event, user: User) -> list:
    """Lo que le toca a la persona según la base (sin mirar el inventario): lo suyo como titular, lo de sus dependientes y lo que le asignaron como dependiente de otro titular."""
    cfg = get_config(event)
    people = deps_mod.people_of(db, event, user.id) if cfg["dep_product"] else []
    dep_rows = []
    for p in people:
        for r in p["rows"]:
            dep_rows.append({"uid": r["uid"], "label": p["label"], "name": p["name"], "data": r["data"]})
    if cfg["dep_product"]:
        for r in deps_mod.own_rows(db, event, user.id):
            dep_rows.append({"uid": r["uid"], "label": (r["name"] or "Esta persona") + " (dependiente de " + r["holder"] + ")", "name": r["name"], "data": r["data"]})
    return core.lines_for(_holder_value(user, cfg["holder_product"]), _holder_value(user, cfg["holder_qty"]), dep_rows, cfg)


def person_lines(db, event, user: User) -> list:
    """Cada asignación con su producto del inventario, lo entregado, lo pendiente y el disponible: lo que se ve en el puesto de entrega."""
    lines = raw_lines(db, event, user)
    items = _items_by_key(db, event)
    delivered = _delivered_by_key(db, event, user.id, [ln["key"] for ln in lines])
    stock = _delivered_by_item(db, event.id)
    out = []
    for ln in lines:
        item = items.get(ln["product_key"])
        done = delivered.get(ln["key"], 0)
        pending = max(ln["qty"] - done, 0)
        problem = ln["problem"]
        if item is None and not problem:
            problem = f"«{ln['product']}» no está en el inventario del evento (pide a un coordinador «Actualizar productos desde la base»)"
        available = (item.initial_qty - stock.get(item.id, 0)) if item is not None else 0
        out.append({**ln, "item_id": item.id if item else None, "item_name": item.name if item else ln["product"], "delivered": done, "pending": pending,
                    "available": available, "problem": problem, "done": pending == 0 and ln["qty"] > 0})
    return out


def assigned_totals(db, event) -> dict:
    """{valor normalizado: {"name": como viene en la base, "assigned": unidades}} en TODO el evento (sin la persona de prueba)."""
    cfg = get_config(event)
    totals = {}

    def add(value, qty):
        key = core.norm(value)
        if not key:
            return
        t = totals.setdefault(key, {"name": str(value).strip(), "assigned": 0})
        t["assigned"] += qty

    if cfg["holder_product"]:
        ids = testperson.drop_test([r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)])
        for part in deps_mod._chunks(ids):
            for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(part)):
                for ln in core.lines_for(_holder_value(u, cfg["holder_product"]), _holder_value(u, cfg["holder_qty"]), [], {**cfg, "dep_product": None}):
                    add(ln["product"], ln["qty"])
    if cfg["dep_product"]:
        rows = [{"uid": r.uid, "data": r.get_data()} for r in db.query(EventDependent).filter(EventDependent.event_id == event.id)]
        for ln in core.lines_for(None, None, rows, {**cfg, "holder_product": None}):
            add(ln["product"], ln["qty"])
    return totals


def summary(db, event) -> dict:
    """Productos que pide la base frente al inventario: asignado, stock, entregado, faltante. Sin crear nada."""
    totals = assigned_totals(db, event)
    items = _items_by_key(db, event)
    delivered = _delivered_by_item(db, event.id)
    rows, used = [], set()
    for key, t in sorted(totals.items(), key=lambda kv: kv[1]["name"].lower()):
        item = items.get(key)
        if item is not None:
            used.add(item.id)
        stock = item.initial_qty if item is not None else 0
        rows.append({"product": t["name"], "item_id": item.id if item else None, "item_name": item.name if item else None, "assigned": t["assigned"], "stock": stock,
                     "delivered": delivered.get(item.id, 0) if item else 0, "missing_item": item is None, "short": max(t["assigned"] - stock, 0)})
    orphan = [{"item_id": i.id, "item_name": i.name} for i in {id(v): v for v in items.values()}.values() if i.id not in used and i.source_value]
    return {"config": get_config(event), "products": rows, "orphans": orphan,
            "assigned_units": sum(r["assigned"] for r in rows), "stock_units": sum(r["stock"] for r in rows), "short_products": sum(1 for r in rows if r["short"] or r["missing_item"])}


def sync_items(db, event, staff=None) -> dict:
    """«Actualizar productos desde la base»: crea los productos que pide la base y todavía no existen, con el stock igual a lo asignado. NO cambia el stock de los que
    ya existen (pudo editarse a propósito); la alerta muestra dónde falta."""
    totals = assigned_totals(db, event)
    items = _items_by_key(db, event)
    created = 0
    for key, t in totals.items():
        if key in items:
            if not items[key].source_value:
                items[key].source_value = key          # producto creado a mano con el mismo nombre: queda enlazado
            continue
        name = t["name"][:200]
        clash = db.query(InventoryItem.id).filter(InventoryItem.event_id == event.id, func.lower(InventoryItem.name) == name.lower()).first()
        if clash:          # el mismo nombre pero archivado o como subcategoría: se le agrega una marca para no chocar
            name = f"{name} (base)"
        item = InventoryItem(event_id=event.id, name=name, initial_qty=t["assigned"], allow_multiple=True, allow_repeat_delivery=True, stats_enabled=True,
                             source_value=key, created_at=utcnow())
        db.add(item)
        items[key] = item
        created += 1
    db.flush()
    out = summary(db, event)
    out["created"] = created
    return out


def match_stock(db, event, item_id: int = None) -> int:
    """«Igualar el stock a lo asignado» (un producto o todos los que piden más de lo que hay): sube la cantidad inicial hasta lo asignado. Nunca la baja."""
    totals = assigned_totals(db, event)
    items = _items_by_key(db, event)
    changed = 0
    for key, t in totals.items():
        item = items.get(key)
        if item is None or (item_id and item.id != item_id):
            continue
        if item.initial_qty < t["assigned"]:
            item.initial_qty = t["assigned"]
            changed += 1
    return changed


def over_deliveries(db, event) -> list:
    """Entregas de MÁS: una asignación entregada más veces de lo que le toca (puede pasar si dos servidores sin internet entregan lo mismo antes de sincronizar).
    No se borra nada: se avisa para revisar. Solo conteos y la cédula de quien recibió (pantalla del coordinador)."""
    by_user = defaultdict(set)
    for uid, key in db.query(InventoryDelivery.user_id, InventoryDelivery.assignment_key).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.assignment_key.isnot(None)).distinct():
        by_user[uid].add(key)
    if not by_user:
        return []
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(list(by_user)))}
    out = []
    for uid in by_user:
        u = users.get(uid)
        if u is None:
            continue
        for ln in person_lines(db, event, u):
            if ln["delivered"] > ln["qty"]:
                out.append({"cedula": uid, "product": ln["item_name"], "who": ln["who"], "assigned": ln["qty"], "delivered": ln["delivered"]})
    return out


def deliver(db, event, staff, user: User, keys, everything: bool = False, precheck=None) -> dict:
    """Entrega lo asignado: `keys` (las asignaciones elegidas) o `everything` (todo lo pendiente). Todo o nada; con los productos BLOQUEADOS (FOR UPDATE) y lo entregado
    recalculado después del candado, dos puestos a la vez no entregan dos veces lo mismo. Solo a personas REGISTRADAS."""
    from app import area_dwell_svc, subcat
    from app.routers.areas_inventory import multi_units_allowed
    if not deps_mod.is_registered(db, event, user.id):
        raise HTTPException(status_code=409, detail=NOT_REGISTERED)
    lines = raw_lines(db, event, user)
    wanted_keys = [ln["key"] for ln in lines] if everything else [str(k) for k in (keys or [])]
    if not wanted_keys:
        raise HTTPException(status_code=400, detail="Elige qué entregar")
    by_key = {ln["key"]: ln for ln in lines}
    unknown = [k for k in wanted_keys if k not in by_key]
    if unknown:
        raise HTTPException(status_code=404, detail="Eso ya no le corresponde a esta persona según la base: recarga la pantalla")
    items_by_value = _items_by_key(db, event)
    chosen = [by_key[k] for k in dict.fromkeys(wanted_keys)]
    missing = [ln for ln in chosen if items_by_value.get(ln["product_key"]) is None]
    if missing:
        raise HTTPException(status_code=400, detail=f"«{missing[0]['product']}» no está en el inventario del evento: un coordinador debe pulsar «Actualizar productos desde la base» en Parámetros")
    item_ids = sorted({items_by_value[ln["product_key"]].id for ln in chosen})
    locked = {i.id: i for i in db.query(InventoryItem).filter(InventoryItem.event_id == event.id, InventoryItem.id.in_(item_ids)).order_by(InventoryItem.id).with_for_update().all()}
    done = _delivered_by_key(db, event, user.id, [ln["key"] for ln in chosen])          # DESPUÉS del candado: lo que otro puesto acaba de entregar ya se ve
    remote = precheck(user.id, [ln["key"] for ln in chosen]) if precheck else {}
    stock = _delivered_by_item(db, event.id)
    plan, per_item = [], defaultdict(int)
    for ln in chosen:
        item = locked[items_by_value[ln["product_key"]].id]
        already = max(done.get(ln["key"], 0), int((remote or {}).get(ln["key"]) or 0))
        pending = ln["qty"] - already
        if pending <= 0:
            if everything:
                continue
            who = f" de {ln['who']}" if ln["who"] else ""
            raise HTTPException(status_code=409, detail=f"«{item.name}»{who} ya se entregó" + (" en otro puesto" if (remote or {}).get(ln["key"]) and not done.get(ln["key"]) else "") + ".")
        qty = pending if multi_units_allowed(item, None) else 1
        if item.requires_dwell and area_dwell_svc.prize_active(event) and not area_dwell_svc.qualifies(db, event, user.id):
            raise HTTPException(status_code=409, detail=f"«{item.name}» solo se entrega a quien cumplió el {area_dwell_svc.threshold(event)} % de permanencia del evento y esta persona todavía no lo alcanza")
        available = item.initial_qty - stock.get(item.id, 0) - per_item[item.id]
        if qty > available:
            raise HTTPException(status_code=400, detail=f"No alcanza «{item.name}»: quedan {max(available, 0)} y se necesitan {qty}. Un coordinador puede subir el stock en Parámetros.")
        problem = subcat.inventory_limit_problem(db, event.id, item, qty, locked, user.id, {k: v for k, v in per_item.items() if k != item.id})
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        per_item[item.id] += qty
        plan.append((ln, item, qty))
    if not plan:
        raise HTTPException(status_code=409, detail="A esta persona no le queda nada pendiente por entregar.")
    batch, now = uuid.uuid4().hex, utcnow()
    for ln, item, qty in plan:
        db.add(InventoryDelivery(event_id=event.id, item_id=item.id, batch_id=batch, user_id=user.id, tenant_id=event.tenant_id, qty=qty, delivered_at=now,
                                 delivered_by_staff_id=staff.id if staff else None, assignment_key=ln["key"]))
    db.commit()
    return {"result": "OK", "batch_id": batch, "delivered": [{"name": item.name, "qty": qty, "who": ln["who"]} for ln, item, qty in plan]}
