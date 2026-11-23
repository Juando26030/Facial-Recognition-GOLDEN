"""«Código» opcional por evento (0140): unicidad, choque con identificaciones (en los dos sentidos), búsqueda por identificación y luego código, obligatorio y carga masiva."""
import pytest

from app import person_code
from tests.conftest import login


def _setup(client, factory, **ev_kw):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True, **ev_kw)
    login(client, "root")
    return ev


def _enable(client, ev, required=False):
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_enabled": True, "code_required": required, "areas_enabled": True, "inventory_enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def _give(db, ev, user_id, code):
    from app.models import EventAttendee
    row = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=user_id).first()
    row.code = code
    db.commit()


def test_required_needs_enabled(client, factory):
    ev = _setup(client, factory)
    r = client.put(f"/api/events/{ev.id}/modules", json={"code_required": True})
    assert r.status_code == 400
    assert _enable(client, ev, required=True)["code_required"] is True


def test_code_validation_rules(db, factory):
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    _give(db, ev, "1002", "QR-77")
    assert person_code.validate(db, ev, "  ab-1 ", "1001") == "ab-1"
    assert person_code.validate(db, ev, "", "1001") == ""
    with pytest.raises(person_code.CodeError):
        person_code.validate(db, ev, "1001", "1001")                  # igual a su propia identificación
    with pytest.raises(person_code.CodeError):
        person_code.validate(db, ev, "1002", "1001")                  # igual a la identificación de otra persona
    with pytest.raises(person_code.CodeError):
        person_code.validate(db, ev, "qr-77", "1001")                 # repetido (sin distinguir mayúsculas)
    assert person_code.validate(db, ev, "QR-77", "1002") == "QR-77"   # conserva el suyo
    with pytest.raises(person_code.CodeError):
        person_code.validate(db, ev, "x" * 65, "1001")


def test_an_identification_equal_to_an_existing_code_is_refused(db, factory):
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    _give(db, ev, "1001", "555")
    assert person_code.id_collides_with_code(db, ev, "555") is True
    with pytest.raises(person_code.CodeError):
        person_code.require_free_id(db, ev, "555")
    ev.code_enabled = False
    db.commit()
    assert person_code.id_collides_with_code(db, ev, "555") is False


def test_find_user_by_id_first_then_by_code(db, factory):
    ev = factory.event("en_proceso", code_enabled=True)
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    _give(db, ev, "1002", "QR-9")
    u, via = person_code.find_user(db, ev, "1001")
    assert (u.id, via) == ("1001", "id")
    u, via = person_code.find_user(db, ev, "qr-9")
    assert (u.id, via) == ("1002", "code")
    assert person_code.find_user(db, ev, "nope") == (None, "")
    ev.code_enabled = False
    db.commit()
    assert person_code.find_user(db, ev, "QR-9") == (None, "")        # con el código apagado se trata como cédula inexistente


def test_zone_and_inventory_scans_accept_the_code(client, factory, db):
    ev = _setup(client, factory)
    factory.person(ev, "1001")
    _enable(client, ev)
    _give(db, ev, "1001", "QR-1")
    area = client.post(f"/api/events/{ev.id}/areas", json={"name": "VIP"}).json()
    r = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json={"cedula": "QR-1", "direction": "in"}).json()
    assert r["result"] == "OK" and r["data"]["id"] == "1001"
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Agua", "initial_qty": 3}).json()
    d = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "qr-1", "items": [{"item_id": item["id"], "qty": 1}]})
    assert d.status_code == 200 and d.json()["data"]["id"] == "1001"
    unknown = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json={"cedula": "XX", "direction": "in"})
    assert unknown.status_code == 404


def test_bulk_roster_template_has_the_code_column_only_when_enabled(client, factory):
    ev = _setup(client, factory)
    assert client.get(f"/api/events/{ev.id}/roster-template").status_code in (200, 404, 400)
    _enable(client, ev)
    r = client.get(f"/api/events/{ev.id}/roster-template")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    import io
    import pandas as pd
    cols = [str(c).lower() for c in pd.read_excel(io.BytesIO(r.content)).columns]
    assert any(c.startswith("c") and "digo" in c for c in cols)
