"""Filas por página de la tabla del directorio, por evento (Parámetros del evento): 10, 20, 50, 100 o 200; 50 por defecto; la tabla del quiosco lo recibe; solo coordinador o más lo cambia."""
import pytest

from app.models import Event
from tests.conftest import login


def _setup(client, factory, username="coord"):
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff("coordinador", username))
    login(client, username)
    return ev


def test_default_is_50_and_the_kiosk_page_receives_it(client, factory, db):
    ev = _setup(client, factory)
    assert db.get(Event, ev.id).directory_page_size == 50
    assert "window.DIRECTORY_PAGE_SIZE = 50;" in client.get(f"/kiosk/{ev.id}/registro").text


@pytest.mark.parametrize("value", [10, 20, 50, 100, 200, "100"])
def test_allowed_values_are_saved_and_reach_the_page_and_the_parameters_screen(client, factory, db, value):
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/directory-page-size", json={"value": value})
    assert r.status_code == 200 and r.json()["directory_page_size"] == int(value)
    db.expire_all()
    assert db.get(Event, ev.id).directory_page_size == int(value)
    assert f"window.DIRECTORY_PAGE_SIZE = {int(value)};" in client.get(f"/kiosk/{ev.id}/registro").text
    assert f'<option value="{int(value)}" selected>' in client.get(f"/kiosk/{ev.id}/parametros").text


@pytest.mark.parametrize("value", [0, 5, 37, 500, -20, "abc", None, 20.5])
def test_other_values_are_rejected_and_nothing_changes(client, factory, db, value):
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/directory-page-size", json={"value": value})
    assert r.status_code == 400 and "10, 20, 50, 100, 200" in r.json()["detail"]
    db.expire_all()
    assert db.get(Event, ev.id).directory_page_size == 50


def test_a_temporary_digitador_cannot_change_it_and_another_events_value_is_independent(client, factory, db):
    ev, other = factory.event("en_proceso"), factory.event("en_proceso")
    dig = factory.staff("digitador", "dig")
    factory.authorize(ev, dig)
    login(client, "dig")
    assert client.put(f"/api/events/{ev.id}/directory-page-size", json={"value": 20}).status_code == 403
    factory.authorize(other, factory.staff("coordinador", "coord"))
    login(client, "coord")
    assert client.put(f"/api/events/{other.id}/directory-page-size", json={"value": 20}).status_code == 200
    db.expire_all()
    assert db.get(Event, ev.id).directory_page_size == 50 and db.get(Event, other.id).directory_page_size == 20
