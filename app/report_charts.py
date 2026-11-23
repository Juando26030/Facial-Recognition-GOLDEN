"""Hoja «Gráficos» del Excel del reporte del evento (Fase 10, bloque E). Sin base de datos: recibe la tabla del reporte (pandas) y los cambios de datos ya leídos y arma gráficos NATIVOS de Excel
(openpyxl.chart), que se pueden editar.

1) `build_specs(df, field_types, changes)` decide, por cada variable del reporte, el gráfico adecuado (pura, se prueba sin Excel):
   * sí/no  -> dona;  pocas categorías (hasta 6) -> dona;  muchas (ciudad, empresa, cargo…) -> barras horizontales con las 10 principales y «Otros»;
   * numéricas -> histograma (columnas por rangos);  registro por hora -> columnas;  registro por día -> línea (columnas si hay un solo día);
   * historial de cambios -> barras por campo y columnas por día.
   Se omiten las columnas que identifican a una persona (cédula, nombres, correo, teléfono), las firmas y los textos casi únicos (no hay nada que contar).
2) `build_sheet(wb, specs)` los dibuja en una cuadrícula de 2 por fila, con título en español, etiquetas de datos y la paleta de Golden. Los datos de apoyo van en columnas ocultas de la misma hoja.
"""
import re
from collections import Counter
from typing import Optional

from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint, Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

NAVY, GOLD, OTHER_GRAY, LIGHT = "0A0E2E", "D4AF37", "9AA0B5", "E6E8F0"
PALETTE = ["D4AF37", "5B7DB1", "2E9AA0", "D98C4A", "8FB04C", "B77FA3", "7F9BA6", "E0C98A", "C86A6A", "A0A0A0"]          # claros: la etiqueta (texto oscuro) se lee sobre cualquier porción
TOP_N = 10
DONUT_MAX = 6
SKIP_HEADERS = {"Cédula", "Nombres", "Apellidos", "Teléfono", "Correo Electrónico", "Hora de Registro", "Fecha de Registro"}
SKIP_TYPES = {"signature"}
YES_NO = {"sí", "si", "no", "true", "false"}
SHEET = "Gráficos"
SHEET_REGISTERED = "Gráficos registrados"          # hotfix 23-nov-2026: las mismas gráficas, solo con las personas registradas
SHEET_NOT_REGISTERED = "Gráficos no registrados"   # … y solo con las no registradas
DATA_COL = 27                    # AA: datos de apoyo (columnas ocultas)
CHART_W, CHART_H = 16.5, 8.6     # cm
ROWS_PER_CHART = 19
LEFT_COL, RIGHT_COL = 2, 11      # B y K


def _label(v, n=40) -> str:
    s = str(v).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def top_with_others(counter: Counter, top: int = TOP_N) -> tuple:
    """([etiquetas], [valores]) con las `top` más frecuentes y el resto sumado en «Otros» (solo si sobra algo)."""
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    head, rest = ordered[:top], ordered[top:]
    cats = [_label(k) for k, _ in head]
    vals = [v for _, v in head]
    if rest:
        cats.append("Otros")
        vals.append(sum(v for _, v in rest))
    return cats, vals


def _to_float(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def histogram(values: list, bins: int = 8) -> tuple:
    lo, hi = min(values), max(values)
    if lo == hi:
        return [f"{lo:g}"], [len(values)]
    bins = max(2, min(bins, int(len(set(values)))))
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / width), bins - 1)] += 1
    cats = [f"{round(lo + i * width, 1):g}–{round(lo + (i + 1) * width, 1):g}" for i in range(bins)]
    return cats, counts


