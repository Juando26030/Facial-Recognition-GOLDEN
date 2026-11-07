"""Pantalla «Diseñar plantilla para eventos»: invariantes estáticos de la plantilla, el diseñador y el vínculo desde Configuración (sin base de datos)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_page_has_both_views_one_savebar_and_the_guide():
    html = _read("templates/plantilla_evento.html")
    assert "Vista de creación de evento" in html and "Vista calendario" in html
    assert html.count('id="paramsSaveBar"') == 1 and html.count('id="paramsSaveBtn"') == 1
    assert 'data-gw-tour="plantilla-evento"' in html and "data-gw-tour-auto" in html
    assert len(re.findall(r"data-gw-tour-step=", html)) >= 3 and html.count("{% call ayuda(") == 3
    for ident in ("tplMeta", "tplPaletteA", "tplCanvasA", "tplPropsA", "tplPaletteB", "tplCanvasB", "tplPropsB", "tplError", "tplRetry", "tplLoading"):
        assert f'id="{ident}"' in html, ident


def test_the_page_scripts_load_in_order():
    html = _read("templates/plantilla_evento.html")
    order = [html.index("path='js/" + n) for n in ("params-save.js", "event-field-render.js", "event-template-designer.js", "plantilla-evento.js")]
    assert order == sorted(order)
    assert "url_for('static'" in html and "css/gw-plantilla-evento.css" in html


def test_the_glue_saves_with_the_single_savebar_and_the_versioned_endpoint():
    js = _read("static/js/plantilla-evento.js")
    assert "GWParams.register" in js and "'/api/event-template'" in js and "method: 'PUT'" in js
    assert "alert(" not in js and "confirm(" not in js


def test_configuracion_links_to_the_designer_for_admins_only():
    html = _read("templates/configuracion.html")
    i = html.index('id="tab_plantilla"')
    assert html.rfind("{% if is_admin_plus %}", 0, i) > html.rfind("{% endif %}", 0, i)      # dentro del bloque admin+
    assert "/configuracion/plantilla-evento" in html
