"""4-nov-2026 (decisión del dueño): los coordinadores crean eventos (`POST /api/events`, mínimo coordinador). Un coordinador «puro» queda como coordinador del evento y no puede asignarlo a otro."""
import pytest

from tests.conftest import login


def _payload(coord_id, code="COORD-1", **extra):
    base = {"tenant_id": "acme", "event_code": code, "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
            "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord_id}
    base.update(extra)
    return base


def test_coordinator_creates_event_assigned_to_himself_and_sees_it(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    r = client.post("/api/events", json=_payload(coord.id))
    assert r.status_code == 200, r.text
    assert r.json()["coordinator_staff_id"] == coord.id and r.json()["commercial_staff_id"] is None
    assert r.json()["id"] in {e["id"] for e in client.get("/api/events").json()}


def test_coordinator_cannot_assign_event_to_other_coordinator_or_pick_commercial(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    other = factory.staff("coordinador", "coord2")
    com = factory.staff("comercial", "com")
    login(client, "coord")
    assert client.post("/api/events", json=_payload(other.id)).status_code == 403
    assert client.post("/api/events", json=_payload(coord.id, commercial_staff_id=com.id)).status_code == 403


def test_coordinator_keeps_the_event_validations(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.post("/api/events", json=_payload(coord.id, tenant_id="nada")).status_code == 404
    assert client.post("/api/events", json=_payload(coord.id, code="con espacio")).status_code == 400
    assert client.post("/api/events", json=_payload(coord.id, end_date="2026-10-01")).status_code == 400
    assert client.post("/api/events", json=_payload(coord.id, code="DUP")).status_code == 200
    assert client.post("/api/events", json=_payload(coord.id, code="dup")).status_code == 400


@pytest.mark.parametrize("role", ["digitador", "cliente"])
def test_digitador_and_client_cannot_create_events(client, factory, role):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    factory.staff(role, "actor1")
    login(client, "actor1")
    assert client.post("/api/events", json=_payload(coord.id)).status_code == 403


def test_coordinator_does_not_gain_other_permissions(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    ev = client.post("/api/events", json=_payload(coord.id)).json()
    assert client.post("/api/tenants", json={"name": "Otro"}).status_code == 403
    assert client.get("/api/staff").status_code == 403
    assert client.get("/api/staff/commercials").status_code == 403
    assert client.post(f"/api/events/{ev['id']}/staff-users", json={"role": "cliente", "username": "c1", "password": "Clave#2026xy", "full_name": "C"}).status_code == 403


@pytest.mark.parametrize("role", ["comercial", "admin", "super_admin"])
def test_commercial_and_admin_still_create(client, factory, role):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    me = factory.staff(role, "actor1")
    login(client, "actor1")
    extra = {} if role == "comercial" else {"commercial_staff_id": factory.staff("comercial", "com").id}
    r = client.post("/api/events", json=_payload(coord.id, **extra))
    assert r.status_code == 200, r.text
    assert r.json()["coordinator_staff_id"] == coord.id               # ellos sí eligen coordinador
    if role == "comercial":
        assert r.json()["commercial_staff_id"] == me.id
    else:
        assert client.post("/api/events", json=_payload(coord.id, code="X2")).status_code == 400    # admin debe elegir comercial


def test_double_role_coordinator_commercial_can_choose_coordinator(client, factory):
    factory.tenant("acme")
    other = factory.staff("coordinador", "coord2")
    me = factory.staff("coordinador", "doble", secondary_role="comercial")
    login(client, "doble")
    r = client.post("/api/events", json=_payload(other.id))
    assert r.status_code == 200, r.text
    assert r.json()["coordinator_staff_id"] == other.id and r.json()["commercial_staff_id"] == me.id
