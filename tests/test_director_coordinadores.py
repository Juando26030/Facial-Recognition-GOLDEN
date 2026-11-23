"""Director de coordinadores (17-nov-2026): un coordinador con el rol sumado `dir_coordinadores`. Asigna coordinadores a los eventos y revisa legalizaciones; los administradores también."""
import pytest

from app.models import Event
from tests.conftest import login


@pytest.fixture()
def team(factory):
    return {
        "coord": factory.staff("coordinador", "coord", full_name="Ana Coord"),
        "otro": factory.staff("coordinador", "otro", full_name="Beto Coord"),
        "director": factory.staff("coordinador", "dirc", full_name="Dir Coords", extra_roles="dir_coordinadores"),
        "admin": factory.staff("admin", "adm", full_name="Admin Uno"),
        "digi": factory.staff("digitador", "7000009"),
    }


def _assign(client, ev, staff_id):
    return client.post(f"/api/events/{ev.id}/assign-coordinator", json={"coordinator_staff_id": staff_id})


def test_director_and_admin_assign_but_plain_coordinator_does_not(client, factory, db, team):
    ev = factory.event("creado")
    login(client, "coord")
    assert _assign(client, ev, team["coord"].id).status_code == 403
    client.cookies.clear()
    login(client, "dirc")
    r = _assign(client, ev, team["otro"].id)
    assert r.status_code == 200 and r.json()["coordinator_staff_id"] == team["otro"].id
    client.cookies.clear()
    login(client, "adm")
    assert _assign(client, ev, team["coord"].id).status_code == 200
    assert _assign(client, ev, None).json()["coordinator_staff_id"] is None
    db.expire_all()
    assert db.get(Event, ev.id).coordinator_staff_id is None


def test_assign_rejects_non_coordinators_and_finished_events(client, factory, team):
    ev = factory.event("creado")
    done = factory.event("finalizado")
    login(client, "dirc")
    assert _assign(client, ev, team["digi"].id).status_code == 400
    assert _assign(client, ev, 999999).status_code == 400
    assert _assign(client, done, team["coord"].id).status_code == 400
    assert _assign(client, ev, team["admin"].id).status_code == 200          # un administrador también puede coordinar


def test_coordinators_list_includes_director_and_admins(client, team):
    login(client, "adm")
    names = {c["username"] for c in client.get("/api/staff/coordinators").json()}
    assert {"coord", "otro", "dirc", "adm"} <= names and "7000009" not in names


def test_director_reviews_legalizations_and_plain_coordinator_does_not(client, factory, team):
    ev = factory.event()
    login(client, "dirc")
    assert client.get(f"/api/events/{ev.id}/legalization").json()["can_review"] is True
    client.cookies.clear()
    login(client, "coord")
    assert client.get(f"/api/events/{ev.id}/legalization").json()["can_review"] is False
    assert client.post(f"/api/events/{ev.id}/legalization/approve").status_code == 403


def test_director_sees_all_events_and_roles_are_validated(client, factory, team):
    ev = factory.event("creado")          # sin coordinador asignado
    login(client, "dirc")
    assert client.get(f"/api/events/{ev.id}").status_code == 200
    client.cookies.clear()
    login(client, "adm")
    sid = team["coord"].id
    assert client.put(f"/api/staff/{sid}/roles", json={"extra_roles": ["dir_coordinadores"]}).status_code == 200
    com = factory.staff("comercial", "com1")
    assert client.put(f"/api/staff/{com.id}/roles", json={"extra_roles": ["dir_coordinadores"]}).status_code == 400          # sin ser coordinador no hay director
    r = client.post("/api/staff", json={"username": "nuevodir", "password": "Clave-Segura-2026!", "full_name": "Nuevo Director", "role": "dir_coordinadores", "phone": "+573001112233"})
    assert r.status_code == 200 and r.json()["role"] == "coordinador" and "dir_coordinadores" in r.json()["extra_roles"]
