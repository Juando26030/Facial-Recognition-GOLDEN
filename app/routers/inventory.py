"""Inventario con catálogo (Fase 5): catálogo de categorías y productos (lo define el Super Admin en Configuración) y las líneas de inventario de cada evento (cantidades y regla de cuadre).

Permisos (Fase 5; los roles «almacen» y «contabilidad» son solo EXTRA, ver app/auth.py):
  - Catálogo: ver = coordinador+, almacén y contabilidad; crear / editar / archivar / eliminar = Admin, Almacén y Super Admin (hasta la Fase 9 era solo Super Admin).
  - Inventario de un evento: ver = coordinador+, almacén, contabilidad. Editar lo que PIDE el evento (asignado, notas, datos del producto) = coordinador+ y almacén; editar lo que MUEVE el
    almacén (salió, volvió, consumido) = almacén y admin+. Contabilidad es solo lectura. Ninguno de estos roles obtiene datos personales de asistentes ni administra cuentas por esta ruta.
Fase 10 (10-nov-2026): la pantalla /inventario muestra el CATÁLOGO (no la lista de eventos) con lo que hay en uso hoy, y un calendario «dónde está cada equipo» (`/inventory/overview`, `/inventory/calendar`).
Cambio del 10-nov-2026 (decisión de Juan David): Admin y Almacén (y Super Admin) también CREAN, renombran, archivan, restauran y eliminan categorías y productos del catálogo; antes era solo del Super Admin. Además `PATCH /inventory/products/{id}/manage` (categoría y existencias).
Este router no usa get_event_for_staff (no toca personas ni respuestas): valida cliente (assert_event_tenant) y, para quien no es almacén/contabilidad/admin, la pertenencia al evento.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import audit_actions, inventory, inventory_alerts, inventory_calendar, inventory_svc, jobs
from app.auth import ROLE_HIERARCHY, assert_event_scope, assert_event_tenant, effective_roles, require_role_or_any
from app.database import get_db
from app.models import Event, EventInventoryItem, InventoryCategory, InventoryProduct, StaffUser
from app.timeutil import to_local, utcnow

router = APIRouter()

VIEWER = require_role_or_any("coordinador", ("almacen", "contabilidad"))
MANAGER = require_role_or_any("admin", ("almacen",))          # Fase 10: admin y almacén (bodega) ajustan categoría y existencias de los productos del catálogo
MOVEMENT_ROLES = {"almacen", "admin", "super_admin"}
WIDE_ROLES = {"almacen", "contabilidad", "admin", "super_admin"}          # ven el inventario de cualquier evento de su cliente


def _rank(staff: StaffUser) -> int:
    return max(ROLE_HIERARCHY[r] for r in effective_roles(staff))


def can_edit_movement(staff: StaffUser) -> bool:
    return bool(effective_roles(staff) & MOVEMENT_ROLES)


def can_edit_plan(staff: StaffUser) -> bool:
    return can_edit_movement(staff) or _rank(staff) >= ROLE_HIERARCHY["coordinador"]


def _err(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def _wrap(fn):
    try:
        return fn()
    except inventory.InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- catálogo

def _category_json(c: InventoryCategory, products: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "position": c.position, "archived": c.archived_at is not None, "products": products}


def _product_json(p: InventoryProduct) -> dict:
    cat = p.category
    return {"id": p.id, "name": p.name, "unit": p.unit, "sku": p.sku, "category_id": p.category_id, "category_name": cat.name if cat else None,
            "fields": inventory.load_fields(p.fields_json), "position": p.position, "archived": p.archived_at is not None, "stock": p.qty_total}


def _catalog(db: Session, include_archived: bool) -> dict:
    cq, pq = db.query(InventoryCategory), db.query(InventoryProduct)
    if not include_archived:
        cq, pq = cq.filter(InventoryCategory.archived_at.is_(None)), pq.filter(InventoryProduct.archived_at.is_(None))
    counts = dict(db.query(InventoryProduct.category_id, func.count(InventoryProduct.id)).filter(InventoryProduct.archived_at.is_(None)).group_by(InventoryProduct.category_id).all())
    cats = cq.order_by(InventoryCategory.position, InventoryCategory.id).all()
    prods = pq.order_by(InventoryProduct.position, InventoryProduct.id).all()
    return {"categories": [_category_json(c, counts.get(c.id, 0)) for c in cats], "products": [_product_json(p) for p in prods], "units": ["unidad", "caja", "paquete", "kg", "litro", "metro", "rollo", "par", "juego"]}


@router.get("/inventory/catalog")
def get_catalog(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    """Catálogo vigente. `include_archived=true` (con los archivados) es de Admin, Almacén y Super Admin."""
    if include_archived and not _can_manage(staff):
        _err("Solo Admin, Almacén y Super Admin ven el catálogo archivado", 403)
    return _catalog(db, include_archived)


def _next_position(db: Session, model) -> int:
    return (db.query(func.coalesce(func.max(model.position), -1)).scalar() or 0) + 1


def _category(db: Session, category_id: int) -> InventoryCategory:
    c = db.get(InventoryCategory, category_id)
    if not c:
        _err("Categoría no encontrada", 404)
    return c


def _product(db: Session, product_id: int) -> InventoryProduct:
    p = db.get(InventoryProduct, product_id)
    if not p:
        _err("Producto no encontrado", 404)
    return p


def _assert_free_category_name(db: Session, name: str, except_id: Optional[int] = None) -> None:
    for (cid, other) in db.query(InventoryCategory.id, InventoryCategory.name).filter(InventoryCategory.archived_at.is_(None)).all():
        if cid != except_id and inventory.same_name(other, name):
            _err(f"Ya existe una categoría llamada «{other}»")


def _assert_free_product_name(db: Session, name: str, except_id: Optional[int] = None) -> None:
    for (pid, other) in db.query(InventoryProduct.id, InventoryProduct.name).filter(InventoryProduct.archived_at.is_(None)).all():
        if pid != except_id and inventory.same_name(other, name):
            _err(f"Ya existe un producto llamado «{other}»")


def _active_category_id(db: Session, raw) -> Optional[int]:
    if raw in (None, ""):
        return None
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        _err("Categoría inválida")
    c = db.get(InventoryCategory, cid)
    if not c or c.archived_at is not None:
        _err("La categoría elegida no existe o está archivada")
    return cid


@router.post("/inventory/categories")
def create_category(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    name = _wrap(lambda: inventory.clean_name(data.get("name"), "El nombre de la categoría"))
    _assert_free_category_name(db, name)
    c = InventoryCategory(name=name, position=_next_position(db, InventoryCategory))
    db.add(c)
    db.flush()
    audit_actions.record(db, staff, "create", "inventory_category", c.id, c.name)
    db.commit()
    return _category_json(c)


@router.patch("/inventory/categories/{category_id}")
def update_category(category_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    c = _category(db, category_id)
    if "name" in data:
        name = _wrap(lambda: inventory.clean_name(data.get("name"), "El nombre de la categoría"))
        _assert_free_category_name(db, name, c.id)
        c.name = name
    if "position" in data:
        try:
            c.position = int(data["position"])
        except (TypeError, ValueError):
            _err("La posición debe ser un número")
    audit_actions.record(db, staff, "update", "inventory_category", c.id, c.name)
    db.commit()
    return _category_json(c)


@router.post("/inventory/categories/{category_id}/archive")
def archive_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    c = _category(db, category_id)
    if c.archived_at is None:
        n = db.query(InventoryProduct).filter(InventoryProduct.category_id == c.id, InventoryProduct.archived_at.is_(None)).count()
        if n:
            _err(f"La categoría tiene {n} producto(s) activos: muévelos a otra categoría o archívalos primero")
        c.archived_at, c.archived_by_id = utcnow(), staff.id
        audit_actions.record(db, staff, "archive", "inventory_category", c.id, c.name)
        db.commit()
    return _category_json(c)


@router.post("/inventory/categories/{category_id}/restore")
def restore_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    c = _category(db, category_id)
    if c.archived_at is not None:
        _assert_free_category_name(db, c.name, c.id)
        c.archived_at = c.archived_by_id = None
        audit_actions.record(db, staff, "restore", "inventory_category", c.id, c.name)
        db.commit()
    return _category_json(c)


@router.delete("/inventory/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    c = _category(db, category_id)
    if c.archived_at is None:
        _err("Archiva la categoría antes de eliminarla")
    if db.query(InventoryProduct).filter(InventoryProduct.category_id == c.id).count():
        _err("La categoría todavía tiene productos (aunque estén archivados): no se puede eliminar")
    audit_actions.record(db, staff, "delete", "inventory_category", c.id, c.name)
    db.delete(c)
    db.commit()
    return {"deleted": True}


def _apply_product(db: Session, p: InventoryProduct, data: dict, creating: bool) -> None:
    if creating or "name" in data:
        name = _wrap(lambda: inventory.clean_name(data.get("name"), "El nombre del producto"))
        _assert_free_product_name(db, name, p.id)
        p.name = name
    if creating or "unit" in data:
        p.unit = _wrap(lambda: inventory.clean_unit(data.get("unit")))
    if creating or "sku" in data:
        p.sku = _wrap(lambda: inventory.clean_sku(data.get("sku")))
    if creating or "category_id" in data:
        p.category_id = _active_category_id(db, data.get("category_id"))
    if "stock" in data:          # existencias de Golden; vacío = no se controla (sin aviso de falta de material)
        raw = data.get("stock")
        if raw in (None, ""):
            p.qty_total = None
        else:
            p.qty_total = _wrap(lambda: inventory.clean_qty(raw, f"Las existencias de «{p.name or 'el producto'}»"))
    if creating or "fields" in data:
        p.fields_json = inventory.dump_fields(_wrap(lambda: inventory.clean_product_fields(data.get("fields"))))


@router.post("/inventory/products")
def create_product(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = InventoryProduct(position=_next_position(db, InventoryProduct))
    _apply_product(db, p, data, creating=True)
    db.add(p)
    db.flush()
    audit_actions.record(db, staff, "create", "inventory_product", p.id, p.name)
    db.commit()
    return _product_json(p)


@router.patch("/inventory/products/{product_id}")
def update_product(product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id)
    if p.archived_at is not None:
        _err("El producto está archivado: restáuralo para editarlo")
    _apply_product(db, p, data, creating=False)
    if "position" in data:
        try:
            p.position = int(data["position"])
        except (TypeError, ValueError):
            _err("La posición debe ser un número")
    audit_actions.record(db, staff, "update", "inventory_product", p.id, p.name)
    db.commit()
    return _product_json(p)


@router.post("/inventory/products/{product_id}/archive")
def archive_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id)
    if p.archived_at is None:
        p.archived_at, p.archived_by_id = utcnow(), staff.id
        audit_actions.record(db, staff, "archive", "inventory_product", p.id, p.name)
        db.commit()
    return _product_json(p)


@router.post("/inventory/products/{product_id}/restore")
def restore_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id)
    if p.archived_at is not None:
        _assert_free_product_name(db, p.name, p.id)
        if p.category_id is not None and p.category.archived_at is not None:
            p.category_id = None          # su categoría se archivó: vuelve «sin categorizar» hasta que se le asigne otra
        p.archived_at = p.archived_by_id = None
        audit_actions.record(db, staff, "restore", "inventory_product", p.id, p.name)
        db.commit()
    return _product_json(p)


@router.delete("/inventory/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id)
    if p.archived_at is None:
        _err("Archiva el producto antes de eliminarlo")
    if db.query(EventInventoryItem).filter(EventInventoryItem.product_id == p.id).count():
        _err("El producto está en el inventario de algún evento: no se puede eliminar (queda archivado)")
    audit_actions.record(db, staff, "delete", "inventory_product", p.id, p.name)
    db.delete(p)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------- inventario de un evento

def _event(db: Session, event_id: int, staff: StaffUser, *, lock: bool = False) -> Event:
    q = db.query(Event).filter(Event.id == event_id)
    event = (q.with_for_update() if lock else q).first()
    if not event:
        _err("Evento no encontrado", 404)
    assert_event_tenant(event, staff)
    if not (effective_roles(staff) & WIDE_ROLES):
        assert_event_scope(event, staff, db)
    return event


def _plan_json(db: Session, event: Event, staff: StaffUser) -> dict:
    lines = {l.product_id: l for l in inventory_svc.event_lines(db, event.id)}
    prods = db.query(InventoryProduct).filter((InventoryProduct.archived_at.is_(None)) | (InventoryProduct.id.in_(list(lines) or [0]))).order_by(InventoryProduct.position, InventoryProduct.id).all()
    out = []
    for p in prods:
        l = lines.get(p.id)
        cat_ok = p.category is not None and p.category.archived_at is None
        out.append({
            "product_id": p.id, "name": p.name, "unit": p.unit, "sku": p.sku, "category_id": p.category_id if cat_ok else None, "category_name": p.category.name if cat_ok else None,
            "fields": inventory.load_fields(p.fields_json), "archived": p.archived_at is not None,
            "assigned": l.qty_assigned if l else 0, "out": l.qty_out if l else 0, "returned": l.qty_returned if l else 0, "consumed": l.qty_consumed if l else 0,
            "notes": l.notes if l else None, "attrs": _attrs(l),
        })
    rep = inventory.check_balance(inventory_svc.to_rows(list(lines.values())), inventory.stage_for_status(event.status))
    return {"event_id": event.id, "status": event.status, "lines": out, "balance": rep.as_dict(), "totals": inventory.summary(inventory_svc.to_rows(list(lines.values()))),
            "can_edit_plan": can_edit_plan(staff) and event.archived_at is None, "can_edit_movement": can_edit_movement(staff) and event.archived_at is None,
            "gate_enabled": inventory_svc.gate_enabled(), "warnings": [w["message"] for w in inventory_alerts.warnings_for_event(db, event)]}          # avisos: nunca bloquean


def _attrs(line: Optional[EventInventoryItem]) -> dict:
    import json
    try:
        return json.loads(line.attrs_json) if line and line.attrs_json else {}
    except ValueError:
        return {}


@router.get("/inventory/events")
def list_inventory_events(q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    """Eventos del cliente para la pantalla /inventario (cuentas solo de almacén o contabilidad, que no tienen el listado de eventos): id, nombre, estado y fechas. Máximo 300, los más recientes primero."""
    query = db.query(Event).filter(Event.archived_at.is_(None))
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter((Event.name.ilike(like)) | (Event.event_code.ilike(like)))
    rows, wide = [], bool(effective_roles(staff) & WIDE_ROLES)
    for e in query.order_by(Event.start_date.desc().nullslast(), Event.id.desc()).limit(600).all():
        try:
            assert_event_tenant(e, staff)
            if not wide:
                assert_event_scope(e, staff, db)
        except HTTPException:
            continue
        rows.append({"id": e.id, "name": e.name, "code": e.event_code, "status": e.status,
                     "start_date": e.start_date.isoformat() if e.start_date else None, "end_date": e.end_date.isoformat() if e.end_date else None})
        if len(rows) >= 300:
            break
    return {"events": rows}


@router.get("/events/{event_id}/inventory-plan")
def get_plan(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    return _plan_json(db, _event(db, event_id, staff), staff)


@router.put("/events/{event_id}/inventory-plan")
def put_plan(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    """Guarda las líneas que lleguen en `lines` ([{product_id, assigned?, out?, returned?, consumed?, notes?, attrs?}]); las demás líneas no se tocan. Solo se aceptan cambios que el rol permite
    (ver el docstring del módulo). Si el resultado rompe la regla de cuadre de siempre (devuelto + consumido > salió, salió > asignado) no se guarda NADA."""
    import json
    event = _event(db, event_id, staff, lock=True)
    if event.archived_at is not None:
        _err("El evento está archivado: restáuralo para editar su inventario")
    if not can_edit_plan(staff):
        _err("Tu rol solo puede ver el inventario", 403)
    raw = data.get("lines")
    if not isinstance(raw, list):
        _err("Envía la lista de líneas en «lines»")
    if len(raw) > 500:
        _err("Demasiadas líneas en una sola petición")
    movement_ok = can_edit_movement(staff)
    current = {l.product_id: l for l in inventory_svc.event_lines(db, event.id)}
    seen, staged = set(), []
    for item in raw:
        if not isinstance(item, dict):
            _err("Línea de inventario inválida")
        try:
            pid = int(item.get("product_id"))
        except (TypeError, ValueError):
            _err("Cada línea necesita su producto")
        if pid in seen:
            _err("Hay un producto repetido en las líneas")
        seen.add(pid)
        prod = db.get(InventoryProduct, pid)
        if not prod:
            _err("Hay un producto que no existe", 404)
        line = current.get(pid)
        if prod.archived_at is not None and line is None:
            _err(f"«{prod.name}» está archivado en el catálogo")
        qty = {}
        for key, col in (("assigned", "qty_assigned"), ("out", "qty_out"), ("returned", "qty_returned"), ("consumed", "qty_consumed")):
            before = getattr(line, col) if line else 0
            qty[key] = _wrap(lambda: inventory.clean_qty(item[key], f"«{prod.name}» ({key})")) if key in item else (before or 0)
            if key != "assigned" and qty[key] != (before or 0) and not movement_ok:
                _err("Solo Almacén (o un Admin) registra lo que sale, vuelve o se consume", 403)
        notes = _wrap(lambda: inventory.clean_notes(item["notes"])) if "notes" in item else (line.notes if line else None)
        attrs = _wrap(lambda: inventory.clean_attrs(item["attrs"], inventory.load_fields(prod.fields_json))) if "attrs" in item else _attrs(line)
        staged.append((prod, line, qty, notes, attrs))
    rows = [inventory.Row(name=prod.name, assigned=q["assigned"], out=q["out"], returned=q["returned"], consumed=q["consumed"], category_id=prod.category_id, product_id=prod.id) for prod, _l, q, _n, _a in staged]
    rep = inventory.check_balance(rows, "creado")
    if not rep.ok:
        _err("No se guardó: " + " ".join(i.message for i in rep.errors[:4]))
    now = utcnow()
    for prod, line, q, notes, attrs in staged:
        empty = not any(q.values()) and not notes and not attrs
        if line is None:
            if empty:
                continue
            line = EventInventoryItem(event_id=event.id, product_id=prod.id)
            db.add(line)
        line.qty_assigned, line.qty_out, line.qty_returned, line.qty_consumed = q["assigned"], q["out"], q["returned"], q["consumed"]
        line.notes = notes
        line.attrs_json = json.dumps(attrs, ensure_ascii=False) if attrs else None
        line.updated_by_id, line.updated_at = staff.id, now
    audit_actions.record(db, staff, "update", "event_inventory", event.id, event.name, f"{len(staged)} línea(s)")
    db.flush()
    alerts = inventory_alerts.notify_event(db, event, staff, inventory_alerts.warnings_for_event(db, event))          # avisa (campana + correo) si falta anticipación o material; NUNCA bloquea
    db.commit()
    if alerts:
        jobs.kick()
    return _plan_json(db, event, staff)


# ---------------------------------------------------------------- Fase 10: catálogo con lo que está en uso y calendario «dónde está cada equipo»

def _can_manage(staff: StaffUser) -> bool:
    return bool(effective_roles(staff) & {"almacen", "admin", "super_admin"})


def _events_in_range(db: Session, a, b) -> list:
    """Eventos (de cualquier cliente: el material es de Golden) que ocupan material entre a y b, con su rango y sus líneas asignadas. Solo números: los nombres se filtran por permiso al responder."""
    q = (db.query(Event).filter(Event.archived_at.is_(None), Event.start_date.isnot(None), or_(Event.start_date <= b, Event.setup_date <= b))
         .filter(func.coalesce(Event.end_date, Event.start_date) >= a))
    out = []
    for e in q.all():
        span = inventory_calendar.event_span(e.start_date, e.end_date, e.setup_date)
        if inventory_calendar.overlaps(span, a, b):
            out.append({"event": e, "span": span, "lines": {}})
    if not out:
        return out
    by_id = {o["event"].id: o for o in out}
    for l in db.query(EventInventoryItem).filter(EventInventoryItem.event_id.in_(list(by_id))).all():
        if (l.qty_assigned or 0) > 0 or (l.qty_out or 0) > 0:
            by_id[l.event_id]["lines"][l.product_id] = l
    return out


@router.get("/inventory/overview")
def inventory_overview(db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    """Catálogo vigente (categorías, productos, existencias) con lo asignado a eventos HOY y lo disponible. Sin nombres de eventos."""
    today = to_local(utcnow()).date()
    cat = _catalog(db, False)
    used = inventory_calendar.usage_on(today, [{"span": o["span"], "lines": {pid: l.qty_assigned for pid, l in o["lines"].items()}} for o in _events_in_range(db, today, today)])
    for p in cat["products"]:
        p["in_use"] = used.get(p["id"], 0)
        p["available"] = inventory_calendar.available(p["stock"], p["in_use"])
    cat["today"] = today.isoformat()
    cat["can_manage"] = _can_manage(staff)
    cat["can_edit_catalog"] = _can_manage(staff)
    return cat


@router.patch("/inventory/products/{product_id}/manage")
def manage_product(product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Admin y almacén: cambian solo la categoría (`category_id`) y las existencias (`stock`) de un producto del catálogo."""
    p = _product(db, product_id)
    if p.archived_at is not None:
        _err("El producto está archivado: restáuralo para editarlo")
    allowed = {k: data[k] for k in ("stock", "category_id") if k in data}
    if not allowed:
        _err("Envía la categoría o las existencias")
    _apply_product(db, p, allowed, creating=False)
    audit_actions.record(db, staff, "update", "inventory_product", p.id, p.name, ", ".join(f"{k}={allowed[k]}" for k in allowed))
    db.commit()
    return _product_json(p)


