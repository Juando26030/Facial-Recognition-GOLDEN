"""Fase 10 (E): comprobaciones «de texto» de la tarjeta «Servidor local» (corren sin base de datos)."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def src(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_endpoints_are_protected_and_go_through_storage():
    r = src("app/routers/local_installer.py")
    assert r.count("local_installer.require_installer_access") == 2 and "get_storage()" in r and "open(" not in r and "FileResponse" not in r
    m = src("app/main.py")
    assert "_include(local_installer_router.router" in m and "can_local_installer" in m


def test_card_hidden_for_digitador_and_cliente_in_template_and_rule():
    assert 'EXCLUDED_ROLES = frozenset({"digitador", "cliente"})' in src("app/local_installer.py")
    t = src("templates/configuracion.html")
    assert t.count("{% if can_local_installer %}") >= 3 and 'id="tab_servidor"' in t and "Aún no disponible" in src("static/js/local-installer-card.js")


def test_card_follows_frontend_rules():
    js = src("static/js/local-installer-card.js")
    assert "alert(" not in js and "onclick" not in js and "innerHTML" not in js
    assert "url_for('static', path='js/local-installer-card.js')" in src("templates/configuracion.html")


def test_explanation_doc_exists_without_jargon():
    d = src("docs/EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md")
    for word in ("Docker", "endpoint", "token", "migración"):
        assert word not in d
