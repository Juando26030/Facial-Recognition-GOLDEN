"""Neutraliza texto que Excel ejecutaría como fórmula en las exportaciones (Fase 0C: B2/D7/E6)."""
import re

_PHONE_LIKE = re.compile(r"^[+-][\d\s().-]+$")


def safe_cell(v):
    """Inyección de fórmulas (0C: B2/D7/E6): un texto que empieza por «=», «@» (o «+»/«-» que no sea un teléfono o un número) lo ejecutaría Excel como fórmula. Se le antepone «'»."""
    if isinstance(v, str) and v:
        if v[0] in ("=", "@", "\t", "\r") or (v[0] in ("+", "-") and not _PHONE_LIKE.match(v)):
            return "'" + v
    return v


def safe_workbook(wb):
    """Neutraliza todas las celdas de texto de un libro de openpyxl (los encabezados propios no empiezan por esos caracteres)."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str):
                    c.value = safe_cell(c.value)
    return wb


def safe_frame(df):
    """Lo mismo para un DataFrame de pandas antes de `to_excel`."""
    return df.astype(object).apply(lambda col: col.map(safe_cell))
