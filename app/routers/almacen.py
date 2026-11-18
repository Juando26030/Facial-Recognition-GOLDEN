"""Almacén (bodega), Pieza 1: control de los elementos del catálogo (con serial / por modelo / por cantidad), unidades con serial, códigos QR, etiquetas y búsqueda por lectura de QR.

Rama almacen/p1-catalogo; plan en claude/58_PLAN_ALMACEN. Se apoya en el catálogo de inventario (app/routers/inventory.py): los productos se crean y se archivan allá; aquí se les agrega cómo se controlan y
sus unidades. Todo responde 404 mientras `ALMACEN_ENABLED` esté apagado (app/almacen.py).
Permisos: almacén, admin y super_admin (los mismos que administran el catálogo). Pieza 2 (rama almacen/p2-movimientos): salidas y entradas por QR, alistado por fila del checklist, tablero del evento
y foto del elemento; las reglas están en app/almacen_moves.py. Las novedades llegan en la Pieza 3.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import almacen, almacen_moves as moves, almacen_novelties as nov, almacen_photos, audit_actions, inventory, inventory_svc
from app.auth import require_role_or_any
from app.database import get_db
from app.models import Event, EventChecklistRow, EventInventoryItem, InventoryMovement, InventoryNovelty, InventoryProduct, InventoryUnit, StaffUser
from app.routers.inventory import _event as _inventory_event          # mismo acceso al evento que el inventario (cliente/empresa y alcance)
from app.storage import get_storage
from app.timeutil import to_local, utcnow


def _gate():
    if not almacen.almacen_enabled():
        raise HTTPException(status_code=404, detail="No encontrado")


router = APIRouter(dependencies=[Depends(_gate)])
MANAGER = require_role_or_any("admin", ("almacen",))
MAX_LIST = 500


def _err(msg: str, code: int = 400):
    raise HTTPException(status_code=code, detail=msg)


def _wrap(fn):
    try:
        return fn()
    except almacen.AlmacenError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _product(db: Session, product_id: int, *, lock: bool = False) -> InventoryProduct:
    q = db.query(InventoryProduct).filter(InventoryProduct.id == product_id)
    if lock:
        q = q.with_for_update()          # serializa el consecutivo de unidades del producto (FOR UPDATE sí es compatible con el pooler de Neon)
    p = q.first()
    if p is None:
        _err("El producto no existe", 404)
    return p


def _unit(db: Session, unit_id: int) -> InventoryUnit:
    u = db.query(InventoryUnit).filter(InventoryUnit.id == unit_id).first()
    if u is None:
        _err("La unidad no existe", 404)
    return u


def _product_json(p: InventoryProduct, units: int = 0) -> dict:
    cat = p.category
    return {"id": p.id, "name": p.name, "category_id": p.category_id, "category_name": cat.name if cat else None, "unit": p.unit, "stock": p.qty_total,
            "tracking": p.tracking or "cantidad", "checklist_row": p.checklist_row, "is_consumable": bool(p.is_consumable), "qr_code": p.qr_code,
            "units": units, "archived": p.archived_at is not None,
            "has_photo": bool(p.photo_key), "photo_url": f"/api/almacen/products/{p.id}/photo?v={(p.photo_key or '')[-12:-4]}" if p.photo_key else None}


def _novelty_unit_ids(db: Session, unit_ids) -> set:
    """Ids de las unidades que tienen una novedad abierta (para el aviso ⚠ de la tabla de objetos)."""
    ids = list(unit_ids)
    if not ids:
        return set()
    return {i for (i,) in db.query(InventoryNovelty.unit_id).filter(InventoryNovelty.unit_id.in_(ids), InventoryNovelty.resolved_at.is_(None)).all()}


def _unit_json(u: InventoryUnit, product: Optional[InventoryProduct] = None, novelty: bool = False) -> dict:
    p = product or u.product
    return {"has_novelty": bool(novelty or u.status == "novedad"), "id": u.id, "product_id": u.product_id, "product_name": p.name, "number": u.number, "title": almacen.unit_title(p.name, u.number), "code": u.code, "serial": u.code,
            "status": u.status, "status_label": almacen.UNIT_STATUS_LABEL.get(u.status, u.status), "archived": u.archived_at is not None,
            "event_id": u.event_id, "event_name": u.event.name if u.event_id and u.event else None}


def _code_taken(db: Session, code: str) -> bool:
    return (db.query(InventoryUnit.id).filter(InventoryUnit.code == code).first() is not None
            or db.query(InventoryProduct.id).filter(InventoryProduct.qr_code == code).first() is not None)


def _free_code(db: Session, taken: set) -> str:
    for _ in range(50):
        c = almacen.new_code()
        if c not in taken and not _code_taken(db, c):
            taken.add(c)
            return c
    _err("No se pudo generar un código libre; intenta de nuevo", 500)


def _ensure_product_code(db: Session, p: InventoryProduct) -> None:
    if p.tracking != "serial" and not p.qr_code:
        p.qr_code = _free_code(db, set())


# ---------------------------------------------------------------- datos fijos
@router.get("/almacen/meta")
def meta(staff: StaffUser = Depends(MANAGER)):
    return {"tracking": [{"key": k, **almacen.TRACKING_INFO[k]} for k in almacen.TRACKING],
            "rows": [r for r in almacen.CHECKLIST_ROWS if r["kind"] == "inv"],
            "sections": almacen.SECTIONS,
            "statuses": [{"key": k, "label": almacen.UNIT_STATUS_LABEL[k]} for k in almacen.UNIT_STATUS],
            "max_units": almacen.MAX_UNITS_PER_BATCH, "max_labels": almacen.MAX_LABELS_PER_PRINT}


# ---------------------------------------------------------------- productos
@router.get("/almacen/products")
def list_products(q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    counts = dict(db.query(InventoryUnit.product_id, func.count(InventoryUnit.id)).filter(InventoryUnit.archived_at.is_(None)).group_by(InventoryUnit.product_id).all())
    query = db.query(InventoryProduct).filter(InventoryProduct.archived_at.is_(None))
    term = (q or "").strip()
    if term:
        query = query.filter(or_(InventoryProduct.name.ilike(f"%{term}%"), InventoryProduct.sku.ilike(f"%{term}%")))
    rows = query.order_by(InventoryProduct.position, InventoryProduct.id).limit(MAX_LIST).all()
    return {"products": [_product_json(p, counts.get(p.id, 0)) for p in rows]}


@router.patch("/almacen/products/{product_id}")
def update_product(product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id, lock=True)
    if p.archived_at is not None:
        _err("El producto está archivado: restáuralo para editarlo")
    if "tracking" in data:
        new = _wrap(lambda: almacen.clean_tracking(data.get("tracking")))
        if new != (p.tracking or "cantidad"):
            active = db.query(func.count(InventoryUnit.id)).filter(InventoryUnit.product_id == p.id, InventoryUnit.archived_at.is_(None)).scalar() or 0
            if active:
                _err(f"«{p.name}» tiene {active} unidades con serial activas: archívalas antes de cambiar cómo se controla")
            p.tracking = new
    if "checklist_row" in data:
        p.checklist_row = _wrap(lambda: almacen.clean_checklist_row(data.get("checklist_row")))
    if "is_consumable" in data:
        p.is_consumable = bool(data.get("is_consumable"))
    _ensure_product_code(db, p)
    audit_actions.record(db, staff, "update", "almacen_product", p.id, p.name)
    db.commit()
    return _product_json(p)


# ---------------------------------------------------------------- unidades con serial
@router.get("/almacen/units")
def list_units(product_id: Optional[int] = None, q: str = "", include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    query = db.query(InventoryUnit).join(InventoryProduct, InventoryProduct.id == InventoryUnit.product_id)
    if product_id:
        query = query.filter(InventoryUnit.product_id == product_id)
    if not include_archived:
        query = query.filter(InventoryUnit.archived_at.is_(None))
    term = (q or "").strip()
    if term:
        query = query.filter(or_(InventoryUnit.code.ilike(f"%{term}%"), InventoryUnit.serial.ilike(f"%{term}%"), InventoryProduct.name.ilike(f"%{term}%")))
    rows = query.order_by(InventoryProduct.position, InventoryProduct.id, InventoryUnit.number).limit(MAX_LIST).all()
    flagged = _novelty_unit_ids(db, [u.id for u in rows])
    return {"units": [_unit_json(u, novelty=u.id in flagged) for u in rows]}


@router.post("/almacen/products/{product_id}/units")
def create_units(product_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id, lock=True)
    if p.archived_at is not None:
        _err("El producto está archivado: restáuralo para crear unidades")
    if (p.tracking or "cantidad") != "serial":
        _err(f"«{p.name}» no se controla con serial: cámbialo a «Con serial» para crear unidades")
    count = _wrap(lambda: almacen.clean_count(data.get("count", 1)))
    serial = _wrap(lambda: almacen.clean_serial(data.get("serial")))
    if serial and count != 1:
        _err("El serial solo se puede escribir al crear una unidad; las demás se editan después")
    if serial and _code_taken(db, serial):
        _err(f"El serial {serial} ya existe en el almacén: cada serial es único (es también el valor del QR)", 409)
    last = db.query(func.max(InventoryUnit.number)).filter(InventoryUnit.product_id == p.id).scalar() or 0          # incluye archivadas: un número nunca se reutiliza
    taken: set = set()
    created = []
    for i in range(count):
        u = InventoryUnit(product_id=p.id, number=last + i + 1, code=(serial if (i == 0 and serial) else _free_code(db, taken)), serial=None, status="disponible", created_by_id=staff.id)
        db.add(u)
        created.append(u)
    for u in created:
        u.serial = u.code          # un solo dato: el serial es el valor del QR
    db.flush()
    audit_actions.record(db, staff, "create", "almacen_unit", p.id, p.name, f"{count} unidad(es): #{created[0].number}–#{created[-1].number}")
    db.commit()
    return {"units": [_unit_json(u, p) for u in created]}


@router.patch("/almacen/units/{unit_id}")
def update_unit(unit_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    u = _unit(db, unit_id)
    if u.archived_at is not None:
        _err("La unidad está archivada: restáurala para editarla")
    if "serial" in data:
        serial = _wrap(lambda: almacen.clean_serial(data.get("serial")))
        if not serial:
            _err("El serial no puede quedar vacío (es el valor del QR de la etiqueta)")
        if serial != u.code:
            if _code_taken(db, serial):
                _err(f"El serial {serial} ya existe en el almacén: cada serial es único (es también el valor del QR)", 409)
            u.code = u.serial = serial          # cambia el valor del QR: la etiqueta ya impresa deja de servir y hay que reimprimirla
    audit_actions.record(db, staff, "update", "almacen_unit", u.id, almacen.unit_title(u.product.name, u.number))
    db.commit()
    return _unit_json(u, novelty=u.id in _novelty_unit_ids(db, [u.id]))


@router.post("/almacen/units/{unit_id}/archive")
def archive_unit(unit_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    u = _unit(db, unit_id)
    if u.archived_at is None:
        if u.status != "disponible":
            _err("Solo se puede archivar una unidad disponible (no una que está en un evento o en novedad)")
        u.archived_at, u.archived_by_id = utcnow(), staff.id
        audit_actions.record(db, staff, "archive", "almacen_unit", u.id, almacen.unit_title(u.product.name, u.number))
        db.commit()
    return _unit_json(u)


@router.post("/almacen/units/{unit_id}/restore")
def restore_unit(unit_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    u = _unit(db, unit_id)
    if u.archived_at is not None:
        u.archived_at, u.archived_by_id = None, None
        audit_actions.record(db, staff, "restore", "almacen_unit", u.id, almacen.unit_title(u.product.name, u.number))
        db.commit()
    return _unit_json(u)


# ---------------------------------------------------------------- lectura de QR y etiquetas
@router.get("/almacen/scan")
def scan(code: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Lo que escribe el lector USB → qué es. Solo identifica (para mover material se usa POST /almacen/move)."""
    c = almacen.normalize_scan(code)
    if not c:
        _err("Ese texto no parece un código de almacén. Revisa que el lector esté en modo teclado.", 404)
    u = db.query(InventoryUnit).filter(InventoryUnit.code == c).first()
    if u is not None:
        return {"kind": "unit", "code": c, "unit": _unit_json(u), "product": _product_json(u.product)}
    p = db.query(InventoryProduct).filter(InventoryProduct.qr_code == c).first()
    if p is not None:
        return {"kind": "product", "code": c, "product": _product_json(p)}
    _err(f"El código {c} no existe en el almacén", 404)


