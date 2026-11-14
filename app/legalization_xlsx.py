"""Excel de la legalización de gastos de un evento, en el formato oficial de Golden (PLANTILLA-LEG.xlsx).

Lógica pura: no toca la base ni FastAPI. Recibe el encabezado y los gastos ya armados como diccionarios y devuelve
los bytes del .xlsx. La plantilla (app/xlsx_templates/PLANTILLA-LEG.xlsx) se construye con scripts/build_plantilla_leg.py
a partir del Excel de ejemplo; aquí solo se llena: logos, combinadas, fórmulas y formato salen de la plantilla.

Hojas que llena: Legalización (resumen), Hosped-Pasajes-TransTermin, Taxis-TransPúblico, PagoDigitadores,
Gastos de Alimentación, Otros gastos y Soportes (un comprobante por cada taxi sin recibo).
Si una tabla tiene más gastos que filas, se agregan filas con el mismo formato y se reescriben los totales.

Cada gasto es un dict con `kind` y los campos que apliquen (ver FIELDS más abajo).
"""
from __future__ import annotations

import io
from copy import copy, deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl.drawing.image import Image as XLImage

TEMPLATE_PATH = Path(__file__).resolve().parent / "xlsx_templates" / "PLANTILLA-LEG.xlsx"

HOSPEDAJE, PASAJE, TAXI_TERMINAL, TAXI_CIUDAD, ALIMENTACION, DIGITADOR, OTRO = (
    "hospedaje", "pasaje", "taxi_terminal", "taxi_ciudad", "alimentacion", "digitador", "otro")
KINDS = (HOSPEDAJE, PASAJE, TAXI_TERMINAL, TAXI_CIUDAD, ALIMENTACION, DIGITADOR, OTRO)

# Campos que entiende cada gasto (todos opcionales salvo `kind`):
FIELDS = (
    "date", "tax_id", "name", "address", "phone", "email", "origin", "destination", "concept", "amount", "iva",
    "support",        # True = tiene recibo/factura (S), False = no (N), None = sin responder
    "approved",       # True = aprobado por el director, False = rechazado, None = pendiente
    "plate", "vehicle",                                   # taxis en la ciudad: placa y 'taxi' | 'otro'
    "breakfast", "lunch", "dinner", "snack", "unit_value", "observation",      # alimentación
    "detail", "observations",                                                    # otros gastos
)

S_RES = "Legalización"
S_HOSP = "Hosped-Pasajes-TransTermin"
S_TAXI = "Taxis-TransPúblico"
S_DIG = "PagoDigitadores"
S_ALIM = "Gastos de Alimentación"
S_OTROS = "Otros gastos"
S_SOP = "Soportes"

# Columnas de cada tabla (letra de la plantilla -> campo del gasto)
_COLS_HOSP = {"A": "date", "B": "tax_id", "C": "name", "D": "address", "E": "phone", "F": "email", "I": "concept",
              "J": "amount", "K": "iva", "L": "support", "M": "approved"}
_COLS_RUTA = {**_COLS_HOSP, "G": "origin", "H": "destination"}
_COLS_TAXI = {"A": "date", "B": "tax_id", "C": "name", "D": "plate", "E": "phone", "F": "email", "G": "origin",
              "H": "destination", "K": "concept", "M": "amount", "N": "support", "O": "approved"}
_COLS_DIG = {"B": "date", "C": "tax_id", "D": "name", "E": "address", "F": "phone", "G": "email", "H": "amount"}
_COLS_ALIM = {"B": "date", "C": "tax_id", "D": "name", "E": "address", "F": "email", "G": "phone", "H": "unit_value",
              "I": "breakfast", "J": "lunch", "K": "dinner", "L": "snack", "N": "observation", "P": "iva",
              "Q": "support", "R": "approved"}
_COLS_OTROS = {"B": "date", "C": "tax_id", "D": "name", "E": "address", "F": "phone", "G": "email", "H": "detail",
               "I": "observations", "J": "amount", "K": "iva", "L": "support", "M": "approved"}


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        v = float(v)
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _meals(line: dict) -> float:
    return sum(float(line.get(k) or 0) for k in ("breakfast", "lunch", "dinner", "snack"))


