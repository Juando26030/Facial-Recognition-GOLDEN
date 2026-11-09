"""Inventario con catálogo (Fase 5): catálogo de categorías y productos (lo define el Super Admin en Configuración) y las líneas de inventario de cada evento (cantidades y regla de cuadre).

Permisos (Fase 5; los roles «almacen» y «contabilidad» son solo EXTRA, ver app/auth.py):
  - Catálogo: ver = coordinador+, almacén y contabilidad; crear / editar / archivar / eliminar = SOLO Super Admin.
  - Inventario de un evento: ver = coordinador+, almacén, contabilidad. Editar lo que PIDE el evento (asignado, notas, datos del producto) = coordinador+ y almacén; editar lo que MUEVE el
    almacén (salió, volvió, consumido) = almacén y admin+. Contabilidad es solo lectura. Ninguno de estos roles obtiene datos personales de asistentes ni administra cuentas por esta ruta.
Este router no usa get_event_for_staff (no toca personas ni respuestas): valida cliente (assert_event_tenant) y, para quien no es almacén/contabilidad/admin, la pertenencia al evento.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_actions, inventory, inventory_svc
from app.auth import ROLE_HIERARCHY, assert_event_scope, assert_event_tenant, effective_roles, require_role_or_any, require_super_admin
from app.database import get_db
from app.models import Event, EventInventoryItem, InventoryCategory, InventoryProduct, StaffUser
from app.timeutil import utcnow

router = APIRouter()

VIEWER = require_role_or_any("coordinador", ("almacen", "contabilidad"))
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
            "fields": inventory.load_fields(p.fields_json), "position": p.position, "archived": p.archived_at is not None}


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
    """Catálogo vigente. `include_archived=true` (con los archivados) es solo del Super Admin."""
    if include_archived and staff.role != "super_admin":
        _err("Solo el Super Admin ve el catálogo archivado", 403)
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
def create_category(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    name = _wrap(lambda: inventory.clean_name(data.get("name"), "El nombre de la categoría"))
    _assert_free_category_name(db, name)
    c = InventoryCategory(name=name, position=_next_position(db, InventoryCategory))
    db.add(c)
    db.flush()
    audit_actions.record(db, staff, "create", "inventory_category", c.id, c.name)
    db.commit()
    return _category_json(c)


@router.patch("/inventory/categories/{category_id}")
def update_category(category_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
def archive_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
def restore_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    c = _category(db, category_id)
    if c.archived_at is not None:
        _assert_free_category_name(db, c.name, c.id)
        c.archived_at = c.archived_by_id = None
        audit_actions.record(db, staff, "restore", "inventory_category", c.id, c.name)
        db.commit()
    return _category_json(c)


@router.delete("/inventory/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
    if creating or "fields" in data:
        p.fields_json = inventory.dump_fields(_wrap(lambda: inventory.clean_product_fields(data.get("fields"))))


@router.post("/inventory/products")
def create_product(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    p = InventoryProduct(position=_next_position(db, InventoryProduct))
    _apply_product(db, p, data, creating=True)
    db.add(p)
    db.flush()
    audit_actions.record(db, staff, "create", "inventory_product", p.id, p.name)
    db.commit()
    return _product_json(p)


@router.patch("/inventory/products/{product_id}")
def update_product(product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
def archive_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
    p = _product(db, product_id)
    if p.archived_at is None:
        p.archived_at, p.archived_by_id = utcnow(), staff.id
        audit_actions.record(db, staff, "archive", "inventory_product", p.id, p.name)
        db.commit()
    return _product_json(p)


@router.post("/inventory/products/{product_id}/restore")
def restore_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
def delete_product(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_super_admin)):
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
            "gate_enabled": inventory_svc.gate_enabled()}


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
    db.commit()
    return _plan_json(db, event, staff)
