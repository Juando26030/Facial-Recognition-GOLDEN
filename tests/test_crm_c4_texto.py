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
