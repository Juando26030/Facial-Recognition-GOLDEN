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


def xlsx_rows(content: bytes, max_rows: int, max_cols: int, is_blank=None, raw_slack: int = 50_000) -> list:
    """Filas de la hoja activa de un .xlsx, con topes REALES (I1/D2, 6-nov-2026). Devuelve [encabezado, fila, fila…] (tuplas de a lo sumo `max_cols`
    valores): el encabezado es la primera fila tal cual y después solo las filas no vacías (`is_blank`, por defecto «todas None»).

    Por qué: openpyxl en modo solo lectura rellena cada fila hasta la dimensión que DECLARA la hoja (`<dimension ref="A1:XFD1048576">`) y produce filas
    vacías para los huecos: un archivo de 5 KB costaba minutos de CPU. Aquí el zip se revisa antes (entradas, tamaño descomprimido, razón de compresión),
    la dimensión declarada se ignora, se leen como máximo `max_cols` columnas y `max_rows + raw_slack` filas crudas (las vacías del final se ignoran) y se
    corta apenas pasa de `max_rows` filas con datos (LimitError, sin leer el resto). Nunca se arma una lista de la hoja completa."""
    from openpyxl import load_workbook
    try:
        zf = zipfile.ZipFile(io.BytesIO(content), "r")
    except (zipfile.BadZipFile, ValueError, OSError):
        raise LimitError("No se pudo leer el archivo. Usa un Excel en formato .xlsx")
    try:
        check_zip(zf)
    finally:
        zf.close()
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — XML roto o entidades prohibidas: nunca se detalla (podría incluir contenido)
        raise LimitError("No se pudo leer el archivo. Usa un Excel en formato .xlsx")
    blank = is_blank or (lambda row: all(v is None for v in row))
    try:
        ws = wb.active if wb.active is not None else wb.worksheets[0]
        if hasattr(ws, "reset_dimensions"):
            ws.reset_dimensions()
        out, data_rows, last_blank = [], 0, None
        for row in ws.iter_rows(min_row=1, max_row=max_rows + raw_slack + 1, max_col=max_cols, values_only=True):
            if not out:
                out.append(tuple(row))
                continue
            if row is last_blank:          # openpyxl rellena los huecos con LA MISMA tupla vacía: no hace falta recorrerla otra vez
                continue
            if blank(row):
                last_blank = row
                continue
            data_rows += 1
            if data_rows > max_rows:
                raise LimitError(f"El archivo tiene más de {max_rows:,} filas con datos; el máximo es {max_rows:,}. Divídelo en varios archivos.".replace(",", "."))
            out.append(tuple(row))
        return out
    finally:
        wb.close()


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


DESIGN_IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".gif": "GIF"}
DESIGN_IMAGE_MAX_BYTES = 8_000_000
DESIGN_IMAGE_MAX_PIXELS = 25_000_000


def check_design_image(content: bytes, ext: str, max_bytes: int = DESIGN_IMAGE_MAX_BYTES) -> None:
    """Imágenes de diseño que sube el personal (fondo/logo de escarapela, ruleta, formularios, logo del evento) — I6, 6-nov-2026. Se muestran en el quiosco, en los
    puestos de impresión y en el formulario público: una imagen «bomba» (pocos KB, decenas de miles de píxeles de lado) los colgaba. Tamaño, píxeles (sin decodificar),
    integridad y que el formato REAL coincida con la extensión. Lanza LimitError con el mensaje listo."""
    if not content:
        raise LimitError("La imagen está vacía.")
    if len(content) > max_bytes:
        raise LimitError(f"La imagen pesa más de {max_bytes // 1_000_000} MB.", 413)
    want = DESIGN_IMAGE_FORMATS.get((ext or "").lower())
    if want is None:
        raise LimitError("Usa una imagen PNG, JPG, WEBP o GIF.")
    check_image_dimensions(content)
    try:
        with Image.open(io.BytesIO(content)) as im:
            fmt, (w, h) = im.format, im.size
            im.verify()
    except Exception:  # noqa: BLE001 — cualquier fallo de lectura: no es una imagen válida
        raise LimitError("El archivo no es una imagen válida.")
    if fmt != want:
        raise LimitError(f"El archivo no es realmente una imagen {ext.lstrip('.').upper()}.")
    if w * h > DESIGN_IMAGE_MAX_PIXELS:
        raise LimitError(f"La imagen es demasiado grande ({w}x{h}); el máximo es {DESIGN_IMAGE_MAX_PIXELS // 1_000_000} megapíxeles.", 413)