@router.get("/inventory/calendar")
def inventory_calendar_view(start: str, end: str, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEWER)):
    """«Dónde está cada equipo»: entre `start` y `end` (AAAA-MM-DD, máx. 100 días) qué material tiene asignado cada evento y cuánto queda disponible cada día.
    `events` = solo los que la cuenta puede ver (por cliente y pertenencia); `daily` = unidades asignadas por día y producto contando TODOS los eventos."""
    a, b = _range(start, end)
    found = _events_in_range(db, a, b)
    products = {p.id: p for p in db.query(InventoryProduct).all()}
    wide = bool(effective_roles(staff) & WIDE_ROLES)
    events = []
    for o in sorted(found, key=lambda x: (x["span"][0], x["event"].id)):
        e = o["event"]
        try:
            assert_event_tenant(e, staff)
            if not wide:
                assert_event_scope(e, staff, db)
        except HTTPException:
            continue
        lines = []
        for pid, l in sorted(o["lines"].items(), key=lambda kv: (products[kv[0]].position, kv[0]) if kv[0] in products else (0, kv[0])):
            p = products.get(pid)
            if p is None:
                continue
            lines.append({"product_id": pid, "name": p.name, "unit": p.unit, "category_id": p.category_id, "assigned": l.qty_assigned or 0, "out": l.qty_out or 0, "returned": l.qty_returned or 0,
                          "consumed": l.qty_consumed or 0, "pending_return": inventory_calendar.pending_return(l.qty_out, l.qty_returned, l.qty_consumed)})
        events.append({"id": e.id, "name": e.name, "code": e.event_code, "status": e.status, "city": e.city, "start": o["span"][0].isoformat(), "end": o["span"][1].isoformat(),
                       "event_start": e.start_date.isoformat(), "event_end": (e.end_date or e.start_date).isoformat(), "lines": lines})
    spans = [{"span": o["span"], "lines": {pid: l.qty_assigned for pid, l in o["lines"].items()}} for o in found]
    daily = {}
    for day in inventory_calendar.days_between(a, b):
        used = {str(pid): q for pid, q in inventory_calendar.usage_on(day, spans).items()}
        if used:
            daily[day.isoformat()] = used
    prods = [{"id": p.id, "name": p.name, "unit": p.unit, "category_id": p.category_id, "category_name": p.category.name if p.category and p.category.archived_at is None else None, "stock": p.qty_total}
             for p in sorted(products.values(), key=lambda x: (x.position, x.id)) if p.archived_at is None]
    return {"start": a.isoformat(), "end": b.isoformat(), "events": events, "daily": daily, "products": prods}


def _range(start, end):
    try:
        return inventory_calendar.clean_range(start, end)
    except inventory_calendar.RangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