@router.post("/almacen/labels")
def labels(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Datos para imprimir etiquetas QR: unidades (`unit_ids`) y/o productos por modelo o cantidad (`product_ids`). El QR lleva SOLO el código."""
    unit_ids = _wrap(lambda: almacen.clean_ids(data.get("unit_ids"), "Unidades"))
    product_ids = _wrap(lambda: almacen.clean_ids(data.get("product_ids"), "Productos"))
    if not unit_ids and not product_ids:
        _err("Elige al menos un elemento para imprimir su etiqueta")
    if len(unit_ids) + len(product_ids) > almacen.MAX_LABELS_PER_PRINT:
        _err(f"Se pueden imprimir hasta {almacen.MAX_LABELS_PER_PRINT} etiquetas a la vez")
    out = []
    if unit_ids:
        found = {u.id: u for u in db.query(InventoryUnit).filter(InventoryUnit.id.in_(unit_ids)).all()}
        for uid in unit_ids:
            u = found.get(uid)
            if u is None:
                _err("Una de las unidades no existe", 404)
            out.append({"code": u.code, "title": almacen.unit_title(u.product.name, u.number), "subtitle": ""})
    if product_ids:
        found_p = {p.id: p for p in db.query(InventoryProduct).filter(InventoryProduct.id.in_(product_ids)).all()}
        for pid in product_ids:
            p = found_p.get(pid)
            if p is None:
                _err("Uno de los productos no existe", 404)
            if (p.tracking or "cantidad") == "serial":
                _err(f"«{p.name}» se controla con serial: imprime la etiqueta de cada unidad")
            _ensure_product_code(db, p)
            out.append({"code": p.qr_code, "title": p.name, "subtitle": "Por modelo" if p.tracking == "modelo" else "Por cantidad"})
        db.commit()
    return {"labels": out}


# ---------------------------------------------------------------- foto del elemento
@router.post("/almacen/products/{product_id}/photo")
def upload_product_photo(product_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Foto del elemento (al crearlo o después). Se valida, se reduce a JPEG y reemplaza la anterior."""
    p = _product(db, product_id, lock=True)
    content = file.file.read(almacen_photos.MAX_PHOTO_BYTES + 1)
    if not content:
        _err("La foto está vacía")
    if len(content) > almacen_photos.MAX_PHOTO_BYTES:
        _err("La foto pesa más de 8 MB")
    jpeg = _wrap(lambda: almacen_photos.process_photo(content, file.filename or ""))
    key = almacen_photos.new_photo_key("elementos")
    get_storage().put(key, jpeg)
    old, p.photo_key = p.photo_key, key
    audit_actions.record(db, staff, "update", "almacen_product_photo", p.id, p.name)
    db.commit()
    if old:
        get_storage().delete(old)
    return _product_json(p)


@router.get("/almacen/products/{product_id}/photo")
def get_product_photo(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id)
    if not p.photo_key or not get_storage().exists(p.photo_key):
        _err("El elemento no tiene foto", 404)
    return get_storage().response(p.photo_key, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.delete("/almacen/products/{product_id}/photo")
def delete_product_photo(product_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    p = _product(db, product_id, lock=True)
    if p.photo_key:
        old, p.photo_key = p.photo_key, None
        audit_actions.record(db, staff, "delete", "almacen_product_photo", p.id, p.name)
        db.commit()
        get_storage().delete(old)
    return _product_json(p)


# ---------------------------------------------------------------- salidas y entradas (Pieza 2)
def _move_error(exc: "moves.MoveError"):
    if exc.needs_reason:
        raise HTTPException(status_code=409, detail={"message": str(exc), "needs_reason": True, "extra": exc.extra})
    raise HTTPException(status_code=400, detail=str(exc))


def _guard(fn):
    try:
        return fn()
    except moves.MoveError as exc:
        _move_error(exc)
    except almacen.AlmacenError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _check_row(db: Session, product: InventoryProduct, line: EventInventoryItem) -> None:
    """La regla de cuadre de siempre (app/inventory.py) sobre la línea ya modificada; si falla, no se guarda nada."""
    cat_ok = product.category is not None and product.category.archived_at is None
    rep = inventory.check_balance([inventory.Row(name=product.name, assigned=line.qty_assigned or 0, out=line.qty_out or 0, returned=line.qty_returned or 0,
                                                 consumed=line.qty_consumed or 0, category_id=product.category_id if cat_ok else None, product_id=product.id)], "creado")
    if not rep.ok:
        db.rollback()
        _err("No se guardó: " + " ".join(i.message for i in rep.errors[:3]))


def _line_json(line: Optional[EventInventoryItem], extra: int = 0) -> dict:
    a, o, r, c = ((line.qty_assigned or 0), (line.qty_out or 0), (line.qty_returned or 0), (line.qty_consumed or 0)) if line else (0, 0, 0, 0)
    return {"needed": max(a - extra, 0), "assigned": a, "out": o, "returned": r, "consumed": c, "pending": max(o - r - c, 0)}


def _movement_json(m: InventoryMovement, can_void: bool = False) -> dict:
    title = almacen.unit_title(m.product.name, m.unit.number) if m.unit_id and m.unit else m.product.name
    return {"id": m.id, "kind": m.kind, "title": title, "qty": m.qty, "extra": m.extra, "reason": m.reason, "plan_b": bool(m.is_plan_b),
            "at": to_local(m.created_at).strftime("%d/%m/%Y %H:%M") if m.created_at else None, "voided": m.voided_at is not None, "can_void": can_void and m.voided_at is None}


@router.post("/almacen/move")
def move(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Una lectura del QR = un movimiento. Cuerpo: {mode: salida|entrada, code, event_id?, qty?, reason?, plan_b?}.
    Equipo con serial: la entrada deduce sola el evento donde estaba. Por modelo/cantidad: siempre hace falta el evento y la cantidad (1 por defecto).
    Salir más de lo asignado NO se bloquea: se registra como extra y la respuesta trae `warning` («falta asignar…»). `reason` y `plan_b` son opcionales.
    Un equipo que vuelve con una novedad abierta queda «En novedad» (bloqueado para salir). Las novedades se reportan en la pestaña «Novedades» (con archivos obligatorios)."""
    mode = _guard(lambda: moves.clean_mode(data.get("mode")))
    code = almacen.normalize_scan(data.get("code"))
    if not code:
        _err("Ese texto no parece un código de almacén. Revisa que el lector esté en modo teclado.", 404)
    unit = db.query(InventoryUnit).filter(InventoryUnit.code == code).first()
    product = unit.product if unit is not None else db.query(InventoryProduct).filter(InventoryProduct.qr_code == code).first()
    if product is None:
        _err(f"El código {code} no existe en el almacén", 404)
    if unit is not None and unit.archived_at is not None:
        _err("Esa unidad está archivada: restáurala para moverla")
    if product.archived_at is not None:
        _err(f"«{product.name}» está archivado en el catálogo")
    tracking = product.tracking or "cantidad"
    event_id = data.get("event_id")
    if unit is not None and mode == "entrada" and unit.event_id:
        event_id = unit.event_id          # el equipo sabe dónde está
    try:
        event_id = int(event_id)
    except (TypeError, ValueError):
        _err("Elige el evento" if unit is None or mode == "salida" else "Ese equipo ya está en bodega: no tiene una salida pendiente.")
    event = _inventory_event(db, event_id, staff, lock=True)
    _guard(lambda: moves.check_event(event.status, event.archived_at is not None, mode))
    if unit is not None:
        unit = db.query(InventoryUnit).filter(InventoryUnit.id == unit.id).with_for_update().populate_existing().first()
        if mode == "entrada" and unit.event_id != event.id:
            _err("Ese equipo no salió a este evento" if unit.event_id else "Ese equipo ya está en bodega: no tiene una salida pendiente.")
    qty = 1 if unit is not None else _guard(lambda: moves.clean_move_qty(data.get("qty")))
    line = db.query(EventInventoryItem).filter(EventInventoryItem.event_id == event.id, EventInventoryItem.product_id == product.id).with_for_update().first()
    if line is None:
        if mode == "entrada":
            _err(f"«{product.name}» no tiene salidas en este evento")
        line = EventInventoryItem(event_id=event.id, product_id=product.id, qty_assigned=0, qty_out=0, qty_returned=0, qty_consumed=0)
        db.add(line)
        db.flush()
    consumable = bool(product.is_consumable)
    from app.routers.almacen_novedades import open_for_unit          # aquí y no arriba: ese módulo importa este (evita el ciclo)
    open_unit_nov = open_for_unit(db, unit.id) if unit is not None else None
    extra_applied, warning = 0, ""
    if mode == "salida":
        plan = _guard(lambda: moves.plan_exit(tracking=tracking, consumable=consumable, assigned=line.qty_assigned or 0, out=line.qty_out or 0, qty=qty,
                                              unit_status=unit.status if unit is not None else None, unit_event_name=unit.event.name if unit is not None and unit.event_id else None,
                                              reason=data.get("reason"), plan_b=bool(data.get("plan_b")), product_name=product.name,
                                              novelty_text=open_unit_nov.description[:80] if open_unit_nov is not None else ""))
        line.qty_out = (line.qty_out or 0) + plan.out_add
        line.qty_consumed = (line.qty_consumed or 0) + plan.consumed_add
        line.qty_assigned = (line.qty_assigned or 0) + plan.extra
        extra_applied, reason, plan_b, warning = plan.extra, plan.reason, plan.plan_b, plan.warning
        if unit is None:          # por modelo o cantidad: las piezas en novedad no cuentan como disponibles; se avisa, no se bloquea
            q_open = nov.open_qty_by_product(db, [product.id]).get(product.id, 0)
            if q_open:
                warning = (warning + " " if warning else "") + f"Ojo: hay {q_open} de «{product.name}» en novedad (no cuentan como disponibles); confirma que no son las que sacas."
        if unit is not None:
            unit.status, unit.event_id = "en_evento", event.id
    else:
        add = _guard(lambda: moves.plan_entry(tracking=tracking, consumable=consumable, out=line.qty_out or 0, returned=line.qty_returned or 0, consumed=line.qty_consumed or 0,
                                              qty=qty, unit_status=unit.status if unit is not None else None, product_name=product.name))
        line.qty_returned = (line.qty_returned or 0) + add
        reason, plan_b = None, False
        if unit is not None:
            unit.status, unit.event_id = ("novedad" if open_unit_nov is not None else "disponible"), None          # con novedad abierta no queda disponible
    _check_row(db, product, line)
    line.updated_by_id, line.updated_at = staff.id, utcnow()
    mv = InventoryMovement(event_id=event.id, product_id=product.id, unit_id=unit.id if unit is not None else None, kind=mode, qty=qty, extra=extra_applied,
                           reason=reason, is_plan_b=plan_b, created_by_id=staff.id)
    db.add(mv)
    db.flush()
    title = almacen.unit_title(product.name, unit.number) if unit is not None else product.name
    audit_actions.record(db, staff, "create", "almacen_movement", event.id, event.name, f"{mode}: {title}" + (f" x{qty}" if unit is None else "") + (" (Plan B)" if plan_b else "") + (" (con razón)" if reason else ""))
    db.commit()
    extras = db.query(func.coalesce(func.sum(InventoryMovement.extra), 0)).filter(InventoryMovement.event_id == event.id, InventoryMovement.product_id == product.id,
                                                                                InventoryMovement.kind == "salida", InventoryMovement.voided_at.is_(None)).scalar() or 0
    ln = _line_json(line, int(extras))
    verb = "Salió" if mode == "salida" else "Volvió"
    msg = f"{verb} {title}" + (f" ×{qty}" if unit is None else "") + f" · {event.name}"
    if mode == "salida":
        msg += f" · {ln['out']} de {ln['assigned']}"
    else:
        msg += f" · faltan {ln['pending']} por volver"
    return {"ok": True, "message": msg, "warning": warning, "movement": _movement_json(mv, True), "line": ln, "product": _product_json(product), "unit": _unit_json(unit, product) if unit is not None else None,
            "event": {"id": event.id, "name": event.name, "status": event.status}}


@router.post("/almacen/movements/{movement_id}/void")
def void_movement(movement_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Anula un movimiento (queda registrado quién y cuándo; nunca se borra). Solo si es el último de ese equipo o de ese producto en el evento."""
    mv = db.query(InventoryMovement).filter(InventoryMovement.id == movement_id).first()
    if mv is None:
        _err("El movimiento no existe", 404)
    event = _inventory_event(db, mv.event_id, staff, lock=True)
    if event.archived_at is not None:
        _err("El evento está archivado: restáuralo para anular movimientos")
    mv = db.query(InventoryMovement).filter(InventoryMovement.id == movement_id).with_for_update().populate_existing().first()
    product = mv.product
    later = db.query(InventoryMovement.id).filter(InventoryMovement.id > mv.id, InventoryMovement.voided_at.is_(None))
    later = later.filter(InventoryMovement.unit_id == mv.unit_id) if mv.unit_id else later.filter(InventoryMovement.event_id == mv.event_id, InventoryMovement.product_id == mv.product_id)
    plan = _guard(lambda: moves.plan_undo(kind=mv.kind, qty=mv.qty, extra=mv.extra or 0, consumable=bool(product.is_consumable), voided=mv.voided_at is not None,
                                           has_later=later.first() is not None))
    line = db.query(EventInventoryItem).filter(EventInventoryItem.event_id == mv.event_id, EventInventoryItem.product_id == mv.product_id).with_for_update().first()
    if line is None:
        _err("La línea de inventario del evento ya no existe", 404)
    line.qty_out = max((line.qty_out or 0) - plan.out_sub, 0)
    line.qty_consumed = max((line.qty_consumed or 0) - plan.consumed_sub, 0)
    line.qty_returned = max((line.qty_returned or 0) - plan.returned_sub, 0)
    line.qty_assigned = max((line.qty_assigned or 0) - plan.assigned_sub, 0)
    _check_row(db, product, line)
    if mv.unit_id:
        unit = db.query(InventoryUnit).filter(InventoryUnit.id == mv.unit_id).with_for_update().first()
        if mv.kind == "salida":
            unit.status, unit.event_id = "disponible", None
        else:
            linked = db.query(InventoryNovelty).filter(InventoryNovelty.movement_id == mv.id, InventoryNovelty.resolved_at.is_(None)).first()
            if unit.status != "disponible" and not (unit.status == "novedad" and linked is not None):
                db.rollback()
                _err("Ese equipo ya no está disponible: no se puede deshacer su entrada")
            unit.status, unit.event_id = "en_evento", mv.event_id
    if mv.kind == "entrada":          # la novedad reportada con esta entrada se anula con ella (queda resuelta, con la razón)
        for n in db.query(InventoryNovelty).filter(InventoryNovelty.movement_id == mv.id, InventoryNovelty.resolved_at.is_(None)).all():
            n.resolved_at, n.resolved_by_id, n.resolution = utcnow(), staff.id, "Anulada junto con la entrada que la reportó."
    mv.voided_at, mv.voided_by_id = utcnow(), staff.id
    line.updated_by_id, line.updated_at = staff.id, utcnow()
    title = almacen.unit_title(product.name, mv.unit.number) if mv.unit_id and mv.unit else product.name
    audit_actions.record(db, staff, "update", "almacen_movement_void", event.id, event.name, f"anulado {mv.kind}: {title}")
    db.commit()
    return {"ok": True, "message": f"Anulado: {mv.kind} de {title}"}


# ---------------------------------------------------------------- tablero del evento y alistado
def _board_data(db: Session, event: Event) -> dict:
    lines = inventory_svc.event_lines(db, event.id)
    extras = {pid: int(v or 0) for pid, v in db.query(InventoryMovement.product_id, func.sum(InventoryMovement.extra)).filter(
        InventoryMovement.event_id == event.id, InventoryMovement.kind == "salida", InventoryMovement.voided_at.is_(None)).group_by(InventoryMovement.product_id).all()}
    planb = {pid for (pid,) in db.query(InventoryMovement.product_id).filter(InventoryMovement.event_id == event.id, InventoryMovement.kind == "salida",
                                                                          InventoryMovement.voided_at.is_(None), InventoryMovement.is_plan_b.is_(True)).distinct().all()}
    checks = {c.row_key: {"done": bool(c.done), "notes": c.notes} for c in db.query(EventChecklistRow).filter(EventChecklistRow.event_id == event.id).all()}
    mapped, unmapped = [], []
    for l in lines:
        d = {"row_key": l.product.checklist_row, "assigned": l.qty_assigned or 0, "out": l.qty_out or 0, "returned": l.qty_returned or 0, "consumed": l.qty_consumed or 0,
             "extra": extras.get(l.product_id, 0), "plan_b": l.product_id in planb}
        if l.product.checklist_row:
            mapped.append(d)
        elif d["assigned"] or d["out"]:
            unmapped.append({"name": l.product.name, "assigned": d["assigned"], "out": d["out"], "returned": d["returned"]})
    board = moves.build_board(mapped, checks)
    outside = db.query(InventoryUnit).filter(InventoryUnit.event_id == event.id, InventoryUnit.status == "en_evento").order_by(InventoryUnit.product_id, InventoryUnit.number).all()
    mvs = db.query(InventoryMovement).filter(InventoryMovement.event_id == event.id).order_by(InventoryMovement.id.desc()).limit(60).all()
    last_by_key = {}
    for m in db.query(InventoryMovement).filter(InventoryMovement.event_id == event.id, InventoryMovement.voided_at.is_(None)).order_by(InventoryMovement.id).all():
        last_by_key[("u", m.unit_id) if m.unit_id else ("p", m.product_id)] = m.id
    return {"event": {"id": event.id, "name": event.name, "status": event.status, "code": event.event_code}, "board": board, "summary": moves.board_summary(board), "unmapped": unmapped,
            "outside": [{"id": u.id, "title": almacen.unit_title(u.product.name, u.number), "serial": u.code, "code": u.code} for u in outside],
            "movements": [_movement_json(m, last_by_key.get(("u", m.unit_id) if m.unit_id else ("p", m.product_id)) == m.id) for m in mvs]}


@router.get("/almacen/events/{event_id}/board")
def event_board(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    return _board_data(db, _inventory_event(db, event_id, staff))


@router.get("/almacen/events/{event_id}/checklist.xlsx")
def download_checklist(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Pieza 4: el checklist del evento en Excel, idéntico al formato GEYL. «Responsable checklist» = quien lo descarga (almacén). Mismos permisos y misma tabla que la pantalla."""
    from fastapi.responses import Response

    from app import almacen_xlsx, event_contacts, heavy
    event = _inventory_event(db, event_id, staff)
    contacts = event_contacts.list_for(db, event.id)
    main = next((c for c in contacts if c["is_primary"]), contacts[0] if contacts else None)
    contact = main["name"] if main else (event.tenant.contact_name if event.tenant is not None else None)
    info = almacen_xlsx.event_info(event, event.tenant.name if event.tenant is not None else "", contact, (event.coordinator.full_name or event.coordinator.username) if event.coordinator is not None else "")
    data = almacen_xlsx.build(info, _board_data(db, event)["board"], staff.full_name or staff.username)
    audit_actions.record(db, staff, "export", "almacen_checklist", event.id, event.name)
    db.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": heavy.content_disposition(heavy.event_report_filename(event, "Checklist GEYL")), "Cache-Control": "no-store"})


@router.put("/almacen/events/{event_id}/checklist/{row_key}")
def update_checklist_row(event_id: int, row_key: str, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Casilla «OK S/N» (alistado) y observación de UNA fila del checklist (incluye las 5 de verificación manual)."""
    key = _guard(lambda: moves.clean_row_key(row_key))
    upd = _guard(lambda: moves.clean_check_update(data))
    event = _inventory_event(db, event_id, staff, lock=True)
    if event.archived_at is not None:
        _err("El evento está archivado: restáuralo para editar su checklist")
    row = db.query(EventChecklistRow).filter(EventChecklistRow.event_id == event.id, EventChecklistRow.row_key == key).first()
    if row is None:
        row = EventChecklistRow(event_id=event.id, row_key=key, done=False)
        db.add(row)
    if "done" in upd:
        row.done = upd["done"]
    if "notes" in upd:
        row.notes = upd["notes"]
    row.updated_by_id, row.updated_at = staff.id, utcnow()
    audit_actions.record(db, staff, "update", "almacen_checklist_row", event.id, event.name, key + (" ✓" if row.done else ""))
    db.commit()
    return {"key": key, "done": bool(row.done), "notes": row.notes or ""}
