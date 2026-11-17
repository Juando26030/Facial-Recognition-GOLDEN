"""Almacén: fotos de los elementos (al crearlos) y de las novedades por daño (Pieza 3).

Se valida con `safe_limits.check_design_image` (tamaño, píxeles, formato real) y se RE-CODIFICA a JPEG de lado mayor 1280 px: pesa poco, queda sin los metadatos del celular (ubicación GPS)
y se ve derecha aunque el teléfono la guardara girada. Las claves van por app/storage.py (nunca `open()` sobre `data/`).
"""
import io
import os
import uuid

from PIL import Image, ImageOps

from app import safe_limits
from app.almacen import AlmacenError

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_PHOTO_BYTES = 8_000_000          # una foto de celular pesa 2–6 MB
MAX_SIDE = 1280
JPEG_QUALITY = 82


def process_photo(content: bytes, filename: str) -> bytes:
    """Foto subida → JPEG listo para guardar. Lanza AlmacenError con el mensaje para el usuario."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in PHOTO_EXT:
        raise AlmacenError("Usa una foto en formato JPG, PNG, WEBP o GIF.")
    try:
        safe_limits.check_design_image(content, ext, max_bytes=MAX_PHOTO_BYTES)
    except safe_limits.LimitError as exc:
        raise AlmacenError(exc.message)
    try:
        with Image.open(io.BytesIO(content)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except Exception:  # noqa: BLE001 — cualquier fallo al leerla: no es una foto utilizable
        raise AlmacenError("No se pudo leer la foto: prueba con otra.")
    return out.getvalue()


def new_photo_key(folder: str) -> str:
    """Clave nueva (única) para una foto: almacen/<carpeta>/<uuid>.jpg."""
    from app.storage import key_of
    return key_of("almacen", folder, f"{uuid.uuid4().hex}.jpg")
