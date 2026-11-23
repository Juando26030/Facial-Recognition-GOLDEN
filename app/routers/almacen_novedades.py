"""Almacén, Pieza 3: novedades (daños o problemas de un elemento) y bloqueo hasta que almacén lo deje «disponible». Reglas puras en app/almacen_novelties.py; plan en docs/ALMACEN.md.

Reportar una novedad (por QR; la foto, PDF o video del daño es OBLIGATORIO y se pueden adjuntar varios archivos), verla con sus archivos (listar abiertas / resueltas) y resolverla con una nota y
los archivos de cómo quedó (también obligatorios). Todo es multipart (Form + File), nunca JSON.
Un equipo con serial «En novedad» no sale a un evento (app/almacen_moves.py: plan_exit). Mismos permisos que el resto de Almacén: almacén, admin y super_admin. Todo responde 404 con ALMACEN_ENABLED apagado.
"""
import unicodedata
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import almacen, almacen_files, almacen_novelties as nov, audit_actions
from app.database import get_db
from app.models import InventoryNovelty, InventoryNoveltyFile, InventoryProduct, InventoryUnit, StaffUser
from app.routers.almacen import MANAGER, _err, _gate, _wrap
from app.storage import get_storage, key_of
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


def _file_json(n: InventoryNovelty, f: InventoryNoveltyFile) -> dict:
    return {"id": f.id, "kind": f.kind, "name": f.filename, "type": f.content_type, "size": f.size, "is_image": f.content_type.startswith("image/"),
            "url": f"/api/almacen/novelties/{n.id}/files/{f.id}"}


