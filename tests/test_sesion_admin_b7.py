"""Fase 3 (B7): admin y super_admin no tienen `sid`; su cierre de sesión debe invalidar la cookie copiada y la sesión tiene un tope absoluto aunque la renueve la actividad."""
import pytest
from fastapi.testclient import TestClient

from app import idle
from tests.conftest import login


@pytest.fixture()
def second():
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _cookie_name():
    import os
    return os.getenv("SESSION_COOKIE", "session")


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_logout_kills_a_copied_cookie(client, second, factory, role):
    factory.staff(role, f"u_{role}")
    login(client, f"u_{role}")
    stolen = client.cookies.get(_cookie_name())
    assert stolen and client.get("/api/my-events").status_code == 200
    client.post("/logout")
    client.cookies.clear()
    second.cookies.set(_cookie_name(), stolen)
    assert second.get("/api/my-events").status_code == 401


def test_logout_then_new_login_works(client, factory):
    factory.staff("admin", "adm_again")
    login(client, "adm_again")
    client.post("/logout")
    client.cookies.clear()
    login(client, "adm_again")
    assert client.get("/api/my-events").status_code == 200


def test_a_stale_cookie_logout_does_not_bump_the_epoch(client, second, factory, db):
    """Quien cierra con una cookie que ya no vale no cierra la sesión vigente del dueño."""
    from app.models import StaffUser
    factory.staff("admin", "adm_stale")
    login(client, "adm_stale")
    old = client.cookies.get(_cookie_name())
    client.post("/logout")
    client.cookies.clear()
    login(client, "adm_stale")
    fresh_epoch = db.query(StaffUser).filter_by(username="adm_stale").first().session_epoch
    second.cookies.set(_cookie_name(), old)
    second.post("/logout")
    db.expire_all()
    assert db.query(StaffUser).filter_by(username="adm_stale").first().session_epoch == fresh_epoch
    assert client.get("/api/my-events").status_code == 200


def test_admin_session_has_an_absolute_limit_even_with_activity(client, factory, monkeypatch):
    factory.staff("admin", "adm_abs")
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")                 # que solo juegue el tope absoluto
    login(client, "adm_abs")
    real = idle.now()
    assert client.get("/api/my-events").status_code == 200
    monkeypatch.setattr(idle, "now", lambda: real + 13 * 3600)
    assert client.get("/api/my-events").status_code == 401


def test_admin_session_inside_the_limit_survives(client, factory, monkeypatch):
    factory.staff("admin", "adm_in")
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")
    login(client, "adm_in")
    real = idle.now()
    monkeypatch.setattr(idle, "now", lambda: real + 11 * 3600)
    assert client.get("/api/my-events").status_code == 200


def test_the_absolute_limit_does_not_apply_to_other_roles(client, factory, monkeypatch):
    factory.staff("coordinador", "coord_abs")
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "0")
    login(client, "coord_abs")
    real = idle.now()
    monkeypatch.setattr(idle, "now", lambda: real + 13 * 3600)
    assert client.get("/api/my-events").status_code == 200


def test_absolute_limit_helpers():
    s = {"staff_role": "admin", "iat": 1000}
    assert idle.absolute_expired(s, at=1000 + 12 * 3600 + 1) and not idle.absolute_expired(s, at=1000 + 12 * 3600)
    assert not idle.absolute_expired({"staff_role": "admin"}, at=10**9)                    # cookie vieja sin iat: no expulsa
    assert not idle.absolute_expired({"staff_role": "digitador", "iat": 1}, at=10**9)
    assert not idle.absolute_expired({"staff_role": "admin", "iat": True}, at=10**9)


def test_absolute_limit_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_MAX_HOURS", "0")
    assert not idle.absolute_expired({"staff_role": "super_admin", "iat": 1}, at=10**9)
