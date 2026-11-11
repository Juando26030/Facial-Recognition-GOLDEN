"""Hoja «Portada» del Excel del reporte del evento (Fase 10, bloque E). Sin base de datos: recibe datos ya armados (`info`) y los logos (bytes) y dibuja la portada con openpyxl.

Diseño (paleta de Golden: azul noche 0A0E2E y dorado D4AF37): cuadrícula oculta, franja blanca con los logos (solo los que existen: sin huecos), bloque azul con «REPORTE DEL EVENTO» y el nombre
del evento, fina banda dorada, tarjetas con los datos (cliente, fechas, lugar, tipo, coordinador, comercial), tarjetas con los totales clave y un pie con la fecha de generación y la nota de privacidad.
Los logos se redimensionan con Pillow conservando la proporción; si uno no se puede leer se omite sin romper nada.
"""
import io
from typing import Iterable, Optional

from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.worksheet.properties import PageSetupProperties

from app.xlsafe import safe_cell

NAVY, GOLD, GOLD_SOFT, GRAY_BG, GRAY_TEXT, WHITE, LINE = "0A0E2E", "D4AF37", "F6EBC8", "F4F5F9", "5B6078", "FFFFFF", "D9DCE6"
FONT = "Calibri"
NCOLS = 14                      # A..N: A y N son márgenes; B..M llevan el contenido (12 columnas)
COL_W = 11.0
COL_PX = 82                     # ancho aproximado de una columna de 11 caracteres
BAND_ROWS, BAND_ROW_H = (2, 5), 20      # franja de logos: filas 2 a 5, 20 pt cada una (≈ 107 px en total)
LOGO_BOX = (3 * COL_PX - 12, 86)         # caja máxima de cada logo (px): 3 columnas de ancho
FOOTER_LOGO_BOX = (110, 26)             # marca pequeña de Golden en el pie (solo cuando el logo principal es el del evento)
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
PRIVACY_NOTE = ("Este documento contiene datos personales de los asistentes (Ley 1581 de 2012). Úsalo solo para la finalidad del evento, no lo compartas con terceros "
                "y elimínalo cuando ya no lo necesites. No incluye datos biométricos (rostros).")


def fill(color: str) -> PatternFill:
    return PatternFill(start_color=color, end_color=color, fill_type="solid")


THIN = Side(style="thin", color=LINE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def date_es(d) -> str:
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}" if d else ""


def dates_text(start, end) -> str:
    if start and end and start != end:
        if start.year == end.year and start.month == end.month:
            return f"Del {start.day} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
        return f"Del {date_es(start)} al {date_es(end)}"
    return date_es(start or end) or "Por definir"