def column_spec(label: str, raw: list, hint: Optional[str] = None) -> Optional[dict]:
    """Spec de gráfico para una columna del reporte (lista de textos, vacíos incluidos) o None si no vale la pena graficarla."""
    vals = [str(v).strip() for v in raw if v is not None and str(v).strip() != "" and str(v).strip().lower() != "nan"]
    n = len(vals)
    if n == 0 or hint in SKIP_TYPES or all(v == "Firmado" for v in vals):
        return None
    low = {v.lower() for v in vals}
    if low <= YES_NO:
        yes = sum(1 for v in vals if v.lower() in ("sí", "si", "true"))
        cats, nums = ["Sí", "No"], [yes, n - yes]
        return {"section": "Variables del reporte", "kind": "doughnut", "title": f"{label}: sí y no", "cats": cats, "vals": nums}
    nums_f = [_to_float(v) for v in vals]
    if hint == "number" or (sum(x is not None for x in nums_f) >= 0.9 * n and len(set(vals)) > 8):
        good = [x for x in nums_f if x is not None]
        if good:
            cats, counts = histogram(good)
            return {"section": "Variables del reporte", "kind": "col", "title": f"{label}: distribución de valores", "cats": cats, "vals": counts}
    items = []
    for v in vals:
        if label == "Categoría":
            items.extend(p.strip() for p in v.split(", "))
        else:
            items.append(v)
    counter = Counter(items)
    k = len(counter)
    if k > 0.8 * len(items) and len(items) > 20:
        return None                                              # casi cada fila distinta (texto libre): nada que contar
    if k <= DONUT_MAX:
        cats, nums = top_with_others(counter, DONUT_MAX)
        return {"section": "Variables del reporte", "kind": "doughnut", "title": f"{label}: proporción de personas", "cats": cats, "vals": nums}
    cats, nums = top_with_others(counter)
    suffix = " (principales y «Otros»)" if cats[-1] == "Otros" else ""
    return {"section": "Variables del reporte", "kind": "barh", "title": f"{label}: personas{suffix}", "cats": cats, "vals": nums}


def time_specs(hours: list, days: list) -> list:
    """Registros por hora (columnas) y por día (línea). `hours`: textos «HH:MM:SS»; `days`: textos «AAAA-MM-DD». Vacíos se ignoran."""
    out = []
    hs = []
    for h in hours:
        m = re.match(r"^(\d{1,2}):", str(h or "").strip())
        if m:
            hs.append(int(m.group(1)))
    if hs:
        c = Counter(hs)
        cats = [f"{h:02d}:00" for h in range(min(hs), max(hs) + 1)]
        out.append({"section": "Registros en el tiempo", "kind": "col", "title": "Registros por hora del día", "cats": cats, "vals": [c.get(h, 0) for h in range(min(hs), max(hs) + 1)]})
    ds = [str(d).strip() for d in days if re.match(r"^\d{4}-\d{2}-\d{2}$", str(d or "").strip())]
    if ds:
        c = Counter(ds)
        keys = sorted(c)
        cats = [f"{k[8:10]}/{k[5:7]}" for k in keys]
        out.append({"section": "Registros en el tiempo", "kind": "line" if len(keys) > 1 else "col", "title": "Registros por día", "cats": cats, "vals": [c[k] for k in keys]})
    return out


def change_specs(changes: list) -> list:
    """Gráficos del historial de datos modificados: cambios por campo (barras) y por día (columnas). `changes`: dicts con `label` y `at_local` («dd/mm/aaaa hh:mm»)."""
    if not changes:
        return []
    by_field = Counter(c.get("label") or c.get("field") or "—" for c in changes)
    cats, vals = top_with_others(by_field)
    out = [{"section": "Historial de cambios de datos", "kind": "barh", "title": "Cambios de datos por campo", "cats": cats, "vals": vals}]
    days = Counter()
    for c in changes:
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", str(c.get("at_local") or ""))
        if m:
            days[(m.group(3), m.group(2), m.group(1))] += 1
    if days:
        keys = sorted(days)
        out.append({"section": "Historial de cambios de datos", "kind": "line" if len(keys) > 2 else "col", "title": "Cambios de datos por día", "cats": [f"{k[2]}/{k[1]}" for k in keys], "vals": [days[k] for k in keys]})
    return out


