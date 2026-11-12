"""CRM C3 (SIN base de datos: `python3 -m pytest -q --noconftest tests/test_crm_c3_texto.py`): reglas puras de cotizaciones, PDF y garantías del código."""
import ast
import pathlib
import re
from datetime import date
from decimal import Decimal

import pytest

from app.crm import pdfdoc, quote_pdf, quote_rules as qr
from app.crm.errors import CrmError


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


# ------------------------------------------------------------------ cálculo
def test_line_and_totals_use_half_up_and_keep_the_net_in_line_total():
    a = qr.line_amounts("3", "10.01", "50", "19")
    assert a == {"gross": Decimal("30.03"), "discount": Decimal("15.02"), "net": Decimal("15.01"), "tax": Decimal("2.85")}          # 15.015 → 15.02 (ROUND_HALF_UP)
    t = qr.totals([{"qty": "2", "unit_price": "1000.50", "discount_percent": "10", "tax_percent": "19"}, {"qty": 1, "unit_price": "333.33", "discount_percent": 0, "tax_percent": 19}])
    assert t == {"subtotal": Decimal("2134.23"), "discount_total": Decimal("200.10"), "tax_total": Decimal("405.50"), "total": Decimal("2539.73")}
    assert qr.totals([]) == {"subtotal": Decimal("0.00"), "discount_total": Decimal("0.00"), "tax_total": Decimal("0.00"), "total": Decimal("0.00")}


def test_clean_line_defaults_ranges_and_errors_are_spanish():
    c = qr.clean_line({"name": " Escarapelas ", "qty": "2,5", "unit_price": "1000"})
    assert c["name"] == "Escarapelas" and c["qty"] == Decimal("2.50") and c["tax_percent"] == Decimal("19.00") and c["discount_percent"] == Decimal("0.00") and c["product_id"] is None
    for bad in ({"name": ""}, {"name": "x", "qty": "-1"}, {"name": "x", "discount_percent": "101"}, {"name": "x", "unit_price": "abc"}, {"name": "x", "qty": "1e30"}, {"name": "x", "unit_price": "NaN"}):
        with pytest.raises(CrmError):
            qr.clean_line(bad)
    with pytest.raises(CrmError) as e:
        qr.clean_line({"name": "x" * 201})
    assert "demasiado largo" in e.value.message


def test_lines_are_numbered_and_capped():
    assert [c["position"] for c in qr.clean_lines([{"name": "a"}, {"name": "b"}])] == [1, 2]
    with pytest.raises(CrmError):
        qr.clean_lines([{"name": "a"}] * (qr.MAX_LINES + 1))
    with pytest.raises(CrmError):
        qr.clean_lines("no es lista")


def test_quote_stage_rules_and_expiry_without_timers():
    qr.check_stage("borrador", "enviada")
    for cur, new in (("enviada", "enviada"), ("enviada", "borrador"), ("borrador", "xx")):
        with pytest.raises(CrmError):
            qr.check_stage(cur, new)
    today = date(2026, 11, 12)
    assert qr.is_expired("enviada", date(2026, 11, 1), today) and not qr.is_expired("aprobada", date(2026, 11, 1), today) and not qr.is_expired("enviada", None, today)


def test_saved_filters_never_keep_free_text():
    f = qr.clean_filter({"scope": "cuentas", "name": "Activas", "filters": {"q": "Lucía Ficticia", "search": "x", "status": "activo", "city": "Bogotá", "owner_id": 7}})
    assert f["filters"] == {"status": "activo", "city": "Bogotá", "owner_id": 7}
    for bad in ({"scope": "otra", "name": "x"}, {"scope": "cuentas", "name": ""}, {"scope": "cuentas", "name": "x" * 81}):
        with pytest.raises(CrmError):
            qr.clean_filter(bad)


