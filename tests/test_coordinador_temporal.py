"""Coordinador temporal del evento (16-nov-2026, app/event_only.py): permisos de coordinador SOLO sobre el evento asignado. DATOS SINTÉTICOS."""
import pytest

from app import event_only
from tests.conftest import PASSWORD, login


# ------------------------------------------------------------------ la regla pura (sin base de datos)
@pytest.mark.parametrize("method,path,ok", [
    ("GET", "/api/events", True), ("POST", "/api/events", False), ("GET", "/api/events/12/staff-users", True), ("POST", "/api/events/12/duplicate", False),
    ("GET", "/api/events/next-code", False), ("GET", "/api/users", True), ("POST", "/api/register", True), ("POST", "/api/recognize/photo", True),
    ("PUT", "/api/staff/5/password", True), ("GET", "/api/staff", False), ("POST", "/api/staff", False), ("GET", "/api/staff/coordinators", False),
    ("GET", "/api/colors", True), ("POST", "/api/colors", False), ("GET", "/api/calendar/notes", False), ("GET", "/api/events/calendar", True),
    ("GET", "/api/crm/accounts", False), ("GET", "/api/tenants", False), ("GET", "/api/gastos/infra/status", False), ("GET", "/api/inventory/catalog", False),
    ("POST", "/api/event-transfer/import", False), ("GET", "/api/event-contacts/options", False), ("GET", "/api/ops/status", False), ("GET", "/api/ops/version-check", True),
    ("GET", "/api/payment-accounts", False), ("GET", "/api/privacy-requests", False), ("POST", "/api/events/3/staff-users/assign-existing", False),
])
def test_api_rules(method, path, ok):
    assert event_only.api_allowed(method, path) is ok


def test_page_rules():
    for denied in ("/crm", "/crm/cuentas/4", "/clientes", "/clientes/acme/nuevo-evento", "/configuracion", "/configuracion/plantilla-evento", "/inventario", "/gastos", "/cuentas-de-cobro",
                   "/sincronizacion", "/servidor-local", "/impresion-usb", "/sistema", "/eventos/nuevo"):
        assert not event_only.page_allowed(denied), denied
    for allowed in ("/", "/eventos", "/calendario", "/kiosk/7", "/kiosk/7/usuarios", "/logout", "/cambiar-contrasena", "/f/evento/form"):
        assert event_only.page_allowed(allowed), allowed


def test_event_id_in_path():
    assert event_only.event_id_in_path("/api/events/45/forms") == 45 and event_only.event_id_in_path("/kiosk/7") == 7 and event_only.event_id_in_path("/kiosk/7/usuarios") == 7
    assert event_only.event_id_in_path("/api/events") is None and event_only.event_id_in_path("/api/events/search") is None


def test_every_global_family_is_closed():
    """Ninguna ruta de estas familias (clientes, CRM, dinero, inventario, nodos, importar/exportar…) se le abre por ningún método, existan hoy o se agreguen después."""
    pytest.importorskip("sqlalchemy")
    from app.main import app
    closed = ("/api/crm", "/api/tenants", "/api/gastos", "/api/inventory", "/api/event-transfer", "/api/payment-accounts", "/api/system-alerts", "/api/nodes", "/api/node", "/api/node-sync",
              "/api/local", "/api/local-installer", "/api/privacy-requests", "/api/super-events", "/api/form-transfer", "/api/staff/coordinators", "/api/staff/assignable", "/api/internal")
    for route in app.routes:
        path = getattr(route, "path", "")
        if any(path == c or path.startswith(c + "/") for c in closed):
            for m in getattr(route, "methods", None) or {"GET"}:
                assert not event_only.api_allowed(m, path), (m, path)


# ------------------------------------------------------------------ de punta a punta
def _make(client, factory, ev, name="Ana Prueba"):
    """Una comercial crea el coordinador temporal de `ev`; devuelve (usuario, contraseña)."""
    factory.staff("comercial", "comer")
    assert login(client, "comer").status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": name})
    assert r.status_code == 200, r.text
    cred = r.json()["credentials"]
    client.post("/logout")
    return cred["username"], cred["password"], r.json()


def test_creation_and_scope(client, factory, db):
    from app.models import AuditAction, StaffUser
    ev, other = factory.event("en_proceso"), factory.event("en_proceso")
    user, password, body = _make(client, factory, ev)
    assert user.startswith("ct-") and len(password) >= 10 and body["event_only"] is True and body["role"] == "coordinador"
    row = db.query(StaffUser).filter_by(username=user).one()
    assert row.event_only and row.role == "coordinador" and row.password_hash != password and row.tenant_id == ev.tenant_id
    assert db.query(AuditAction).filter(AuditAction.entity == "event_only_coordinator").count() == 1
    assert login(client, user, password).status_code == 302
    mine = client.get("/api/events")
    assert [e["id"] for e in mine.json()] == [ev.id]                                      # solo SU evento
    assert client.get(f"/api/events/{ev.id}").status_code == 200
    assert client.get(f"/api/events/{other.id}").status_code == 404                       # el otro evento ni siquiera «existe»
    assert client.get(f"/api/events/{other.id}/staff-users").status_code == 404
    assert client.get(f"/api/users?event_id={other.id}").status_code in (403, 404)
    assert client.get(f"/api/users?event_id={ev.id}").status_code == 200
    assert [e["id"] for e in client.get("/api/events/search?q=").json()] == [ev.id]
    assert [e["id"] for e in client.get("/api/my-events").json()["events"]] == [ev.id]


