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


# ------------------------------------------------------------------ herramientas (C3-3)
def test_csv_cells_that_look_like_formulas_are_neutralised():
    src = _read("app/crm/tools.py")
    ns = {}
    exec(src[src.index("def safe_cell"):src.index("def _rows")], ns)          # la función es pura: se prueba sin importar sqlalchemy
    safe = ns["safe_cell"]
    assert safe("=1+1") == "'=1+1" and safe("+57 300") == "'+57 300" and safe("-5") == "'-5" and safe("@x") == "'@x" and safe("\tx") == "'\tx"
    assert safe("Hotel") == "Hotel" and safe(None) == "" and safe(1234) == "1234"


def test_tools_guarantees_in_the_source():
    tools, router = _read("app/crm/tools.py"), _read("app/routers/crm_tools.py")
    assert "async def" not in router and "_require_crm_enabled" in router
    assert "admin_staff" in router.split("def export(")[1].split("\n")[0] and 'f"{n} filas"' in router
    assert tools.count(".limit(") >= 5 and "SEARCH_MIN" in tools and "utf-8" in tools and "\\ufeff" in tools
    assert "setInterval" not in _read("static/js/crm_buscar.js") if pathlib.Path("static/js/crm_buscar.js").exists() else True


# ------------------------------------------------------------------ pantallas (C3-4)
C3_PAGES = {"crm_buscar": ("templates/crm_buscar.html", "static/js/crm_buscar.js"), "crm_cotizaciones": ("templates/crm_cotizaciones.html", "static/js/crm_cotizaciones.js"),
            "crm_cotizacion": ("templates/crm_cotizacion.html", "static/js/crm_cotizacion.js"), "crm_productos": ("templates/crm_productos.html", "static/js/crm_productos.js")}


@pytest.mark.parametrize("name", sorted(C3_PAGES))
def test_c3_pages_follow_the_frontend_rules(name):
    tpl, js = (_read(p) for p in C3_PAGES[name])
    for code in (tpl, js):
        assert not re.search(r"\bon(click|change|input|submit)\s*=", code), "nada de eventos inline"
    assert not re.search(r"setInterval|setTimeout|EventSource|WebSocket", js), "sin temporizadores ni sondeos"
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert not re.search(r"(?<![.\w])(alert|confirm|prompt)\(", js), "usar showToast/showConfirm/showPrompt"
    assert "style=" not in tpl and not re.search(r"#[0-9a-fA-F]{3,6}\b", tpl), "solo tokens y clases del sistema de diseño"
    icons = _read("static/img/icons.svg") if pathlib.Path("static/img/icons.svg").exists() else ""
    for ic in re.findall(r"ic\('([a-z-]+)'", tpl):
        assert f'id="i-{ic}"' in icons, f"icono desconocido: {ic}"


def test_c3_css_uses_only_tokens():
    css = re.sub(r"@media\s*\([^)]*\)", "", _read("static/css/p-crm-c3.css"))
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|\brgba?\(|\b(?:[02-9]|\d{2,})px\b", css.split("*/", 1)[1]), "ni colores ni píxeles sueltos"


def test_c3_page_routes_exist_and_the_catalog_page_is_admin_only():
    main = _read("app/main.py")
    for route in ('"/crm/cotizaciones"', '"/crm/cotizaciones/{quote_id}"', '"/crm/buscar"', '"/crm/productos"'):
        assert f"@app.get({route})" in main
    block = main.split('@app.get("/crm/productos")', 1)[1].split("@app.get", 1)[0]
    assert '_require_page_role(request, "admin")' in block
    init = _read("app/crm/__init__.py")
    assert '"cotizaciones"' in init.split("SECTIONS_BUILT", 1)[1] and '"buscar"' in init.split("SECTIONS_BUILT", 1)[1]


def test_quote_editor_never_trusts_screen_totals_and_warns_about_unsaved_changes():
    js = _read("static/js/crm_cotizacion.js")
    body = js.split("function body()", 1)[1].split("async function save", 1)[0]
    assert "subtotal" not in body and "total" not in body.replace("lines", ""), "los totales no se envían: el servidor los calcula"
    assert "beforeunload" in js and "updated_at" in body


def test_free_text_searches_fold_accents_in_sql_for_columns_without_norm():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    fold = (root / "app/crm/sqlfold.py").read_text(encoding="utf-8")
    assert "translate" in fold
    for rel in ("app/crm/quotes.py", "app/crm/tools.py", "app/crm/opportunities.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "import fold" in src
        assert not re.search(r"func\.lower\(Crm(Quote\.title|Opportunity\.name)\)", src), rel          # tildes: siempre fold(), nunca lower() a secas


def test_sqlfold_table_is_aligned_and_matches_normalize():
    """IMPORTA el módulo (no solo lo lee): un desajuste o un error de importación se ve sin base de datos."""
    from app.crm import normalize, sqlfold
    assert len(sqlfold._FROM) == len(sqlfold._TO) == len(sqlfold.PAIRS)
    assert all(len(a) == 1 and len(b) == 1 for a, b in sqlfold.PAIRS)
    for ch in "áéíóúüñàèìòùâêîôûäëïöçÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÄËÏÖÇ":
        assert sqlfold._TO[sqlfold._FROM.index(ch)].lower() == normalize(ch), ch          # el SQL traduce igual que normalize()
    for word in ("Cámara", "ÑANDÚ", "Pingüino", "Ceñidor", "Français ç", "Ópera"):
        folded = "".join(sqlfold._TO[sqlfold._FROM.index(c)] if c in sqlfold._FROM else c for c in word).lower()
        assert folded == normalize(word)
