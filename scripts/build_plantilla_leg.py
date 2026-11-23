"""Construye `app/xlsx_templates/PLANTILLA-LEG.xlsx` a partir del Excel de ejemplo de una legalización real.

Uso (una sola vez, o si el formato cambia):
    python scripts/build_plantilla_leg.py <ejemplo.xlsx> [salida.xlsx]

Qué hace con el ejemplo (LEG-COD_23736-MOSCA_LABORATORIO.xlsx):
  - quita la hoja AUDITORIA (decisión de Juan David, 14-nov-2026: no se usa);
  - vacía todos los datos de ejemplo y deja el formato, los logos, las celdas combinadas y las fórmulas;
  - deja el término «Digitadores(as)» (la hoja se llama PagoDigitadores y el rubro del resumen también);
  - corrige las fórmulas que en el ejemplo estaban incompletas (Alimentación filas 9-12, IVA de Alimentación).
Las columnas IVA / SOPORTE / APROBADO que el formato original deja ocultas se mantienen ocultas.
"""
from __future__ import annotations

import sys
from copy import copy
from pathlib import Path

import openpyxl

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "app" / "xlsx_templates" / "PLANTILLA-LEG.xlsx"


def clear(ws, ref: str) -> None:
    for row in ws[ref]:
        for cell in row:
            cell.value = None


def build(src: str, dst: Path) -> None:
    wb = openpyxl.load_workbook(src)
    del wb["AUDITORIA"]

    # Resumen
    ws = wb["Legalización"]
    for ref in ("C3", "C4", "C6", "C7", "C8", "C9", "C10", "C11", "C13", "C14", "C43"):
        ws[ref].value = None
    ws["B23"].value = "Pago a digitadores(as) con soportes de Documentos Equivalentes y Comprobantes de Egreso"

    # Hospedaje, pasajes y taxis a terminales
    ws = wb["Hosped-Pasajes-TransTermin"]
    for ref in ("A10:M15", "A19:M22", "A26:M34"):
        clear(ws, ref)

    # Taxis y transporte público
    clear(wb["Taxis-TransPúblico"], "A9:O31")

    # Digitadores(as)
    ws = wb["PagoNiñas"]
    ws.title = "PagoDigitadores"
    clear(ws, "B9:H28")
    wb["Legalización"]["C23"].value = "=+PagoDigitadores!H29"

    # Alimentación: las fórmulas de las filas 9-12 faltaban en el ejemplo; el IVA sumaba un rango corto
    ws = wb["Gastos de Alimentación"]
    clear(ws, "B9:R25")
    for i, r in enumerate(range(9, 26), start=1):
        ws[f"A{r}"].value = i
        ws[f"M{r}"].value = f"=SUM(I{r}:L{r})"
        ws[f"O{r}"].value = f"=M{r}"
        for col in "MO":
            ws[f"{col}{r}"]._style = copy(ws[f"{col}13"]._style)
    ws["O26"].value = "=SUM(O9:O25)"
    ws["P26"].value = "=SUM(P9:P25)"

    # Otros gastos: la fila 9 no tenía número
    ws = wb["Otros gastos"]
    clear(ws, "B9:M36")
    ws["A9"]._style = copy(ws["A10"]._style)
    for i, r in enumerate(range(9, 37), start=1):
        ws[f"A{r}"].value = i
    ws["J37"].value = "=SUM(J9:J36)"

    # Soportes: un comprobante en blanco (el generador lo copia una vez por gasto sin recibo)
    ws = wb["Soportes"]
    for ref in ("A7", "C7", "D7", "A9", "D9", "B11", "B13"):
        ws[ref].value = None

    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    build(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT)
    print("Plantilla escrita en", sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT)
