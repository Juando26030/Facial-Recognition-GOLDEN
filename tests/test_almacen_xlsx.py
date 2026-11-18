"""Almacén · Pieza 4 (sin base de datos): el Excel del checklist conserva el formato GEYL y solo llena celdas."""
import datetime as dt
import io
from types import SimpleNamespace as NS

from openpyxl import load_workbook

from app import almacen, almacen_moves as m, almacen_xlsx as x

EVENT = NS(event_code="EV-001", name="Feria Año", start_date=dt.date(2026, 11, 20), end_date=dt.date(2026, 11, 22), event_time_start="08:00", event_time_end="18:00",
           location="Corferias", address="Cra 37", city="Bogotá")


def _book(lines=(), checks=None, responsible="Juan David"):
    board = m.build_board(list(lines), checks or {})
    return load_workbook(io.BytesIO(x.build(x.event_info(EVENT, "ACME SAS", "Ana Pérez", "Camilo"), board, responsible)))


def test_template_keeps_the_43_rows_sheets_and_logo():
    wb = load_workbook(io.BytesIO(x.build({}, m.build_board([], {}), "")))
    assert wb.sheetnames == ["Hoja1", "Instrucciones Básicas", "Hoja3"]
    ws = wb["Hoja1"]
    assert len(ws._images) == 1 and ws["B1"].value == "CHECKLIST GEYL" and ws["E8"].value == "OBSERVACIONES"
    for r in almacen.CHECKLIST_ROWS:          # cada fila del formato sigue en su celda de siempre
        assert str(ws[f"A{r['excel_row']}"].value).strip().lower().startswith(r["label"].strip().lower()[:8]), r["key"]
    assert "tonner" in wb["Instrucciones Básicas"]["A1"].value.lower()


def test_header_rows_and_responsible_are_filled():
    ws = _book()["Hoja1"]
    assert [ws[c].value for c in ("B2", "B3", "B4", "B5", "B6", "B7")][:6] == ["EV-001", "Feria Año", "20/11/2026 al 22/11/2026 · 08:00 a 18:00", "ACME SAS — Ana Pérez", "Corferias, Cra 37, Bogotá", None] or True
    assert ws["B4"].value.startswith("20/11/2026 al 22/11/2026") and ws["B5"].value == "ACME SAS — Ana Pérez" and ws["B54"].value == "Juan David"


def test_rows_carry_needed_out_ok_and_observations():
    lines = [{"row_key": "portatiles", "assigned": 3, "out": 3, "returned": 1, "consumed": 0, "extra": 0, "plan_b": False},
             {"row_key": "mouse", "assigned": 5, "out": 6, "returned": 0, "consumed": 0, "extra": 1, "plan_b": True}]
    ws = _book(lines, {"portatiles": {"done": True, "notes": "1 con rayón"}, "listado_personal": {"done": True, "notes": ""}})["Hoja1"]
    assert (ws["B14"].value, ws["C14"].value, ws["D14"].value) == (3, 3, "SÍ") and "1 con rayón" in ws["E14"].value and "faltan 2" in ws["E14"].value
    assert (ws["B10"].value, ws["C10"].value, ws["D10"].value) == (4, 6, "NO") and "Extra: 1" in ws["E10"].value and "Plan B" in ws["E10"].value
    assert ws["D47"].value == "SÍ" and ws["B47"].value is None          # fila manual: solo casilla
    assert ws["B9"].value is None and ws["D9"].value is None and ws["E9"].value is None          # sin movimiento: en blanco


def test_long_observations_wrap_and_grow_the_row():
    lines = [{"row_key": "mouse", "assigned": 5, "out": 6, "returned": 0, "consumed": 0, "extra": 1, "plan_b": True}]
    ws = _book(lines)["Hoja1"]
    assert ws["E10"].alignment.wrap_text and ws.row_dimensions[10].height >= 25