def novelty_json(n: InventoryNovelty, who: dict) -> dict:
    files = [_file_json(n, f) for f in sorted(n.files, key=lambda x: x.id)]
    if n.photo_key:          # foto de la versión anterior (antes de los archivos adjuntos)
        files.insert(0, {"id": 0, "kind": "reporte", "name": "Foto del daño", "type": "image/jpeg", "size": 0, "is_image": True, "url": f"/api/almacen/novelties/{n.id}/photo"})
    return {"id": n.id, "product_id": n.product_id, "product_name": n.product.name, "title": _title(n), "unit_id": n.unit_id, "code": n.unit.code if n.unit_id and n.unit else n.product.qr_code,
            "serial": n.unit.code if n.unit_id and n.unit else None, "qty": n.qty, "description": n.description, "event_name": n.event.name if n.event_id and n.event else None,
            "files": files, "created_by": who.get(n.created_by_id), "created_at": to_local(n.created_at).strftime("%d/%m/%Y %H:%M") if n.created_at else None,
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



# ---------------------------------------------------------------- archivos
def _store(db: Session, staff: StaffUser, n: InventoryNovelty, kind: str, ready: List[dict]) -> List[str]:
    """Guarda los archivos ya validados y crea sus filas. Devuelve las claves (para borrarlas si la transacción falla)."""
    keys: List[str] = []
    for f in ready:
        key = key_of("almacen", "novedades", f"{uuid.uuid4().hex}{f['ext']}")
        get_storage().put(key, f["data"])
        keys.append(key)
        db.add(InventoryNoveltyFile(novelty_id=n.id, kind=kind, file_key=key, filename=f["name"], content_type=f["content_type"], size=len(f["data"]), created_by_id=staff.id))
    db.flush()
    return keys


def _drop(keys: List[str]) -> None:
    for k in keys:
        try:
            get_storage().delete(k)
        except Exception:          # limpieza de mejor esfuerzo: un archivo huérfano no daña nada
            pass


def _commit_with_files(db: Session, keys: List[str]) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        _drop(keys)
        raise


# ---------------------------------------------------------------- reportar
@router.post("/almacen/novelties")
def report_novelty(code: str = Form(""), description: str = Form(""), qty: Optional[int] = Form(None), files: Optional[List[UploadFile]] = File(None),
                   db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Reporta una novedad escaneando o escribiendo el código del elemento. Formulario: code, description, qty? y files (≥1 archivo OBLIGATORIO: foto, PDF o video del daño).
    Un equipo con serial queda «En novedad» y bloqueado para salir a un evento."""
    norm_code = almacen.normalize_scan(code)
    if not norm_code:
        _err("Escanea o escribe el código del elemento.")
    text = _wrap(lambda: nov.clean_text(description, "Qué pasó"))
    ready = _wrap(lambda: almacen_files.classify_all(_read_sync(files), required=True, what="la foto (o el archivo) del daño"))
    unit = db.query(InventoryUnit).filter(InventoryUnit.code == norm_code).with_for_update().first()
    product = unit.product if unit is not None else db.query(InventoryProduct).filter(InventoryProduct.qr_code == norm_code).with_for_update().first()
    if product is None:
        _err(f"El código {norm_code} no existe en el almacén", 404)
    if unit is not None and unit.archived_at is not None:
        _err("Esa unidad está archivada: restáurala para reportarle una novedad")
    if product.archived_at is not None:
        _err(f"«{product.name}» está archivado en el catálogo")
    open_qty = nov.open_qty_by_product(db, [product.id]).get(product.id, 0)
    plan = _wrap(lambda: nov.plan_open(tracking=product.tracking or "cantidad", consumable=bool(product.is_consumable), unit_status=unit.status if unit is not None else None,
                                       qty=qty, open_qty=open_qty, stock=product.qty_total, product_name=product.name))
    n = open_novelty_row(db, staff, product, unit, plan, text, event_id=unit.event_id if unit is not None else None)
    keys = _store(db, staff, n, "reporte", ready)
    _commit_with_files(db, keys)
    return {"ok": True, "message": f"Novedad registrada: {_title(n)}" + (" · queda bloqueado hasta que Almacén lo deje disponible" if unit is not None and plan.unit_status else ""),
            "novelty": novelty_json(n, _who(db, [n.created_by_id]))}


def _read_sync(files: Optional[List[UploadFile]]):
    return [(f.filename or "", f.file.read(almacen_files.MAX_FILE_BYTES + 1)) for f in (files or [])]


# ---------------------------------------------------------------- ver un archivo
@router.get("/almacen/novelties/{novelty_id}/files/{file_id}")
def get_novelty_file(novelty_id: int, file_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    f = db.query(InventoryNoveltyFile).filter(InventoryNoveltyFile.id == file_id, InventoryNoveltyFile.novelty_id == novelty_id).first()
    if f is None or not get_storage().exists(f.file_key):
        _err("El archivo no existe", 404)
    return get_storage().response(f.file_key, filename=f.filename, media_type=f.content_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/almacen/novelties/{novelty_id}/photo")
def get_novelty_photo(novelty_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Foto de las novedades de la versión anterior (antes de los archivos adjuntos)."""
    n = _novelty(db, novelty_id)
    if not n.photo_key or not get_storage().exists(n.photo_key):
        _err("La novedad no tiene foto", 404)
    return get_storage().response(n.photo_key, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------- resolver
@router.post("/almacen/novelties/{novelty_id}/resolve")
def resolve_novelty(novelty_id: int, note: str = Form(""), files: Optional[List[UploadFile]] = File(None), db: Session = Depends(get_db), staff: StaffUser = Depends(MANAGER)):
    """Resolver = dejar el elemento «disponible» de nuevo. Formulario: note (qué se hizo) y files (≥1 archivo OBLIGATORIO: foto, PDF o video de cómo quedó).
    Queda quién y cuándo; la novedad y sus archivos no se borran."""
    text = _wrap(lambda: nov.clean_text(note, "Qué se hizo"))
    ready = _wrap(lambda: almacen_files.classify_all(_read_sync(files), required=True, what="la foto (o el archivo) de cómo quedó"))
    n = _novelty(db, novelty_id, lock=True)
    unit = db.query(InventoryUnit).filter(InventoryUnit.id == n.unit_id).with_for_update().first() if n.unit_id else None
    new_status = _wrap(lambda: nov.plan_resolve(resolved=n.resolved_at is not None, unit_status=unit.status if unit is not None else None))
    n.resolved_at, n.resolved_by_id, n.resolution = utcnow(), staff.id, text
    if unit is not None and new_status:
        unit.status = new_status
    keys = _store(db, staff, n, "resolucion", ready)
    audit_actions.record(db, staff, "update", "almacen_novelty_resolve", n.id, _title(n), text[:120])
    _commit_with_files(db, keys)
    db.refresh(n)
    return {"ok": True, "message": f"{_title(n)}: novedad resuelta" + (" · ya está disponible" if unit is not None and new_status else ""), "novelty": novelty_json(n, _who(db, [n.created_by_id, n.resolved_by_id]))}