def prepare_logo(data: Optional[bytes], box=LOGO_BOX) -> Optional[tuple]:
    """(PNG redimensionado en bytes, ancho, alto) conservando la proporción, o None si no hay datos o no son una imagen válida. Nunca lanza."""
    if not data:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        scale = min(box[0] / img.width, box[1] / img.height, 1.0)          # conserva la proporción y no agranda
        w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
        img = img.resize((w, h), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue(), w, h
    except Exception:
        return None


def _merge(ws, rng: str, value=None, font=None, fill_color: Optional[str] = None, align=None, border=None):
    ws.merge_cells(rng)
    first = ws[rng.split(":")[0]]
    if value is not None:
        first.value = safe_cell(value) if isinstance(value, str) else value
    if font:
        first.font = font
    if align:
        first.alignment = align
    for row in ws[rng]:
        for c in row:
            if fill_color:
                c.fill = fill(fill_color)
            if border:
                c.border = border
    return first


def _card(ws, row: int, c1: int, c2: int, label: str, value: str, *, big: bool = False, tint: str = GRAY_BG, value_color: str = NAVY):
    """Tarjeta de 2 filas (etiqueta pequeña arriba, valor abajo) entre las columnas c1 y c2."""
    a, b = get_column_letter(c1), get_column_letter(c2)
    _merge(ws, f"{a}{row}:{b}{row}", label.upper(), Font(name=FONT, size=8, bold=True, color=GRAY_TEXT), tint, Alignment(horizontal="left", vertical="bottom", indent=1))
    _merge(ws, f"{a}{row + 1}:{b}{row + 1}", value, Font(name=FONT, size=24 if big else 13, bold=True, color=value_color), tint,
           Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1))
    for r in (row, row + 1):                     # borde fino alrededor de la tarjeta
        for c in range(c1, c2 + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = Border(left=THIN if c == c1 else None, right=THIN if c == c2 else None, top=THIN if r == row else None, bottom=THIN if r == row + 1 else None)
    ws.row_dimensions[row].height = 18
    ws.row_dimensions[row + 1].height = 40 if big else 30


def _place_logo(ws, prepared: tuple, col_letter: str, band_px: float, row: int = BAND_ROWS[0]) -> None:
    png, w, h = prepared
    img = XLImage(io.BytesIO(png))
    img.width, img.height = w, h
    col = ws[f"{col_letter}1"].column - 1
    row_off = max(0, int((band_px - h) / 2))
    marker = AnchorMarker(col=col, colOff=pixels_to_EMU(6), row=row - 1, rowOff=pixels_to_EMU(row_off))
    img.anchor = OneCellAnchor(_from=marker, ext=XDRPositiveSize2D(pixels_to_EMU(w), pixels_to_EMU(h)))
    ws.add_image(img)


def build_cover(ws, info: dict, logo: Optional[bytes], footer_logo: Optional[bytes] = None) -> int:
    """Dibuja la portada en `ws` (hoja ya creada). `info`: tenant, event_name, event_code, dates, place, event_type, coordinator, commercial, generated, kpis [(etiqueta, valor)], kpis2 [(etiqueta, valor)],
    privacy (opcional). `logo`: bytes del ÚNICO logo principal (el del evento, o el de Golden si el evento no tiene). `footer_logo`: marca pequeña de Golden para el pie (None = sin marca).
    Devuelve cuántos logos se dibujaron (0 si el principal no se pudo leer: la franja queda limpia)."""
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 100
    ws.sheet_properties.tabColor = GOLD
    for c in range(1, NCOLS + 1):
        ws.column_dimensions[get_column_letter(c)].width = 3.0 if c in (1, NCOLS) else COL_W
    last = get_column_letter(NCOLS)
    # fondo blanco de toda la zona (tapa la cuadrícula) y franja superior dorada
    ws.row_dimensions[1].height = 8
    for c in range(1, NCOLS + 1):
        ws.cell(row=1, column=c).fill = fill(GOLD)
    # franja de logos
    for r in range(BAND_ROWS[0], BAND_ROWS[1] + 1):
        ws.row_dimensions[r].height = BAND_ROW_H
    drawn = 0
    band_px = (BAND_ROWS[1] - BAND_ROWS[0] + 1) * BAND_ROW_H * 96 / 72
    main = prepare_logo(logo)
    if main:
        _place_logo(ws, main, "B", band_px)
        drawn += 1
    ws.row_dimensions[6].height = 4
    for c in range(1, NCOLS + 1):
        ws.cell(row=6, column=c).fill = fill(GOLD)

    # bloque azul: título y nombre del evento
    ws.row_dimensions[7].height = 14
    _merge(ws, f"A7:{last}7", None, None, NAVY)
    ws.row_dimensions[8].height = 24
    _merge(ws, "B8:M8", "REPORTE DEL EVENTO", Font(name=FONT, size=14, bold=True, color=GOLD), NAVY, Alignment(horizontal="left", vertical="center"))
    ws.cell(row=8, column=1).fill = fill(NAVY)
    ws.cell(row=8, column=NCOLS).fill = fill(NAVY)
    ws.row_dimensions[9].height = 78
    _merge(ws, "B9:M9", info.get("event_name") or "", Font(name=FONT, size=30, bold=True, color=WHITE), NAVY, Alignment(horizontal="left", vertical="center", wrap_text=True))
    ws.cell(row=9, column=1).fill = fill(NAVY)
    ws.cell(row=9, column=NCOLS).fill = fill(NAVY)
    ws.row_dimensions[10].height = 22
    sub = " · ".join(x for x in (info.get("tenant"), info.get("event_code")) if x)
    _merge(ws, "B10:M10", sub, Font(name=FONT, size=13, color="C9CCE0"), NAVY, Alignment(horizontal="left", vertical="center"))
    ws.cell(row=10, column=1).fill = fill(NAVY)
    ws.cell(row=10, column=NCOLS).fill = fill(NAVY)
    ws.row_dimensions[11].height = 14
    _merge(ws, f"A11:{last}11", None, None, NAVY)
    ws.row_dimensions[12].height = 6
    for c in range(1, NCOLS + 1):
        ws.cell(row=12, column=c).fill = fill(GOLD)
    ws.row_dimensions[13].height = 14

    # tarjetas de datos (3 por fila: columnas B-E, F-I, J-M)
    cards = [("Cliente", info.get("tenant")), ("Fechas", info.get("dates")), ("Lugar", info.get("place")),
             ("Tipo de evento", info.get("event_type")), ("Coordinador(a)", info.get("coordinator")), ("Comercial", info.get("commercial"))]
    spans = [(2, 5), (6, 9), (10, 13)]
    row = 14
    for i in range(0, len(cards), 3):
        for (label, value), (c1, c2) in zip(cards[i:i + 3], spans):
            _card(ws, row, c1, c2, label, value or "—")
        row += 2
        ws.row_dimensions[row].height = 8
        row += 1
    # totales clave
    ws.row_dimensions[row].height = 22
    _merge(ws, f"B{row}:M{row}", "RESUMEN", Font(name=FONT, size=11, bold=True, color=NAVY), None, Alignment(horizontal="left", vertical="center"))
    for c in range(2, 14):
        ws.cell(row=row, column=c).border = Border(bottom=Side(style="medium", color=GOLD))
    row += 1
    ws.row_dimensions[row].height = 6
    row += 1
    kspans = [(2, 4), (5, 7), (8, 10), (11, 13)]
    for i, kp in enumerate((info.get("kpis") or [], info.get("kpis2") or [])):
        for (label, value), (c1, c2) in zip(kp, kspans):
            _card(ws, row, c1, c2, label, str(value), big=(i == 0), tint=GOLD_SOFT if i == 0 else GRAY_BG)
        if kp:
            row += 2
            ws.row_dimensions[row].height = 8
            row += 1
    # pie
    row += 1
    ws.row_dimensions[row].height = 34
    mark = prepare_logo(footer_logo, FOOTER_LOGO_BOX)
    if mark:
        _place_logo(ws, mark, "L", 34 * 96 / 72, row)
        drawn += 1
    _merge(ws, f"B{row}:M{row}", "Generado el " + (info.get("generated") or ""), Font(name=FONT, size=10, bold=True, color=NAVY), GRAY_BG, Alignment(horizontal="left", vertical="center", indent=1), BOX)
    row += 1
    ws.row_dimensions[row].height = 48
    _merge(ws, f"B{row}:M{row}", info.get("privacy") or PRIVACY_NOTE, Font(name=FONT, size=9, italic=True, color=GRAY_TEXT), GRAY_BG, Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1), BOX)
    row += 1
    ws.row_dimensions[row].height = 8
    for c in range(1, NCOLS + 1):
        ws.cell(row=row, column=c).fill = fill(GOLD)
    # impresión: una página horizontal
    ws.print_area = f"A1:{last}{row}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    return drawn
