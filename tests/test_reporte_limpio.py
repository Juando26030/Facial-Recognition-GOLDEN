"""Reporte del evento (17-nov-2026): casilla «Eliminar del reporte campos no usados» y hojas «Personas registradas» / «Personas no registradas»."""
import pathlib
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook

from app.models import AccessLog
from app.reports import ReportManager, prune_unused_columns

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_prune_drops_only_columns_nobody_filled_and_keeps_identity_and_state():
    df = pd.DataFrame({
        "Cédula": ["1", "2"], "Nombres": ["A", "B"], "Apellidos": ["", ""],
        "Cargo": ["", "  "], "Ciudad": ["Cali", ""], "Origen de carga": ["Base (Excel)", "Base (Excel)"], "Estado": ["No registrado", "No registrado"],
        "Tipo de Registro": ["No registrado", "No registrado"], "Fecha de Registro": ["", ""], "Registrado por": ["", ""],
    })
    out = prune_unused_columns(df)
    assert list(out.columns) == ["Cédula", "Nombres", "Apellidos", "Ciudad", "Origen de carga", "Estado"]
    assert len(out) == 2


def test_prune_keeps_registration_columns_when_someone_registered():
    df = pd.DataFrame({"Cédula": ["1"], "Nombres": ["A"], "Apellidos": ["B"], "Origen de carga": ["x"], "Estado": ["Registrado"],
                       "Tipo de Registro": ["Tradicional"], "Fecha de Registro": ["2026-11-12"], "Registrado por": [""]})
    assert list(prune_unused_columns(df).columns) == ["Cédula", "Nombres", "Apellidos", "Origen de carga", "Estado", "Tipo de Registro", "Fecha de Registro"]


def test_export_checkbox_is_off_by_default_and_sent_to_the_api():
    tpl = (ROOT / "templates/kiosk_estadisticas.html").read_text(encoding="utf-8")
    box = tpl[tpl.index('id="exportPrune"') - 80:tpl.index('id="exportPrune"') + 200]
    assert "checked" not in box and "Eliminar del reporte campos no usados" in box
    assert "prune_unused" in (ROOT / "static/js/stats-event.js").read_text(encoding="utf-8")


def _setup(factory, db):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso", coordinator=coord)
    for uid in ("1001", "1002", "1003"):
        factory.person(ev, uid)
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, record_type="Nuevo", registration_method="tradicional", timestamp=datetime(2026, 11, 12, 15, 0, 5)))
    db.commit()
    return ev


def _ids(ws):
    return [r[0] for r in ws.iter_rows(min_row=6, values_only=True) if r and r[0]]


def test_report_has_registered_and_not_registered_sheets(client, factory, db, tmp_path):
    ev = _setup(factory, db)
    out = tmp_path / "r.xlsx"
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(out))
    wb = load_workbook(out)
    assert wb.sheetnames[-2:] == ["Personas registradas", "Personas no registradas"]
    assert sorted(_ids(wb["Reporte"])) == ["1001", "1002", "1003"]
    assert _ids(wb["Personas registradas"]) == ["1001"]
    assert sorted(_ids(wb["Personas no registradas"])) == ["1002", "1003"]
    header = [c.value for c in wb["Reporte"][5]]
    assert [c.value for c in wb["Personas registradas"][5]] == header == [c.value for c in wb["Personas no registradas"][5]]


def test_prune_option_removes_empty_columns_only_when_asked(client, factory, db, tmp_path):
    ev = _setup(factory, db)
    full, lean = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(full))
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(lean), prune_unused=True)
    h_full = [c.value for c in load_workbook(full)["Reporte"][5]]
    wb = load_workbook(lean)
    h_lean = [c.value for c in wb["Reporte"][5]]
    assert len(h_lean) <= len(h_full) and {"Cédula", "Nombres", "Apellidos", "Estado"} <= set(h_lean)
    assert "Registrado por" in h_full and "Registrado por" not in h_lean               # nadie lo tiene: se quita solo con la casilla
    assert "Hora de Registro" in [c.value for c in wb["Personas registradas"][5]]
    assert "Hora de Registro" not in [c.value for c in wb["Personas no registradas"][5]]   # en esa hoja nadie se registró
