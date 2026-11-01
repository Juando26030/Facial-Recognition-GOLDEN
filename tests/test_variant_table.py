"""P11: tabla de variantes en Excel — celdas, plantilla, lectura y defensas contra archivos hostiles (construidos aquí), inyección de fórmulas, permisos y que nada se guarde."""
import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from app import variant_table as vt

V = json.loads((Path(__file__).parent / "variant_cell_vectors.json").read_text(encoding="utf-8"))
SECRET = "SECRETO-9f3a"


def _spec(rows=None):
    return {
        "variables": [{"label": "Ciudad", "options": ["Bogotá", "Cali", "Pasto"]}],
        "columns": [{"id": "k1", "name": "Lugar", "type": "text"}, {"id": "k2", "name": "Fecha", "type": "date"}, {"id": "k3", "name": "Cantidad", "type": "number"},
                    {"id": "k4", "name": "Nivel", "type": "options", "options": ["Alto", "Bajo"]}, {"id": "k5", "name": "Foto", "type": "image"}],
        "rows": rows if rows is not None else [{"keys": ["Bogotá"], "cells": {}}, {"keys": ["Cali"], "cells": {}}, {"keys": ["Pasto"], "cells": {}}],
    }


def _xlsx(edit=None, spec=None):
    wb = openpyxl.load_workbook(io.BytesIO(vt.build_template(spec or _spec())))
    if edit:
        edit(wb["Tabla"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _rebuild(data: bytes, replace=None, add=None) -> bytes:
    """Copia un .xlsx cambiando/agregando partes (para armar archivos hostiles)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            body = src.read(item.filename)
            if replace and item.filename in replace:
                body = replace[item.filename]
            dst.writestr(item.filename, body)
        for name, body in (add or {}).items():
            dst.writestr(name, body)
    return out.getvalue()


# ------------------------------------------------------------------ celdas: los mismos casos que el navegador
@pytest.mark.parametrize("raw,out", V["date"])
def test_date_cells(raw, out):
    v, err = vt.parse_cell("date", raw)
    assert (None if err else v) == out


@pytest.mark.parametrize("raw,out", V["number"])
def test_number_cells(raw, out):
    v, err = vt.parse_cell("number", raw)
    assert (None if err else v) == out


@pytest.mark.parametrize("raw,out", V["options"]["cases"])
def test_options_cells(raw, out):
    v, err = vt.parse_cell("options", raw, V["options"]["options"])
    assert (None if err else v) == out


@pytest.mark.parametrize("raw,out", V["image"])
def test_image_cells(raw, out):
    v, err = vt.parse_cell("image", raw)
    assert (None if err else v) == out


def test_native_excel_types_become_the_same_text():
    assert vt.parse_cell("date", datetime(2026, 3, 5)) == ("05/03/2026", None)
    assert vt.parse_cell("number", 1234.5) == ("1.234,5", None)
    assert vt.parse_cell("number", 7) == ("7", None)
    assert vt.parse_cell("text", 12) == ("12", None)
    assert vt.parse_cell("text", None) == ("", None)


# ------------------------------------------------------------------ plantilla y ida y vuelta
def test_template_has_the_three_sheets_and_the_valid_values():
    wb = openpyxl.load_workbook(io.BytesIO(vt.build_template(_spec())))
    assert wb.sheetnames == ["Tabla", "Instrucciones", "_meta", "Valores válidos"] and wb["_meta"].sheet_state == "veryHidden"
    assert [c.value for c in wb["Tabla"][1]] == ["Ciudad", "Lugar", "Fecha", "Cantidad", "Nivel", "Foto"]
    assert [r[0].value for r in wb["Tabla"].iter_rows(min_row=2)] == ["Bogotá", "Cali", "Pasto"]
    valid = {c.value: [r[i].value for r in wb["Valores válidos"].iter_rows(min_row=2) if r[i].value] for i, c in enumerate(wb["Valores válidos"][1])}
    assert valid == {"Ciudad": ["Bogotá", "Cali", "Pasto"], "Nivel": ["Alto", "Bajo"]}
    assert "fórmulas" in " ".join(str(r[0].value) for r in wb["Instrucciones"].iter_rows())


def test_round_trip_download_then_upload_gives_the_same_table():
    rows = [{"keys": ["Bogotá"], "cells": {"k1": "Chapinero", "k2": "05/03/2026", "k3": "1.234,56", "k4": "Alto", "k5": "bogota.jpg"}}, {"keys": ["Cali"], "cells": {"k1": "<b>Sur</b>"}}, {"keys": ["Pasto"], "cells": {}}]
    spec = _spec(rows)
    got = vt.read_table(vt.build_template(spec), "tabla.xlsx", spec)
    assert got["problems"] == [] and got["unmatched_rows"] == [] and got["missing_rows"] == 0
    assert got["matched_rows"] == [0, 1, 2]
    assert [r["cells"] for r in got["rows"]] == [r["cells"] for r in rows]


def test_reading_a_filled_in_file_with_native_types_and_free_text():
    def edit(ws):
        ws["B2"] = "Chapinero"; ws["C2"] = datetime(2026, 3, 5); ws["D2"] = 1234.5; ws["E2"] = "alto"
        ws["B3"] = "x"; ws["C3"] = "31/02/2026"; ws["D3"] = "abc"; ws["E3"] = "Medio"
        ws["G1"] = "Comentario"; ws["G2"] = SECRET
    got = vt.read_table(_xlsx(edit), "t.xlsx", _spec())
    assert got["rows"][0]["cells"] == {"k1": "Chapinero", "k2": "05/03/2026", "k3": "1.234,5", "k4": "Alto"}
    assert {(p["row"], p["col"]) for p in got["problems"]} == {(1, "k2"), (1, "k3"), (1, "k4")}
    assert got["ignored_columns"] == ["Comentario"]
    assert got["rows"][1]["cells"] == {"k1": "x"}                       # lo inválido no entra, lo válido de la misma fila sí


def test_unknown_missing_and_repeated_rows_are_reported():
    def edit(ws):
        ws["A3"] = "Medellín"; ws["B3"] = "x"          # no está en la tabla
        ws.append(["Bogotá", "repetida"])              # repetida: gana la primera
        ws["B2"] = "primera"
    got = vt.read_table(_xlsx(edit), "t.xlsx", _spec())
    assert got["unmatched_rows"] == [3] and got["duplicated_rows"] == [5] and got["missing_rows"] == 1
    assert got["rows"][0]["cells"] == {"k1": "primera"}


def test_header_names_and_order_do_not_matter_but_the_key_column_must_exist():
    def shuffle(ws):
        ws.move_range("A1:F4", cols=1)
        ws["A1"] = "Notas"; ws["A2"] = SECRET
    got = vt.read_table(_xlsx(shuffle), "t.xlsx", _spec())
    assert got["ignored_columns"] == ["Notas"] and got["missing_rows"] == 0

    def drop_key(ws):
        ws["A1"] = "Otra cosa"
    with pytest.raises(vt.ExcelRejected, match="plantilla"):
        vt.read_table(_xlsx(drop_key), "t.xlsx", _spec())


# ------------------------------------------------------------------ inyección de fórmulas al GENERAR
HOSTILE = ['=HYPERLINK("http://evil.example","x")', "+cmd|' /C calc'!A0", "-1+2", "@SUM(A1:A9)", "\t=1+1", "\r=1+1", "=1+1"]


def test_cells_that_look_like_formulas_are_written_as_text():
    rows = [{"keys": ["Bogotá"], "cells": {"k1": h}} for h in HOSTILE]
    spec = _spec(rows)
    spec["variables"][0]["options"] = list(spec["variables"][0]["options"]) + HOSTILE
    spec["columns"][3]["options"] = HOSTILE
    spec["columns"][0]["name"] = "=Lugar"
    data = vt.build_template(spec)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith(".xml"):
                body = z.read(name)
                assert b"<f>" not in body and b"<f " not in body, f"fórmula en {name}"
    wb = openpyxl.load_workbook(io.BytesIO(data))                      # sin read_only ni data_only: así se ve el tipo real
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"{ws.title}!{cell.coordinate}"
                if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@", "\t", "\r"):
                    assert cell.data_type == "s" and cell.quotePrefix, f"{ws.title}!{cell.coordinate} sin proteger"
    assert wb["Tabla"]["B2"].value == HOSTILE[0]                       # el texto se conserva tal cual, solo que como texto


def test_a_template_with_hostile_text_can_be_read_back_without_executing_anything():
    spec = _spec([{"keys": ["Bogotá"], "cells": {"k1": "=1+1"}}, {"keys": ["Cali"], "cells": {}}, {"keys": ["Pasto"], "cells": {}}])
    got = vt.read_table(vt.build_template(spec), "t.xlsx", spec)
    assert got["rows"][0]["cells"] == {"k1": "=1+1"}


# ------------------------------------------------------------------ archivos hostiles
def test_formulas_in_an_uploaded_file_reject_it():
    with pytest.raises(vt.ExcelRejected, match="fórmulas"):
        vt.read_table(_xlsx(lambda ws: ws.__setitem__("B2", "=1+1") or setattr(ws["B2"], "data_type", "f")), "t.xlsx", _spec())
    with pytest.raises(vt.ExcelRejected, match="fórmulas"):
        vt.read_table(_xlsx(lambda ws: ws.__setitem__("B3", '=HYPERLINK("http://evil.example","x")')), "t.xlsx", _spec())


def test_extension_size_and_format_checks():
    ok = _xlsx()
    for name in ("t.xlsm", "t.xls", "t.csv", "t", "t.xlsx.exe"):
        with pytest.raises(vt.ExcelRejected):
            vt.read_table(ok, name, _spec())
    with pytest.raises(vt.ExcelRejected, match="2 MB"):
        vt.read_table(ok + b"\0" * (vt.MAX_FILE_BYTES + 1), "t.xlsx", _spec())
    for junk in (b"hola", b"", b"PK\x03\x04roto", b"%PDF-1.4"):
        with pytest.raises(vt.ExcelRejected):
            vt.read_table(junk, "t.xlsx", _spec())


def test_zip_bomb_is_rejected_before_anything_is_parsed():
    ok = _xlsx()
    big = b"<row>" + b"<c r='A1'><v>0</v></c>" * 2_000_000 + b"</row>"                       # ~44 MB descomprimido, unos KB comprimido
    bomb = _rebuild(ok, replace={"xl/worksheets/sheet1.xml": big})
    assert len(bomb) < vt.MAX_FILE_BYTES, "la bomba cabe en el tope de 2 MB: la defensa es el tamaño DESCOMPRIMIDO"
    with pytest.raises(vt.ExcelRejected, match="descomprimido"):
        vt.read_table(bomb, "t.xlsx", _spec())
    many = _rebuild(ok, add={f"xl/extra{i}.xml": b"<a/>" for i in range(vt.MAX_PARTS + 5)})
    with pytest.raises(vt.ExcelRejected, match="partes"):
        vt.read_table(many, "t.xlsx", _spec())
    ratio = _rebuild(ok, add={"xl/extra.xml": b"0" * 3_000_000})                              # 3 MB de ceros: compresión absurda
    with pytest.raises(vt.ExcelRejected, match="sospechosa"):
        vt.read_table(ratio, "t.xlsx", _spec())


def test_xml_entities_are_rejected():
    ok = _xlsx()
    laughs = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
              b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is></c></row></sheetData></worksheet>')
    with pytest.raises(vt.ExcelRejected, match="XML"):
        vt.read_table(_rebuild(ok, replace={"xl/worksheets/sheet1.xml": laughs}), "t.xlsx", _spec())
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&e;</t></si></sst>'
    with pytest.raises(vt.ExcelRejected, match="XML"):
        vt.read_table(_rebuild(ok, replace={"xl/styles.xml": xxe}), "t.xlsx", _spec())
    with pytest.raises(vt.ExcelRejected, match="XML"):
        vt.read_table(_rebuild(ok, add={"docProps/x.rels": b"<?xml version='1.0'?><!ENTITY a 'b'><r/>"}), "t.xlsx", _spec())


def test_defusedxml_is_in_use_and_required():
    import openpyxl.xml
    assert openpyxl.xml.DEFUSEDXML is True
    import defusedxml  # noqa: F401  (dependencia obligada del lector)
    old = openpyxl.xml.DEFUSEDXML
    openpyxl.xml.DEFUSEDXML = False
    try:
        with pytest.raises(vt.ExcelRejected, match="defusedxml"):
            vt.read_table(_xlsx(), "t.xlsx", _spec())
    finally:
        openpyxl.xml.DEFUSEDXML = old


def test_macros_external_links_and_embedded_objects_are_rejected():
    ok = _xlsx()
    for name in ("xl/vbaProject.bin", "xl/externalLinks/externalLink1.xml", "xl/embeddings/oleObject1.bin", "xl/activeX/activeX1.xml"):
        with pytest.raises(vt.ExcelRejected, match="macros|vínculos"):
            vt.read_table(_rebuild(ok, add={name: b"x"}), "t.xlsx", _spec())
    with zipfile.ZipFile(io.BytesIO(ok)) as z:
        ct = z.read("[Content_Types].xml")
    macro = ct.replace(b"spreadsheetml.sheet.main+xml", b"ms-excel.sheet.macroEnabled.main+xml")
    with pytest.raises(vt.ExcelRejected, match="macros"):
        vt.read_table(_rebuild(ok, replace={"[Content_Types].xml": macro}), "t.xlsx", _spec())
    with pytest.raises(vt.ExcelRejected):
        vt.read_table(_rebuild(ok, add={"../evil.xml": b"x"}), "t.xlsx", _spec())


def test_huge_declared_dimensions_and_too_many_rows_are_rejected():
    with pytest.raises(vt.ExcelRejected, match="demasiado grande"):
        vt.read_table(_xlsx(lambda ws: ws.cell(row=1_000_000, column=1).__setattr__("value", "x")), "t.xlsx", _spec())
    with pytest.raises(vt.ExcelRejected, match="demasiado grande"):
        vt.read_table(_xlsx(lambda ws: ws.cell(row=2, column=500).__setattr__("value", "x")), "t.xlsx", _spec())

    def many(ws):
        for i in range(600):
            ws.append(["Bogotá", "x"])
    with pytest.raises(vt.ExcelRejected, match="500 filas"):
        vt.read_table(_xlsx(many), "t.xlsx", _spec())


def test_long_text_cell_is_reported_not_stored():
    got = vt.read_table(_xlsx(lambda ws: ws.__setitem__("B2", "x" * (vt.MAX_TEXT + 1))), "t.xlsx", _spec())
    assert got["problems"][0]["message"].startswith("El texto es demasiado largo") and "k1" not in got["rows"][0]["cells"]


def test_spec_limits():
    spec = _spec()
    spec["columns"] = [{"id": f"c{i}", "name": f"C{i}", "type": "text"} for i in range(16)]
    with pytest.raises(vt.ExcelRejected, match="15"):
        vt.build_template(spec)
    with pytest.raises(vt.ExcelRejected, match="200"):
        vt.build_template(_spec([{"keys": [str(i)], "cells": {}} for i in range(201)]))
    dup = _spec(); dup["columns"][1]["name"] = "lugar"
    with pytest.raises(vt.ExcelRejected, match="mismo nombre"):
        vt.build_template(dup)
    with pytest.raises(vt.ExcelRejected):
        vt.build_template({"variables": [], "columns": [], "rows": []})
    bad = _spec(); bad["columns"][0]["type"] = "formula"
    with pytest.raises(vt.ExcelRejected):
        vt.build_template(bad)


# ------------------------------------------------------------------ nada del contenido en logs ni en los errores
def test_cell_contents_never_reach_logs_or_error_messages(caplog):
    caplog.set_level(logging.DEBUG)
    spec = _spec()
    vt.read_table(_xlsx(lambda ws: ws.__setitem__("B2", SECRET) or ws.__setitem__("C2", SECRET)), "t.xlsx", spec)
    for payload in (_xlsx(lambda ws: ws.__setitem__("B2", "=" + SECRET)), _rebuild(_xlsx(), replace={"xl/worksheets/sheet1.xml": b"<!DOCTYPE a [<!ENTITY b '" + SECRET.encode() + b"'>]><a/>"}), SECRET.encode()):
        with pytest.raises(vt.ExcelRejected) as exc:
            vt.read_table(payload, "t.xlsx", spec)
        assert SECRET not in str(exc.value)
    assert SECRET not in caplog.text


# ------------------------------------------------------------------ los endpoints: permisos y que nada se guarde
def _client_setup(client, factory):
    from tests.test_forms import _create, _event
    ev = _event(client, factory)
    return ev, _create(client, ev)


def test_endpoints_return_the_xlsx_and_parse_it_without_touching_storage(client, factory, monkeypatch):
    ev, f = _client_setup(client, factory)

    def no_storage(*a, **k):
        raise AssertionError("el archivo no se guarda: no debe tocar el almacenamiento")
    monkeypatch.setattr("app.routers.forms.get_storage", no_storage)
    base = f"/api/events/{ev.id}/forms/{f['id']}/variant-table"
    r = client.post(f"{base}/template", json=_spec())
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.headers["cache-control"] == "no-store" and "tabla-de-variantes.xlsx" in r.headers["content-disposition"]
    p = client.post(f"{base}/parse", files={"file": ("t.xlsx", _xlsx(lambda ws: ws.__setitem__("B2", "Chapinero")), "application/octet-stream")}, data={"spec": json.dumps(_spec())})
    assert p.status_code == 200 and p.json()["rows"][0]["cells"] == {"k1": "Chapinero"}
    for bad in (("t.xlsm", _xlsx()), ("t.xlsx", b"no es un excel"), ("t.xlsx", _xlsx(lambda ws: ws.__setitem__("B2", "=1+1")))):
        r = client.post(f"{base}/parse", files={"file": (bad[0], bad[1], "application/octet-stream")}, data={"spec": json.dumps(_spec())})
        assert r.status_code == 400 and SECRET not in r.text
    assert client.post(f"{base}/parse", files={"file": ("t.xlsx", _xlsx(), "application/octet-stream")}, data={"spec": "{no es json"}).status_code == 400
    assert client.post(f"{base}/template", json={"variables": []}).status_code == 400


def test_only_the_roles_that_can_edit_the_design_can_use_the_endpoints(client, factory):
    from tests.conftest import login
    ev, f = _client_setup(client, factory)
    base = f"/api/events/{ev.id}/forms/{f['id']}/variant-table/template"
    factory.staff("digitador", "dig1"); factory.staff("cliente", "cli1"); factory.staff("admin", "adm1")
    factory.authorize(ev, factory.staff("digitador", "dig2"))
    client.post("/logout")
    assert client.post(base, json=_spec()).status_code in (401, 403)           # sin sesión
    for user in ("dig1", "dig2", "cli1"):
        login(client, user)
        assert client.post(base, json=_spec()).status_code == 403, user
        client.post("/logout")
    for user in ("coord1", "adm1"):
        login(client, user)
        assert client.post(base, json=_spec()).status_code == 200, user
        client.post("/logout")
    login(client, "adm1")
    assert client.post(f"/api/events/{ev.id}/forms/999999/variant-table/template", json=_spec()).status_code == 404       # el formulario debe ser de este evento


def test_openpyxl_with_defusedxml_also_refuses_entities_on_its_own():
    """Defensa en profundidad: aunque la revisión previa del zip fallara, el lector (defusedxml) no expande entidades."""
    laughs = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
              b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is></c></row></sheetData></worksheet>')
    data = _rebuild(_xlsx(), replace={"xl/worksheets/sheet1.xml": laughs})
    with pytest.raises(Exception) as exc:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, keep_links=False)
        list(wb["Tabla"].iter_rows(values_only=True))
    assert "lollol" not in str(exc.value)


# ------------------------------------------------------------------ P11b: la identidad de cada columna es su id (hoja oculta `_meta`), no su nombre
def _spec_ids():
    spec = _spec()
    spec["variables"][0]["field"] = "ciudad_f"
    return spec


def test_renaming_and_reordering_do_not_break_an_exported_file():
    spec = _spec_ids()
    spec["rows"] = [{"keys": ["Bogotá"], "cells": {"k1": "Chapinero", "k2": "05/03/2026"}}, {"keys": ["Cali"], "cells": {"k1": "Sur"}}, {"keys": ["Pasto"], "cells": {}}]
    data = vt.build_template(spec)
    renamed = _spec_ids()                                                   # el diseñador renombró los elementos y reordenó las columnas; los ids son los mismos
    renamed["variables"][0]["label"] = "Ciudad del evento"
    renamed["columns"] = [dict(c, name=f"Nuevo {i}") for i, c in enumerate(reversed(renamed["columns"]))]
    renamed["rows"] = [{"keys": r["keys"], "cells": {}} for r in spec["rows"]]
    got = vt.read_table(data, "t.xlsx", renamed)
    assert got["problems"] == [] and got["ignored_columns"] == [] and got["missing_rows"] == 0
    assert got["rows"][0]["cells"] == {"k1": "Chapinero", "k2": "05/03/2026"} and got["rows"][1]["cells"] == {"k1": "Sur"}


def test_reordering_columns_inside_excel_does_not_break_it():
    def swap(ws):
        for row in ws.iter_rows(min_row=1, max_row=4):
            row[1].value, row[2].value = row[2].value, row[1].value        # intercambia las columnas B y C (también los encabezados)
    spec = _spec_ids()
    spec["rows"] = [{"keys": ["Bogotá"], "cells": {"k1": "Chapinero", "k2": "05/03/2026"}}, {"keys": ["Cali"], "cells": {}}, {"keys": ["Pasto"], "cells": {}}]
    got = vt.read_table(_xlsx(swap, spec), "t.xlsx", spec)
    assert got["rows"][0]["cells"] == {"k1": "Chapinero", "k2": "05/03/2026"}


def test_a_column_whose_id_no_longer_exists_is_reported_not_guessed():
    spec = _spec_ids()
    spec["rows"] = [{"keys": ["Bogotá"], "cells": {"k1": "Chapinero", "k2": "05/03/2026"}}, {"keys": ["Cali"], "cells": {}}, {"keys": ["Pasto"], "cells": {}}]
    data = vt.build_template(spec)
    gone = _spec_ids()
    gone["columns"] = [c for c in gone["columns"] if c["id"] != "k2"]                  # el elemento de «Fecha» se borró
    got = vt.read_table(data, "t.xlsx", gone)
    assert got["ignored_columns"] == ["Fecha"] and "k2" not in got["rows"][0]["cells"] and got["rows"][0]["cells"] == {"k1": "Chapinero"}


def test_files_without_the_hidden_sheet_still_match_by_name_and_hostile_meta_is_ignored():
    spec = _spec_ids()
    plain = _xlsx(lambda ws: ws.__setitem__("B2", "x"), spec)
    wb = openpyxl.load_workbook(io.BytesIO(plain)); del wb["_meta"]; buf = io.BytesIO(); wb.save(buf)
    assert vt.read_table(buf.getvalue(), "t.xlsx", spec)["rows"][0]["cells"] == {"k1": "x"}
    for junk in ("no es json", "[" * 5000, json.dumps({"cols": [{"h": "Lugar", "id": "no_existe"}], "vars": [{"h": "Ciudad", "field": "otro"}]}), json.dumps({"cols": "x", "vars": 5}), "x" * 25000):
        wb = openpyxl.load_workbook(io.BytesIO(plain)); wb["_meta"]["A1"].value = junk; buf = io.BytesIO(); wb.save(buf)
        got = vt.read_table(buf.getvalue(), "t.xlsx", spec)
        assert got["rows"][0]["cells"] == {"k1": "x"}, junk[:30]                         # cae a los nombres y no pasa nada
    wb = openpyxl.load_workbook(io.BytesIO(plain)); wb["_meta"]["A1"].value = "=1+1"; wb["_meta"]["A1"].data_type = "f"; buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(vt.ExcelRejected, match="fórmulas"):
        vt.read_table(buf.getvalue(), "t.xlsx", spec)


def test_spec_variable_field_must_look_like_an_id():
    bad = _spec(); bad["variables"][0]["field"] = "<script>"
    with pytest.raises(vt.ExcelRejected):
        vt.build_template(bad)


def test_empty_template_has_one_row_per_value_and_no_data_while_the_other_carries_the_current_data():
    filled = _spec([{"keys": ["Bogotá"], "cells": {"k1": "Chapinero"}}, {"keys": ["Cali"], "cells": {"k1": "Sur"}}, {"keys": ["Pasto"], "cells": {}}])
    empty = dict(filled, rows=[{"keys": r["keys"], "cells": {}} for r in filled["rows"]])
    wb_empty = openpyxl.load_workbook(io.BytesIO(vt.build_template(empty)))
    ws = wb_empty["Tabla"]
    assert [c.value for c in ws[1]] == ["Ciudad", "Lugar", "Fecha", "Cantidad", "Nivel", "Foto"]
    assert [r[0].value for r in ws.iter_rows(min_row=2)] == ["Bogotá", "Cali", "Pasto"]
    assert all(c.value in (None, "") for r in ws.iter_rows(min_row=2) for c in r[1:]), "sin datos"
    assert {"Instrucciones", "Valores válidos"} <= set(wb_empty.sheetnames)
    ws2 = openpyxl.load_workbook(io.BytesIO(vt.build_template(filled)))["Tabla"]
    assert [ws2.cell(row=2, column=2).value, ws2.cell(row=3, column=2).value] == ["Chapinero", "Sur"]
    assert vt.read_table(vt.build_template(empty), "t.xlsx", filled)["rows"][0]["cells"] == {}            # subir la vacía no cambia nada
    assert vt.read_table(vt.build_template(filled), "t.xlsx", empty)["rows"][1]["cells"] == {"k1": "Sur"}       # y la llena, de ida y vuelta


# ------------------------------------------------------------------ P11b: «Asignar columnas» cuando los encabezados no coinciden
def _foreign_xlsx(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tabla"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FOREIGN = _foreign_xlsx(["Ciudad", "Lugar del evento", "Cuándo", "Comentario"], [["Bogotá", "Chapinero", "5/3/26", SECRET], ["cali", "Sur", "31/02/2026", ""], ["Medellín", "x", "", ""]])


def test_headers_that_do_not_match_ask_for_an_assignment_and_nothing_is_read():
    got = vt.read_table(FOREIGN, "t.xlsx", _spec_ids(), ask=True)
    assert got["needs_mapping"] is True and "rows" not in got
    assert [h["header"] for h in got["headers"]] == ["Ciudad", "Lugar del evento", "Cuándo", "Comentario"]
    assert got["headers"][0]["suggested"] == "v0" and all(h["suggested"] is None for h in got["headers"][1:])        # «Ciudad» sí coincide por nombre
    assert SECRET not in json.dumps(got), "solo viajan los encabezados, nunca el contenido de las celdas"


def test_a_file_whose_headers_all_match_is_read_without_asking():
    spec = _spec_ids()
    got = vt.read_table(_xlsx(lambda ws: ws.__setitem__("B2", "x"), spec), "t.xlsx", spec, ask=True)
    assert "needs_mapping" not in got and got["rows"][0]["cells"] == {"k1": "x"}


def test_an_explicit_assignment_reads_the_file_with_other_headers():
    mapping = {"Ciudad": "v0", "Lugar del evento": "c:k1", "Cuándo": "c:k2", "Comentario": "ignore"}
    got = vt.read_table(FOREIGN, "t.xlsx", _spec_ids(), mapping=mapping)
    assert got["rows"][0]["cells"] == {"k1": "Chapinero", "k2": "05/03/2026"} and got["rows"][1]["cells"] == {"k1": "Sur"}
    assert [(p["row"], p["col"]) for p in got["problems"]] == [(1, "k2")] and got["unmatched_rows"] == [4] and got["ignored_columns"] == ["Comentario"]
    again = vt.read_table(FOREIGN, "t.xlsx", _spec_ids(), mapping={"Ciudad": "v0", "Cuándo": "c:k1"})              # lo no asignado se ignora
    assert again["rows"][0]["cells"] == {"k1": "5/3/26"} and again["ignored_columns"] == ["Lugar del evento", "Comentario"]


def test_assignment_can_send_one_excel_column_to_a_different_table_column():
    spec = _spec_ids()
    got = vt.read_table(_foreign_xlsx(["Ciudad", "Nivel raro"], [["Bogotá", "alto"]]), "t.xlsx", spec, mapping={"Ciudad": "v0", "Nivel raro": "c:k4"})
    assert got["rows"][0]["cells"] == {"k4": "Alto"}                                                       # los tipos y las listas de la columna destino se aplican igual


@pytest.mark.parametrize("mapping", [
    {"Lugar del evento": "c:k1"},                                  # falta la variable: no se sabe a qué fila va cada dato
    {"Ciudad": "v0", "Lugar del evento": "c:k1", "Cuándo": "c:k1"},   # dos columnas del Excel al mismo destino
    {"Ciudad": "v0", "Lugar del evento": "c:no_existe"},
    {"Ciudad": "v7"}, {"Ciudad": "v0", "Lugar del evento": "formula"}, {"Ciudad": "v0", "Lugar del evento": ["c:k1"]},
    ["Ciudad", "v0"], "Ciudad=v0", 5, {f"h{i}": "ignore" for i in range(201)},
])
def test_bad_assignments_are_rejected(mapping):
    with pytest.raises(vt.ExcelRejected):
        vt.read_table(FOREIGN, "t.xlsx", _spec_ids(), mapping=mapping)


def test_security_checks_still_apply_when_the_person_assigns_columns():
    mapping = {"Ciudad": "v0", "Lugar del evento": "c:k1"}
    bad = _rebuild(FOREIGN, add={"xl/vbaProject.bin": b"x"})
    with pytest.raises(vt.ExcelRejected, match="macros"):
        vt.read_table(bad, "t.xlsx", _spec_ids(), mapping=mapping)
    with pytest.raises(vt.ExcelRejected, match="fórmulas"):
        wb = openpyxl.load_workbook(io.BytesIO(FOREIGN)); wb["Tabla"]["B2"].value = "=1+1"; wb["Tabla"]["B2"].data_type = "f"; buf = io.BytesIO(); wb.save(buf)
        vt.read_table(buf.getvalue(), "t.xlsx", _spec_ids(), mapping=mapping)
    with pytest.raises(vt.ExcelRejected, match="2 MB"):
        vt.read_table(FOREIGN + b"\0" * (vt.MAX_FILE_BYTES + 1), "t.xlsx", _spec_ids(), mapping=mapping)


def test_a_deleted_column_id_goes_to_the_assignment_step_with_no_guess():
    spec = _spec_ids()
    spec["rows"] = [{"keys": ["Bogotá"], "cells": {"k2": "05/03/2026"}}, {"keys": ["Cali"], "cells": {}}, {"keys": ["Pasto"], "cells": {}}]
    data = vt.build_template(spec)
    gone = _spec_ids(); gone["columns"] = [c for c in gone["columns"] if c["id"] != "k2"]
    got = vt.read_table(data, "t.xlsx", gone, ask=True)
    assert got["needs_mapping"] and [h["header"] for h in got["headers"] if h["suggested"] is None] == ["Fecha"]
    assert [h["suggested"] for h in got["headers"] if h["header"] == "Lugar"] == ["c:k1"]


def test_endpoint_asks_for_the_assignment_then_reads_with_it(client, factory):
    ev, f = _client_setup(client, factory)
    url = f"/api/events/{ev.id}/forms/{f['id']}/variant-table/parse"
    r = client.post(url, files={"file": ("t.xlsx", FOREIGN, "application/octet-stream")}, data={"spec": json.dumps(_spec_ids())})
    assert r.status_code == 200 and r.json()["needs_mapping"] is True and SECRET not in r.text
    ok = client.post(url, files={"file": ("t.xlsx", FOREIGN, "application/octet-stream")}, data={"spec": json.dumps(_spec_ids()), "mapping": json.dumps({"Ciudad": "v0", "Lugar del evento": "c:k1"})})
    assert ok.status_code == 200 and ok.json()["rows"][0]["cells"] == {"k1": "Chapinero"}
    for bad in ("{no es json", json.dumps({"Ciudad": "c:no_existe"}), json.dumps({"Lugar del evento": "c:k1"}), "x" * 60000):
        assert client.post(url, files={"file": ("t.xlsx", FOREIGN, "application/octet-stream")}, data={"spec": json.dumps(_spec_ids()), "mapping": bad}).status_code == 400
