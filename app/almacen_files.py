"""Almacén · Pieza 3: archivos adjuntos de una novedad (al reportarla y al resolverla). Lógica pura, sin base de datos ni almacenamiento.

Se aceptan fotos (se re-codifican a JPEG, como las de los elementos), PDF y videos cortos MP4/MOV. El tipo se comprueba por el CONTENIDO (no solo por la extensión). Límites: hasta 8 archivos,
10 MB cada uno y 25 MB en total por envío (Cloud Run recibe como máximo 32 MB por petición)."""
import os
import re
from typing import List, Tuple

from app import almacen_photos
from app.almacen import AlmacenError

MAX_FILES = 8
MAX_FILE_BYTES = 10_000_000
MAX_TOTAL_BYTES = 25_000_000
ACCEPT = "image/*,application/pdf,video/mp4,video/quicktime"          # para el <input type="file">
_VIDEO = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime"}
_NAME_BAD = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]")


def safe_name(filename: str) -> str:
    base = _NAME_BAD.sub("", os.path.basename(str(filename or "")).strip())[:120]
    return base or "archivo"


def classify(filename: str, content: bytes) -> dict:
    """Un archivo → {name, kind: image|pdf|video, ext, content_type, data}. Lanza AlmacenError con el mensaje para el usuario."""
    name = safe_name(filename)
    ext = os.path.splitext(name)[1].lower()
    if not content:
        raise AlmacenError(f"«{name}» está vacío.")
    if len(content) > MAX_FILE_BYTES:
        raise AlmacenError(f"«{name}» pesa más de {MAX_FILE_BYTES // 1_000_000} MB.")
    if ext in almacen_photos.PHOTO_EXT:
        return {"name": name, "kind": "image", "ext": ".jpg", "content_type": "image/jpeg", "data": almacen_photos.process_photo(content, name)}
    if ext == ".pdf":
        if not content.startswith(b"%PDF"):
            raise AlmacenError(f"«{name}» no es un PDF válido.")
        return {"name": name, "kind": "pdf", "ext": ".pdf", "content_type": "application/pdf", "data": content}
    if ext in _VIDEO:
        if content[4:8] != b"ftyp":
            raise AlmacenError(f"«{name}» no es un video MP4 o MOV válido.")
        return {"name": name, "kind": "video", "ext": ".mp4" if _VIDEO[ext] == "video/mp4" else ".mov", "content_type": _VIDEO[ext], "data": content}
    raise AlmacenError(f"«{name}»: usa fotos (JPG, PNG, WEBP, GIF), PDF o video MP4/MOV.")


def classify_all(files: List[Tuple[str, bytes]], *, required: bool, what: str) -> List[dict]:
    """Todos los archivos de un envío. `required`: debe haber al menos uno (`what` = «la foto o el archivo del daño», para el mensaje)."""
    files = [(n, c) for n, c in files if n or c]
    if required and not files:
        raise AlmacenError(f"Adjunta al menos un archivo: {what}.")
    if len(files) > MAX_FILES:
        raise AlmacenError(f"Se pueden adjuntar hasta {MAX_FILES} archivos a la vez.")
    if sum(len(c) for _, c in files) > MAX_TOTAL_BYTES:
        raise AlmacenError(f"Los archivos pesan más de {MAX_TOTAL_BYTES // 1_000_000} MB en total: envía menos a la vez.")
    return [classify(n, c) for n, c in files]
