"""CRM etapa C2 (SIN base de datos: corre con `python3 -m pytest -q --noconftest tests/test_crm_c2_texto.py`): reglas puras de embudos, oportunidades, leads y actividades, topes de la API contra las columnas
de los modelos, y reglas de código (endpoints `def`, sin `onclick`, sin temporizadores, sin colores sueltos, tablero con dos consultas, texto libre fuera del historial)."""
import ast
import pathlib
import re
from datetime import datetime
from decimal import Decimal

import pytest

from app.crm import pipeline_rules as R
from app.crm.errors import CrmError

ROOT = pathlib.Path(__file__).resolve().parent.parent
C2_JS = ["static/js/crm_common.js", "static/js/crm_kanban.js", "static/js/crm_oportunidad.js", "static/js/crm_leads.js", "static/js/crm_embudos.js"]
C2_TEMPLATES = ["templates/crm_oportunidades.html", "templates/crm_oportunidad.html", "templates/crm_leads.html", "templates/crm_embudos.html",
                "templates/_crm_shell_top.html", "templates/_crm_shell_bottom.html", "templates/_crm_macros.html"]
C2_PY = ["app/crm/pipeline_rules.py", "app/crm/pipeline.py", "app/crm/opportunities.py", "app/crm/leads.py", "app/crm/activities.py", "app/crm/lead_erase.py", "app/routers/crm_pipeline.py"]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _code(rel):
    """El archivo sin comentarios (/* */, {# #}, <!-- -->): las reglas de código no aplican a lo que dice un comentario."""
    return re.sub(r"/\*.*?\*/|\{#.*?#\}|<!--.*?-->", "", _read(rel), flags=re.S)


