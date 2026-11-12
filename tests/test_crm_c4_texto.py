"""CRM C4 (SIN base de datos: `python3 -m pytest -q --noconftest tests/test_crm_c4_texto.py`): garantías del código de «ganada → cliente y evento», «Mi día» y tableros."""
import pathlib
import re

import pytest


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


C4_PAGES = {"crm_midia": ("templates/crm_midia.html", "static/js/crm_midia.js"), "crm_tableros": ("templates/crm_tableros.html", "static/js/crm_tableros.js")}


@pytest.mark.parametrize("name", sorted(C4_PAGES))
def test_c4_pages_follow_the_frontend_rules(name):
    tpl, js = (_read(p) for p in C4_PAGES[name])
    for code in (tpl, js):
        assert not re.search(r"\bon(click|change|input|submit)\s*=", code)
    assert not re.search(r"setInterval|setTimeout|EventSource|WebSocket", js), "nada que despierte la base solo"
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert not re.search(r"(?<![.\w])(alert|confirm|prompt)\(", js)
    assert "style=" not in tpl and not re.search(r"#[0-9a-fA-F]{3,6}\b", tpl)
    icons = _read("static/img/icons.svg")
    for ic in re.findall(r"ic\('([a-z-]+)'", tpl):
        assert f'id="i-{ic}"' in icons, ic


