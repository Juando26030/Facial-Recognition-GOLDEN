"""Fase 3 (pantallas de archivados): «Estados de evento» en Configuración y gestión de plantillas de formulario guardadas. Pruebas de fuente (sin diálogos nativos ni onclick en línea,
solo plantillas con url_for('static'), sin colores sueltos) más la visibilidad de la pestaña por rol."""
import re
from pathlib import Path

from jinja2 import Environment

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent
JS = ["static/js/archive-rules.js", "static/js/event-states-admin.js", "static/js/kiosk-formularios.js"]
HTML = ["templates/configuracion.html", "templates/kiosk_formularios.html"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_native_dialogs_nor_inline_handlers():
    for rel in JS:
        src = read(rel)
        assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", src), rel
        assert not re.search(r"on(click|change)\s*=|\bonclick\b\s*[\"']", src, re.I), rel
    for rel in HTML:
        assert not re.search(r"\son(click|change|submit|input)\s*=", read(rel)), rel


def test_new_screens_use_toast_helpers_and_delegation():
    states, forms = read("static/js/event-states-admin.js"), read("static/js/kiosk-formularios.js")
    for src in (states, forms):
        assert "showToast" in src and "showConfirm" in src
    assert "showPrompt" in states
    assert "$('estadosList').addEventListener('click'" in states and "$('tplList').addEventListener('click'" in forms
    # el borrado definitivo pide confirmación y solo se ofrece a super_admin (archive-rules.js)
    assert "Eliminar definitivamente" in states and "Eliminar definitivamente" in forms
    rules = read("static/js/archive-rules.js")
    assert "del: role === 'super_admin'" in rules and "form_template: 'coordinador'" in rules and "event_state: 'admin'" in rules


def test_templates_parse_and_use_url_for_static():
    env = Environment()
    for rel in HTML:
        env.parse(read(rel))
    for rel in HTML:
        for src in re.findall(r'<script[^>]+src="([^"]+)"', read(rel)) + re.findall(r'<link[^>]+href="([^"]+\.css)"', read(rel)):
            assert "url_for('static'" in src, (rel, src)
    assert "js/event-states-admin.js" in read("templates/configuracion.html") and "js/archive-rules.js" in read("templates/kiosk_formularios.html")


def test_no_loose_colors_or_sizes_in_new_css():
    css = read("static/css/p-configuracion.css").split("Estados de evento (static/js/event-states-admin.js)")[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\d(px|rem)\b", css) and "var(--gw-" in css


def test_states_tab_only_for_admin(client, factory):
    factory.staff("admin", "adm1")
    factory.staff("coordinador", "coord1")
    login(client, "adm1")
    page = client.get("/configuracion").text
    assert 'id="tab_estados"' in page and 'id="estadosList"' in page and "event-states-admin.js" in page
    client.post("/logout")
    login(client, "coord1")
    page = client.get("/configuracion").text
    assert 'id="tab_estados"' not in page and "event-states-admin.js" not in page