def _column_lengths(cls_name):
    src = _read("app/models.py")
    start = src.index(f"class {cls_name}(")
    nxt = src.find("\nclass ", start + 5)
    body = src[start: nxt if nxt != -1 else len(src)]
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^\s+(\w+)\s*=\s*Column\(String\((\d+)\)", body, re.M)}


# ------------------------------------------------------------------ topes == columnas
@pytest.mark.parametrize("limits,model,text_columns", [(R.OPPORTUNITY_LIMITS, "CrmOpportunity", ("description",)), (R.LEAD_LIMITS, "CrmLead", ("description",)),
                                                       (R.ACTIVITY_LIMITS, "CrmActivity", ("description",)), (R.STAGE_LIMITS, "CrmStage", ()), (R.PIPELINE_LIMITS, "CrmPipeline", ())])
def test_api_limits_equal_the_column_lengths_of_the_models(limits, model, text_columns):
    cols = _column_lengths(model)
    for key, limit in limits.items():
        if key in text_columns:
            assert key not in cols and limit == 20000          # Text: sin tope en la base; la API lo limita a 20.000
        else:
            assert cols.get(key) == limit, f"{model}.{key}: API {limit} vs columna {cols.get(key)}"


def test_a_text_that_is_too_long_is_a_400_in_spanish_never_a_500():
    for fn, data in ((R.clean_opportunity, {"name": "x" * 201}), (R.clean_lead, {"first_name": "x" * 121}), (R.clean_activity, {"subject": "x" * 201, "kind": "call"}), (R.clean_stage, {"name": "x" * 81})):
        kwargs = {"creating": False} if fn is not R.clean_stage else {}
        with pytest.raises(CrmError) as exc:
            fn(data, **kwargs)
        assert exc.value.status == 400 and "demasiado largo" in exc.value.message


# ------------------------------------------------------------------ reglas puras
def test_amount_currency_and_probability_are_validated():
    assert R.clean_amount("1.500,5".replace(".", "")) == Decimal("1500.50") and R.clean_amount(None) == Decimal("0.00")
    for bad in ("-1", "abc", "NaN", "Infinity", "9" * 20):
        with pytest.raises(CrmError):
            R.clean_amount(bad)
    assert R.clean_currency("usd") == "USD"
    with pytest.raises(CrmError):
        R.clean_currency("EUR")
    assert R.clean_probability("") is None and R.clean_probability("65") == 65 and R.clean_probability(0) == 0
    for bad in ("101", "-1", "x"):
        with pytest.raises(CrmError):
            R.clean_probability(bad)


def test_weighted_amount_uses_the_opportunitys_probability_or_the_stages():
    assert R.effective_probability(None, 50) == 50 and R.effective_probability(0, 50) == 0 and R.effective_probability(80, 50) == 80
    assert R.weighted("1000000", 65) == Decimal("650000.00") and R.weighted(Decimal("10.01"), 50) == Decimal("5.01") and R.weighted(None, 90) == Decimal("0.00")


def test_dates_come_in_as_utc_without_zone():
    assert R.clean_datetime("2026-11-20T15:00:00Z", "x") == datetime(2026, 11, 20, 15, 0)
    assert R.clean_datetime("2026-11-20T10:00:00-05:00", "x") == datetime(2026, 11, 20, 15, 0)
    assert R.clean_datetime("2026-11-20T10:00", "x") == datetime(2026, 11, 20, 10, 0) and R.clean_datetime("", "x") is None
    for bad in ("mañana", "1999-01-01T00:00:00Z"):
        with pytest.raises(CrmError):
            R.clean_datetime(bad, "x")
    assert str(R.clean_date("2026-11-20", "x")) == "2026-11-20"
    with pytest.raises(CrmError):
        R.clean_date("20/11/2026", "x")


def test_ids_that_do_not_fit_the_database_are_rejected():
    assert R.clean_id("", "x") is None and R.clean_id("7", "x") == 7
    for bad in ("0", "-3", "abc", str(2_147_483_648)):
        with pytest.raises(CrmError):
            R.clean_id(bad, "x")


def test_moving_to_won_or_lost_closes_and_moving_to_open_reopens():
    now = datetime(2026, 11, 12, 9, 0)
    assert R.move_effects("won", "open", "ignorado", now) == {"outcome": "won", "closed_at": now, "lost_reason": None, "stage_entered_at": now}
    assert R.move_effects("lost", "open", "  precio  ", now)["lost_reason"] == "precio" and R.move_effects("lost", "open", "", now)["lost_reason"] is None
    assert R.move_effects("open", "lost", None, now) == {"outcome": "open", "closed_at": None, "lost_reason": None, "stage_entered_at": now}
    with pytest.raises(CrmError):
        R.move_effects("lost", "open", "x" * 201, now)
    with pytest.raises(CrmError):
        R.move_effects("otra", "open", None, now)


def test_a_pipeline_keeps_one_open_one_won_and_one_lost_stage():
    R.check_stage_set([("open", False), ("won", False), ("lost", False)])
    R.check_stage_set([("open", False), ("open", True), ("won", False), ("lost", False)])
    for bad in ([("open", True), ("won", False), ("lost", False)], [("open", False), ("won", True), ("lost", False)], [("open", False), ("won", False)]):
        with pytest.raises(CrmError):
            R.check_stage_set(bad)
    assert R.clean_stage({"kind": "won"})["probability"] == 100 and R.clean_stage({"kind": "lost"})["probability"] == 0
    with pytest.raises(CrmError):
        R.clean_stage({"kind": "otra"})


def test_next_activity_is_the_earliest_planned_one():
    a, b, c = datetime(2026, 11, 20), datetime(2026, 11, 15), datetime(2026, 11, 10)
    assert R.next_due([("planned", a), ("planned", b), ("done", c), ("cancelled", c), ("planned", None)]) == b
    assert R.next_due([("done", c)]) is None and R.next_due([]) is None


def test_activities_need_a_link_a_valid_kind_and_a_reminder_before_the_date():
    with pytest.raises(CrmError):
        R.check_attached(None, None, None, None)
    R.check_attached(None, None, 5, None)
    with pytest.raises(CrmError):
        R.clean_activity({"subject": "Llamar", "kind": "visita"}, creating=True)
    with pytest.raises(CrmError):
        R.clean_activity({"subject": "Llamar", "kind": "call", "due_at": "2026-11-20T10:00:00Z", "remind_at": "2026-11-21T10:00:00Z"}, creating=True)
    ok = R.clean_activity({"subject": " Llamar ", "kind": "call", "due_at": "2026-11-20T10:00:00Z", "remind_at": "2026-11-20T09:00:00Z"}, creating=True)
    assert ok["subject"] == "Llamar" and ok["kind"] == "call"
    assert R.clean_result("no_answer") == "no_answer" and R.clean_result("") is None
    with pytest.raises(CrmError):
        R.clean_result("inventado")
    assert all(len(k) <= 24 for k in R.RESULTS) and all(len(k) <= 8 for k in R.ACTIVITY_KINDS)          # caben en las columnas result(24) y kind(8)


def test_leads_validate_email_status_and_conversion_rules():
    with pytest.raises(CrmError):
        R.clean_lead({"email": "no-es-correo"}, creating=True)
    with pytest.raises(CrmError):
        R.clean_lead({"status": "convertido"}, creating=False)          # solo la conversión lo fija
    assert R.clean_lead({"status": "Calificado"}, creating=False)["status"] == "calificado"
    assert R.lead_has_identity(None, None, "Empresa Ficticia", None) and not R.lead_has_identity("", " ", None, "")
    R.check_convertible("nuevo")
    for status in ("convertido", "descartado"):
        with pytest.raises(CrmError) as exc:
            R.check_convertible(status)
        assert exc.value.status == 409


def test_board_paging_is_bounded():
    assert R.board_paging(None) == (0, 50) and R.board_paging("-5") == (0, 50) and R.board_paging("abc") == (0, 50) and R.board_paging(10**9)[0] == R.BOARD_MAX_OFFSET and R.board_paging(0, 10**6)[1] == 200


# ------------------------------------------------------------------ código
def test_endpoints_are_plain_def_and_the_services_have_no_async():
    for rel in C2_PY:
        assert "async def" not in _read(rel), rel


def test_the_router_is_switched_off_with_the_crm_and_guards_roles():
    src = _read("app/routers/crm_pipeline.py")
    assert "dependencies=[Depends(crm_router._require_crm_enabled)]" in src and "router.dependencies.append(Depends(crm_router._check_path_ids))" in src
    tree = ast.parse(src)
    admin_only = {"create_pipeline", "rename_pipeline", "default_pipeline", "archive_pipeline", "restore_pipeline", "create_stage", "reorder_stages", "update_stage", "archive_stage", "restore_stage", "list_pipelines",
                  "archive_opportunity", "restore_opportunity", "archive_lead", "restore_lead", "erase_lead_preview", "erase_lead_route"}
    seen = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(isinstance(d, ast.Call) and getattr(d.func, "value", None) is not None and getattr(d.func.value, "id", "") == "router" for d in node.decorator_list):
            text = ast.get_source_segment(src, node)
            seen.add(node.name)
            assert ("admin_staff" in text) == (node.name in admin_only), node.name
            assert "view_staff" in text or "admin_staff" in text, node.name
    assert admin_only <= seen and {"board", "move_opportunity", "convert_lead", "complete_activity", "pipeline_meta"} <= seen


def test_the_main_app_mounts_the_router_and_the_pages_and_the_nav_lists_the_new_sections():
    main = _read("app/main.py")
    assert "_include(crm_pipeline_router.router" in main
    for path in ("/crm/oportunidades", "/crm/oportunidades/{opportunity_id}", "/crm/leads", "/crm/embudos"):
        assert f'@app.get("{path}")' in main, path
    assert '_require_page_role(request, "admin")' in main.split('def crm_embudos_page')[1].split("@app.get")[0]
    init = _read("app/crm/__init__.py")
    built = re.search(r"^SECTIONS_BUILT = \{([^}]*)\}", init, re.M).group(1)
    assert all(f'"{k}"' in built for k in ("cuentas", "oportunidades", "leads", "embudos"))


def test_the_board_costs_two_queries_whatever_the_size():
    tree = ast.parse(_read("app/crm/opportunities.py"))
    fns = {n.name: ast.get_source_segment(_read("app/crm/opportunities.py"), n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    board, cards = fns["board"], fns["_cards"]
    assert board.count(".all()") == 1 and board.count("_cards(") == 1 and cards.count(".all()") == 1          # totales + tarjetas
    assert "row_number()" in cards and ".limit(" not in board                                                  # ventana por etapa, no una consulta por columna
    for fn in ("board", "_cards"):          # nada de consultas dentro de bucles (sin N+1)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn)
        for loop in (x for x in ast.walk(node) if isinstance(x, (ast.For, ast.ListComp, ast.GeneratorExp))):
            assert not any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", "") == "db" for c in ast.walk(loop)), fn
    assert "group_by(CrmOpportunity.stage_id, CrmOpportunity.currency)" in board                               # COP y USD nunca se suman


def test_free_text_of_leads_and_opportunities_stays_out_of_the_history():
    src = _read("app/crm/history.py")
    assert re.search(r'"lead": \("description",\)', src) and re.search(r'"opportunity": \("description", "next_step"\)', src)
    assert "next_step" in R.OPPORTUNITY_LIMITS and "description" in R.OPPORTUNITY_LIMITS


def test_move_is_one_short_update_and_delegates_the_event_to_won_module():
    src = _read("app/crm/opportunities.py")
    move = src.split("def move_stage")[1].split("\n# ------")[0]
    assert "def on_won" in src and "won.create_event_for" in src.split("def on_won")[1].split("def ")[0]          # C4: el evento lo crea app/crm/won.py en la misma transacción
    assert "Evento(" not in move and "create_event" not in move and "make_client" not in move and "Tenant(" not in move


def test_erasing_a_lead_returns_counts_never_values():
    src = _read("app/crm/lead_erase.py")
    for fn in ("preview_lead", "erase_lead"):
        body = src.split(f"def {fn}")[1].split("\ndef ")[0]
        assert "lead.email" not in body.split("return")[-1] and "first_name" not in body.split("return")[-1]
    erase = _read("app/crm/erase.py")
    assert "erase_lead(" in erase and "CrmActivity" in erase and "_leads_by_email" in erase and "leads_to_check" in erase
    assert 'entity == "opportunity"' in erase          # el historial de las oportunidades de una cuenta suprimida también se borra


def test_leads_are_matched_for_automatic_erase_only_by_exact_email():
    erase = _read("app/crm/erase.py")
    by_email = erase.split("def _leads_by_email")[1].split("def _leads_to_check")[0]
    assert "email_norm.in_" in by_email and "phone" not in by_email and "name" not in by_email.replace("emails", "")


def test_frontend_rules_hold_for_every_c2_file():
    for rel in C2_JS + C2_TEMPLATES + ["static/css/p-crm-c2.css"]:
        src = _code(rel)
        assert "onclick" not in src.lower() and "onchange=" not in src.lower(), rel
        assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", src), rel
        assert not re.search(r"setInterval|setTimeout|requestAnimationFrame\(.*setTimeout", src), f"{rel}: nada se refresca solo"
        assert "innerHTML" not in src.replace("bodyHtml", ""), rel
        assert "rgb(" not in src and "rgba(" not in src and "hsl(" not in src, rel
    css = _read("static/css/p-crm-c2.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and re.search(r"var\(--gw-", css)
    assert not re.search(r"\d+(\.\d+)?px\s*[;}]", css)          # los px solo van en las consultas de medios; el resto usa --gw-sp-*/--gw-fs-*


def test_templates_use_url_for_static_and_the_shared_nav():
    for rel in C2_TEMPLATES[:4]:
        src = _read(rel)
        assert "crm_section" in src and '_crm_shell_top.html' in src and '_crm_shell_bottom.html' in src, rel
        assert 'href="/static' not in src and 'src="/static' not in src, rel
    top = _read("templates/_crm_shell_top.html")
    assert '_crm_nav.html' in top and "url_for('static'" in top and top.rstrip().endswith('{% include "_crm_nav.html" %}')
    assert "<main" in top and "</main>" in _read("templates/_crm_shell_bottom.html")


def test_every_screen_has_title_three_steps_one_primary_button_and_empty_and_error_states():
    for rel in ("templates/crm_oportunidades.html", "templates/crm_leads.html", "templates/crm_embudos.html"):
        src = _read(rel)
        assert 'gw-page-head__title' in src and src.count('class="gw-steps__n"') == 3, rel
        assert src.count("gw-btn gw-btn--primary") >= 1, rel
    for rel in ("static/js/crm_kanban.js", "static/js/crm_leads.js", "static/js/crm_embudos.js"):
        src = _read(rel)
        assert "stateBlock(\"error\"" in src and "stateBlock(\"empty\"" in src, rel


def test_the_kanban_has_a_keyboard_and_touch_alternative_to_dragging():
    js = _read("static/js/crm_kanban.js")
    assert "dragstart" in js and "Mover a…" in js and "data-move" in js and "dragover" in js
    assert "lost_reason" in js and "updated_at" in js          # el motivo de pérdida y la versión van al servidor


def test_import_page_is_admin_only_without_polling_and_uses_known_icons():
    main = _read("app/main.py")
    assert '_require_page_role(request, "admin")' in main.split("def crm_importar_page")[1].split("@app.get")[0]
    js, html = _read("static/js/crm_importar.js"), _read("templates/crm_importar.html")
    assert "setInterval" not in js and "setTimeout" not in js and "innerHTML" not in js and "alert(" not in js.replace("showToast", "")
    icons = _read("static/img/icons.svg")
    import re as _re
    for name in _re.findall(r"ic\('([a-z-]+)'", html):
        assert f'id="i-{name}"' in icons, name
    assert '"importar"' in _re.search(r"^SECTIONS_BUILT = \{([^}]*)\}", _read("app/crm/__init__.py"), _re.M).group(1)
