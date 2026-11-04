"""Plan 7 (Registro limpio): el engranaje «Configuración del registro» y quién lo ve (coordinador+ siempre; digitador solo con la opción de Parámetros). Es solo visual."""
from tests.conftest import login

GEAR = 'id="gwRegCfgBtn"'


def _ev(client, factory, role, username):
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff(role, username))
    login(client, username)
    return ev


def test_coordinator_always_sees_the_gear_with_the_whole_config_inside_the_panel(client, factory):
    ev = _ev(client, factory, "coordinador", "coord1")
    html = client.get(f"/kiosk/{ev.id}/registro").text
    assert GEAR in html and 'aria-label="Configuración del registro"' in html and 'id="gwRegCfgPanel"' in html
    assert 'id="autoRegisterBtn"' in html and 'id="autoPrintBtn"' in html


def test_digitador_does_not_see_the_gear_until_the_option_is_on_and_loses_it_when_turned_off(client, factory, db):
    ev = _ev(client, factory, "digitador", "dig1")
    assert GEAR not in client.get(f"/kiosk/{ev.id}/registro").text
    from app import registro_gear
    registro_gear.set_digitadores_enabled(db, ev.id, True)
    db.commit()
    assert GEAR in client.get(f"/kiosk/{ev.id}/registro").text
    registro_gear.set_digitadores_enabled(db, ev.id, False)
    db.commit()
    assert GEAR not in client.get(f"/kiosk/{ev.id}/registro").text


def test_option_endpoint_is_coordinator_only_validates_and_defaults_off(client, factory, db):
    ev = _ev(client, factory, "coordinador", "coord2")
    assert client.get(f"/api/events/{ev.id}/registro-gear-digitadores").json() == {"enabled": False}
    assert client.put(f"/api/events/{ev.id}/registro-gear-digitadores", json={"enabled": "si"}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/registro-gear-digitadores", json={"enabled": True}).json() == {"enabled": True}
    assert client.get(f"/api/events/{ev.id}/registro-gear-digitadores").json() == {"enabled": True}
    assert 'id="regGearDig" checked' in client.get(f"/kiosk/{ev.id}/parametros").text


def test_digitador_cannot_change_the_option(client, factory):
    ev = _ev(client, factory, "digitador", "dig2")
    assert client.put(f"/api/events/{ev.id}/registro-gear-digitadores", json={"enabled": True}).status_code in (401, 403)


def test_option_is_registered_in_the_global_save():
    p = open("templates/kiosk_parametros.html", encoding="utf-8").read()
    assert "GWParams.register({ key: 'reggear'" in p and 'data-psave="reggear"' in p
