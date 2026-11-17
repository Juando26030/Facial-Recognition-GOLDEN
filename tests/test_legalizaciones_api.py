"""Legalizaciones por rubro (14-nov-2026): registrar, editar, encabezado, envío y aprobación, y el Excel en el formato oficial."""
import io

import openpyxl
import pytest
from PIL import Image

from app.models import EventExpense, EventLegalization
from tests.conftest import login


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def ev(client, factory):
    event = factory.event(city="Bogotá")
    factory.staff("coordinador", "coord", full_name="Ana Coord")
    factory.staff("admin", "director", full_name="Dir Coordinadores")
    login(client, "coord")
    return event


def _url(ev, tail=""):
    return f"/api/events/{ev.id}/legalization{tail}"


def _line(client, ev, **kw):
    body = {"kind": "hospedaje", "expense_date": "2026-11-03", "vendor_name": "Hotel Sol", "tax_id": "900111", "amount": "200000"}
    body.update(kw)
    r = client.post(_url(ev, "/lines"), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _header(client, ev, **kw):
    body = {"responsible_name": "Ana Coord", "responsible_cc": "1000000", "advance_amount": "500000", "legalization_date": "2026-11-14"}
    body.update(kw)
    r = client.put(_url(ev), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_la_pantalla_trae_los_rubros_el_encabezado_y_los_totales(client, ev):
    data = client.get(_url(ev)).json()
    assert [k["kind"] for k in data["kinds"]] == ["hospedaje", "pasaje", "taxi_terminal", "taxi_ciudad", "alimentacion", "digitador", "otro"]
    assert data["header"]["status"] == "borrador" and data["header"]["responsible_name"] == "Ana Coord"      # sugerido: quien está logueado
    assert data["file_name"].startswith("LEG-COD_") and data["summary"]["total"] == 0 and data["can_review"] is False


def test_registrar_un_gasto_por_rubro_y_sumar(client, ev, db):
    _header(client, ev)
    _line(client, ev)
    _line(client, ev, kind="taxi_ciudad", vendor_name="Pedro", plate="ABC123", vehicle="taxi", amount="20000", has_support=False)
    _line(client, ev, kind="alimentacion", vendor_name="Restaurante", breakfast="10000", lunch="15000", amount=None)
    _line(client, ev, kind="digitador", vendor_name="Laura", amount="90000")
    _line(client, ev, kind="otro", concept="Cinta", amount="8000")
    data = client.get(_url(ev)).json()
    assert data["summary"]["total"] == 200000 + 20000 + 25000 + 90000 + 8000
    assert data["summary"]["hospedaje"] == 200000 and data["summary"]["alimentacion"] == 25000 and data["summary"]["digitadores"] == 90000
    row = db.query(EventExpense).filter_by(kind="alimentacion").one()
    assert float(row.amount) == 25000 and row.category == "Alimentación" and row.responsible == "Ana Coord"


@pytest.mark.parametrize("body", [
    {"amount": "-1"}, {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "1e13"}, {"amount": None}, {"kind": "otro", "concept": "", "amount": "5"},
    {"kind": "digitador", "vendor_name": "", "amount": "5"}, {"kind": "inventado"}, {"expense_date": "no-es-fecha"}, {"kind": "taxi_ciudad", "vehicle": "bici", "amount": "5"},
])
def test_valores_invalidos_se_rechazan(client, ev, body):
    base = {"kind": "hospedaje", "amount": "10"}
    base.update(body)
    assert client.post(_url(ev, "/lines"), json=base).status_code == 400


def test_editar_corrige_y_no_deja_cambiar_el_rubro(client, ev):
    line = _line(client, ev)
    r = client.put(_url(ev, f"/lines/{line['id']}"), json={"kind": "hospedaje", "vendor_name": "Hotel Luna", "amount": "250000"})
    assert r.status_code == 200 and r.json()["vendor_name"] == "Hotel Luna" and r.json()["amount"] == 250000
    assert client.put(_url(ev, f"/lines/{line['id']}"), json={"kind": "pasaje", "amount": "1"}).status_code == 400
    assert client.post(f"/api/events/{ev.id}/expenses/{line['id']}/archive").status_code == 200
    assert client.put(_url(ev, f"/lines/{line['id']}"), json={"kind": "hospedaje", "amount": "1"}).status_code == 400      # archivado: no se edita


def test_el_soporte_se_adjunta_y_se_descarga(client, ev):
    line = _line(client, ev)
    r = client.post(_url(ev, f"/lines/{line['id']}/evidence"), files={"evidence": ("f.png", _png(), "image/png")})
    assert r.status_code == 200 and r.json()["has_evidence"] is True
    assert client.get(f"/api/events/{ev.id}/expenses/{line['id']}/evidence").status_code == 200
    assert client.post(_url(ev, f"/lines/{line['id']}/evidence"), files={"evidence": ("f.txt", b"x", "text/plain")}).status_code == 400


def test_el_excel_tiene_el_formato_oficial_y_el_nombre_del_ejemplo(client, ev):
    _header(client, ev)
    _line(client, ev)
    _line(client, ev, kind="digitador", vendor_name="Laura", amount="90000")
    for path in (_url(ev, "/report"), f"/api/events/{ev.id}/expenses/report"):
        r = client.get(path)
        assert r.status_code == 200
        assert f"LEG-COD_{ev.event_code}-" in r.headers["content-disposition"] and r.headers["content-disposition"].endswith('.xlsx"')
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Legalización", "Hosped-Pasajes-TransTermin", "Taxis-TransPúblico", "PagoDigitadores", "Gastos de Alimentación", "Otros gastos", "Soportes"]
        assert wb["Legalización"]["C6"].value == "Ana Coord" and wb["Legalización"]["C13"].value == 500000


def test_un_gasto_archivado_no_sale_en_el_excel(client, ev):
    a, b = _line(client, ev), _line(client, ev, amount="1000")
    client.post(f"/api/events/{ev.id}/expenses/{a['id']}/archive")
    assert client.get(_url(ev)).json()["summary"]["total"] == 1000
    assert {x["id"] for x in client.get(_url(ev)).json()["lines"]} == {b["id"]}


def test_enviar_exige_gastos_responsable_y_cedula_y_bloquea_los_cambios(client, ev):
    assert client.post(_url(ev, "/submit")).status_code == 400      # sin gastos
    _line(client, ev)
    assert client.post(_url(ev, "/submit")).status_code == 400      # sin responsable ni cédula
    _header(client, ev)
    assert client.post(_url(ev, "/submit")).json()["header"]["status"] == "enviada"
    assert client.post(_url(ev, "/lines"), json={"kind": "otro", "concept": "x", "amount": "1"}).status_code == 400
    assert client.put(_url(ev), json={"responsible_name": "Otro"}).status_code == 400
    assert client.post(_url(ev, "/submit")).status_code == 400      # ya está enviada


def test_el_coordinador_no_aprueba_ni_devuelve_pero_el_director_si(client, ev, factory):
    line = _line(client, ev)
    _header(client, ev)
    client.post(_url(ev, "/submit"))
    assert client.post(_url(ev, "/approve")).status_code == 403
    assert client.post(_url(ev, f"/lines/{line['id']}/review"), json={"approved": True}).status_code == 403
    client.post("/logout")
    login(client, "director")
    assert client.get(_url(ev)).json()["can_review"] is True
    assert client.post(_url(ev, f"/lines/{line['id']}/review"), json={"approved": False}).json()["approved"] is False
    assert client.post(_url(ev, "/return"), json={"note": ""}).status_code == 400      # la devolución lleva nota
    r = client.post(_url(ev, "/return"), json={"note": "Falta el soporte del hotel"})
    assert r.json()["header"]["status"] == "devuelta" and r.json()["header"]["review_note"] == "Falta el soporte del hotel"
    client.post("/logout")
    login(client, "coord")
    assert client.put(_url(ev, f"/lines/{line['id']}"), json={"kind": "hospedaje", "vendor_name": "Hotel", "amount": "1"}).status_code == 200      # devuelta: editable otra vez
    assert client.post(_url(ev, "/submit")).json()["header"]["status"] == "enviada"
    client.post("/logout")
    login(client, "director")
    done = client.post(_url(ev, "/approve")).json()
    assert done["header"]["status"] == "aprobada" and done["lines"][0]["approved"] is True       # corregir un gasto lo deja pendiente y la aprobación completa lo aprueba


def test_aprobar_conserva_el_no_del_director(client, ev):
    a, b = _line(client, ev), _line(client, ev, amount="5")
    _header(client, ev)
    client.post(_url(ev, "/submit"))
    client.post("/logout")
    login(client, "director")
    client.post(_url(ev, f"/lines/{a['id']}/review"), json={"approved": False})
    lines = {x["id"]: x["approved"] for x in client.post(_url(ev, "/approve")).json()["lines"]}
    assert lines == {a["id"]: False, b["id"]: True}


def test_digitador_y_cliente_no_entran(client, factory, ev):
    client.post("/logout")
    factory.staff("digitador", "dig")
    login(client, "dig")
    assert client.get(_url(ev)).status_code == 403


def test_los_estados_y_las_fuentes_estan_de_acuerdo():
    from app.models import LEGALIZATION_STATUSES
    from app.routers import legalizations
    assert set(legalizations.EDITABLE_STATES) <= set(LEGALIZATION_STATUSES) and "enviada" not in legalizations.EDITABLE_STATES


def test_la_legalizacion_es_una_por_evento(client, ev, db):
    _header(client, ev)
    _header(client, ev, advance_amount="1")
    _line(client, ev)
    assert db.query(EventLegalization).filter_by(event_id=ev.id).count() == 1


def test_las_fotos_subidas_salen_en_la_hoja_soportes_del_excel(client, ev):
    a, b = _line(client, ev), _line(client, ev, amount="5")
    for line in (a, b):
        assert client.post(_url(ev, f"/lines/{line['id']}/evidence"), files={"evidence": ("f.png", _png(), "image/png")}).status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(client.get(_url(ev, "/report")).content))["Soportes"]
    assert len(ws._images) == 1 + 2 and any(str(c.value).startswith("FOTOS DE SOPORTE (2)") for row in ws.iter_rows() for c in row if c.value)      # el logo del comprobante en blanco + las 2 fotos
    client.post(f"/api/events/{ev.id}/expenses/{a['id']}/archive")
    ws = openpyxl.load_workbook(io.BytesIO(client.get(_url(ev, "/report")).content))["Soportes"]
    assert len(ws._images) == 1 + 1          # el gasto archivado no aporta su foto
