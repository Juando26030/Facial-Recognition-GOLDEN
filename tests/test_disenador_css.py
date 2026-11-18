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
