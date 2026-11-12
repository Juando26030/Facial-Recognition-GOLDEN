"""CRM C1b-2: pruebas SIN base de datos (`python3 -m pytest -q --noconftest tests/test_crm_pantallas_texto.py`): reglas visuales y de seguridad de las pantallas de lista y ficha."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["templates/crm_cuentas.html", "templates/crm_cuenta.html", "static/js/crm_cuentas.js", "static/js/crm_cuenta.js", "static/js/crm_cuenta_tabs.js", "static/css/p-crm.css"]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_inline_handlers_or_native_dialogs():
    for rel in FILES:
        text = _read(rel)
        assert not re.search(r"\sonclick\s*=", text), rel
        assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", text), rel


def test_templates_use_url_for_static_and_design_tokens():
    for rel in ("templates/crm_cuentas.html", "templates/crm_cuenta.html"):
        text = _read(rel)
        assert 'href="/static' not in text and 'src="/static' not in text, rel
        assert "style=" not in text, rel
    css = _read("static/css/p-crm.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "colores sueltos en p-crm.css"
    assert not re.search(r"font-size:\s*[\d.]+(px|rem|em)", css), "tamaños de letra sueltos en p-crm.css"


def test_user_text_is_never_written_with_innerhtml():
    for rel in ("static/js/crm_cuentas.js", "static/js/crm_cuenta.js", "static/js/crm_cuenta_tabs.js"):
        text = _read(rel)
        assert text.count("innerHTML") <= 1 and ("innerHTML" not in text or "GW.skeleton.html" in text), rel


def test_page_routes_are_guarded():
    main = _read("app/main.py")
    block = main[main.index("def _crm_page"):main.index('@app.get("/clientes")')]
    assert "crm_enabled()" in block and "status_code=404" in block
    assert '_require_page_role(request, "comercial")' in block
    assert block.index('"/crm/cuentas/nueva"') < block.index('"/crm/cuentas/{account_id}"')


def test_sidebar_link_only_when_crm_visible():
    assert "crm_nav_visible(request)" in _read("templates/_sidebar.html")
    assert 'templates.env.globals["crm_nav_visible"]' in _read("app/main.py")


def test_ficha_sends_the_version_it_saw_and_handles_conflict():
    js = _read("static/js/crm_cuenta.js")
    assert "updated_at = account.updated_at" in js and "err.status === 409" in js
    assert "confirm_duplicate" in js


def test_erase_flow_shows_a_preview_and_keeps_the_review_notice():
    js = _read("static/js/crm_cuenta_tabs.js")
    assert "/erase-preview" in js and js.index("/erase-preview") < js.index('"/erase"'), "la vista previa va antes de suprimir"
    assert "showReview(r.counts)" in js and 'ok.dataset.go = "close"' in js      # el aviso se cierra solo con el botón, no desaparece solo
    assert "setTimeout" not in js
    assert "review.description" in js or "r.description" in js
    assert js.count("insertAdjacentHTML") == 1, "HTML armado a mano solo con texto fijo"


def test_confirmation_needs_reason_and_the_typed_name():
    js = _read("static/js/crm_cuenta_tabs.js")
    assert "go.disabled = true" in js and "reason.value.trim()" in js and "toLowerCase() === c.full_name" in js