def line_amount(line: dict) -> float:
    """Valor de un gasto (en alimentación: la suma de las comidas, o el valor directo si no hay desglose)."""
    if line.get("kind") == ALIMENTACION:
        return _meals(line) or float(line.get("amount") or 0)
    return float(line.get("amount") or 0)


def summarize(lines: list[dict], anticipo=0) -> dict:
    """Los mismos totales que calcula el Excel, para mostrarlos en pantalla y comprobar el archivo."""
    t = {k: 0.0 for k in KINDS}
    for ln in lines:
        t[ln["kind"]] += line_amount(ln)
    total = sum(t.values())
    adv = float(anticipo or 0)
    return {
        "hospedaje": t[HOSPEDAJE], "taxis_ciudad": t[TAXI_CIUDAD], "traslado_terminales": t[TAXI_TERMINAL],
        "pasajes": t[PASAJE], "alimentacion": t[ALIMENTACION], "otros": t[OTRO], "digitadores": t[DIGITADOR],
        "total": total, "neto_sin_digitadores": total - t[DIGITADOR],
        "reembolsar": max(total - adv, 0.0), "devolver": max(adv - total, 0.0),
    }


def _flag(v, yes: str, no: str):
    return None if v is None else (yes if v else no)


def _cell_value(field: str, line: dict):
    v = line.get(field)
    if field == "support":
        return _flag(v, "S", "N")
    if field == "approved":
        return _flag(v, "SI", "NO")
    if field == "date" and isinstance(v, datetime):
        return v.date()
    if field in ("amount", "iva", "breakfast", "lunch", "dinner", "snack", "unit_value"):
        return _num(v)
    return v if v != "" else None


def _put(ws, row: int, cols: dict, line: dict) -> None:
    for col, field in cols.items():
        ws[f"{col}{row}"].value = _cell_value(field, line)


def _insert_rows(ws, at_row: int, count: int, style_row: int) -> None:
    """Agrega `count` filas antes de `at_row` con el formato de `style_row` (la última fila de datos) y baja lo de abajo
    con sus alturas. Las fórmulas de lo que baja NO se ajustan solas: quien llama las reescribe."""
    if count <= 0:
        return
    heights = {r: d.height for r, d in ws.row_dimensions.items() if d.height is not None and r >= at_row}
    ws.insert_rows(at_row, count)
    for r in heights:
        ws.row_dimensions[r].height = None
    for r, h in heights.items():
        ws.row_dimensions[r + count].height = h
    h_style = ws.row_dimensions[style_row].height
    for i in range(count):
        r = at_row + i
        ws.row_dimensions[r].height = h_style
        for c in range(1, ws.max_column + 1):
            ws.cell(r, c)._style = copy(ws.cell(style_row, c)._style)


def _fill_table(ws, first: int, cap: int, total_row: int, offset: int, rows: list[dict], cols: dict) -> tuple[int, int]:
    """Llena una tabla de la plantilla. Devuelve (fila_total_real, nuevo_desplazamiento)."""
    first += offset
    total_row += offset
    extra = max(0, len(rows) - cap)
    _insert_rows(ws, total_row, extra, total_row - 1)
    total_row += extra
    for i, ln in enumerate(rows):
        _put(ws, first + i, cols, ln)
    return total_row, offset + extra


def _renumber(ws, first: int, last: int, col: str = "A") -> None:
    for i, r in enumerate(range(first, last + 1), start=1):
        ws[f"{col}{r}"].value = i


def _fill_header(ws, header: dict) -> None:
    def txt_or_num(v):
        s = "" if v is None else str(v).strip()
        return int(s) if s.isdigit() else (s or None)

    ws["C3"].value = header.get("consecutivo") or None
    ws["C4"].value = header.get("fecha_legalizacion")
    ws["C6"].value = header.get("responsable")
    ws["C7"].value = txt_or_num(header.get("cc"))
    ws["C8"].value = txt_or_num(header.get("cod_evento"))
    ws["C9"].value = header.get("evento")
    ws["C10"].value = header.get("ciudad")
    ws["C11"].value = header.get("fecha_evento")
    ws["C13"].value = _num(header.get("anticipo"))
    ws["C14"].value = _num(header.get("ce_final"))
    ws["C43"].value = header.get("observaciones_contables") or None


