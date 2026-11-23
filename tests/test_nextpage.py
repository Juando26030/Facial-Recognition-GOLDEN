"""Dirección de regreso tras una sesión cerrada por tiempo (app/nextpage.py, 20-nov-2026). Pura: corre con `pytest --noconftest`."""
import pytest

from app import nextpage


@pytest.mark.parametrize("ok", ["/configuracion", "/kiosk/3/parametros?tab=a&b=2", "/eventos/5#registro", "/"])
def test_same_site_pages_are_accepted(ok):
    assert nextpage.safe_next(ok) == ok


@pytest.mark.parametrize("bad", ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)", "/login", "/logout", "/cambiar-contrasena", "/ingreso/espera", "/api/x", "/internal/jobs", "/ok\nx", "", None, 5, "/" + "a" * 700])
def test_everything_else_is_refused(bad):
    assert nextpage.safe_next(bad) is None


def test_login_url_back_keeps_the_page_and_ignores_the_home():
    assert nextpage.login_url_back("/kiosk/3/parametros", "tab=a&b=2") == "/login?expirada=1&next=%2Fkiosk%2F3%2Fparametros%3Ftab%3Da%26b%3D2"
    assert nextpage.login_url_back("/") == "/login?expirada=1"
    assert nextpage.login_url_back("/api/ping") == "/login?expirada=1"
