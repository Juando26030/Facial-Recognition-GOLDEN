"""Excel de «Usuarios del evento» (27-nov-2026, pedido de Juan David).

1. `list_workbook`: «Listado de usuarios», con el MISMO formato del listado que Golden ya usa con sus clientes (ejemplo: LISTADO_EV23164_CORFERIAS…xlsx): fila 2 con la fecha
   resaltada en amarillo, fila 3 combinada (A:C) con los datos del evento en un recuadro azul claro, y desde la fila 4 «#, NOMBRE, CÉDULA» con bordes finos y la cédula en número (#,##0).
2. `pledge_workbook`: «Respuestas del compromiso», todo lo que cada digitador llenó en el compromiso digital, INCLUIDO lo sensible (contacto de emergencia, salud y el «¿Cuál?»).
   Decisión de Juan David (27-nov-2026), advertido de que el texto de la auditora promete que esos datos solo los ve el coordinador y se borran 30 días después del evento: un archivo
   descargado ya no se borra solo. Por eso el archivo lleva el aviso arriba, solo lo descargan coordinador del evento y admin+ (nunca la comercial pura) y queda en audit_actions (sin datos).

Solo construye el libro (bytes); quién puede y qué filas van lo decide el router. Todo texto pasa por `xlsafe.safe_workbook`."""
import io
import re
from datetime import date
from typing import Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.xlsafe import safe_workbook

FONT = "Aptos Narrow"
FONT_ID = "Book Antiqua"          # la columna de la cédula del ejemplo
YELLOW = PatternFill("solid", fgColor="FFFF00")
BLUE = PatternFill("solid", fgColor="99CCFF")          # el índice 44 de la paleta de Excel, como el recuadro del ejemplo
ALERT = PatternFill("solid", fgColor="FFF2CC")          # amarillo suave: la fila que el coordinador debe mirar (igual que la alerta en pantalla)
HEAD = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
_DIGITS = re.compile(r"\d{1,15}")

MONTHS = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")
DAYS = ("LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO")
STATUS = {"creado": "Creado", "en_proceso": "En proceso", "finalizado": "Finalizado"}


def _long_date(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} DE {MONTHS[d.month - 1]} DE {d.year}"


