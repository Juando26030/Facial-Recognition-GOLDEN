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
    closed = ("/api/crm", "/api/tenants", "/api/gastos", "/api/inventory", "/api/almacen", "/api/event-transfer", "/api/payment-accounts", "/api/system-alerts", "/api/nodes", "/api/node", "/api/node-sync",
              "/api/local", "/api/local-installer", "/api/privacy-requests", "/api/super-events", "/api/form-transfer", "/api/staff/coordinators", "/api/staff/assignable", "/api/internal")
    for route in app.routes:
        path = getattr(route, "path", "")
        if any(path == c or path.startswith(c + "/") for c in closed):
            for m in getattr(route, "methods", None) or {"GET"}:
                assert not event_only.api_allowed(m, path), (m, path)


# ------------------------------------------------------------------ de punta a punta
_N = [0]
TEMP_PASSWORD = "Temporal#2026x"


def _make(client, factory, ev, name="Ana Prueba", keep_must_change=False):
    """Una comercial crea el coordinador temporal de `ev` como a un coordinador normal (usuario, contraseña inicial y teléfono); devuelve (usuario, contraseña, cuerpo)."""
    from app.database import SessionLocal
    from app.models import StaffUser
    _N[0] += 1
    username = f"coord.temp{_N[0]}"
    factory.staff("comercial", "comer")
    assert login(client, "comer").status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": name, "username": username,
                                                               "password": TEMP_PASSWORD, "phone": f"+5730000{_N[0]:05d}"})
    assert r.status_code == 200, r.text
    client.post("/logout")
    if not keep_must_change:                    # en la práctica la persona cambia su contraseña al entrar; aquí se salta ese paso para probar el alcance
        s = SessionLocal()
        try:
            s.query(StaffUser).filter_by(username=username).update({"must_change_password": False})
            s.commit()
        finally:
            s.close()
    return username, TEMP_PASSWORD, r.json()


def test_created_like_a_normal_coordinator(client, factory, db):
    from app.models import StaffUser
    ev = factory.event("en_proceso")
    user, password, body = _make(client, factory, ev, keep_must_change=True)
    assert "credentials" not in body and body["username"] == user and body["role"] == "coordinador" and body["event_only"] is True
    row = db.query(StaffUser).filter_by(username=user).one()
    assert row.must_change_password is True and row.phone and row.password_hash != password          # elige su contraseña al primer ingreso, como cualquier coordinador
    assert login(client, user, password).status_code == 302
    assert client.get("/api/events").status_code in (200, 302, 403)
    client.post("/logout")
    assert login(client, "comer").status_code == 302
    base = {"role": "digitador", "temp_coordinator": True, "full_name": "Otra", "username": "otra.temp", "password": TEMP_PASSWORD, "phone": "+573009990001"}
    for patch, code in ((dict(password="123"), 400), (dict(phone=""), 400), (dict(username=""), 400), (dict(username=user, phone="+573009990002"), 400), (dict(phone=row.phone), 400), ({}, 200)):
        r = client.post(f"/api/events/{ev.id}/staff-users", json={**base, **patch})
        assert r.status_code == code, (patch, r.text)


def test_creation_and_scope(client, factory, db):
    from app.models import AuditAction, StaffUser
    ev, other = factory.event("en_proceso"), factory.event("en_proceso")
    user, password, body = _make(client, factory, ev)
    assert body["event_only"] is True and body["role"] == "coordinador"
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
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Otro", "username": "otro.temp", "password": TEMP_PASSWORD, "phone": "+573001112233"})
    assert r.status_code == 403                                                            # un coordinador (ni siquiera temporal) no crea coordinadores
    assert client.post(f"/api/events/{other.id}/staff-users", json={"role": "digitador", "username": "1020304051", "full_name": "X"}).status_code == 404
    assert client.delete(f"/api/events/{ev.id}/staff-users/{body['id']}").status_code == 403           # ni se quita a sí mismo ni a otro coordinador temporal