def test_text_limits_match_the_model_columns():
    models = ast.parse(_read("app/models.py"))
    cols = {}
    for node in models.body:
        if isinstance(node, ast.ClassDef):
            for n in node.body:
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "Column":
                    arg = n.value.args[0] if n.value.args else None
                    if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "String" and arg.args:
                        cols[(node.name, n.targets[0].id)] = arg.args[0].value
    for cls, limits in (("CrmProduct", qr.PRODUCT_LIMITS), ("CrmTerm", {"name": 80}), ("CrmDocTemplate", {"name": 80}), ("CrmQuote", {"title": 200}), ("CrmQuoteLine", {"name": 200}),
                        ("CrmProforma", qr.PROFORMA_LIMITS)):
        for key, limit in limits.items():
            if (cls, key) in cols:
                assert cols[(cls, key)] == limit, (cls, key)


# ------------------------------------------------------------------ PDF
def test_money_dates_and_quantities_are_formatted_for_colombia():
    assert quote_pdf.fmt_money("1234567.5") == "1.234.567,50 COP" and quote_pdf.fmt_money("0.5", "USD") == "0,50 USD" and quote_pdf.fmt_money("-1000") == "-1.000,00 COP"
    assert quote_pdf.fmt_qty("400.00") == "400" and quote_pdf.fmt_qty("1.5") == "1,50" and quote_pdf.fmt_date("2027-03-15") == "15/03/2027" and quote_pdf.fmt_date(None) == ""


def test_the_pdf_is_a_valid_multipage_document_with_accents_and_escapes():
    d = pdfdoc.Doc("Prueba ñ")
    for i in range(120):
        d.table_row([i, "Logística (ñandú) \\ barra " * 4, "1.000,00"], [40, 350, 111], ["l", "l", "r"])
    raw = d.render()
    assert raw.startswith(b"%PDF-1.4") and raw.rstrip().endswith(b"%%EOF") and raw.count(b"/Type /Page ") >= 2 and b"startxref" in raw
    xref = int(re.search(rb"startxref\n(\d+)\n", raw).group(1))
    assert raw[xref:xref + 4] == b"xref"


def test_wrap_breaks_long_words_and_keeps_newlines():
    lines = pdfdoc.wrap("X" * 400, 10, 200)
    assert len(lines) > 1 and all(pdfdoc.text_width(ln, 10) <= 200 + 1 for ln in lines)
    assert pdfdoc.wrap("a\nb", 10, 100) == ["a", "b"]


def test_render_quote_hides_the_contact_when_it_was_erased():
    q = {"number": 1, "version": 1, "account_name": "Hotel Ejemplo", "contact_name": None, "title": "Feria", "currency": "COP", "lines": [], "subtotal": "0", "tax_total": "0", "total": "0"}
    assert b"Atenci" not in quote_pdf.render_quote(q)


# ------------------------------------------------------------------ garantías del código
def test_totals_are_always_computed_on_the_server_and_pdf_is_dropped_on_change():
    src = _read("app/crm/quotes.py")
    assert "qr.totals(" in src and "_drop_pdf(q)" in src and "next_code(db, \"quote\")" in src and "next_code(db, \"proforma\")" in src
    assert '"subtotal"' not in src.split("def create_quote")[1].split("def update_quote")[0].split("_apply_lines(db, q")[0]          # nunca se toma el subtotal que manda el navegador


def test_quote_router_is_sync_gated_and_admin_only_for_catalogs():
    src = _read("app/routers/crm_quotes.py")
    assert "async def" not in src and "_require_crm_enabled" in src
    for fn in ("create_product", "update_product", "create_term", "update_term", "create_template", "update_template", "archive_quote", "restore_quote"):
        body = src.split(f"def {fn}(")[1].split("\n")[0]
        assert "admin_staff" in body, fn
    assert src.index('"/quotes/meta"') < src.index('"/quotes/{quote_id}"')


def test_erasing_deletes_pdfs_and_counts_quotes():
    src = _read("app/crm/erase.py")
    assert "_delete_files" in src and "CrmQuote" in src and "CrmProforma" in src
    assert '"quote", CrmChangeLog.entity_id.in_(quote_ids)' in src.replace("CrmChangeLog.entity == ", "")
    assert "quote_texts" in src and "quotes" in _read("static/js/crm_cuenta_tabs.js")


def test_quote_history_never_stores_meeting_notes():
    src = _read("app/crm/history.py")          # sin importar el módulo (necesita sqlalchemy)
    assert '"quote": ("meeting_notes",)' in src and '"meeting_notes", "contact_id"' in src
