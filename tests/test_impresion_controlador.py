"""Impresión por el controlador de Windows (25-oct-2026): modo por equipo, lanzador sin cuadro, guía del operador y el aviso de «acceso denegado» sin afirmar que «se imprime con el cuadro de Windows».
El comportamiento se prueba con impresora simulada en tests/js/driver_print_check.js y tests/js/shared_print_rules_check.js; aquí se vigila que las piezas estén conectadas."""
import pathlib
import re

from tests.conftest import login


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def test_the_registration_page_loads_the_driver_module_before_the_shared_print_script(client, factory, db):
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso")
    ev.shared_print_enabled = True
    db.commit()
    login(client, "adm")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert page.index("js/ql-usb.js") < page.index("js/driver-print.js") < page.index("js/shared-print.js")
    assert client.get("/static/js/driver-print.js").status_code == 200


def test_the_operator_guide_is_served_and_has_the_required_steps_without_third_parties():
    html = _read("static/ayuda/impresion-windows.html")
    for needle in ("solo el controlador", "Editor Lite", "predeterminada", "62 mm", "Corte automático", "Descargar lanzador", "Windows protegió su PC", "Ejecutar de todos modos", "Automático", "Imprimir-GoldenWeb.bat"):
        assert needle in html, needle
    assert not re.search(r"https?://(?!support\.brother|www\.google\.com/chrome)", html), "sin scripts, fuentes ni enlaces de terceros (solo las páginas de descarga que se nombran)"
    assert "<script" not in html


def test_the_guide_page_is_reachable_from_the_app(client):
    r = client.get("/static/ayuda/impresion-windows.html")
    assert r.status_code == 200 and "Controlador de Windows" in r.text


def test_the_denied_message_no_longer_claims_windows_prints_with_its_dialog_and_points_to_the_guide():
    ql = _read("static/js/ql-usb.js")
    sp = _read("static/js/shared-print.js")
    assert "no puede usar la impresora por USB directo (Windows)" in ql and "tablet o celular como puesto de impresión" in ql
    assert "cuadro de Windows pero no puede atender" not in ql and "imprime con el cuadro de Windows" not in ql
    assert "/static/ayuda/impresion-windows.html" in sp and 'id="spGuide"' in sp


def test_the_three_modes_are_wired_in_the_panel_the_bar_and_the_shared_queue():
    sp = _read("static/js/shared-print.js")
    assert "data-mode" in sp and "Automático (recomendado)" in sp and "USB directo" in sp and "Controlador de Windows" in sp
    assert "kind = 'info'" in sp and "Impresión por controlador de Windows" in sp and "impresión automática activa" in sp and "impresión con cuadro de diálogo" in sp
    assert "Usar siempre este modo en este equipo" in sp and "Imprimir pendientes" in sp and "Descargar lanzador para este computador" in sp
    assert "Controlador de Windows (Brother QL-800)" in sp                                                   # el equipo anuncia «Impresora conectada por Windows» a los demás
    assert "if (printMode === 'driver' || driverOn()) { render(); heartbeat(); return Promise.resolve(); }" in sp   # en este modo no se intenta WebUSB
    dp = _read("static/js/driver-print.js")
    assert "--kiosk-printing" in dp and "GoldenWebImpresion" in dp and "@page { size: " in dp and "margin: 0 }" in dp


def test_the_designer_can_try_the_longest_name_of_the_event(client, factory, db):
    """«Probar con el nombre más largo del evento» (25-oct-2026): la persona con el texto más largo, para ver lo que de verdad pasa con los textos."""
    from app.models import User
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    factory.person(ev, "1001", "Ana", "Mora")
    factory.person(ev, "1002", "MARÍA DE LOS ÁNGELES", "RODRÍGUEZ VILLAMIZAR")
    factory.person(ev, "1003", "Luis", "Paz")
    db.query(User).filter_by(id="1003", tenant_id=ev.tenant_id).update({"opt_1": "x"})
    db.commit()
    login(client, "coord1")
    empty = client.get(f"/api/events/{factory.event('creado').id}/badge-longest-sample").json()
    assert empty == {"sample": None}
    s = client.get(f"/api/events/{ev.id}/badge-longest-sample").json()["sample"]
    assert (s["id"], s["first_name"], s["last_name"]) == ("1002", "MARÍA DE LOS ÁNGELES", "RODRÍGUEZ VILLAMIZAR")
    assert "extra_fields" in s and "optional_field_labels" in s


def test_the_designer_has_the_fit_option_the_longest_name_button_and_the_amber_warning():
    ed = _read("templates/badge_editor.html")
    assert 'id="longestBtn"' in ed and "Probar con el nombre más largo del evento" in ed
    assert "Crecer hacia abajo" in ed and "Reducir para caber" in ed and "Una sola línea" in ed and 'id="p_fit"' in ed
    assert "se achicaría al" in ed and "se cortaría con «…»" in ed and "f.ratio < 0.8" in ed
    rd = _read("static/js/badge-render.js")
    assert "const MIN_RATIO = 0.6;" in rd and "function planText" in rd and "const withPlan = Object.assign({}, opts, { plan: planText(template, data) });" in rd
    assert "data-fit=\"truncated\"" in _read("static/js/shared-print.js")                      # «…» solo como último recurso y con aviso al imprimir


def test_the_driver_page_never_goes_over_the_useful_tape_width_and_has_the_calibration():
    dp = _read("static/js/driver-print.js")
    assert "var pageW = pageWidthMm && pageWidthMm >= imgW ? pageWidthMm : imgW;" in dp and "clampOffset" in dp
    sp = _read("static/js/shared-print.js")
    assert "data-dx" in sp and "data-dy" in sp and "Calibración: desplazamiento horizontal" in sp and "DP.getOffsets(storage())" in sp


def test_kiosk_printing_goes_as_pdf_without_chrome_headers_in_every_path():
    """Hotfix 27-oct-2026: con --kiosk-printing Chrome dibujaba sus encabezados y pies (fecha, título, dirección, «1/1») en el margen de la impresora real. Sin cuadro, la etiqueta va como PDF
    del tamaño exacto (el visor de PDF no los dibuja): controlador, etiqueta de prueba y compartida (drvPrint) y la ruta antigua. El PDF se prueba en tests/js/driver_print_check.js."""
    dp = _read("static/js/driver-print.js")
    assert "function pdfFromBitmap(" in dp and "function printPdf(" in dp and 'type: "application/pdf"' in dp and "if (opts && opts.pdf)" in dp
    sp = _read("static/js/shared-print.js")
    assert "const pdf = kiosk ? { bitmap: out.bitmap, width: out.tapeDots, height: out.height, mirror: p.mirror } : null;" in sp
    legacy = _read("templates/badge_print.html")
    assert "js/driver-print.js" in legacy and "html2canvas" in legacy and "if (kioskMode()) await printAsPdf(template, rotate, pw, ph); else window.print();" in legacy
