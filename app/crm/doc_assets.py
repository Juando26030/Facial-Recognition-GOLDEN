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
    return hashlib.sha1("|".join(keys).encode(), usedforsecurity=False).hexdigest()[:6] if keys else ""


def copy_layout(src: CrmDocTemplate, dst: CrmDocTemplate) -> Optional[dict]:
    """Copia el diseño de `src` para `dst`: cada logo, imagen y PDF se duplica en la carpeta de `dst` (así borrar o cambiar uno no afecta al otro). Devuelve el diseño limpio SIN guardarlo
    (quien llama lo guarda); None si `src` usa la plantilla sencilla. Un bloque o elemento cuyo archivo ya no existe no se copia. Sirve para el diseño por bloques (v1) y el libre (v2)."""
    import json
    if not src.layout_json:
        return None
    layout = json.loads(src.layout_json)
    st = get_storage()
    prefix = f"{ql.ASSET_PREFIX}{src.id}/"

    def copy(key: str) -> Optional[str]:
        if not key.startswith(prefix) or not st.exists(key):
            return None
        new_key = f"{ql.ASSET_PREFIX}{dst.id}/{uuid.uuid4().hex}.{key.rsplit('.', 1)[-1]}"
        st.put(new_key, st.get(key))
        return new_key
    remap_assets(layout, copy)
    return ql.clean_layout(layout, dst.id)


def remap_assets(layout: dict, new_key) -> None:
    """Cambia la clave de cada archivo del diseño por `new_key(clave)`; si devuelve None, ese bloque o elemento se quita (su archivo ya no existe)."""
    from app.crm import quote_free
    for lst in quote_free.asset_lists(layout):
        keep = []
        for item in lst:
            key = item.get("asset") if isinstance(item, dict) else None
            if key is None or (key == "" and item.get("type") not in ("logo", "image", "pdf")):
                keep.append(item)
                continue
            nk = new_key(key) if key else None
            if nk:
                item["asset"] = nk
                keep.append(item)
        lst[:] = keep


MAX_EXPORT_BYTES = 30 * 1024 * 1024


def export_package(template: CrmDocTemplate, layout: dict) -> dict:
    """La plantilla en un archivo que se puede importar en otra plantilla o en otro entorno (staging → producción): el diseño y sus imágenes y PDF dentro, en base64."""
    import base64
    st = get_storage()
    files: Dict[str, str] = {}
    total = 0
    for key in ql.used_assets(layout):
        if key in files:
            continue
        try:
            raw = st.get(key)
        except Exception:          # noqa: BLE001 - un archivo que ya no está: el bloque se quita al importar
            log.warning("falta un archivo al exportar la plantilla", exc_info=True)
            continue
        total += len(raw)
        if total > MAX_EXPORT_BYTES:
            raise CrmError("La plantilla pesa más de 30 MB con sus imágenes y PDF: usa archivos más livianos para poder exportarla.")
        files[key] = base64.b64encode(raw).decode("ascii")
    return {"formato": "golden-plantilla-pdf", "version": 2, "kind": template.kind, "name": template.name, "layout": layout, "archivos": files}


def import_package(template: CrmDocTemplate, raw: bytes) -> dict:
    """Lee un archivo exportado y guarda sus imágenes y PDF en la carpeta de `template` (cada uno se revisa por su contenido, igual que al subirlo). Devuelve el diseño limpio SIN guardarlo."""
    import base64
    import json
    try:
        pkg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CrmError("El archivo no es una plantilla exportada desde GoldenWeb.")
    if not isinstance(pkg, dict) or pkg.get("formato") != "golden-plantilla-pdf" or not isinstance(pkg.get("layout"), dict):
        raise CrmError("El archivo no es una plantilla exportada desde GoldenWeb.")
    files = pkg.get("archivos") if isinstance(pkg.get("archivos"), dict) else {}
    layout = pkg["layout"]
    done: Dict[str, str] = {}

    def put(key: str) -> Optional[str]:
        if key in done:
            return done[key]
        data = files.get(key)
        if not isinstance(data, str):
            return None
        try:
            blob = base64.b64decode(data, validate=True)
        except ValueError:
            return None
        done[key] = save_template_asset(None, template, blob)["key"]          # valida que sea una imagen o un PDF de verdad
        return done[key]
    remap_assets(layout, put)
    return {"layout": ql.clean_layout(layout, template.id), "kind": pkg.get("kind") if pkg.get("kind") in ("quote", "proforma") else "", "name": str(pkg.get("name") or "")[:80]}