def test_c4_css_uses_only_tokens():
    css = re.sub(r"@media\s*\([^)]*\)", "", _read("static/css/p-crm-c4.css"))
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|\brgba?\(|\b(?:[02-9]|\d{2,})px\b", css.split("*/", 1)[1])


def test_routes_pages_and_sections_exist():
    main, init = _read("app/main.py"), _read("app/crm/__init__.py")
    assert '@app.get("/crm/mi-dia")' in main and '@app.get("/crm/tableros")' in main and "crm_today_router.router" in main
    built = re.search(r"^SECTIONS_BUILT = \{([^}]*)\}", init, re.M).group(1)
    assert '"midia"' in built and '"tableros"' in built


def test_won_module_never_commits_and_never_logs_personal_data():
    for path in ("app/crm/won.py", "app/crm/today.py"):
        code = _read(path)
        assert "commit(" not in code, "quien llama (el router) confirma o revierte: ganar y crear el evento son UNA transacción"
        assert "logging" not in code and "print(" not in code
    won = _read("app/crm/won.py")
    assert "event_code_for" in won and "409" in won and "testperson.ensure_for_event" in won and "public_slug.ensure" in won
    assert "def on_won" in _read("app/crm/opportunities.py") and "won.create_event_for" in _read("app/crm/opportunities.py")


def test_make_client_router_delegates_to_the_shared_function():
    router = _read("app/routers/crm.py")
    body = router.split('@router.post("/accounts/{account_id}/make-client")', 1)[1].split("@router", 1)[0]
    assert "won.make_client" in body


def test_c4_router_is_sync_gated_and_the_commercial_only_sees_her_own():
    code = _read("app/routers/crm_today.py")
    assert "async def" not in code and "_require_crm_enabled" in code and "view_staff" in code
    assert "owner = staff.id" in code and "is_admin" in code
    assert "/opportunities/{opportunity_id}/win" in code and "def win_opportunity" in code


def test_today_queries_are_bounded_and_money_is_never_summed_across_currencies():
    code = _read("app/crm/today.py")
    assert code.count(".limit(") >= 6, "cada lista lleva LIMIT"
    assert "CrmOpportunity.currency" in code and "group_by(" in code
    assert "day_bounds" in code and "local_to_utc" in code, "los límites del día se calculan en hora local"


def test_no_migration_0134_was_needed_for_c4():
    """C4 usa los índices que ya existen (ix_crm_act_owner_due, ix_crm_opps_owner): la 0134 reservada queda SIN USAR (anotado en docs/crm/ETAPA_C1C_C4_DISENO.md)."""
    assert not list(pathlib.Path("alembic/versions").glob("0134_*"))
    models = _read("app/models.py")
    assert "ix_crm_act_owner_due" in models and "ix_crm_opps_owner" in models


def test_win_texts_tell_the_truth_about_what_gets_created():
    for path in ("static/js/crm_kanban.js", "static/js/crm_oportunidad.js"):
        js = _read(path)
        assert "por ahora solo se cierra" not in js and "Ganar y crear evento" in js


def test_staging_findings_nov12_won_stagebar_event_link_subtotal_label_and_counter_choices():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    opp = (root / "static/js/crm_oportunidad.js").read_text(encoding="utf-8")
    assert "const locked = Boolean(opp.event_id) && s.kind !== \"won\"" in opp and "b.disabled = isCurrent || opp.archived || locked" in opp          # botones deshabilitados con evento
    assert "No disponible" in opp and "no puede volver a una etapa anterior" in opp                                                      # y un aviso visible
    assert "\"Ver evento \" + opp.code" in opp and "\"/kiosk/\" + opp.event_id" in opp
    assert "Subtotal con descuento" in (root / "static/js/crm_cotizacion.js").read_text(encoding="utf-8")
    assert "Subtotal con descuento" in (root / "app/crm/quote_pdf.py").read_text(encoding="utf-8")
    script = (root / "scripts/crm_set_counter.py").read_text(encoding="utf-8")
    assert 'choices=("account", "event", "quote", "proforma")' in script


def test_nav_order_is_defined_once_importar_is_last_and_admin_only():
    import re
    from pathlib import Path
    from app.crm import SECTIONS, sections
    root = Path(__file__).resolve().parent.parent
    order = ["buscar", "midia", "tableros", "cuentas", "leads", "oportunidades", "cotizaciones", "embudos", "importar"]
    assert [k for k, *_ in SECTIONS] == order
    assert [s["key"] for s in sections(True)] == order
    assert [s["key"] for s in sections(False)] == order[:-2]                      # un comercial no ve Embudos ni Importar
    assert [label for _k, label, *_ in SECTIONS][-1] == "Importar" and dict((k, a) for k, _l, _h, a in SECTIONS)["importar"] is True
    # una sola definición: ninguna plantilla ni el arnés repiten la lista de pestañas
    for f in (root / "templates").glob("crm_*.html"):
        assert "/crm/mi-dia" not in re.sub(r"\{#.*?#\}", "", f.read_text(encoding="utf-8"), flags=re.S) or f.name == "crm_midia.html", f.name
    nav = (root / "templates/_crm_nav.html").read_text(encoding="utf-8")
    assert "for s in crm_nav" in nav
    assert "from app.crm import SECTIONS" in (root / "scripts/visual_harness/pages.py").read_text(encoding="utf-8")


def test_import_is_admin_only_in_the_server_page_and_every_api_route():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    api = (root / "app/routers/crm_import.py").read_text(encoding="utf-8")
    assert 'admin_staff = ' in api or "admin_staff" in api
    routes = re.findall(r"@router\.(?:get|post|put|delete)\(.*?\)\ndef \w+\((.*?)\):", api, flags=re.S)
    assert len(routes) >= 6 and all("Depends(admin_staff)" in r for r in routes)                  # TODAS las rutas piden admin
    assert 'admin_staff = crm_router.require_platform_role("admin")' in api or "require_platform_role(\"admin\")" in (root / "app/routers/crm.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")
    page = main[main.index('def crm_importar_page'):]
    page = page[:page.index("\n\n\n")]
    assert '_require_page_role(request, "admin")' in page and "status_code=403" in page


def test_nav_aligns_with_the_page_column():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "static/css/design-system.css").read_text(encoding="utf-8")
    rule = next(l for l in css.splitlines() if l.startswith(".gw-crm-nav {"))
    assert "max-width: var(--gw-content-w)" in rule and "margin: 0 auto" in rule and "padding: var(--gw-sp-1) var(--gw-sp-4)" in rule
    assert ".gw-page .gw-container, .gw-page .gw-crm-nav" in css                                  # mismo relleno lateral en celular
