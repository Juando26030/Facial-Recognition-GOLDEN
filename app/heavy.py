"""Trabajo pesado que NO debe correr sin límite dentro de una petición (reportes Excel: pandas/openpyxl, varios segundos y cientos de MB con miles de filas).

`heavy_slot()` deja pasar a `HEAVY_CONCURRENCY` (1 por defecto) a la vez por proceso; los demás esperan hasta `HEAVY_QUEUE_TIMEOUT` segundos y, si no
llega su turno, reciben 503 con «Reintenta en un minuto» en vez de acumularse y agotar memoria y conexiones durante un evento. Es un límite de
contención, no una cola: mover los reportes a un trabajo en segundo plano (Cloud Run Job) es la Fase 2. Los archivos se arman en memoria (`bytes`),
sin dejar temporales en disco.

`workbook_response` / `excel_response` devuelven la respuesta HTTP lista."""
import os
import tempfile
import threading
from contextlib import contextmanager
from io import BytesIO
from typing import Callable
from urllib.parse import quote

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


def _attachment(data: bytes, filename: str, media_type: str = XLSX) -> Response:
    return Response(data, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


def workbook_response(wb, filename: str) -> Response:
    """Guarda un `openpyxl.Workbook` en memoria y lo entrega como descarga."""
    with heavy_slot():
        buffer = BytesIO()
        wb.save(buffer)
    return _attachment(buffer.getvalue(), filename)


def excel_response(write_to: Callable[[str], None], filename: str) -> Response:
    """Para generadores que escriben a una ruta (ReportManager): se usa una carpeta temporal que se borra sola."""
    with heavy_slot(), tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "reporte.xlsx")
        write_to(path)
        with open(path, "rb") as fh:
            data = fh.read()
    return _attachment(data, filename)
