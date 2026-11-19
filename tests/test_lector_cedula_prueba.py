"""Página de prueba del lector de cédula (PDF417) en /pruebas/lector-cedula: acceso por sesión, contenido idéntico al entregado y nada de salida de datos."""
import hashlib
import re
from pathlib import Path

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "app" / "pruebas" / "lector_cedula.html"
# Huella de la página tal como se entregó (cedula-scanner.html, versión 3.1 con recuadro guía, 19-nov-2026). Si se cambia a propósito, se actualiza aquí.
PAGE_SHA256 = "e060aef06481c83dc59e61fd538a25453d9d74b2425864abebd008d723e26ebf"


def test_the_page_is_the_delivered_file_unchanged():
    assert hashlib.sha256(PAGE.read_bytes()).hexdigest() == PAGE_SHA256


def test_the_page_never_sends_data_to_the_server():
    src = PAGE.read_text(encoding="utf8")
    assert not re.search(r"\b(fetch|XMLHttpRequest|sendBeacon)\b", src) and "/api/" not in src and "localStorage" not in src      # solo procesa en el navegador


def test_the_page_needs_a_staff_session_and_declares_its_own_csp(client, factory):
    anonymous = client.get("/pruebas/lector-cedula", follow_redirects=False)
    assert anonymous.status_code in (302, 303, 307) and "/login" in anonymous.headers["location"]
    factory.staff("digitador", "dig_lector")
    login(client, "dig_lector")
    r = client.get("/pruebas/lector-cedula")
    assert r.status_code == 200 and "Lector de cédula" in r.text and "PDF417" in r.text and "Tomar foto" in r.text
    assert "cdn.jsdelivr.net" in r.headers["content-security-policy-report-only"] and "camera=(self)" in r.headers["permissions-policy"]
