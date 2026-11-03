"""Trabajo pesado que NO debe correr sin límite dentro de una petición (reportes Excel: pandas/openpyxl, varios segundos y cientos de MB con miles de filas).

`heavy_slot()` deja pasar a `HEAVY_CONCURRENCY` (1 por defecto) a la vez por proceso; los demás esperan hasta `HEAVY_QUEUE_TIMEOUT` segundos y, si no
llega su turno, reciben 503 con «Reintenta en un minuto» en vez de acumularse y agotar memoria y conexiones durante un evento. Es un límite de
contención, no una cola: mover los reportes a un trabajo en segundo plano (Cloud Run Job) es la Fase 2. Los archivos se arman en memoria (`bytes`),
sin dejar temporales en disco.

`workbook_response` / `excel_response` devuelven la respuesta HTTP lista."""
import os
import re
import tempfile
import unicodedata
import threading
from contextlib import contextmanager
from io import BytesIO
from typing import Callable
from urllib.parse import quote

from app.xlsafe import safe_cell, safe_frame, safe_workbook  # noqa: F401 — se reexportan aquí
from fastapi import HTTPException
from fastapi.responses import Response

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_slots = threading.BoundedSemaphore(max(1, int(os.getenv("HEAVY_CONCURRENCY", "1"))))
QUEUE_TIMEOUT = float(os.getenv("HEAVY_QUEUE_TIMEOUT", "30"))


@contextmanager
def heavy_slot():
    if not _slots.acquire(timeout=QUEUE_TIMEOUT):
        raise HTTPException(status_code=503, detail="Hay otro reporte generándose. Reintenta en un minuto.", headers={"Retry-After": "60"})
    try:
        yield
    finally:
        _slots.release()


_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
FILENAME_MAX = 100          # largo máximo del nombre del evento dentro del archivo (el código y el tipo de reporte siempre van completos)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", _INVALID_FILENAME_CHARS.sub(" ", str(text or ""))).strip(" .")


def event_report_filename(event, kind: str, ext: str = ".xlsx") -> str:
    """«<nombre del evento> - <código> - <tipo de reporte>.xlsx», sin caracteres que los sistemas de archivos no admiten. Sin código no quedan guiones sueltos; el nombre se recorta a ~100."""
    code, tail = _clean(getattr(event, "event_code", "")), _clean(kind)
    name = _clean(getattr(event, "name", ""))[:FILENAME_MAX].strip(" .")
    return " - ".join(p for p in (name, code, tail) if p) + ext


def content_disposition(filename: str) -> str:
    """Cabecera con nombre ASCII de respaldo (navegadores viejos) y `filename*` UTF-8 (RFC 5987/6266) para que tildes y ñ lleguen bien."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode().replace("%", "").replace(";", ",") or "reporte"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _attachment(data: bytes, filename: str, media_type: str = XLSX) -> Response:
    return Response(data, media_type=media_type, headers={"Content-Disposition": content_disposition(filename)})


def workbook_response(wb, filename: str) -> Response:
    """Guarda un `openpyxl.Workbook` en memoria y lo entrega como descarga."""
    with heavy_slot():
        buffer = BytesIO()
        safe_workbook(wb).save(buffer)
    return _attachment(buffer.getvalue(), filename)


def excel_response(write_to: Callable[[str], None], filename: str) -> Response:
    """Para generadores que escriben a una ruta (ReportManager): se usa una carpeta temporal que se borra sola."""
    with heavy_slot(), tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "reporte.xlsx")
        write_to(path)
        with open(path, "rb") as fh:
            data = fh.read()
    return _attachment(data, filename)
