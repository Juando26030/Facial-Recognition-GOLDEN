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


def test_aceptar_open_path_cannot_set_birth_date_or_purge(client, factory, db):
    """C1/C-N3: con solo la cédula (sin enlace) y sin fecha registrada, declarar «menor» no borra el rostro ni guarda la fecha."""
    from app.models import User
    from datetime import date
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True)
    factory.person(ev, "9001", "Ana", "Mora")
    code = getattr(ev, "accept_code", None) or getattr(ev, "aceptar_code", None)
    if not code:
        import pytest
        pytest.skip("el evento de prueba no expone código de aceptación")
    u = db.query(User).filter_by(id="9001", tenant_id=ev.tenant_id).first()
    assert u.birth_date is None
    fake = date.today().replace(year=date.today().year - 5).isoformat()
    client.post(f"/api/aceptar/{code}/check", data={"cedula": "9001", "birth_date": fake})
    db.expire_all()
    assert db.query(User).filter_by(id="9001", tenant_id=ev.tenant_id).first().birth_date is None


def test_admin_cannot_change_email_of_peer_or_superior(client, factory):
    factory.staff("admin", "adm1")
    peer = factory.staff("admin", "adm2")
    low = factory.staff("coordinador", "coord9")
    boss = factory.staff("super_admin", "root1")
    assert login(client, "adm1").status_code == 302
    for victim in (peer, boss):
        r = client.patch(f"/api/staff/{victim.id}/email", json={"email": "atacante@example.com"})
        assert r.status_code == 403, victim.role
    assert client.patch(f"/api/staff/{low.id}/email", json={"email": "ok@example.com"}).status_code == 200


def test_staff_tenant_isolation_when_enforced(client, factory, monkeypatch):
    """H1/A9: con ENFORCE_STAFF_TENANT=1 un coordinador de un tenant no ve (404) ni edita eventos de otro; el personal global (tenant nulo) sí."""
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.staff("coordinador", "coordA", tenant_id="acme")
    factory.staff("coordinador", "coordG")                      # global (tenant nulo)
    own = factory.event("en_proceso", tenant_id="acme")
    other = factory.event("en_proceso", tenant_id="otra")
    assert login(client, "coordA").status_code == 302
    assert client.get(f"/api/events/{own.id}/consent-text").status_code != 404
    assert client.get(f"/api/events/{other.id}/consent-text").status_code == 404
    assert client.patch(f"/api/events/{other.id}", json={"notes": "x"}).status_code == 404
    client.post("/logout")
    assert login(client, "coordG").status_code == 302
    assert client.get(f"/api/events/{other.id}/consent-text").status_code != 404


def test_tenant_isolation_is_off_by_default(client, factory):
    factory.staff("coordinador", "coordA", tenant_id="acme")
    other = factory.event("en_proceso", tenant_id="otra")
    assert login(client, "coordA").status_code == 302
    assert client.get(f"/api/events/{other.id}/consent-text").status_code != 404
