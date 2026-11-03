"""Topes contra «bombas» de descompresión (0C, B3 y B-N1): ZIP e imágenes.

Todo configurable por variables de entorno (ver .env.example). Las funciones lanzan `LimitError`
con un mensaje listo para mostrar en español; los routers lo convierten en 400/413.
"""
import io
import os
import zipfile

from PIL import Image


class LimitError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except ValueError:
        return default


def zip_max_entries() -> int:
    return _int_env("ZIP_MAX_ENTRIES", 20000)


def zip_max_total_mb() -> int:
    return _int_env("ZIP_MAX_UNCOMPRESSED_MB", 4096)


def zip_max_entry_mb() -> int:
    return _int_env("ZIP_MAX_ENTRY_MB", 50)


def zip_max_ratio() -> int:
    return _int_env("ZIP_MAX_RATIO", 100)


def image_max_pixels() -> int:
    return _int_env("IMAGE_MAX_PIXELS", 50_000_000)


# Pillow avisa al pasar de MAX_IMAGE_PIXELS y falla al pasar del doble: queda como segunda red en cualquier Image.open.
Image.MAX_IMAGE_PIXELS = image_max_pixels()


def check_zip(zf: zipfile.ZipFile) -> list:
    """Revisa el índice del ZIP SIN descomprimir: nº de entradas, tamaño total y por entrada, y razón de compresión."""
    infos = zf.infolist()
    if len(infos) > zip_max_entries():
        raise LimitError(f"El ZIP trae demasiados archivos ({len(infos)}); el máximo es {zip_max_entries()}.")
    entry_cap, total_cap, total = zip_max_entry_mb() * 1024 * 1024, zip_max_total_mb() * 1024 * 1024, 0
    for i in infos:
        if i.is_dir():
            continue
        total += i.file_size
        if i.file_size > entry_cap:
            raise LimitError(f"El archivo «{os.path.basename(i.filename)[:60]}» del ZIP pesa más de {zip_max_entry_mb()} MB descomprimido.", 413)
        if total > total_cap:
            raise LimitError(f"El ZIP pesa más de {zip_max_total_mb()} MB una vez descomprimido.", 413)
        if i.compress_size and i.file_size > 1_000_000 and i.file_size / i.compress_size > zip_max_ratio():
            raise LimitError("El ZIP está comprimido de forma sospechosa (posible bomba de descompresión) y no se acepta.")
    return infos


def open_checked_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except (zipfile.BadZipFile, ValueError, OSError):
        raise LimitError("El archivo ZIP no es válido o está dañado.")
    check_zip(zf)
    return zf


def read_entry(zf: zipfile.ZipFile, name: str) -> bytes:
    """Lee una entrada con tope real (no confía en el tamaño declarado en el encabezado)."""
    cap = zip_max_entry_mb() * 1024 * 1024
    with zf.open(name) as f:
        data = f.read(cap + 1)
    if len(data) > cap:
        raise LimitError(f"El archivo «{os.path.basename(name)[:60]}» del ZIP pesa más de {zip_max_entry_mb()} MB descomprimido.", 413)
    return data


def check_image_dimensions(content: bytes) -> None:
    """Lee solo el encabezado y rechaza imágenes con demasiados píxeles ANTES de decodificarlas."""
    try:
        with Image.open(io.BytesIO(content)) as im:
            w, h = im.size
    except Image.DecompressionBombError:
        raise LimitError("La imagen tiene demasiados píxeles; reduce su tamaño e inténtalo de nuevo.", 413)
    except Exception:
        raise LimitError("El archivo no es una imagen válida.")
    if w * h > image_max_pixels():
        raise LimitError(f"La imagen tiene demasiados píxeles ({w}x{h}); el máximo es {image_max_pixels() // 1_000_000} megapíxeles.", 413)
