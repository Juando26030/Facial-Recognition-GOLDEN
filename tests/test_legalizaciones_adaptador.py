"""El adaptador que pasa gastos de la base al Excel oficial (app/legalization_svc.py). No necesita base de datos: usa objetos simples.
Si FastAPI/SQLAlchemy no están instalados (entorno mínimo), se cargan con sustitutos mudos solo para poder importar el módulo."""
import importlib
import io
import sys
import types
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import openpyxl
import pytest


@pytest.fixture(scope="module")
def svc():
    added = []
    try:
        import fastapi.responses, sqlalchemy.orm, app.models, app.storage  # noqa: F401, E401
    except ImportError:
        for name, attrs in (("fastapi", {"HTTPException": Exception}), ("app.storage", {"get_storage": lambda: None}), ("fastapi.responses", {"StreamingResponse": object}), ("sqlalchemy", {}), ("sqlalchemy.orm", {"Session": object}),
                            ("app.models", {"Event": object, "EventExpense": type("EventExpense", (), {}), "EventLegalization": object})):
            if name not in sys.modules:
                mod = types.ModuleType(name)
                mod.__dict__.update(attrs)
                sys.modules[name] = mod
                added.append(name)
        sys.modules.pop("app.legalization_svc", None)
    mod = importlib.import_module("app.legalization_svc")
    yield mod
    for name in added:
        sys.modules.pop(name, None)
    sys.modules.pop("app.legalization_svc", None)


def _e(**kw):
    base = dict(id=1, kind="otro", category="Otros gastos", responsible="Ana Coord", description=None, applies_to=None, expense_date=None, tax_id=None, vendor_name=None,
                address=None, phone=None, email=None, origin=None, destination=None, concept=None, plate=None, vehicle=None, amount=Decimal("0"), iva=None,
                has_support=None, breakfast=None, lunch=None, dinner=None, snack=None, unit_value=None, observation=None, approved=None, evidence_path=None,
                archived_at=None, created_at=datetime(2026, 11, 10, 15, 0))
    base.update(kw)
    return NS(**base)


def test_gasto_viejo_sale_en_otros_gastos_con_categoria_y_descripcion(svc):
    ln = svc.line_for_xlsx(_e(category="Transporte", description="Bus del staff", amount=Decimal("50000")))
    assert ln["kind"] == "otro" and ln["detail"] == "Transporte — Bus del staff" and ln["name"] == "Ana Coord"
    assert ln["date"] == date(2026, 11, 10)      # sin fecha propia: la del día en que se registró (hora local)


def test_gasto_nuevo_de_otros_no_usa_al_coordinador_como_proveedor(svc):
    ln = svc.line_for_xlsx(_e(concept="Cinta de enmascarar", vendor_name=None, expense_date=date(2026, 11, 12), amount=Decimal("8000")))
    assert ln["name"] is None and ln["detail"] == "Cinta de enmascarar"


def test_encabezado_deja_en_blanco_lo_de_administrativa(svc):
    ev = NS(event_code="23736", name="MOSCA - LABORATORIO", city="Bogotá", start_date=date(2026, 11, 3))
    leg = NS(responsible_name="Ana Coord", responsible_cc="1000000", advance_amount=Decimal("500000"), legalization_date=date(2026, 11, 14))
    h = svc.header_for_xlsx(ev, leg)
    assert h["consecutivo"] is None and h["ce_final"] is None and h["observaciones_contables"] is None
    assert h["cod_evento"] == "23736" and h["anticipo"] == Decimal("500000") and h["ciudad"] == "Bogotá"
    assert svc.header_for_xlsx(ev, None)["responsable"] is None      # sin encabezado guardado todavía


