"""Almacén · Pieza 4: el checklist del evento como Excel (.xlsx) idéntico al formato GEYL (logo, encabezado, las 43 filas y la hoja «Instrucciones Básicas»).
Se parte de la plantilla app/xlsx_templates/Checklist_GEYL.xlsx (el Checklist_GEYL.xls original convertido sin tocar su formato) y SOLO se llenan celdas: encabezado del evento (B2:B7), NECESARIO / CANTIDAD / OK S/N /
OBSERVACIONES de cada fila y el responsable. Sin base de datos: recibe lo ya calculado (`board` de almacen_moves.build_board y los datos del evento)."""
import copy
import io
import math
import os
import re
import zipfile
from typing import Dict, Iterable, Optional

from openpyxl import load_workbook

from app import almacen

TEMPLATE = os.path.join(os.path.dirname(__file__), "xlsx_templates", "Checklist_GEYL.xlsx")
TEMPLATE_SHEET = "Hoja1"          # nombre de la hoja en la plantilla original
SHEET = "Checklist"            # nombre con el que sale en el Excel (18-nov-2026: «Hoja1» → «Checklist»; la «Hoja3» vacía del formato ya no viene)
EXTRA_SHEETS = ("Hoja3",)
HEADER_CELLS = {"code": "B2", "name": "B3", "when": "B4", "client": "B5", "place": "B6", "coordinator": "B7"}
RESPONSIBLE_CELL = "B54"
YES, NO = "SÍ", "NO"
OBS_WIDTH, OBS_CHARS = 64, 46          # columna E ampliada (era 46): caracteres por línea con la letra del formato
HEADER_CHARS = 80          # datos del encabezado (B:E combinadas)
OBS_LINE, HEADER_LINE = 17, 16          # alto de una línea con la letra del formato (13 pt en observaciones, 12 pt en el encabezado)


def sentence_case(text) -> str:
    """Mayúscula al inicio de cada frase (inicio del texto y después de punto, signo de cierre o salto de línea): «es plan B» → «Es plan B». Lo demás no se toca (siglas, nombres, «Plan B»)."""
    s = str(text or "")
    out, start = [], True
    for ch in s:
        if start and ch.isalpha():
            ch, start = ch.upper(), False
        elif ch.isalnum():
            start = False
        if ch in ".!?\n":
            start = True
        out.append(ch)
    return "".join(out)


def join_names(names) -> str:
    """Los responsables del checklist, sin repetir y en el orden dado: «Ana, Luis y Juan David»."""
    seen, clean = set(), []
    for n in names or []:
        n = " ".join(str(n or "").split())
        if n and n.lower() not in seen:
            seen.add(n.lower()); clean.append(n)
    return clean[0] if len(clean) == 1 else (", ".join(clean[:-1]) + " y " + clean[-1] if clean else "")


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
            f"D{excel_row}": YES if row.get("done") else (NO if active and row["kind"] == "inv" else None), f"E{excel_row}": " · ".join(sentence_case(n) for n in notes) or None}


def _fit(ws, cell: str, row: int, chars_per_line: int, line_height: float) -> None:
    """Texto largo: se parte en líneas (ajuste de texto) y la fila crece lo necesario; si no, el Excel lo corta."""
    c = ws[cell]
    text = c.value
    if not text or len(str(text)) <= chars_per_line:
        return
    al = copy.copy(c.alignment)
    al.wrap_text = True
    al.vertical = al.vertical or "center"
    c.alignment = al
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 15, line_height * math.ceil(len(str(text)) / chars_per_line))


# Orden de las propiedades de una tirada de texto con formato tal como lo escribe Excel (openpyxl las escribe en otro orden y Excel «repara» el archivo al abrirlo).
_RPR_ORDER = ["b", "i", "strike", "condense", "extend", "outline", "shadow", "u", "vertAlign", "sz", "color", "rFont", "family", "charset", "scheme"]


def _sort_rpr(match) -> str:
    kids = re.findall(r"<(\w+)\b[^>]*/>", match.group(1))
    parts = re.findall(r"<\w+\b[^>]*/>", match.group(1))
    order = sorted(zip(kids, parts), key=lambda kp: _RPR_ORDER.index(kp[0]) if kp[0] in _RPR_ORDER else len(_RPR_ORDER))
    return "<rPr>" + "".join(p for _, p in order) + "</rPr>"


def repair_for_excel(data: bytes) -> bytes:
    """Deja el .xlsx como Excel lo exige (sin esto, Excel abre con «Registros reparados»): (1) texto con espacios al inicio o al final lleva xml:space="preserve" (también los
    «<t> </t>» de las tiradas con formato); (2) las propiedades de cada tirada van en el orden de Excel; (3) la imagen del logo no puede tener id 0 en el dibujo."""
    src, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            raw = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet") and item.filename.endswith(".xml"):
                xml = raw.decode("utf-8")
                xml = re.sub(r"<t>(\s[^<]*|[^<]*\s)</t>", r'<t xml:space="preserve">\1</t>', xml)
                xml = re.sub(r"<rPr>(.*?)</rPr>", _sort_rpr, xml)
                raw = xml.encode("utf-8")
            elif item.filename.startswith("xl/drawings/drawing") and item.filename.endswith(".xml"):
                raw = re.sub(r'(<cNvPr id=")0(")', r"\g<1>1\2", raw.decode("utf-8")).encode("utf-8")
            dst.writestr(item, raw)
    return out.getvalue()


def build(event_info: Dict[str, str], board: Iterable[dict], responsible: str) -> bytes:
    """`responsible`: quienes llenaron el checklist de ESE evento (ya unidos en un texto; ver join_names). `event_info`: code, name, when, client, place, coordinator (texto ya armado). `board`: las filas de build_board en el orden del formato. Devuelve el .xlsx."""
    wb = load_workbook(TEMPLATE, rich_text=True)          # rich_text: conserva los textos con dos tipos de letra de la columna A
    ws = wb[TEMPLATE_SHEET]
    ws.title = SHEET
    for extra in EXTRA_SHEETS:
        if extra in wb.sheetnames and wb[extra].max_row <= 1 and wb[extra].max_column <= 1 and wb[extra]["A1"].value is None:          # solo la hoja vacía; si alguna vez trae algo, se deja
            del wb[extra]
    ws.column_dimensions["E"].width = OBS_WIDTH          # observaciones más anchas que en el formato a mano (ahí se escribe con lapicero; aquí hay texto armado)
    for key, cell in HEADER_CELLS.items():
        ws[cell] = event_info.get(key) or None
        _fit(ws, cell, int(cell[1:]), HEADER_CHARS, HEADER_LINE)
    by_key = {r["key"]: r for r in almacen.CHECKLIST_ROWS}
    for row in board:
        meta = by_key.get(row["key"])
        if meta is None:
            continue
        for cell, value in _row_cells(row, meta["excel_row"]).items():
            ws[cell] = value
        _fit(ws, f"E{meta['excel_row']}", meta["excel_row"], OBS_CHARS, OBS_LINE)
    ws[RESPONSIBLE_CELL] = responsible or None
    _fit(ws, RESPONSIBLE_CELL, int(RESPONSIBLE_CELL[1:]), HEADER_CHARS, HEADER_LINE)
    ws.sheet_view.selection[0].activeCell = "A1"
    ws.sheet_view.selection[0].sqref = "A1"
    wb.active = wb.sheetnames.index(SHEET)
    out = io.BytesIO()
    wb.save(out)
    return repair_for_excel(out.getvalue())


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
