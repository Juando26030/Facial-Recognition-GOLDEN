"""Archivos del diseño de PDF: logo e imágenes de una plantilla, PDF a insertar y foto de cada producto. Guardan y leen con `get_storage()` (nunca disco directo); validan el contenido real del
archivo (no el nombre) con app/crm/quote_layout.py. Sin commit propio: quien llama confirma."""
import logging
import uuid
from typing import Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.crm import quote_layout as ql
from app.crm.errors import CrmError
from app.models import CrmDocTemplate, CrmProduct
from app.storage import get_storage

log = logging.getLogger("golden.crm_assets")


def _kind_and_ext(raw: bytes) -> tuple:
    if raw.lstrip()[:5] == b"%PDF-":
        return "pdf", "pdf", ql.check_pdf(raw)
    info = ql.check_image(raw)
    return "image", info["ext"], info


def save_template_asset(db: Session, template: CrmDocTemplate, raw: bytes, filename: str = "") -> dict:
    kind, ext, info = _kind_and_ext(raw)
    key = f"{ql.ASSET_PREFIX}{template.id}/{uuid.uuid4().hex}.{ext}"
    get_storage().put(key, raw)
    return {"key": key, "kind": kind, "name": (filename or "")[:120], **info}


def save_product_image(db: Session, product: CrmProduct, raw: bytes) -> str:
    info = ql.check_image(raw)
    key = f"{ql.PRODUCT_IMAGE_PREFIX}{product.id}/{uuid.uuid4().hex}.{info['ext']}"
    old = product.image_key
    get_storage().put(key, raw)
    product.image_key = key
    if old:
        _drop(old)
    return key


def clear_product_image(product: CrmProduct) -> None:
    if product.image_key:
        _drop(product.image_key)
        product.image_key = None


def _drop(key: str) -> None:
    try:
        get_storage().delete(key)
    except Exception:          # noqa: BLE001 - un archivo suelto no debe frenar el cambio
        log.warning("no se pudo borrar un archivo del diseño de PDF", exc_info=True)


def product_images(db: Session, product_ids: Iterable[Optional[int]]) -> Dict[int, bytes]:
    """Fotos de los productos usados en las líneas ({id: bytes}); las que faltan en el almacén se omiten (la celda queda vacía)."""
    ids = sorted({i for i in product_ids if i})
    out: Dict[int, bytes] = {}
    if not ids:
        return out
    st = get_storage()
    for pid, key in db.query(CrmProduct.id, CrmProduct.image_key).filter(CrmProduct.id.in_(ids), CrmProduct.image_key.isnot(None)).all():
        try:
            out[pid] = st.get(key)
        except Exception:          # noqa: BLE001
            log.warning("falta la foto de un producto", exc_info=True)
    return out


def images_signature(db: Session, product_ids: Iterable[Optional[int]]) -> str:
    """Cambia cuando se sube otra foto a un producto de la cotización: así el PDF guardado se regenera."""
    ids = sorted({i for i in product_ids if i})
    if not ids:
        return ""
    keys = [k for (k,) in db.query(CrmProduct.image_key).filter(CrmProduct.id.in_(ids), CrmProduct.image_key.isnot(None)).order_by(CrmProduct.id).all()]
    import hashlib
    return hashlib.sha1("|".join(keys).encode()).hexdigest()[:6] if keys else ""
