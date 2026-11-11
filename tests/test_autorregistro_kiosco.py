"""Fase 8, pieza 3: autorregistro sin base de datos en el kiosco (app/selfreg.py, app/routers/selfreg.py)."""
import pytest

from app import selfreg
from app.models import AccessLog, EventAttendee, User
from tests.conftest import login


@pytest.fixture(autouse=True)
def _clean_limiter():
    selfreg.reset()
    yield
    selfreg.reset()


@pytest.fixture()
def station(client, factory, db):
    ev = factory.event("en_proceso", selfreg_enabled=True)
    st = factory.staff("digitador", "kiosco1")
    factory.authorize(ev, st)
    login(client, "kiosco1")
    return ev


def _send(client, ev, **over):
    body = {"id": "7001", "first_name": "Luisa", "last_name": "Mora", "values": {}}
    body.update(over)
    return client.post(f"/api/events/{ev.id}/selfreg", json=body)


# ---- piezas puras ----
def test_form_fields_keeps_required_and_always_id_and_name():
    cfgs = [
        {"key": "id", "label": "Cédula", "required": False, "field_type": "text_short"},
        {"key": "first_name", "label": "Nombres", "required": False, "field_type": "text_short"},
        {"key": "last_name", "label": "Apellidos", "required": True, "field_type": "text_short"},
        {"key": "entity", "label": "Empresa", "required": False, "field_type": "text_short"},
        {"key": "email", "label": "Correo", "required": True, "field_type": "email"},
    ]
    fields, unsupported = selfreg.form_fields(cfgs)
    assert [f["key"] for f in fields] == ["id", "first_name", "last_name", "email"] and unsupported == []


def test_required_signature_blocks_the_screen():
    fields, unsupported = selfreg.form_fields([{"key": "firma", "label": "Firma", "required": True, "field_type": "signature"}])
    assert fields == [] and unsupported == ["Firma"]


def test_split_values_separates_direct_and_optional():
    direct, extras = selfreg.split_values({"entity": " ACME ", "opcional_2": "x", "otro": "no"})
    assert direct == {"entity": "ACME"} and extras == {"opcional_2": "x"}


def test_limiter_is_sliding():
    key = ("e", 1)
    assert all(selfreg.allow(key, now=0) for _ in range(selfreg.MAX_PER_WINDOW))
    assert not selfreg.allow(key, now=1)
    assert selfreg.allow(key, now=selfreg.WINDOW_S + 5)


# ---- pantalla y endpoints ----
def test_page_opens_for_staff(client, station):
    assert client.get(f"/kiosk/{station.id}/autoregistro").status_code == 200


def test_form_lists_fields_when_available(client, station):
    d = client.get(f"/api/events/{station.id}/selfreg/form").json()
    assert d["available"] and [f["key"] for f in d["fields"]][:2] == ["id", "first_name"]


def test_registers_a_new_person_with_origin_and_method(client, db, station):
    r = _send(client, station)
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert db.query(User).filter_by(id="7001", tenant_id=station.tenant_id).first() is not None
    log = db.query(AccessLog).filter_by(event_id=station.id, user_id="7001").one()
    assert log.registration_method == "autoregistro"
    assert db.query(EventAttendee).filter_by(event_id=station.id, user_id="7001").one().origin == "autoregistro"


def test_duplicate_gets_kind_message_without_data(client, station):
    assert _send(client, station).status_code == 200
    r = _send(client, station)
    assert r.status_code == 200 and r.json()["status"] == "already"
    assert "Luisa" not in r.text and "Mora" not in r.text and "7001" not in r.text


def test_off_switch_refuses(client, factory, db):
    ev = factory.event("en_proceso")
    st = factory.staff("digitador", "kiosco2")
    factory.authorize(ev, st)
    login(client, "kiosco2")
    assert client.get(f"/api/events/{ev.id}/selfreg/form").json()["reason"] == "off"
    assert _send(client, ev).status_code == 403


def test_closed_event_refuses(client, factory):
    ev = factory.event("creado", selfreg_enabled=True)
    st = factory.staff("digitador", "kiosco3")
    factory.authorize(ev, st)
    login(client, "kiosco3")
    assert _send(client, ev).status_code == 403


def test_missing_id_or_name_is_400(client, station):
    assert _send(client, station, id="").status_code == 400
    assert _send(client, station, first_name="").status_code == 400


def test_attempt_limit_per_device(client, station, monkeypatch):
    monkeypatch.setattr(selfreg, "MAX_PER_WINDOW", 2)
    assert _send(client, station, id="8001").status_code == 200
    assert _send(client, station, id="8002").status_code == 200
    assert _send(client, station, id="8003").status_code == 429


def test_no_biometrics_are_stored(client, db, station):
    _send(client, station)
    u = db.query(User).filter_by(id="7001", tenant_id=station.tenant_id).one()
    assert not u.is_biometric_enabled


def test_config_needs_coordinator_and_toggles(client, factory, db):
    coord = factory.staff("coordinador", "coord9")
    ev = factory.event("en_proceso", coordinator=coord)
    dig = factory.staff("digitador", "dig9")
    factory.authorize(ev, dig)
    login(client, "dig9")
    assert client.put(f"/api/events/{ev.id}/selfreg-config", json={"enabled": True}).status_code == 403
    login(client, "coord9")
    assert client.put(f"/api/events/{ev.id}/selfreg-config", json={"enabled": True}).json() == {"enabled": True}
    db.refresh(ev)
    assert ev.selfreg_enabled is True


# ---- F5-9 B (revisión de seguridad): suplantar a una persona que ya existe ----
def test_same_person_matches_one_name_word_without_accents():
    assert selfreg.same_person("maria", "María José")
    assert selfreg.same_person("JOSE perez", "María José")
    assert not selfreg.same_person("Pedro", "María José")
    assert not selfreg.same_person("Pedro", "")


def test_test_person_cannot_selfregister(client, station):
    assert _send(client, station, id="PRUEBA", first_name="Prueba").status_code == 409


def test_existing_person_with_other_name_is_refused_and_untouched(client, db, factory, station):
    db.add(User(id="9100", tenant_id=station.tenant_id, first_name="Carolina", last_name="Ruiz", is_biometric_enabled=True))
    db.commit()
    r = _send(client, station, id="9100", first_name="Intruso", values={"birth_date": "2015-01-01", "digital_contact": "atacante@example.com"})
    assert r.status_code == 409 and "Carolina" not in r.text
    assert db.query(AccessLog).filter_by(event_id=station.id, user_id="9100").count() == 0
    db.expire_all()
    u = db.query(User).filter_by(id="9100", tenant_id=station.tenant_id).one()
    assert u.birth_date is None and u.is_biometric_enabled is True


def test_existing_person_with_matching_name_checks_in_without_changing_data(client, db, station):
    db.add(User(id="9101", tenant_id=station.tenant_id, first_name="Carolina", last_name="Ruiz", is_biometric_enabled=True))
    db.commit()
    r = _send(client, station, id="9101", first_name="carolina", values={"birth_date": "2015-01-01", "digital_contact": "atacante@example.com"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    db.expire_all()
    u = db.query(User).filter_by(id="9101", tenant_id=station.tenant_id).one()
    assert u.birth_date is None and u.is_biometric_enabled is True                 # una fecha de menor no le borra la biometría
    att = db.query(EventAttendee).filter_by(event_id=station.id, user_id="9101").one()
    assert not att.digital_contact                                                   # el correo escrito no se queda con su escarapela
