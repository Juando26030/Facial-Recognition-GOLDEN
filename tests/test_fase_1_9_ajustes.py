"""Fase 1.9 (6-nov-2026): iconos en las cifras de texto de las estadísticas, Estadísticas oculto al digitador, diseñador del formulario de persona con lienzo/arrastre/vista previa y una sola papelera por buscador.
Pruebas de código fuente (sin base de datos): la lógica pura del diseñador se prueba en Node (tests/js/person_form_check.js)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_las_cifras_de_texto_de_las_estadisticas_llevan_icono():
    an, rt = read("app/analytics.py"), read("app/routers/analytics.py")
    assert 'icon: str = ""' in an and '"icon": icon' in an
    for label, icon in (("Primer registro", "flag-start"), ("Último registro", "flag-end"), ("Hora pico", "peak"), ("Ritmo promedio", "gauge"),
                        ("Vienen del Excel (base)", "sheet"), ("Nuevos digitados a mano", "hand"), ("Llegaron por formulario", "form")):
        assert re.search(rf'kpi\("{re.escape(label)}".*icon="{icon}"', rt), (label, icon)
    sprite = read("static/img/icons.svg")
    for name in ("sheet", "hand", "flag-start", "flag-end", "peak", "gauge", "form", "help"):
        assert f'id="i-{name}"' in sprite, name
    # los símbolos nuevos quedan DENTRO del sprite (no en el comentario del encabezado)
    assert sprite.index('id="i-sheet"') > sprite.index("-->")
    js = read("static/js/analytics-dashboard.js")
    assert "ad-kpi__icon" in js and "k.icon" in js and ".ad-kpi__icon--sheet" in js
    assert "icon(" in read("static/js/form-stats.js") and ".fs-kpi__icon" in read("static/css/form-stats.css")


def test_el_digitador_no_ve_la_puerta_de_estadisticas():
    sel = read("templates/kiosk_select.html")
    tile = sel.index('"/kiosk/%s/estadisticas"')
    assert 'staff_role != "digitador"' in sel[tile - 400:tile]
    assert 'exclude_roles=["digitador"]' in read("app/main.py")          # el servidor sigue negándolo igual


def test_el_disenador_de_persona_es_un_lienzo_como_el_de_formularios_web():
    js = read("static/js/person-form-designer.js")
    for token in ("draggable", "dragstart", "drop", "gw-pf-card", "gw-pf-gap", "pfPreview", "pfProps", "dropAt", "moveKey", "rowsOf", "Previsualizar"):
        assert token in js, token
    assert "<table" not in js and "'tbody'" not in js and "Junto al anterior" not in js          # se fue la tabla con «junto al anterior»
    css = read("static/css/parametros.css")
    for cls in (".gw-pf-grid", ".gw-pf-card", ".gw-pf-row--4", ".gw-pf-gap--over", ".gw-pf-props"):
        assert cls in css, cls
    assert "register({ key: 'personform'" in js and "id: 'pfSave'" in js        # el guardado global sigue igual


def test_una_sola_papelera_por_buscador_mas_grande_y_con_margen():
    css, ui = read("static/css/design-system.css"), read("static/js/gw-ui.js")
    assert not (ROOT / "static/js/gw-clear.js").exists() and "gw-clear.js" not in read("templates/_gw_head.html")
    assert "right: var(--gw-sp-4)" in css and re.search(r"\.gw-search__clear--in \.gw-icon \{ width: 1\.5rem", css)
    assert "data-gw-clear-btn" in ui
