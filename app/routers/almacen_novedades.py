"""Almacén, Pieza 3: novedades (daños o problemas de un elemento) y bloqueo hasta que almacén lo deje «disponible». Reglas puras en app/almacen_novelties.py; plan en docs/ALMACEN.md.

Reportar una novedad (por QR, o al devolver con «vuelve con novedad» en app/routers/almacen.py), adjuntarle la foto del daño, listarlas (abiertas / resueltas) y resolverlas con una nota.
Un equipo con serial «En novedad» no sale a un evento (app/almacen_moves.py: plan_exit). Mismos permisos que el resto de Almacén: almacén, admin y super_admin. Todo responde 404 con ALMACEN_ENABLED apagado.
"""
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import almacen, almacen_novelties as nov, almacen_photos, audit_actions
from app.database import get_db
from app.models import InventoryNovelty, InventoryProduct, InventoryUnit, StaffUser
from app.routers.almacen import MANAGER, _err, _gate, _wrap
from app.storage import get_storage
from app.timeutil import to_local, utcnow

router = APIRouter(dependencies=[Depends(_gate)])
MAX_LIST = 300


def _norm(text) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "").lower()) if unicodedata.category(c) != "Mn")


def _novelty(db: Session, novelty_id: int, *, lock: bool = False) -> InventoryNovelty:
    q = db.query(InventoryNovelty).filter(InventoryNovelty.id == novelty_id)
    if lock:
        q = q.with_for_update()
    n = q.first()
    if n is None:
        _err("La novedad no existe", 404)
    return n


def _title(n: InventoryNovelty) -> str:
    return almacen.unit_title(n.product.name, n.unit.number) if n.unit_id and n.unit else n.product.name


def _who(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: (u.full_name or u.username) for u in db.query(StaffUser).filter(StaffUser.id.in_(ids)).all()}


def novelty_json(n: InventoryNovelty, who: dict) -> dict:
    return {"id": n.id, "product_id": n.product_id, "product_name": n.product.name, "title": _title(n), "unit_id": n.unit_id, "code": n.unit.code if n.unit_id and n.unit else n.product.qr_code,
            "serial": n.unit.serial if n.unit_id and n.unit else None, "qty": n.qty, "description": n.description, "event_name": n.event.name if n.event_id and n.event else None,
            "has_photo": bool(n.photo_key), "photo_url": f"/api/almacen/novelties/{n.id}/photo?v={(n.photo_key or '')[-12:-4]}" if n.photo_key else None,
            "created_by": who.get(n.created_by_id), "created_at": to_local(n.created_at).strftime("%d/%m/%Y %H:%M") if n.created_at else None,
            "resolved": n.resolved_at is not None, "resolved_by": who.get(n.resolved_by_id), "resolution": n.resolution,
            "resolved_at": to_local(n.resolved_at).strftime("%d/%m/%Y %H:%M") if n.resolved_at else None}


def open_novelty_row(db: Session, staff: StaffUser, product: InventoryProduct, unit: Optional[InventoryUnit], plan: "nov.NoveltyPlan", text: str, *, event_id=None, movement_id=None) -> InventoryNovelty:
    """Crea la novedad y deja el equipo como dice el plan. La transacción la cierra quien llama (aquí solo flush)."""
    n = InventoryNovelty(product_id=product.id, unit_id=unit.id if unit is not None else None, qty=plan.qty, description=text, event_id=event_id, movement_id=movement_id, created_by_id=staff.id)
    db.add(n)
    if unit is not None and plan.unit_status:
        unit.status = plan.unit_status
    db.flush()
    audit_actions.record(db, staff, "create", "almacen_novelty", n.id, _title(n), text[:120])
    return n


def open_for_unit(db: Session, unit_id: int) -> Optional[InventoryNovelty]:
    return db.query(InventoryNovelty).filter(InventoryNovelty.unit_id == unit_id, InventoryNovelty.resolved_at.is_(None)).first()


