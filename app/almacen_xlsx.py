"""Almacén · Pieza 4: el checklist del evento como Excel (.xlsx) idéntico al formato GEYL (logo, encabezado, las 43 filas y la hoja «Instrucciones Básicas»).
Se parte de la plantilla app/xlsx_templates/Checklist_GEYL.xlsx (el Checklist_GEYL.xls original convertido sin tocar su formato) y SOLO se llenan celdas: encabezado del evento (B2:B7), NECESARIO / CANTIDAD / OK S/N /
OBSERVACIONES de cada fila y el responsable. Sin base de datos: recibe lo ya calculado (`board` de almacen_moves.build_board y los datos del evento)."""
import copy
import io
import math
import os
from typing import Dict, Iterable, Optional

from openpyxl import load_workbook

from app import almacen

TEMPLATE = os.path.join(os.path.dirname(__file__), "xlsx_templates", "Checklist_GEYL.xlsx")
SHEET = "Hoja1"
HEADER_CELLS = {"code": "B2", "name": "B3", "when": "B4", "client": "B5", "place": "B6", "coordinator": "B7"}
RESPONSIBLE_CELL = "B54"
YES, NO = "SÍ", "NO"
OBS_WIDTH, OBS_CHARS = 64, 52          # columna E ampliada (era 46): caracteres por línea con la letra del formato
HEADER_CHARS = 80          # datos del encabezado (B:E combinadas)
LINE_HEIGHT = 13


def _row_cells(row: dict, excel_row: int) -> Dict[str, object]:
    """Valores de una fila del formato. Lo que no aplica queda en blanco (como en el formato a mano)."""
    needed, out, returned, pending = row.get("needed"), row.get("out"), row.get("returned"), row.get("pending")
    notes = [row["notes"]] if row.get("notes") else []
    if row["kind"] == "inv":
        if row.get("extra"):
            notes.append(f"Extra: {row['extra']} (no pedido por el evento)")
        if row.get("plan_b"):
            notes.append("Salió Plan B")
        if returned or pending:
            notes.append(f"Volvieron {returned or 0}" + (f" · faltan {pending}" if pending else ""))
    active = bool((needed or 0) or (out or 0) or row.get("done") or notes)
    return {f"B{excel_row}": needed or None, f"C{excel_row}": out or None,
            f"D{excel_row}": YES if row.get("done") else (NO if active and row["kind"] == "inv" else None), f"E{excel_row}": " · ".join(notes) or None}


def _fit(ws, cell: str, row: int, chars_per_line: int) -> None:
    """Texto largo: se parte en líneas (ajuste de texto) y la fila crece lo necesario; si no, el Excel lo corta."""
    c = ws[cell]
    text = c.value
    if not text or len(str(text)) <= chars_per_line:
        return
    al = copy.copy(c.alignment)
    al.wrap_text = True
    al.vertical = al.vertical or "center"
    c.alignment = al
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 15, LINE_HEIGHT * math.ceil(len(str(text)) / chars_per_line))


def build(event_info: Dict[str, str], board: Iterable[dict], responsible: str) -> bytes:
    """`event_info`: code, name, when, client, place, coordinator (texto ya armado). `board`: las filas de build_board en el orden del formato. Devuelve el .xlsx."""
    wb = load_workbook(TEMPLATE, rich_text=True)          # rich_text: conserva los textos con dos tipos de letra de la columna A
    ws = wb[SHEET]
    ws.column_dimensions["E"].width = OBS_WIDTH          # observaciones más anchas que en el formato a mano (ahí se escribe con lapicero; aquí hay texto armado)
    for key, cell in HEADER_CELLS.items():
        ws[cell] = event_info.get(key) or None
        _fit(ws, cell, int(cell[1:]), HEADER_CHARS)
    by_key = {r["key"]: r for r in almacen.CHECKLIST_ROWS}
    for row in board:
        meta = by_key.get(row["key"])
        if meta is None:
            continue
        for cell, value in _row_cells(row, meta["excel_row"]).items():
            ws[cell] = value
        _fit(ws, f"E{meta['excel_row']}", meta["excel_row"], OBS_CHARS)
    ws[RESPONSIBLE_CELL] = responsible or None
    ws.sheet_view.selection[0].activeCell = "A1"
    ws.sheet_view.selection[0].sqref = "A1"
    wb.active = wb.sheetnames.index(SHEET)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def event_info(event, client: str, contact: Optional[str], coordinator: str) -> Dict[str, str]:
    """Arma los textos del encabezado a partir del evento (fechas y horas como se escriben en Colombia)."""
    def d(v):
        return v.strftime("%d/%m/%Y") if v else ""
    start, end = d(event.start_date), d(event.end_date)
    days = start if not end or end == start else f"{start} al {end}"
    hours = f"{event.event_time_start} a {event.event_time_end}" if event.event_time_start and event.event_time_end else (event.event_time_start or "")
    place = ", ".join(p for p in (event.location, event.address, event.city) if p)
    return {"code": event.event_code, "name": event.name, "when": " · ".join(p for p in (days, hours) if p), "place": place, "coordinator": coordinator or "",
            "client": " — ".join(p for p in (client, contact) if p)}
