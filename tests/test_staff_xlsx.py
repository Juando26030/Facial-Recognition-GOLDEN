"""Excel de «Usuarios del evento» (27-nov-2026): listado con el formato de Golden y respuestas del compromiso. Pruebas puras (sin base)."""
import io
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from openpyxl import load_workbook

from app import staff_xlsx

ROOT = Path(__file__).resolve().parent.parent


def _event(**kw):
    base = dict(event_code="23164", name="MOMENTO COLABORADORES 2026", start_date=date(2026, 11, 28), end_date=date(2026, 11, 28), event_time_start="15:00",
                event_time_end="22:00", location="CORFERIAS PABELLON 20", city="Bogotá", address="Cra 37 # 24-67", notes="", status="creado")
    base.update(kw)
    return SimpleNamespace(**base)


def test_when_line_dates_hours_place():
    assert staff_xlsx.when_line(_event()) == "SÁBADO 28 DE NOVIEMBRE DE 2026 de 3:00 p. m. a 10:00 p. m. — CORFERIAS PABELLON 20"
    two = staff_xlsx.when_line(_event(end_date=date(2026, 11, 29), event_time_start=None, event_time_end=None, location=None, city=None))
    assert two == "SÁBADO 28 DE NOVIEMBRE DE 2026 AL DOMINGO 29 DE NOVIEMBRE DE 2026"
    assert staff_xlsx.when_line(_event(start_date=None, end_date=None, location=None, city=None, event_time_start=None)) == "FECHA POR DEFINIR"


def test_list_workbook_matches_golden_format():
    people = [("Julieth Dayana Marquez", "1023371225"), ("Coordinadora Uno (coordinador temporal)", "coord.uno"), ("=HYPERLINK(1)", "0123")]
    wb = load_workbook(io.BytesIO(staff_xlsx.list_workbook(_event(), "FUNDACION GRUPO SOCIAL", "Juan David", people)))
    ws = wb.active
    assert ws["B2"].fill.fgColor.rgb.endswith("FFFF00") and ws["B2"].value == "SÁBADO 28 DE NOVIEMBRE DE 2026 de 3:00 p. m. a 10:00 p. m."      # línea amarilla
    assert "A3:C3" in {str(r) for r in ws.merged_cells.ranges}               # recuadro combinado
    head = ws["A3"].value
    assert head.startswith("[23164] FUNDACION GRUPO SOCIAL - MOMENTO COLABORADORES 2026") and "Coordinador: Juan David" in head and head.endswith("Estado: Creado")
    assert ws["A3"].font.b and ws["A3"].alignment.wrap_text
    assert [ws.cell(4, c).value for c in (1, 2, 3)] == [1, "JULIETH DAYANA MARQUEZ", 1023371225]
    assert ws["C4"].number_format == "#,##0" and ws["C4"].font.b and ws["A4"].border.left.style == "thin"
    assert ws["C5"].value == "coord.uno"                                       # usuario que no es número: texto
    assert ws["C6"].value == "0123"                                            # con cero inicial no se vuelve número (se perdería el cero)
    assert ws["B6"].value == "'=HYPERLINK(1)"                                  # nada de fórmulas
    assert ws.max_column == 3


def test_pledge_workbook_alerts_and_warning():
    cols = ["#", "Cédula", "Nombre", "Celular", "Alertas"]
    rows = [{"values": [1, 1014261854, "Paula", "3001234567", "Sí: toma medicamento"], "alert": True}, {"values": [2, 52543005, "Johana", "", ""], "alert": False}]
    ws = load_workbook(io.BytesIO(staff_xlsx.pledge_workbook(_event(), "Cliente", "", cols, rows))).active
    assert "DATOS SENSIBLES" in ws["A3"].value and "30 días" in ws["A3"].value
    assert [ws.cell(5, i).value for i in range(1, 6)] == cols
    assert ws["B6"].value == 1014261854 and ws["B6"].fill.fgColor.rgb.endswith("FFF2CC")
    assert ws["B7"].fill.fgColor.rgb in ("00000000", None) or not ws["B7"].fill.fill_type
    assert ws.auto_filter.ref == "A5:E7" and ws.freeze_panes == "D6"


def test_pledge_export_columns_cover_every_question():
    src = (ROOT / "app" / "pledge.py").read_text(encoding="utf-8")
    block = src.split("EXPORT_QUESTIONS = ", 1)[1].split("EXPORT_ALERTS", 1)[0]
    for q in ("T.Q_MEDICAL", "T.Q_MEDICATION", "T.Q_SUPPORT", "FID_MED_C", "FID_DRUG_C", "FID_SUPPORT_C"):
        assert q in block
    for name in ("FID_EM_NAME", "FID_EM_PHONE", "FID_CONTRACT", "FID_ATTEND", "FID_PHONE"):
        assert name in src.split("def export_rows", 1)[1]


def test_buttons_and_routes():
    tpl = (ROOT / "templates" / "kiosk_usuarios.html").read_text(encoding="utf-8")
    head = tpl.split('id="tituloCuentas"', 1)[1].split("approveAllBtn", 1)[0]
    assert "Descargar lista de usuarios en Excel" in head and "staff-users/export.xlsx" in head and "ic('download'" in head
    assert re.search(r'\{% if staff_role != "comercial" %\}<a[^>]+pledge/export\.xlsx', head)
    ev = (ROOT / "app" / "routers" / "events.py").read_text(encoding="utf-8")
    pl = (ROOT / "app" / "routers" / "pledge.py").read_text(encoding="utf-8")
    assert '"/events/{event_id}/staff-users/export.xlsx"' in ev
    assert '"/events/{event_id}/pledge/export.xlsx"' in pl and 'Depends(MANAGER)' in pl.split("def pledge_export", 1)[1].split("\n", 1)[0]
    assert 'audit_actions.record(db, staff, "pledge_export"' in pl