def test_el_excel_sale_con_los_gastos_en_sus_hojas_y_los_totales_del_resumen(svc):
    from app import legalization_xlsx as lx
    rows = [
        _e(id=1, kind="hospedaje", vendor_name="Hotel Sol", amount=Decimal("200000"), expense_date=date(2026, 11, 3), has_support=True),
        _e(id=2, kind="taxi_ciudad", vendor_name="Pedro", plate="ABC123", vehicle="taxi", amount=Decimal("20000"), expense_date=date(2026, 11, 3), has_support=False),
        _e(id=3, kind="alimentacion", vendor_name="Restaurante", breakfast=Decimal("10000"), lunch=Decimal("15000"), amount=Decimal("25000"), expense_date=date(2026, 11, 3)),
        _e(id=4, kind="digitador", vendor_name="Laura", amount=Decimal("90000"), expense_date=date(2026, 11, 3)),
        _e(id=5, category="Materiales", description="Papelería", amount=Decimal("12000")),
    ]
    lines = [svc.line_for_xlsx(e) for e in rows]
    ev = NS(event_code="23736", name="MOSCA - LABORATORIO", city="Bogotá", start_date=date(2026, 11, 3))
    data = lx.build_workbook(svc.header_for_xlsx(ev, NS(responsible_name="Ana", responsible_cc="1", advance_amount=Decimal("300000"), legalization_date=None)), lines)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert "AUDITORIA" not in wb.sheetnames and "PagoDigitadores" in wb.sheetnames
    s = svc.lx.summarize(lines, 300000)
    assert s["total"] == 200000 + 20000 + 25000 + 90000 + 12000 and s["reembolsar"] == s["total"] - 300000
    assert wb["Legalización"]["C6"].value == "Ana"


def test_json_de_un_gasto_viejo_muestra_la_categoria_como_concepto(svc):
    j = svc.line_json(_e(category="Transporte", amount=Decimal("1500.5")))
    assert j["kind"] == "otro" and j["concept"] == "Transporte" and j["amount"] == 1500.5 and j["date"] == "2026-11-10"
    assert svc.line_json(_e(kind="digitador", vendor_name="Laura", category="Digitadores(as)"))["concept"] == ""


def _png(color="white", size=(40, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_las_fotos_van_agrupadas_por_rubro_con_su_pie_y_se_omiten_las_que_faltan(svc, monkeypatch):
    class Store:
        files = {"a": _png("red"), "b": _png("blue")}

        def get(self, key):
            return self.files[key]          # «c» no existe: KeyError

    monkeypatch.setattr(svc, "get_storage", lambda: Store())
    rows = [
        _e(id=1, kind="otro", concept="Cinta", amount=Decimal("8000"), expense_date=date(2026, 11, 5), evidence_path="a"),
        _e(id=2, kind="hospedaje", vendor_name="Hotel Sol", amount=Decimal("200000"), expense_date=date(2026, 11, 3), evidence_path="b"),
        _e(id=3, kind="taxi_ciudad", vendor_name="Pedro", amount=Decimal("20000"), expense_date=date(2026, 11, 3), evidence_path="c"),
        _e(id=4, kind="pasaje", vendor_name="Avianca", amount=Decimal("1"), expense_date=date(2026, 11, 3)),          # sin foto
    ]
    photos = svc.photos_for_xlsx(rows)
    assert [p["caption"] for p in photos] == ["Hospedaje · Hotel Sol · 03/11/2026 · $ 200.000", "Otros gastos · Cinta · 05/11/2026 · $ 8.000"]


def test_hoja_soportes_con_fotos_en_cuadricula_y_sin_romper_los_comprobantes(svc):
    from app import legalization_xlsx as lx
    taxis = [svc.line_for_xlsx(_e(id=i, kind="taxi_ciudad", vendor_name=f"Taxista {i}", amount=Decimal("10000"), expense_date=date(2026, 11, 3), has_support=False)) for i in (1, 2)]
    photos = [{"caption": f"Foto {i}", "data": _png(size=(1200, 800))} for i in range(5)]
    wb = openpyxl.load_workbook(io.BytesIO(lx.build_workbook({}, taxis, photos)))
    ws = wb["Soportes"]
    assert len(ws._images) == 2 + 5                  # un logo por comprobante + las 5 fotos
    anchors = sorted((im.anchor._from.row, im.anchor._from.col) for im in ws._images if im.anchor._from.row > 30)      # los logos de los comprobantes están más arriba
    assert [c for _r, c in anchors] == [0, 2, 0, 2, 0]      # cuadrícula de 2 por fila
    assert len(anchors) == 5 and anchors[0][0] > 16 + 14      # empiezan debajo del último comprobante
    assert ws["A33"].value is not None or any(str(c.value).startswith("FOTOS DE SOPORTE (5)") for row in ws.iter_rows() for c in row if c.value)
    assert all(ws.row_dimensions[r].height for r in (anchors[0][0],))      # la fila de la foto tiene su alto fijo


def test_sin_fotos_la_hoja_soportes_queda_como_antes(svc):
    from app import legalization_xlsx as lx
    wb = openpyxl.load_workbook(io.BytesIO(lx.build_workbook({}, [], [])))
    assert len(wb["Soportes"]._images) == 1 and not any("FOTOS DE SOPORTE" in str(c.value) for row in wb["Soportes"].iter_rows() for c in row)