def build_specs(df, field_types: Optional[dict] = None, changes: Optional[list] = None) -> list:
    """Todos los gráficos del reporte, en orden: variables, registros en el tiempo e historial de cambios. `field_types`: {encabezado: tipo del campo} (pista, opcional)."""
    field_types = field_types or {}
    specs = []
    for header in list(df.columns):
        if header in SKIP_HEADERS:
            continue
        values = df[header].tolist()
        if header == "Tipo de Registro":
            values = [v for v in values if v != "No registrado"]          # solo de quienes sí se registraron
        spec = column_spec(header, values, field_types.get(header))
        if spec:
            specs.append(spec)
    if "Hora de Registro" in df.columns and "Fecha de Registro" in df.columns:
        specs.extend(time_specs(df["Hora de Registro"].tolist(), df["Fecha de Registro"].tolist()))
    specs.extend(change_specs(changes or []))
    order = {"Variables del reporte": 0, "Registros en el tiempo": 1, "Historial de cambios de datos": 2}
    return sorted(specs, key=lambda s: order[s["section"]])          # estable: conserva el orden dentro de cada sección


# ------------------------------------------------------------------ dibujo
def _labels(show_pct: bool = False) -> DataLabelList:
    d = DataLabelList()
    d.showVal = True
    d.showPercent = show_pct
    d.showCatName = False
    d.showSerName = False
    d.showLegendKey = False
    return d


def _make_chart(spec: dict, cats_ref, vals_ref):
    kind = spec["kind"]
    if kind == "doughnut":
        ch = DoughnutChart()
        ch.holeSize = 55
        ch.dataLabels = _labels(show_pct=True)
        ch.legend.position = "r"
    elif kind in ("barh", "col"):
        ch = BarChart()
        ch.type = "bar" if kind == "barh" else "col"
        ch.gapWidth = 50
        ch.dataLabels = _labels()
        ch.legend = None
        ch.y_axis.majorGridlines.spPr = GraphicalProperties(ln=None)
        ch.y_axis.numFmt = "0"
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        if kind == "barh":
            ch.x_axis.scaling.orientation = "maxMin"          # la más grande arriba
            ch.y_axis.crosses = "max"                          # y la escala numérica abajo
    else:
        ch = LineChart()
        ch.dataLabels = _labels()
        ch.legend = None
        ch.y_axis.numFmt = "0"
        ch.x_axis.delete = False
        ch.y_axis.delete = False
    ch.add_data(vals_ref, titles_from_data=True)
    ch.set_categories(cats_ref)
    ch.title = spec["title"]
    ch.width, ch.height = CHART_W, CHART_H
    ch.visible_cells_only = False                              # los datos de apoyo están en columnas ocultas: igual se dibujan
    s = ch.series[0]
    if kind == "doughnut":
        for i, cat in enumerate(spec["cats"]):
            pt = DataPoint(idx=i)
            pt.graphicalProperties = GraphicalProperties(solidFill=OTHER_GRAY if cat == "Otros" else PALETTE[i % len(PALETTE)])
            s.dPt.append(pt)
    elif kind == "barh":          # categorías: un color por barra (hotfix 23-nov-2026), «Otros» en gris
        s.graphicalProperties = GraphicalProperties(solidFill=GOLD)
        s.graphicalProperties.line.solidFill = NAVY
        for i, cat in enumerate(spec["cats"]):
            pt = DataPoint(idx=i)
            pt.graphicalProperties = GraphicalProperties(solidFill=OTHER_GRAY if cat == "Otros" else PALETTE[i % len(PALETTE)])
            pt.graphicalProperties.line.solidFill = NAVY
            s.dPt.append(pt)
    elif kind == "col":
        s.graphicalProperties = GraphicalProperties(solidFill=GOLD)
        s.graphicalProperties.line.solidFill = NAVY
        if spec["cats"] and spec["cats"][-1] == "Otros":
            pt = DataPoint(idx=len(spec["cats"]) - 1)
            pt.graphicalProperties = GraphicalProperties(solidFill=OTHER_GRAY)
            s.dPt.append(pt)
    else:
        s.graphicalProperties.line.solidFill = NAVY
        s.graphicalProperties.line.width = 28000
        s.marker = Marker(symbol="circle", size=7)
        s.marker.graphicalProperties = GraphicalProperties(solidFill=GOLD)
        s.marker.graphicalProperties.line.solidFill = NAVY
        s.smooth = False
    return ch


