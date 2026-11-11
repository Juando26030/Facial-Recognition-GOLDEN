"""Fase 10 (E): portada y gráficos del Excel del reporte (app/report_cover.py, app/report_charts.py, app/report_book.py). Corren SIN base de datos (datos simulados):
estructura del libro (hojas y orden), gráficos nativos presentes, elección del tipo de gráfico por variable, tolerancia a logos ausentes o dañados y a tablas vacías."""
import io
import types
from datetime import date

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from PIL import Image

from app import report_book, report_charts, report_cover


def png(w, h, color=(10, 120, 160)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def make_df(n=60):
    rows = []
    for i in range(n):
        reg = i % 5 != 0
        rows.append({"Cédula": str(1000 + i), "Nombres": f"P{i}", "Apellidos": "X", "Teléfono": "300", "Correo Electrónico": f"p{i}@x.com",
                     "Cargo": ["GERENTE", "ANALISTA", "JEFE", "DIRECTOR", "ASISTENTE", "COORDINADOR", "CONSULTOR", "PRACTICANTE"][i % 8],
                     "Entidad": [f"EMPRESA {k}" for k in range(14)][i % 14], "Tipo de Asistente": ["VIP", "Prensa", "Invitado"][i % 3],
                     "Certificado": "Sí" if i % 2 else "No", "Edad": 20 + (i % 40), "Firma": "Firmado" if i % 2 else "", "Categoría": "General, VIP" if i % 4 == 0 else "General",
                     "Estado": "Registrado" if reg else "No registrado", "Tipo de Registro": "QR" if reg else "No registrado",
                     "Fecha de Registro": ("2026-11-12" if i % 2 else "2026-11-13") if reg else "", "Hora de Registro": f"{8 + i % 6:02d}:15:00" if reg else ""})
    return pd.DataFrame(rows)


CHANGES = [{"label": "Ciudad", "at_local": "10/11/2026 09:00"}, {"label": "Correo", "at_local": "10/11/2026 10:00"}, {"label": "Ciudad", "at_local": "11/11/2026 08:00"}]


def event(**kw):
    base = dict(id=7, name="Congreso Nacional", event_code="CN26", start_date=date(2026, 11, 12), end_date=date(2026, 11, 14), location="Ágora", city="Bogotá",
                event_type=types.SimpleNamespace(name="Congreso"), coordinator=types.SimpleNamespace(full_name="Ana Coord", username="ac"),
                commercial=types.SimpleNamespace(full_name="Carlos Comercial", username="cc"), logo_mode="custom", logo_path="ev.png")
    base.update(kw)
    return types.SimpleNamespace(**base)


def key_of(*p):
    return "/".join(map(str, p))


def book(files=None, ev=None, df=None, changes=None):
    wb = Workbook()
    wb.active.title = "Reporte"
    report_book.decorate(wb, ev or event(), "Cliente S.A.S.", "acme", df if df is not None else make_df(), {"Edad": "number"}, CHANGES if changes is None else changes, lambda k: (files or {}).get(k), key_of)
    return wb


def charts_of(wb):
    return wb[report_charts.SHEET]._charts


# ------------------------------------------------------------------ estructura
def test_sheet_order_and_cover_first():
    wb = book()
    assert wb.sheetnames == ["Portada", "Reporte", "Gráficos"]
    assert wb.active.title == "Portada"
    assert [ws.sheet_view.tabSelected for ws in wb.worksheets] == [True, False, False]          # una sola hoja seleccionada
    assert wb["Portada"].sheet_view.showGridLines is False and wb["Gráficos"].sheet_view.showGridLines is False


def test_cover_content_and_totals_exclude_nothing_extra():
    wb = book()
    text = " ".join(str(c.value) for row in wb["Portada"].iter_rows() for c in row if c.value)
    for must in ("REPORTE DEL EVENTO", "Congreso Nacional", "Cliente S.A.S.", "Del 12 al 14 de noviembre de 2026", "Ágora, Bogotá", "Congreso", "Ana Coord", "Carlos Comercial",
                 "(hora de Colombia)", "Ley 1581", "PERSONAS EN LA BASE"):
        assert must in text, must
    df = make_df()
    assert str(len(df)) in text and "Datos modificados".upper() in text


def test_single_logo_event_logo_wins_and_golden_stays_as_small_footer_mark():
    wb = book({"ev.png": png(600, 200)})
    assert len(wb["Portada"]._images) == 2                          # logo del evento + marca pequeña de Golden en el pie
    main, mark = wb["Portada"]._images
    assert main.width > mark.width and mark.height <= report_cover.FOOTER_LOGO_BOX[1]


def test_without_event_logo_only_golden_appears_once():
    for ev in (event(logo_mode="default"), event(logo_path=None)):
        wb = book({"ev.png": png(600, 200)}, ev=ev)
        assert len(wb["Portada"]._images) == 1                       # Golden como logo principal, sin repetirlo en el pie


def test_client_and_extra_logo_files_are_never_read():
    asked = []
    wb = Workbook()
    wb.active.title = "Reporte"
    report_book.decorate(wb, event(), "Cliente", "acme", make_df(), {}, [], lambda k: (asked.append(k), png(50, 50))[1], key_of)
    assert asked == ["ev.png"]                                       # solo el logo del evento; nada de client-logo ni extra-logo


def test_missing_corrupt_or_hidden_logos_do_not_break():
    wb = book({"ev.png": b"no es una imagen"})
    assert len(wb["Portada"]._images) == 1                           # logo dañado: se usa el de Golden
    wb = book({}, ev=event(logo_path="otro.png"))
    assert len(wb["Portada"]._images) == 1
    assert report_cover.prepare_logo(None) is None and report_cover.prepare_logo(b"x") is None


def test_logo_is_resized_keeping_proportion():
    data, w, h = report_cover.prepare_logo(png(2000, 500))
    assert w <= report_cover.LOGO_BOX[0] and h <= report_cover.LOGO_BOX[1] and abs(w / h - 4) < 0.1
    small = report_cover.prepare_logo(png(40, 20))
    assert (small[1], small[2]) == (40, 20)                                        # no agranda


def test_empty_report_still_gets_cover_and_a_charts_notice():
    wb = book(df=make_df(0).reindex(columns=make_df(1).columns), changes=[])
    assert wb.sheetnames == ["Portada", "Reporte", "Gráficos"]
    assert charts_of(wb) == []
    assert "Todavía no hay datos" in wb["Gráficos"]["B4"].value


def test_dates_text_variants():
    assert report_cover.dates_text(date(2026, 11, 12), date(2026, 11, 12)) == "12 de noviembre de 2026"
    assert report_cover.dates_text(date(2026, 11, 30), date(2026, 12, 2)) == "Del 30 de noviembre de 2026 al 2 de diciembre de 2026"
    assert report_cover.dates_text(None, None) == "Por definir"


# ------------------------------------------------------------------ gráficos
def specs():
    return {s["title"]: s for s in report_charts.build_specs(make_df(), {"Edad": "number"}, CHANGES)}


def test_chart_type_by_variable():
    sp = specs()
    assert sp["Certificado: sí y no"]["kind"] == "doughnut"
    assert sp["Tipo de Asistente: proporción de personas"]["kind"] == "doughnut"          # 3 categorías
    assert sp["Estado: proporción de personas"]["kind"] == "doughnut"
    assert sp["Edad: distribución de valores"]["kind"] == "col"                              # numérica: histograma
    ent = next(s for t, s in sp.items() if t.startswith("Entidad"))
    assert ent["kind"] == "barh" and len(ent["cats"]) == 11 and ent["cats"][-1] == "Otros" and sum(ent["vals"]) == 60          # top 10 + Otros, sin perder a nadie
    assert sp["Registros por hora del día"]["kind"] == "col" and sp["Registros por día"]["kind"] == "line"
    assert sp["Cambios de datos por campo"]["kind"] == "barh" and sp["Cambios de datos por campo"]["vals"] == [2, 1]
    assert sp["Cambios de datos por día"]["kind"] == "col" and sp["Cambios de datos por día"]["cats"] == ["10/11", "11/11"]


def test_identifiers_signatures_and_registration_type_noise_are_skipped():
    titles = " ".join(specs())
    for skipped in ("Cédula", "Nombres", "Apellidos", "Teléfono", "Correo", "Firma"):
        assert skipped not in titles, skipped
    tr = specs()["Tipo de Registro: proporción de personas"]
    assert tr["cats"] == ["QR"]                                                              # «No registrado» no es un tipo de registro


def test_multi_value_category_counts_each_one():
    sp = specs()["Categoría: proporción de personas"]
    got = dict(zip(sp["cats"], sp["vals"]))
    assert got["General"] == 60 and got["VIP"] == 15


def test_near_unique_free_text_is_not_charted():
    df = pd.DataFrame({"Comentario": [f"texto {i}" for i in range(40)], "Estado": ["Registrado"] * 40})
    assert [s["title"] for s in report_charts.build_specs(df)] == ["Estado: proporción de personas"]


def test_native_charts_two_per_row_with_titles_and_labels():
    wb = book()
    charts = charts_of(wb)
    assert len(charts) == len(report_charts.build_specs(make_df(), {"Edad": "number"}, CHANGES)) >= 12
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
    anchors = [(column_index_from_string(coordinate_from_string(c.anchor)[0]) - 1, coordinate_from_string(c.anchor)[1]) for c in charts]
    assert {a[0] for a in anchors} == {report_charts.LEFT_COL - 1, report_charts.RIGHT_COL - 1}
    for c in charts:
        assert c.title is not None and c.dataLabels is not None and c.dataLabels.showVal
    left_rows = [r for col, r in anchors if col == report_charts.LEFT_COL - 1]
    assert left_rows == sorted(left_rows)
    ws = wb[report_charts.SHEET]
    assert ws.column_dimensions["AA"].hidden and ws.column_dimensions["AB"].hidden          # datos de apoyo ocultos


def test_workbook_roundtrip_and_xlsx_has_chart_parts(tmp_path):
    out = tmp_path / "r.xlsx"
    book().save(out)
    wb = load_workbook(out)
    assert wb.sheetnames == ["Portada", "Reporte", "Gráficos"]
    import zipfile
    names = zipfile.ZipFile(out).namelist()
    assert sum(n.startswith("xl/charts/chart") for n in names) >= 12 and any(n.startswith("xl/media/") for n in names)


def test_chart_failure_does_not_remove_the_cover(monkeypatch):
    monkeypatch.setattr(report_charts, "build_specs", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla simulada")))
    wb = book()
    assert wb.sheetnames == ["Portada", "Reporte"]


def test_histogram_and_top_helpers():
    assert report_charts.histogram([5, 5, 5]) == (["5"], [3])
    cats, counts = report_charts.histogram(list(range(0, 100)))
    assert sum(counts) == 100 and len(cats) == 8
    from collections import Counter
    cats, vals = report_charts.top_with_others(Counter({f"c{i}": i + 1 for i in range(15)}), 10)
    assert cats[-1] == "Otros" and sum(vals) == sum(range(1, 16)) and len(cats) == 11
    assert report_charts.top_with_others(Counter({"a": 2}), 10) == (["a"], [2])


@pytest.mark.parametrize("raw,expected", [(["Sí", "No", "sí"], "doughnut"), (["a", "b", "a"], "doughnut"), ([str(i) for i in range(30)], "col")])
def test_column_spec_kinds(raw, expected):
    assert report_charts.column_spec("X", raw * (3 if expected == "col" else 1))["kind"] == expected
