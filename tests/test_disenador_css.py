"""Diseñador de escarapelas: el lienzo no se centra con flex dentro del contenedor con scroll (con zoom grande dejaba inalcanzable lo de arriba)."""
import pathlib

CSS = (pathlib.Path(__file__).resolve().parent.parent / "static" / "css" / "gw-disenador.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    start = CSS.index(selector + " {")
    return CSS[start:CSS.index("}", start)]


def test_wrapper_no_centra_con_flex():
    assert "justify-content: center" not in _rule(".badge-canvas-wrapper")
    assert "align-items: center" not in CSS.split("@media (min-width: 821px)")[1].split(".badge-canvas-wrapper {", 1)[1].split("}", 1)[0]


def test_host_se_centra_con_margin_auto():
    assert "margin: auto" in _rule(".badge-canvas-host")


def test_movil_una_sola_vista_con_lienzo_fijo():
    movil = CSS.split("@media (max-width: 820px)")[1]
    assert ".badge-canvas-zone { position: sticky; top: 0" in movil
    assert ".editor-mobile-tabs { display: none; }" in movil
    assert 'data-tab="props"' not in movil          # ya no se esconde el lienzo al editar propiedades


def test_movil_el_rotulo_del_zoom_no_se_encoge():
    movil = CSS.split("@media (max-width: 820px)")[1]
    assert "#zoomLabel { flex: 0 0 auto; min-width: 6.5rem" in movil


def test_pantalla_completa_del_disenador():
    assert "body.editor-full .gw-ed-body { position: fixed" in CSS
    assert "body.editor-full .gw-savebar { position: fixed" in CSS and "z-index: 1200" in CSS          # la barra única de guardado queda por encima de la ventana
    tpl = (pathlib.Path(__file__).resolve().parent.parent / "templates" / "badge_editor.html").read_text(encoding="utf-8")
    assert 'id="edFullOpen"' in tpl and 'id="edFullClose"' in tpl
    assert "Hacer clic afuera no cierra" in tpl


def test_pantalla_completa_no_se_cierra_con_clic_afuera_ni_esc():
    tpl = (pathlib.Path(__file__).resolve().parent.parent / "templates" / "badge_editor.html").read_text(encoding="utf-8")
    bloque = tpl.split("function setFull(on)")[1].split("let resizeTimer")[0]
    assert "keydown" not in bloque and "backdrop" not in bloque.lower()


def test_guia_de_3_pasos_arranca_cerrada_y_se_cierra_afuera():
    tpl = (pathlib.Path(__file__).resolve().parent.parent / "templates" / "badge_editor.html").read_text(encoding="utf-8")
    bloque = tpl.split("const guideEl")[1].split("let resizeTimer")[0]
    assert "guideEl.open = false" in bloque and "'Escape'" in bloque and "guideEl.contains(e.target)" in bloque
