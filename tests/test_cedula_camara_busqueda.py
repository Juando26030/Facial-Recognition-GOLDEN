"""Cédula vieja/nueva leída con la cámara (19-nov-2026): busca por cédula, luego por nombre, y sin coincidencias avisa con una ventana roja grande. El QR no cambia."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_camera_cedula_uses_the_search_flow_and_only_it_raises_the_big_alert():
    js = (ROOT / "static/js/directory.js").read_text(encoding="utf-8")
    assert "scanCedulaCard" in js and "showNotFoundAlert" in js
    assert "No encontramos coincidencias de esta persona en la base de datos" in js
    assert js.count("if (bigNotFound) showNotFoundAlert(") == 2                  # sin coincidencias por nombre y sin nombre
    assert "submitScannedCedula: (cedula, nameInfo, method)" in js                # el camino del QR queda igual
    html = (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "directorySearch.scanCedulaCard(d.cedula" in html
    assert "submitScannedCedula(r.cedula, { nombres: r.nombres, apellidos: r.apellidos }, 'qr')" in html
    assert ".gw-notfound" in (ROOT / "static/css/registro.css").read_text(encoding="utf-8")


def test_scan_updates_the_directory_incrementally_and_the_reader_is_warmed_up_when_idle():
    js = (ROOT / "static/js/directory.js").read_text(encoding="utf-8")
    core = js[js.index("async function fastCheckinCore("):js.index("if (opts.fastCheckin && cedulaInput) {")]
    assert "await reload();" not in core and core.count("await syncAfterScan();") == 3        # tras escanear: solo lo que cambió (40.000 personas = 40 páginas por escaneo antes)
    qr = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert "function warm()" in qr and "requestIdleCallback" in qr and "if (warmPromise) await warmPromise;" in qr
    assert "QrScanner.warm()" in (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "await yieldUI();" in (ROOT / "static/js/cedula-readers.js").read_text(encoding="utf-8")


def test_cedula_is_read_from_a_guided_high_resolution_photo_and_the_qr_stays_live():
    """24-nov-2026 (Juan David): la cédula vieja/nueva ya no se lee cuadro a cuadro; misma cámara con recuadro guía + «Tomar foto» en alta resolución (static/js/cedula-foto.js).
    El QR sigue en vivo como siempre. Un solo componente para todas las pantallas (Registro, alta manual, Áreas, Inventario)."""
    qr = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    cedula = qr[qr.index("/* ---- Cédula vieja / nueva"):qr.index("async function setMode(m)")]
    assert "F.attach(" in cedula and "startCamera" not in cedula and "resume()" not in cedula        # nada de lectura en vivo para la cédula
    assert "FOTO_URL = '/static/js/cedula-foto.js?v=9'" in qr and "gw-cam__shoot" in qr and ">Tomar foto</button>" in qr
    live_qr = qr[qr.index("async function start() {"):qr.index("/* ---- Cédula vieja / nueva")]
    assert "await detector.detect(video)" in live_qr and "jsQR(img.data" in live_qr and "setTimeout(tick, 150)" in live_qr   # el QR sigue en vivo
    foto = (ROOT / "static/js/cedula-foto.js").read_text(encoding="utf-8")
    assert "takePhoto(" in foto and "cedula-mrz-scan" in foto and "Procesando la foto…" in foto
    assert "No se pudo leer la cédula: acérquela, evite reflejos y tome otra foto." in foto
    for page in ("templates/kiosk_registro.html", "static/js/areas.js", "static/js/inventario.js"):
        assert "modes: ['old', 'new', 'qr']" in (ROOT / page).read_text(encoding="utf-8")            # todas usan el mismo QrScanner.open
    assert "QrScanner.FOTO_URL" in (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")   # el service worker del quiosco lo guarda para sin conexión
    css = (ROOT / "static/css/gw-captura.css").read_text(encoding="utf-8")
    assert ".gw-cam__shoot[hidden] { display: none; }" in css


def test_small_qr_camera_reads_a_1cm_code():
    """26-nov-2026 (Juan David): el QR oficial mide 1 × 1 cm y la cámara no lo leía (el lector 2D sí). Alta resolución, enfoque continuo, zoom y el centro ampliado."""
    qr = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert "width: { ideal: 1920 }, height: { ideal: 1080 }" in qr                                  # antes: resolución por defecto (640×480)
    assert "focusMode = 'continuous'" in qr and "adv.zoom" in qr and "gw-cam__zoom" in qr            # enfoque continuo y «Acercar»
    assert "function center()" in qr and "detector.detect(center())" in qr and "readJs(center(), cctx)" in qr          # el recuadro guía, ampliado
    assert "gw-cam__aim" not in qr and ".gw-cam__aim" not in (ROOT / "static/css/gw-captura.css").read_text(encoding="utf-8")          # 28-nov-2026: sin recuadro guía visible (el QR se lee en cualquier parte)
    assert "facingMode: 'environment' } });" in qr                                                   # si la cámara no acepta alta resolución, se abre igual
