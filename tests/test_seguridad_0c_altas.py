"""Fase 0C, pasada 2: cabeceras de seguridad, logos sin SVG y validación de texto (familia XSS)."""
import pytest

from app.inputcheck import check_text, check_username
from tests.conftest import login


def test_security_headers_on_every_response(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp and "object-src 'none'" in csp


def test_check_text_rejects_markup_and_control_chars():
    assert check_text("Feria de Bogotá & Cía.") == "Feria de Bogotá & Cía."
    for bad in ("<img src=x onerror=1>", "a>b", "a\x00b"):
        with pytest.raises(ValueError):
            check_text(bad)


def test_check_username_whitelist():
    assert check_username("juan.perez-1@golden") == "juan.perez-1@golden"
    for bad in ("ab", "a'b", 'a"b', "a b", "<x>", "x" * 65):
        with pytest.raises(ValueError):
            check_username(bad)


def test_staff_create_rejects_html_username_and_name(client, factory):
    factory.staff("admin", "adm1")
    assert login(client, "adm1").status_code == 302
    base = {"password": "Clave-segura-123", "role": "coordinador"}
    r = client.post("/api/staff", json={**base, "username": "x'y", "full_name": "Ok"})
    assert r.status_code == 422
    r = client.post("/api/staff", json={**base, "username": "buenusuario", "full_name": "<script>alert(1)</script>"})
    assert r.status_code == 422


def test_logo_svg_not_allowed(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    assert login(client, "coord1").status_code == 302
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = client.post(f"/api/events/{ev.id}/logo/upload", files={"file": ("logo.svg", svg, "image/svg+xml")})
    assert r.status_code == 400


def test_consent_when_discards_future_and_ancient_dates():
    from datetime import datetime, timedelta, timezone
    from app.routers.consents import _when
    now = datetime.now(timezone.utc)
    assert _when((now - timedelta(hours=3)).isoformat()) is not None
    assert _when((now + timedelta(days=400)).isoformat()) is None
    assert _when((now - timedelta(days=30)).isoformat()) is None
    assert _when("no es fecha") is None
