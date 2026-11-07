"""Fase 1.10 (6-nov-2026): «deshabilitar demos automáticas» por CUENTA y bloques plegables en las pantallas de configuración.
Pruebas de código fuente (sin base de datos); el comportamiento se verificó en navegador (ver docs/historial.md)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_la_preferencia_de_demos_vive_en_la_cuenta():
    assert "tours_auto_off = Column(Boolean" in read("app/models.py")
    mig = read("alembic/versions/0085_tours_auto_off.py")
    assert 'revision = "0085_tours_auto_off"' in mig and len("0085_tours_auto_off") <= 32
    assert 'down_revision = "0084_stats_links"' in mig and "ADD COLUMN IF NOT EXISTS tours_auto_off" in mig
    au = read("app/routers/auth.py")
    assert 'request.session["tours_off"] = bool(staff.tours_auto_off)' in au          # se copia a la sesión al ingresar (cualquier dispositivo)
    assert '@router.put("/api/me/tours-auto-off")' in au and "Depends(get_current_staff)" in au
    assert re.search(r"def set_tours_auto_off\(", au)                                   # endpoint `def`, no `async def`


def test_las_demos_automaticas_respetan_la_preferencia_y_la_guia_manual_sigue():
    js = read("static/js/gw-ui.js")
    assert "if (auto && !window.GW_TOURS_OFF)" in js                                    # el arranque automático se salta
    assert "startTour(el.getAttribute('data-gw-tour-restart'), { force: true })" in js  # el botón «Guía» siempre funciona
    assert "/api/me/tours-auto-off" in js and "data-gw-tour-off" in js
    assert "window.GW_TOURS_OFF" in read("templates/_gw_head.html")
    cfg = read("templates/configuracion.html")
    assert 'id="toursOff"' in cfg and "Deshabilitar demos automáticas" in cfg and "tours_off" in cfg


def test_los_bloques_de_configuracion_se_pliegan_sin_mover_nodos():
    js = read("static/js/gw-ui.js")
    assert "function foldInit" in js and "data-gw-fold-btn" in js and "data-gw-fold-all" in js and "foldInit();" in js
    assert "wrapChild" not in js and "appendChild(item" not in js                         # solo clase gw-is-folded: ids y selectores no cambian
    css = read("static/css/design-system.css")
    assert ".gw-group__item.gw-is-folded > :not(.gw-item-head) { display: none !important; }" in css
    # «Formulario de persona» ahora tiene cabecera plegable como «Campos de la persona»
    assert '<div class="gw-item-head"><h4 id="personFormTitle">Formulario de persona</h4></div>' in read("templates/kiosk_parametros.html")