def _fill_vouchers(ws, vouchers: list[dict]) -> None:
    """Soportes: un comprobante por cada taxi sin recibo. El primero ya está en la plantilla; los demás se copian
    cada 14 filas (así venía en el ejemplo: el logo está en las filas 5, 19, 33…)."""
    step, top, bottom = 14, 5, 16
    block = {(r, c): ws.cell(r, c) for r in range(top, bottom + 1) for c in range(1, 6)}
    heights = {r: ws.row_dimensions[r].height for r in range(top, bottom + 1)}
    merges = [m for m in ws.merged_cells.ranges if m.min_row >= top and m.max_row <= bottom]
    logo = ws._images[0] if ws._images else None
    logo_bytes = None
    if logo is not None:      # leer sin consumir el archivo: `_data()` lo cierra y después no se puede guardar el libro
        logo.ref.seek(0)
        logo_bytes = logo.ref.read()
        logo.ref.seek(0)
    for k, v in enumerate(vouchers):
        off = step * k
        if k:
            for (r, c), src in block.items():
                dst = ws.cell(r + off, c)
                dst._style = copy(src._style)
                dst.value = src.value
            for r, h in heights.items():
                ws.row_dimensions[r + off].height = h
            for m in merges:
                ws.merge_cells(start_row=m.min_row + off, end_row=m.max_row + off, start_column=m.min_col, end_column=m.max_col)
            if logo_bytes:
                img = XLImage(io.BytesIO(logo_bytes))
                img.width, img.height = logo.width, logo.height
                img.anchor = deepcopy(logo.anchor)
                img.anchor._from.row += off
                if hasattr(img.anchor, "to"):
                    img.anchor.to.row += off
                ws.add_image(img)
        ws[f"C{5 + off}"].value = f"Nº    {k + 1} "
        ws[f"A{7 + off}"].value = v.get("name")
        ws[f"C{7 + off}"].value = _num(v.get("tax_id")) if str(v.get("tax_id") or "").isdigit() else v.get("tax_id")
        ws[f"D{7 + off}"].value = _cell_value("date", v)
        ws[f"A{9 + off}"].value = 1
        ws[f"B{9 + off}"].value = v.get("concept")
        ws[f"D{9 + off}"].value = _num(v.get("amount"))
        ws[f"B{11 + off}"].value = v.get("origin")
        ws[f"B{13 + off}"].value = v.get("destination")
        ws[f"D{16 + off}"].value = f"=SUM(D{9 + off}:D{15 + off})"
    if len(vouchers) > 1:
        ws.print_area = f"A2:E{bottom + step * (len(vouchers) - 1)}"


