"""Ajustes del 11-nov-2026: ruleta (tamaño en la proyección y sorteos en fila), «Volver al kiosco», editar persona sin «cédula nueva» y parámetros de estadía.
Pruebas «de texto» (leen el código fuente): corren sin base de datos."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _t(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_display_css_does_not_override_fields_scale():
    css = _t("static/css/gw-ruleta-display.css")
    rules = re.findall(r"\.rr-winner__entity\s*\{([^}]*)\}", css)
    sized = [r for r in rules if "font-size" in r]
    assert len(sized) == 1 and "--rr-fields-scale" in sized[0]          # la última regla con tamaño es la que usa la escala del operador


def test_roulette_queue_backend_exists():
    src = _t("app/routers/roulette.py")
    assert 'roulette/queue"' in src and "MAX_QUEUE_STEPS" in src
    assert 'data.get("queue")' in src and '"queue": True' in src                 # una autorización para toda la fila
    assert "_next_info" in src and "authorized_next" in src
    assert 'new["queue"] = old.get("queue")' in src                              # guardar el comportamiento no borra la fila


def test_roulette_queue_ui_and_display():
    ui, disp = _t("templates/kiosk_ruleta.html"), _t("templates/roulette_display.html")
    assert 'id="grp_fila"' in ui and 'id="qRun"' in ui and "queue: true" in ui
    assert 'id="qSave"' not in ui and "key: 'queue'" in ui                    # un solo botón de guardado: la fila se registra en GWParams
    assert "scheduleAuto" in disp and "draw.spin_seconds" in disp and "draw.next" in disp


def test_back_to_kiosk_button_everywhere():
    js, side = _t("static/js/kiosk-back.js"), _t("templates/_sidebar.html")
    assert "Volver al kiosco" in js and "kiosk-back.js" in side
    assert r"/^\/kiosk\/(\d+)\/[^/]+/" in js and "golden-event-strip-inner" in js


def test_edit_person_has_no_new_cedula_option():
    assert "editNewCedulaChk" not in _t("static/js/directory.js")


def test_dwell_params_explain_steps():
    html = _t("templates/kiosk_parametros.html")
    assert "Paso 1 · Medir" in html and "Paso 2 · Exigir" in html and 'id="dwellSummary"' in html


def test_more_tools_open_by_default():
    assert 'id="gwMoreTools" open' in _t("templates/kiosk_select.html")