def test_only_commercial_or_more_creates_them(client, factory):
    ev = factory.event("en_proceso")
    factory.staff("coordinador", "coord")
    assert login(client, "coord").status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Ana", "username": "ana.temp", "password": TEMP_PASSWORD, "phone": "+573001112244"})
    assert r.status_code == 403
    client.post("/logout")
    factory.staff("digitador", "dig")
    assert login(client, "dig").status_code == 302
    assert client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "temp_coordinator": True, "full_name": "Ana", "username": "ana.temp", "password": TEMP_PASSWORD, "phone": "+573001112244"}).status_code == 403


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


def test_temp_coordinator_manages_digitadores_and_their_logins(client, factory, db):
    from app.models import StaffUser
    ev, other = factory.event("en_proceso"), factory.event("en_proceso")
    user, password, _ = _make(client, factory, ev)
    assert login(client, user, password).status_code == 302
    r = client.post(f"/api/events/{ev.id}/staff-users", json={"role": "digitador", "username": "1020304050", "full_name": "Luis Digitador"})
    assert r.status_code == 200, r.text
    dig_id = r.json()["id"]
    assert client.get(f"/api/events/{ev.id}/staff-users/login-state").status_code == 200          # ve quién intenta ingresar
    assert client.post(f"/api/events/{ev.id}/staff-users/{dig_id}/unlock").status_code == 200
    assert client.post(f"/api/events/{ev.id}/staff-users/approve-all", json={"reqs": {}}).status_code in (200, 400)
    assert client.post(f"/api/events/{ev.id}/staff-users/{dig_id}/login-request", json={"allow": True}).status_code != 403
    # y NADA de eso en otro evento
    assert client.get(f"/api/events/{other.id}/staff-users/login-state").status_code == 404
    assert client.post(f"/api/events/{other.id}/staff-users/{dig_id}/unlock").status_code == 404
    assert db.query(StaffUser).filter_by(id=dig_id).one().role == "digitador"


def test_account_survives_the_event_and_can_be_reassigned_by_search(client, factory, db):
    from app.models import Event, EventStaffAuthorization, StaffUser
    ev, nxt = factory.event("en_proceso"), factory.event("en_proceso")
    user, password, body = _make(client, factory, ev)
    db.query(Event).filter_by(id=ev.id).update({"status": "finalizado"})
    db.commit()
    row = db.query(StaffUser).filter_by(username=user).one()
    assert row.is_active and row.archived_at is None                                       # la cuenta NO se borra ni se desactiva al terminar el evento
    assert login(client, user, password).status_code == 302                                # puede entrar, pero sin eventos
    assert client.get("/api/events").json() == []
    client.post("/logout")
    # la comercial la busca y la asigna a otro evento
    assert login(client, "comer").status_code == 302
    found = client.get("/api/staff/assignable").json()
    assert [s["username"] for s in found] == [user] and found[0]["event_only"] is True      # el comercial solo ve coordinadores temporales
    r = client.post(f"/api/events/{nxt.id}/staff-users/assign-existing", json={"staff_id": body["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["credentials_mail"] != "queued"
    assert db.query(EventStaffAuthorization).filter_by(staff_user_id=body["id"], event_id=nxt.id).count() == 1
    client.post("/logout")
    assert login(client, user, password).status_code == 302
    assert [e["id"] for e in client.get("/api/events").json()] == [nxt.id]                  # recupera el acceso, solo al evento nuevo


def test_commercial_cannot_assign_digitadores_and_event_only_cannot_assign(client, factory):
    ev = factory.event("en_proceso")
    dig = factory.staff("digitador", "dig2")
    user, password, _ = _make(client, factory, ev)
    assert login(client, "comer").status_code == 302
    assert client.post(f"/api/events/{ev.id}/staff-users/assign-existing", json={"staff_id": dig.id}).status_code == 403
    client.post("/logout")
    assert login(client, user, password).status_code == 302
    assert client.post(f"/api/events/{ev.id}/staff-users/assign-existing", json={"staff_id": dig.id}).status_code in (403, 404)
    assert client.get("/api/staff/assignable").status_code in (403, 404)