def _hour(hhmm: Optional[str]) -> str:
    """«15:00» → «3:00 p. m.» (como se dice en Colombia)."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
    except (TypeError, ValueError):
        return ""
    suffix = "a. m." if h < 12 else "p. m."
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def when_line(event, with_place: bool = True) -> str:
    """La línea amarilla: fechas del evento, horario y lugar («SÁBADO 28 DE NOVIEMBRE DE 2026 de 3:00 p. m. a 10:00 p. m. — CORFERIAS»)."""
    start, end = event.start_date, event.end_date
    if start and end and end != start:
        days = f"{_long_date(start)} AL {_long_date(end)}"
    elif start or end:
        days = _long_date(start or end)
    else:
        days = "FECHA POR DEFINIR"
    h1, h2 = _hour(event.event_time_start), _hour(event.event_time_end)
    hours = f"de {h1} a {h2}" if h1 and h2 else (f"desde {h1}" if h1 else "")
    place = (event.location or event.city or "") if with_place else ""
    return " ".join(p for p in (days, hours) if p) + (f" — {place}" if place else "")


def header_text(event, client: str, coordinator: str) -> str:
    """El recuadro azul (fila 3): «[código] cliente - evento», lugar, notas, coordinador y estado, como el listado de ejemplo."""
    first = f"[{event.event_code}] " + " - ".join(p for p in (client, event.name) if p)
    place = ", ".join(p for p in (event.city, event.location, event.address) if p)
    lines = [first.strip()]
    if place:
        lines.append(place.upper())
    notes = (event.notes or "").strip()
    if notes:
        lines.append(notes[:600])
    if coordinator:
        lines.append(f"Coordinador: {coordinator}")
    lines.append(f"Estado: {STATUS.get(event.status, event.status or '')}")
    return "\n".join(lines)


def _id_value(v):
    """La cédula como número (se ve 1.023.371.225 igual que el ejemplo) si son solo dígitos; si no, como texto."""
    s = str(v or "").strip()
    return int(s) if _DIGITS.fullmatch(s) and not s.startswith("0") else s


def _save(wb: Workbook) -> bytes:
    safe_workbook(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _box_height(text: str, width_chars: float) -> float:
    lines = sum(max(1, -(-len(line) // int(width_chars))) for line in text.split("\n"))
    return max(30.0, 13.5 * lines + 6)


def list_workbook(event, client: str, coordinator: str, people: Iterable[Sequence]) -> bytes:
    """`people`: (nombre, cédula o usuario) en el orden en que deben salir."""
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\\/*?:\[\]]", " ", f"{event.event_code} {event.name}")[:31].strip() or "Usuarios"
    ws.column_dimensions["A"].width = 8.86
    ws.column_dimensions["B"].width = 35.71
    ws.column_dimensions["C"].width = 17.71
    ws["B2"] = when_line(event, with_place=False)          # el lugar ya va en el recuadro; así la línea cabe en el amarillo
    ws.merge_cells("B2:C2")
    ws["B2"].font = Font(name=FONT, size=11)
    ws["B2"].fill = YELLOW
    head = header_text(event, client, coordinator)
    ws["A3"] = head
    ws.merge_cells("A3:C3")
    ws["A3"].font = Font(name=FONT, size=10, bold=True)
    ws["A3"].fill = BLUE
    ws["A3"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[3].height = _box_height(head, 62)
    row = 4
    for n, (name, ident) in enumerate(people, start=1):
        a, b, c = ws.cell(row, 1, n), ws.cell(row, 2, (name or "").upper()), ws.cell(row, 3, _id_value(ident))
        for cell in (a, b, c):
            cell.border = BOX
            cell.font = Font(name=FONT, size=10)
        a.alignment = Alignment(horizontal="center")
        c.font = Font(name=FONT_ID, size=10, bold=True)
        c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        if isinstance(c.value, int):
            c.number_format = "#,##0"
        row += 1
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    return _save(wb)


WARNING = ("CONTIENE DATOS SENSIBLES (salud y contacto de emergencia). Uso exclusivo del coordinador y del personal autorizado de Golden, solo para la salud y seguridad del personal "
           "durante el evento. No lo reenvíes y bórralo 30 días después de finalizado el evento, como se le prometió a cada persona al firmar.")


def pledge_workbook(event, client: str, coordinator: str, columns: List[str], rows: List[dict]) -> bytes:
    """`columns`: títulos en orden. `rows`: {"values": [...] (mismo largo), "alert": bool}. Las filas con alerta van en amarillo suave (lo mismo que en pantalla)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Respuestas del compromiso"
    last = get_column_letter(len(columns))
    ws["A1"] = f"Respuestas del compromiso digital — [{event.event_code}] " + " - ".join(p for p in (client, event.name) if p)
    ws["A1"].font = Font(name=FONT, size=12, bold=True)
    ws["A2"] = when_line(event) + (f" · Coordinador: {coordinator}" if coordinator else "")
    ws["A2"].font = Font(name=FONT, size=10)
    ws["A2"].fill = YELLOW
    ws.merge_cells(f"A2:{last}2")
    ws["A3"] = WARNING
    ws.merge_cells(f"A3:{last}3")
    ws["A3"].font = Font(name=FONT, size=10, bold=True, color="9C0006")
    ws["A3"].fill = PatternFill("solid", fgColor="FFC7CE")
    ws["A3"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[3].height = 32
    for i, title in enumerate(columns, start=1):
        c = ws.cell(5, i, title)
        c.font = Font(name=FONT, size=10, bold=True)
        c.fill = HEAD
        c.border = BOX
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[5].height = 66
    for r, item in enumerate(rows, start=6):
        for i, v in enumerate(item["values"], start=1):
            c = ws.cell(r, i, v)
            c.font = Font(name=FONT, size=10)
            c.border = BOX
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if item.get("alert"):
                c.fill = ALERT
            if isinstance(v, int) and i > 1:
                c.number_format = "0"
    widths = {"#": 5, "Cédula": 14, "Nombre": 30, "Celular": 15, "Alertas": 34, "Firmado": 17, "Estado": 16}
    for i, title in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(title, 26 if title.startswith("¿Cuál") else 20)
    ws.freeze_panes = "D6"
    if rows:
        ws.auto_filter.ref = f"A5:{last}{5 + len(rows)}"
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    return _save(wb)