def build_sheet(wb, specs: list, index: Optional[int] = None, name: str = SHEET, title: str = "Gráficos del reporte", empty_text: str = "Todavía no hay datos suficientes para graficar."):
    """Crea una hoja de gráficos (por defecto «Gráficos») en `wb` (openpyxl) con los `specs`. Devuelve la hoja. Sin specs deja un aviso claro."""
    ws = wb.create_sheet(name, index) if index is not None else wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = GOLD
    ws.column_dimensions["A"].width = 2.5
    for c in range(2, 21):
        ws.column_dimensions[get_column_letter(c)].width = 9.5
    navy = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
    ws.merge_cells("A1:T1")
    ws["A1"] = title
    ws["A1"].font = Font(name="Calibri", size=20, bold=True, color="FFFFFF")
    ws["A1"].fill = navy
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 40
    ws.merge_cells("A2:T2")
    ws["A2"] = "Gráficos nativos de Excel (se pueden editar). Los datos de apoyo están en las columnas AA y AB, ocultas: clic derecho sobre las columnas → Mostrar."
    ws["A2"].font = Font(name="Calibri", size=9, italic=True, color="5B6078")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    if not specs:
        ws["B4"] = empty_text
        ws["B4"].font = Font(name="Calibri", size=12, color="5B6078")
        return ws
    ws.column_dimensions[get_column_letter(DATA_COL)].hidden = True
    ws.column_dimensions[get_column_letter(DATA_COL + 1)].hidden = True
    data_row = 1
    row = 4
    section = None
    slot = 0                                                    # 0 = izquierda, 1 = derecha
    for spec in specs:
        if spec["section"] != section:
            if slot == 1:
                row += ROWS_PER_CHART
            section, slot = spec["section"], 0
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=19)
            c = ws.cell(row=row, column=2, value=section.upper())
            c.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
            c.alignment = Alignment(horizontal="left", vertical="center")
            for col in range(2, 20):
                ws.cell(row=row, column=col).border = Border(bottom=Side(style="medium", color=GOLD))
            ws.row_dimensions[row].height = 24
            row += 2
        # datos de apoyo (columnas ocultas): encabezado con el título y luego categorías/valores
        ws.cell(row=data_row, column=DATA_COL, value=spec["title"])
        ws.cell(row=data_row, column=DATA_COL + 1, value="Personas" if spec["section"] != "Historial de cambios de datos" else "Cambios")
        for i, (cat, val) in enumerate(zip(spec["cats"], spec["vals"]), start=1):
            ws.cell(row=data_row + i, column=DATA_COL, value=str(cat))
            ws.cell(row=data_row + i, column=DATA_COL + 1, value=val)
        n = len(spec["cats"])
        cats_ref = Reference(ws, min_col=DATA_COL, min_row=data_row + 1, max_row=data_row + n)
        vals_ref = Reference(ws, min_col=DATA_COL + 1, min_row=data_row, max_row=data_row + n)
        data_row += n + 2
        chart = _make_chart(spec, cats_ref, vals_ref)
        ws.add_chart(chart, f"{get_column_letter(LEFT_COL if slot == 0 else RIGHT_COL)}{row}")
        if slot == 1:
            row += ROWS_PER_CHART
        slot = 1 - slot
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    return ws