# ---------------------------------------------------------------- listar
@router.get("/almacen/novelties")
def list_novelties(state: str = "abiertas", q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Novedades más recientes primero. `state`: abiertas | resueltas | todas. `q`: busca en el nombre del elemento, el código, el serial o el texto."""
    query = db.query(InventoryNovelty).join(InventoryProduct, InventoryProduct.id == InventoryNovelty.product_id)
    if state == "abiertas":
        query = query.filter(InventoryNovelty.resolved_at.is_(None))
    elif state == "resueltas":
        query = query.filter(InventoryNovelty.resolved_at.isnot(None))
    elif state != "todas":
        _err("El filtro debe ser abiertas, resueltas o todas")
    rows = query.order_by(InventoryNovelty.id.desc()).limit(MAX_LIST).all()
    term = _norm(q).strip()
    who = _who(db, [i for n in rows for i in (n.created_by_id, n.resolved_by_id)])
    items = [novelty_json(n, who) for n in rows]
    if term:
        items = [i for i in items if term in _norm(" ".join(str(i.get(k) or "") for k in ("title", "code", "serial", "description", "event_name")))]
    open_count = db.query(InventoryNovelty).filter(InventoryNovelty.resolved_at.is_(None)).count()
    return {"novelties": items, "open_count": open_count}



# ---------------------------------------------------------------- reportar
@router.post("/almacen/novelties")
def report_novelty(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Reporta una novedad escaneando o escribiendo el código del elemento. Cuerpo: {code, description, qty?}. Un equipo con serial queda «En novedad» y bloqueado para salir a un evento."""
    code = almacen.normalize_scan(data.get("code"))
    if not code:
        _err("Escanea o escribe el código del elemento.")
    text = _wrap(lambda: nov.clean_text(data.get("description"), "Qué pasó"))
    unit = db.query(InventoryUnit).filter(InventoryUnit.code == code).with_for_update().first()
    product = unit.product if unit is not None else db.query(InventoryProduct).filter(InventoryProduct.qr_code == code).with_for_update().first()
    if product is None:
        _err(f"El código {code} no existe en el almacén", 404)
    if unit is not None and unit.archived_at is not None:
        _err("Esa unidad está archivada: restáurala para reportarle una novedad")
    if product.archived_at is not None:
        _err(f"«{product.name}» está archivado en el catálogo")
    open_qty = nov.open_qty_by_product(db, [product.id]).get(product.id, 0)
    plan = _wrap(lambda: nov.plan_open(tracking=product.tracking or "cantidad", consumable=bool(product.is_consumable), unit_status=unit.status if unit is not None else None,
                                       qty=data.get("qty"), open_qty=open_qty, stock=product.qty_total, product_name=product.name))
    n = open_novelty_row(db, staff, product, unit, plan, text, event_id=unit.event_id if unit is not None else None)
    db.commit()
    who = _who(db, [n.created_by_id])
    return {"ok": True, "message": f"Novedad registrada: {_title(n)}" + (" · queda bloqueado hasta que Almacén lo deje disponible" if unit is not None and plan.unit_status else ""), "novelty": novelty_json(n, who)}


# ---------------------------------------------------------------- foto del daño
@router.post("/almacen/novelties/{novelty_id}/photo")
def upload_novelty_photo(novelty_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    n = _novelty(db, novelty_id, lock=True)
    content = file.file.read(almacen_photos.MAX_PHOTO_BYTES + 1)
    if not content:
        _err("La foto está vacía")
    if len(content) > almacen_photos.MAX_PHOTO_BYTES:
        _err("La foto pesa más de 8 MB")
    jpeg = _wrap(lambda: almacen_photos.process_photo(content, file.filename or ""))
    key = almacen_photos.new_photo_key("novedades")
    get_storage().put(key, jpeg)
    old, n.photo_key = n.photo_key, key
    audit_actions.record(db, staff, "update", "almacen_novelty_photo", n.id, _title(n))
    db.commit()
    if old:
        get_storage().delete(old)
    return novelty_json(n, _who(db, [n.created_by_id, n.resolved_by_id]))


@router.get("/almacen/novelties/{novelty_id}/photo")
def get_novelty_photo(novelty_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    n = _novelty(db, novelty_id)
    if not n.photo_key or not get_storage().exists(n.photo_key):
        _err("La novedad no tiene foto", 404)
    return get_storage().response(n.photo_key, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------- resolver
@router.post("/almacen/novelties/{novelty_id}/resolve")
def resolve_novelty(novelty_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Resolver = dejar el elemento «disponible» de nuevo. Cuerpo: {note} (qué se hizo). Queda quién y cuándo; la novedad no se borra."""
    note = _wrap(lambda: nov.clean_text(data.get("note"), "Qué se hizo"))
    n = _novelty(db, novelty_id, lock=True)
    unit = db.query(InventoryUnit).filter(InventoryUnit.id == n.unit_id).with_for_update().first() if n.unit_id else None
    new_status = _wrap(lambda: nov.plan_resolve(resolved=n.resolved_at is not None, unit_status=unit.status if unit is not None else None))
    n.resolved_at, n.resolved_by_id, n.resolution = utcnow(), staff.id, note
    if unit is not None and new_status:
        unit.status = new_status
    audit_actions.record(db, staff, "update", "almacen_novelty_resolve", n.id, _title(n), note[:120])
    db.commit()
    return {"ok": True, "message": f"{_title(n)}: novedad resuelta" + (" · ya está disponible" if unit is not None and new_status else ""), "novelty": novelty_json(n, _who(db, [n.created_by_id, n.resolved_by_id]))}
