"""Página de prueba de la impresión directa por USB (Brother QL): acceso por rol y recursos; la lógica de los comandos se comprueba en tests/js/ql_usb_check.js."""
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def test_the_usb_print_page_needs_a_staff_session_and_loads_its_script(client, factory):
    anonymous = client.get("/impresion-usb", follow_redirects=False)
    assert anonymous.status_code in (302, 303, 307) and "/login" in anonymous.headers["location"]
    factory.staff("digitador", "dig1")
    login(client, "dig1")
    r = client.get("/impresion-usb")
    assert r.status_code == 200 and "ql-usb.js" in r.text and "Conectar impresora" in r.text and "Probar conexión" in r.text
    assert client.get("/static/js/ql-usb.js").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="sin node")
def test_the_brother_ql_command_stream_check_passes():
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "ql_usb_check.js")], capture_output=True, text=True, encoding="utf8", timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr
