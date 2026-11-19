"""Escáner de cámara universal (19-nov-2026): el lector ZXing propio (static/vendor/zxing, lo deja scripts/vendor_zxing.sh) es OPCIONAL: sin el archivo el escáner sigue con BarcodeDetector/jsQR."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_scanner_loads_zxing_when_the_browser_lacks_pdf417_and_keeps_fallbacks():
    js = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert "/static/vendor/zxing/" in js and "loadZxing" in js
    assert "loadJsQr" in js and "BarcodeDetector" in js               # los caminos de siempre siguen
    assert "pointsOfInterest" in js                                   # tocar la imagen enfoca ese punto


def test_vendor_script_and_csp_allow_wasm():
    sh = (ROOT / "scripts/vendor_zxing.sh").read_text(encoding="utf-8")
    assert "npm pack" in sh and "static/vendor/zxing" in sh
    assert "'wasm-unsafe-eval'" in (ROOT / "app/main.py").read_text(encoding="utf-8")


def test_registro_closes_the_camera_when_the_code_is_recognised_and_both_engines_run():
    html = (ROOT / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "sc.close()" in html and "sc2.close()" in html
    js = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert "GlobalHistogram" in js and "[escáner] motores:" in js


def test_zxing_runs_in_a_worker_and_has_a_native_photo_fallback():
    js = (ROOT / "static/js/qr.js").read_text(encoding="utf-8")
    assert "zxing-worker.js" in js and "qr-still" in js and 'capture="environment"' in js
    wk = (ROOT / "static/js/zxing-worker.js").read_text(encoding="utf-8")
    assert "importScripts('/static/vendor/zxing/zxing-reader.js')" in wk and "zxing_reader.wasm" in wk
