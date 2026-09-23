"""Certificado público /c/<token>: mensajes según la cédula, acceso sin sesión y límite de consultas."""
from tests.conftest import login


def _setup(factory, db, status="finalizado"):
    from app.models import EventAttendee

    factory.staff("admin", "root")
    ev = factory.event(status, certificates_enabled=True, certificates_token="TOKEN123")
    factory.person(ev, "1001", "Ana", "Pidio")
    factory.person(ev, "1002", "Beto", "NoPidio")
    factory.person(factory.event("en_proceso", tenant_id="otro"), "3003", "Otro", "Cliente")
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").update({"certificate": True})
    db.commit()
    return ev


def test_three_lookup_outcomes_without_session(client, factory, db):
    _setup(factory, db)
    ok = client.get("/c/TOKEN123/lookup", params={"id": "1001"})
    assert ok.status_code == 200 and ok.json()["display"]["name"] == "Ana Pidio"
    not_requested = client.get("/c/TOKEN123/lookup", params={"id": "1002"})
    assert not_requested.status_code == 404 and "no pidió certificado" in not_requested.json()["detail"]
    missing = client.get("/c/TOKEN123/lookup", params={"id": "9999"})
    assert missing.status_code == 404 and "No encontramos un certificado" in missing.json()["detail"]
    other_tenant = client.get("/c/TOKEN123/lookup", params={"id": "3003"})       # existe, pero en otro cliente
    assert "No encontramos un certificado" in other_tenant.json()["detail"]


def test_lookup_needs_finished_event_and_valid_token(client, factory, db):
    _setup(factory, db, status="en_proceso")
    assert client.get("/c/TOKEN123/lookup", params={"id": "1001"}).status_code == 409
    assert client.get("/c/NOPE/lookup", params={"id": "1001"}).status_code == 404
    assert client.get("/c/NOPE").status_code == 404


def test_public_page_and_endpoints_need_no_login_but_staff_pages_do(client, factory, db):
    _setup(factory, db)
    assert client.get("/c/TOKEN123").status_code == 200
    assert client.get("/clientes").status_code == 302
    assert client.get("/api/events").status_code == 401


def test_only_template_fields_are_exposed_never_the_photo(client, factory, db):
    _setup(factory, db)
    person = client.get("/c/TOKEN123/lookup", params={"id": "1001"}).json()["person"]
    assert person["has_photo"] is False
    assert "phone" not in person and "email" not in person   # la plantilla por defecto solo usa nombre/apellido


def test_lookup_is_rate_limited_per_ip_and_persisted(client, factory, db):
    _setup(factory, db)
    codes = [client.get("/c/TOKEN123/lookup", params={"id": str(i)}).status_code for i in range(32)]
    assert codes[:30].count(429) == 0 and codes[30] == 429 and codes[31] == 429


def test_generate_public_link_from_staff_side(client, factory, db):
    ev = _setup(factory, db)
    ev.certificates_token = None
    db.commit()
    login(client, "root")
    assert client.get(f"/api/events/{ev.id}/certificates/public-link").json() == {"url": None}
    url = client.post(f"/api/events/{ev.id}/certificates/public-link").json()["url"]
    assert "/c/" in url
    assert client.post(f"/api/events/{ev.id}/certificates/public-link").json()["url"] == url          # mismo enlace
    new = client.post(f"/api/events/{ev.id}/certificates/public-link", params={"regenerate": "true"}).json()["url"]
    assert new != url
