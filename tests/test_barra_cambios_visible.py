"""La barra «Guardar cambios» solo se muestra donde hay algo editable; el worker del quiosco no aborta archivos sin copia."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _leer(ruta):
    return (RAIZ / ruta).read_text(encoding="utf-8")


def test_barra_se_oculta_sin_bloques_editables():
    js = _leer("static/js/params-save.js")
    assert "gw-savebar--vacia" in js and "[data-psave]" in js and "MutationObserver" in js
    assert ".gw-savebar.gw-savebar--vacia { display: none; }" in _leer("static/css/design-system.css")


def test_worker_sin_copia_espera_la_red_sin_tope():
    sw = _leer("static/js/kiosk-sw.js")
    assert "(await cached()) ? await withTimeout(req) : await fetch(req)" in sw
