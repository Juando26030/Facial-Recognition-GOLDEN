"""Almacén (bodega), Pieza 1: control de los elementos del catálogo (con serial / por modelo / por cantidad), unidades con serial, códigos QR, etiquetas y búsqueda por lectura de QR.

Rama almacen/p1-catalogo; plan en claude/58_PLAN_ALMACEN. Se apoya en el catálogo de inventario (app/routers/inventory.py): los productos se crean y se archivan allá; aquí se les agrega cómo se controlan y
sus unidades. Todo responde 404 mientras `ALMACEN_ENABLED` esté apagado (app/almacen.py).
Permisos: almacén, admin y super_admin (los mismos que administran el catálogo). Salidas, entradas y novedades llegan en las Piezas 2 y 3.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import almacen, audit_actions
from app.auth import require_role_or_any
from app.database import get_db
from app.models import InventoryProduct, InventoryUnit, StaffUser
from app.timeutil import utcnow


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
            "units": units, "archived": p.archived_at is not None}


def _unit_json(u: InventoryUnit, product: Optional[InventoryProduct] = None) -> dict:
    p = product or u.product
    return {"id": u.id, "product_id": u.product_id, "product_name": p.name, "number": u.number, "title": almacen.unit_title(p.name, u.number), "code": u.code, "serial": u.serial,
            "status": u.status, "status_label": almacen.UNIT_STATUS_LABEL.get(u.status, u.status), "archived": u.archived_at is not None}


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
    return {"units": [_unit_json(u) for u in rows]}


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
    if serial and db.query(InventoryUnit.id).filter(InventoryUnit.product_id == p.id, InventoryUnit.archived_at.is_(None), func.lower(InventoryUnit.serial) == serial.lower()).first():
        _err(f"Ya existe una unidad de «{p.name}» con el serial {serial}", 409)
    last = db.query(func.max(InventoryUnit.number)).filter(InventoryUnit.product_id == p.id).scalar() or 0          # incluye archivadas: un número nunca se reutiliza
    taken: set = set()
    created = []
    for i in range(count):
        u = InventoryUnit(product_id=p.id, number=last + i + 1, code=_free_code(db, taken), serial=serial if i == 0 else None, status="disponible", created_by_id=staff.id)
        db.add(u)
        created.append(u)
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
        if serial and db.query(InventoryUnit.id).filter(InventoryUnit.product_id == u.product_id, InventoryUnit.id != u.id, InventoryUnit.archived_at.is_(None),
                                                         func.lower(InventoryUnit.serial) == serial.lower()).first():
            _err(f"Ya existe una unidad de «{u.product.name}» con el serial {serial}", 409)
        u.serial = serial
    audit_actions.record(db, staff, "update", "almacen_unit", u.id, almacen.unit_title(u.product.name, u.number))
    db.commit()
    return _unit_json(u)


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
    """Lo que escribe el lector USB → qué es. Pieza 1: solo identifica; las salidas y entradas llegan en la Pieza 2."""
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
            out.append({"code": u.code, "title": almacen.unit_title(u.product.name, u.number), "subtitle": (f"Serial {u.serial}" if u.serial else "")})
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
