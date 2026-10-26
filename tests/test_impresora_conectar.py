"""«Conectar impresora» (25-oct-2026): idempotente, un solo intento a la vez, coordinada entre pestañas, mensajes en español y que suelta la impresora al cerrar. El comportamiento se prueba
con una impresora simulada en tests/js/ql_usb_connect_check.js y tests/js/shared_print_rules_check.js; aquí se vigila que las piezas sigan en su sitio."""
import pathlib


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_the_usb_layer_is_idempotent_single_flight_and_talks_between_tabs():
    ql = _read("static/js/ql-usb.js")
    assert "var inflight = null;" in ql and "if (state.device && state.device.opened) return Promise.resolve(state.device);" in ql          # ya abierta: no se vuelve a abrir
    assert "var wasLive = state.device === device && device.opened;" in ql                                                                  # un fallo al reabrir no cierra la conexión viva
    assert 'new BroadcastChannel("golden-ql-usb")' in ql and "function remoteOwner" in ql and "function sendViaOwner" in ql and "function releaseNow" in ql
    assert "no puede usar la impresora por USB directo (Windows)" in ql and "Controlador de Windows" in ql and "cuadro de Windows" not in ql          # «Access denied» con la acción a seguir


def test_the_registration_screen_shows_the_real_state_and_releases_the_printer_on_close():
    sp = _read("static/js/shared-print.js")
    assert "QLUsb.ready()" in sp and "viaTab" in sp and "QLUsb.remoteOwner()" in sp                                                        # el estado sale de la conexión real o de la pestaña dueña
    assert "['pagehide', 'beforeunload']" in sp and "QLUsb.releaseNow()" in sp                                                             # se suelta al cerrar o recargar
    assert "Impresora conectada en otra pestaña de este navegador" in sp and "ya está conectada" in sp
    assert "printer_connected: usb.busy || (usb.ok && usb.viaTab && !driverOn()) ? null : canAuto()" in sp                                                            # el latido anuncia lo que sirve para imprimir (USB o controlador)
