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
