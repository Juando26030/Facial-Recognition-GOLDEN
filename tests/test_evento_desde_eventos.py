"""Fase 2 (7-nov-2026): un evento se crea también desde la pestaña Eventos. Es el MISMO formulario de Clientes, con el primer campo «Cliente»
(lista con buscador, static/js/gw-combobox.js). Los permisos y la API de creación no cambian."""
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_eventos_page_has_the_new_event_button(client, factory):
    from tests.conftest import login
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    page = client.get("/eventos").text
    assert 'href="/eventos/nuevo"' in page and "Nuevo evento" in page and "gw-btn--primary" in page


def test_new_event_from_eventos_asks_for_the_client(client, factory):
    from tests.conftest import login
    factory.staff("admin", "adm1")
    login(client, "adm1")
    page = client.get("/eventos/nuevo").text
    assert 'data-pick-tenant="true"' in page and 'id="neTenant"' in page and "data-gw-combobox" in page
    assert 'data-tenant-id=""' in page and 'href="/eventos"' in page
    assert "gw-combobox.js" in page


def test_new_event_from_client_keeps_the_client_fixed(client, factory):
    from tests.conftest import login
    factory.tenant("acme")
    factory.staff("admin", "adm1")
    login(client, "adm1")
    page = client.get("/clientes/acme/nuevo-evento").text
    assert 'data-pick-tenant="false"' in page and 'id="neTenant"' not in page and 'data-tenant-id="acme"' in page
    assert 'href="/clientes"' in page


def test_new_event_page_permissions_are_the_same_as_the_client_entry(client, factory):
    from tests.conftest import login
    factory.staff("digitador", "dig1")
    login(client, "dig1")
    r = client.get("/eventos/nuevo", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/"


def test_new_event_page_requires_login(client):
    r = client.get("/eventos/nuevo", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"


def test_tenant_list_for_the_combobox_respects_the_role(client, factory, monkeypatch):
    from tests.conftest import login
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("acme")
    factory.tenant("otro")
    factory.staff("coordinador", "limitado", tenant_id="acme")
    login(client, "limitado")
    ids = [t["id"] for t in client.get("/api/tenants").json()]
    assert ids == ["acme"]


def test_creating_an_event_still_adds_the_test_person(client, factory, db):
    from app import testperson
    from app.models import Event, EventAttendee
    from tests.conftest import login
    from datetime import date
    factory.tenant("acme")
    factory.staff("admin", "adm1")
    comm = factory.staff("comercial", "com1")
    coord = factory.staff("coordinador", "coord1")
    login(client, "adm1")
    r = client.post("/api/events", json={
        "tenant_id": "acme", "event_code": "FERIA-2026", "name": "Feria", "country": "Colombia", "city": "Bogotá",
        "location": "Corferias", "address": "Cra 37", "start_date": str(date(2027, 1, 10)), "end_date": str(date(2027, 1, 11)),
        "setup_date": str(date(2027, 1, 9)), "event_time_start": "08:00", "event_time_end": "18:00",
        "setup_time_start": "08:00", "setup_time_end": "18:00", "coordinator_staff_id": coord.id, "commercial_staff_id": comm.id,
    })
    assert r.status_code == 200, r.text
    ev = db.query(Event).filter(Event.event_code == "FERIA-2026").first()
    assert ev is not None and ev.tenant_id == "acme"
    assert db.query(EventAttendee).filter(EventAttendee.event_id == ev.id, EventAttendee.user_id == testperson.TEST_ID).count() == 1          # nace la persona PRUEBA


def test_template_and_js_wire_the_client_selector():
    html = (ROOT / "templates/nuevo_evento.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/nuevo-evento.js").read_text(encoding="utf-8")
    assert "{% if pick_tenant %}" in html and 'name="tenant_label"' in html and "js/gw-combobox.js" in html
    assert "/api/tenants" in js and "delete payload.tenant_label" in js and "payload.tenant_id = TENANT_ID" in js
    assert "AFTER_URL" in js


def test_combobox_component_is_documented_and_tokenised():
    css = (ROOT / "static/css/design-system.css").read_text(encoding="utf-8")
    block = css[css.index(".gw-combobox {"):]
    assert "var(--gw-tap)" in block and "#" not in block.replace("#i-", "")
    js = (ROOT / "static/js/gw-combobox.js").read_text(encoding="utf-8")
    for needle in ("aria-expanded", "aria-activedescendant", "role', 'listbox'", "data-allow-free-text", "ArrowDown", "Escape"):
        assert needle in js, needle
    assert "gw-combobox" in (ROOT / "docs/ux/guia_visual.html").read_text(encoding="utf-8")
    assert "gw-combobox" in (ROOT / "docs/ux/ESTANDARES_VISUALES.md").read_text(encoding="utf-8")