def test_global_areas_are_closed(client, factory):
    ev = factory.event("en_proceso")
    user, password, _ = _make(client, factory, ev)
    assert login(client, user, password).status_code == 302
    for path in ("/api/tenants", "/api/staff", "/api/crm/accounts", "/api/gastos/infra/status", "/api/inventory/catalog", "/api/payment-accounts", "/api/events/next-code",
                 "/api/calendar/notes?start=2026-01-01&end=2026-12-31", "/api/event-transfer/log"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/events", json={"tenant_id": "acme", "event_code": "X1", "name": "Otro"}).status_code == 403
    assert client.post(f"/api/events/{ev.id}/duplicate", json={}).status_code == 403
    for page in ("/clientes", "/crm", "/configuracion", "/inventario", "/gastos", "/sistema", "/eventos/nuevo", "/cuentas-de-cobro"):
        r = client.get(page)
        assert r.status_code == 302 and r.headers["location"] == "/", page
    assert client.get("/calendario").status_code == 200 and client.get("/eventos").status_code == 200
    assert client.get("/").headers["location"] == f"/kiosk/{ev.id}"                       # un solo evento: entra derecho a él
    menu = client.get("/eventos").text
    assert 'href="/clientes"' not in menu and 'href="/crm"' not in menu and 'href="/inventario"' not in menu and 'href="/configuracion"' not in menu and "Nuevo evento" not in menu
    assert 'href="/eventos"' in menu and 'href="/calendario"' in menu


def test_event_pages_and_work_inside_the_event(client, factory):
    ev = factory.event("en_proceso")
    user, password, _ = _make(client, factory, ev)
    assert login(client, user, password).status_code == 302
    for page in (f"/kiosk/{ev.id}", f"/kiosk/{ev.id}/usuarios", f"/kiosk/{ev.id}/registro"):
        assert client.get(page).status_code == 200, page
    # como coordinador, puede crear un digitador temporal en SU evento
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "username": "1020304050", "full_name": "Luis Digitador"})
    assert r.status_code == 200, r.text


def test_cannot_make_other_coordinators_or_touch_other_events(client, factory):
    ev, other = factory.event("en_proceso"), factory.event("en_proceso")
    user, password, body = _make(client, factory, ev)
    assert login(client, user, password).status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Otro"})
    assert r.status_code == 403                                                            # un coordinador (ni siquiera temporal) no crea coordinadores
    assert client.post(f"/api/events/{other.id}/staff-users", json={"role": "digitador", "username": "1020304051", "full_name": "X"}).status_code == 404
    assert client.delete(f"/api/events/{ev.id}/staff-users/{body['id']}").status_code == 403           # ni se quita a sí mismo ni a otro coordinador temporal


def test_only_commercial_or_more_creates_them(client, factory):
    ev = factory.event("en_proceso")
    factory.staff("coordinador", "coord")
    assert login(client, "coord").status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Ana"})
    assert r.status_code == 403
    client.post("/logout")
    factory.staff("digitador", "dig")
    assert login(client, "dig").status_code == 302
    assert client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Ana"}).status_code == 403


def test_access_ends_when_the_event_finishes(client, factory, db):
    from app.models import Event
    ev = factory.event("en_proceso")
    user, password, _ = _make(client, factory, ev)
    assert login(client, user, password).status_code == 302
    assert client.get(f"/api/events/{ev.id}").status_code == 200
    db.query(Event).filter_by(id=ev.id).update({"status": "finalizado"})
    db.commit()
    assert client.get(f"/api/events/{ev.id}").status_code == 403
    assert client.get("/api/events").json() == []


def test_commercial_can_list_and_remove_them(client, factory, db):
    from app.models import StaffUser
    ev = factory.event("en_proceso")
    user, password, body = _make(client, factory, ev)
    assert login(client, "comer").status_code == 302
    listed = client.get(f"/api/events/{ev.id}/staff-users").json()
    assert [u["username"] for u in listed if u["event_only"]] == [user]
    r = client.post(f"/api/events/{ev.id}/staff-users/{body['id']}/delete-account")
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert db.query(StaffUser).filter_by(username=user).count() == 0


def test_not_offered_as_event_coordinator_nor_in_staff_list(client, factory):
    ev = factory.event("en_proceso")
    user, _, _ = _make(client, factory, ev)
    factory.staff("admin", "adm")
    assert login(client, "adm").status_code == 302
    assert user not in [c["username"] for c in client.get("/api/staff/coordinators").json()]
    assert user not in [c["username"] for c in client.get("/api/staff").json()]


def test_login_still_needs_the_password(client, factory):
    ev = factory.event("en_proceso")
    user, password, _ = _make(client, factory, ev)
    assert login(client, user, PASSWORD).status_code != 302