def build_workbook(header: dict, lines: list[dict]) -> bytes:
    """Devuelve el .xlsx de la legalización. `header`: consecutivo, fecha_legalizacion, responsable, cc, cod_evento, evento,
    ciudad, fecha_evento, anticipo, ce_final, observaciones_contables. `lines`: gastos (ver FIELDS), en el orden en que
    deben salir."""
    wb = openpyxl.load_workbook(TEMPLATE_PATH)
    by = {k: [ln for ln in lines if ln.get("kind") == k] for k in KINDS}

    # Hospedaje / pasajes / taxis a terminales: tres tablas en una hoja, cada una empuja a la de abajo si se llena
    ws = wb[S_HOSP]
    tot_hosp, off = _fill_table(ws, 10, 6, 16, 0, by[HOSPEDAJE], _COLS_HOSP)
    tot_pas, off = _fill_table(ws, 19, 4, 23, off, by[PASAJE], _COLS_RUTA)
    tot_ter, off = _fill_table(ws, 26, 9, 35, off, by[TAXI_TERMINAL], _COLS_RUTA)
    for tot, first in ((tot_hosp, tot_hosp - max(6, len(by[HOSPEDAJE]))), (tot_pas, tot_pas - max(4, len(by[PASAJE]))),
                       (tot_ter, tot_ter - max(9, len(by[TAXI_TERMINAL])))):
        ws[f"J{tot}"].value = f"=SUM(J{first}:J{tot - 1})"
        ws[f"K{tot}"].value = f"=SUM(K{first}:K{tot - 1})"

    # Taxis y transporte público en la ciudad
    ws = wb[S_TAXI]
    tot_taxi, _ = _fill_table(ws, 9, 23, 32, 0, by[TAXI_CIUDAD], _COLS_TAXI)
    for i, ln in enumerate(by[TAXI_CIUDAD]):
        ws[f"I{9 + i}"].value = "SI" if ln.get("vehicle") != "otro" else None
        ws[f"J{9 + i}"].value = "SI" if ln.get("vehicle") == "otro" else None
    ws[f"M{tot_taxi}"].value = f"=SUM(M9:M{tot_taxi - 1})"

    # Digitadores(as)
    ws = wb[S_DIG]
    tot_dig, _ = _fill_table(ws, 9, 20, 29, 0, by[DIGITADOR], _COLS_DIG)
    _renumber(ws, 9, tot_dig - 1)
    ws[f"H{tot_dig}"].value = f"=SUM(H9:H{tot_dig - 1})"
    ws.print_area = f"A1:H{tot_dig}"

    # Alimentación: M = suma de las comidas y O = valor; si solo hay un valor sin desglose, va directo en O
    ws = wb[S_ALIM]
    tot_ali, _ = _fill_table(ws, 9, 17, 26, 0, by[ALIMENTACION], _COLS_ALIM)
    _renumber(ws, 9, tot_ali - 1)
    for r in range(9, tot_ali):
        for col in "MO":
            ws[f"{col}{r}"]._style = copy(ws[f"{col}13"]._style)
        ws[f"M{r}"].value = f"=SUM(I{r}:L{r})"
        ws[f"O{r}"].value = f"=M{r}"
    for i, ln in enumerate(by[ALIMENTACION]):
        if not _meals(ln) and ln.get("amount"):
            ws[f"O{9 + i}"].value = _num(ln["amount"])
    ws[f"O{tot_ali}"].value = f"=SUM(O9:O{tot_ali - 1})"
    ws[f"P{tot_ali}"].value = f"=SUM(P9:P{tot_ali - 1})"
    ws.print_area = f"A1:Q{tot_ali}"

    # Otros gastos
    ws = wb[S_OTROS]
    tot_otr, _ = _fill_table(ws, 9, 28, 37, 0, by[OTRO], _COLS_OTROS)
    _renumber(ws, 9, tot_otr - 1)
    ws[f"J{tot_otr}"].value = f"=SUM(J9:J{tot_otr - 1})"

    # Soportes: taxis (ciudad y terminales) marcados «sin recibo»
    _fill_vouchers(wb[S_SOP], [ln for ln in by[TAXI_CIUDAD] + by[TAXI_TERMINAL] if ln.get("support") is False] or [{}])

    # Resumen
    ws = wb[S_RES]
    _fill_header(ws, header)
    ws["C17"].value = f"=+'{S_HOSP}'!J{tot_hosp}"
    ws["C18"].value = f"=+'{S_TAXI}'!M{tot_taxi}"
    ws["C19"].value = f"=+'{S_HOSP}'!J{tot_ter}"
    ws["C20"].value = f"=+'{S_HOSP}'!J{tot_pas}"
    ws["C21"].value = f"=+'{S_ALIM}'!O{tot_ali}"
    ws["C22"].value = f"=+'{S_OTROS}'!J{tot_otr}"
    ws["C23"].value = f"=+{S_DIG}!H{tot_dig}"
    # El ejemplo calculaba «a devolver» con signo negativo; aquí sale positivo
    ws["C29"].value = "=IF(C24>=C13,0,C13-C24)"

    wb.active = 0
    wb.calculation.fullCalcOnLoad = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name(event_code, event_name: str) -> str:
    """LEG-COD_<código>-<NOMBRE_DEL_EVENTO>.xlsx, como se llamaba el ejemplo (sin caracteres que rompan el nombre)."""
    base = "".join(ch if ch.isalnum() else "_" for ch in (event_name or "").upper().split(" - ")[0]).strip("_")
    base = "_".join(p for p in base.split("_") if p)
    return f"LEG-COD_{event_code}-{base}.xlsx" if base else f"LEG-COD_{event_code}.xlsx"
