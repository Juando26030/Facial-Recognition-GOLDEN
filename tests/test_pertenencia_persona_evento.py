"""Fase 3 (P1): una persona es de un evento si está inscrita o tiene algún registro ahí. La cédula sola no basta aunque exista en el mismo cliente (B2, R2-1)."""
import pytest

from app.models import AccessLog, EventAttendee, PrintLog
from tests.conftest import login


@pytest.fixture()
def two_events(factory, db):
    a, b = factory.event("en_proceso"), factory.event("en_proceso")          # mismo cliente «acme»
    factory.person(a, "1001", registered=True)
    factory.person(b, "2002", "Beto", "Ajeno")
    coord = factory.staff("coordinador", "coord_a")
    factory.authorize(a, coord)
    dig = factory.staff("digitador", "dig_a")
    factory.authorize(a, dig)
    return a, b, coord, dig


def test_badge_print_data_is_scoped_to_the_event(client, two_events):
    a, b, _, _ = two_events
    login(client, "coord_a")
    assert client.get(f"/api/users/1001/badge-print-data?event_id={a.id}").status_code == 200
    assert client.get(f"/api/users/2002/badge-print-data?event_id={a.id}").status_code == 404


def test_badge_photo_print_count_and_log_are_scoped(client, two_events, db):
    a, b, _, _ = two_events
    a.badge_bio_photo_allowed = True
    db.commit()
    login(client, "coord_a")
    assert client.get(f"/api/users/2002/photo?event_id={a.id}").status_code == 404
    assert client.get(f"/api/users/2002/print-count?event_id={a.id}").status_code == 404
    assert client.post(f"/api/users/2002/print-log?event_id={a.id}").status_code == 404
    assert db.query(PrintLog).filter_by(event_id=a.id, user_id="2002").count() == 0
    # la persona del propio evento sí
    assert client.get(f"/api/users/1001/print-count?event_id={a.id}").status_code == 200
    assert client.post(f"/api/users/1001/print-log?event_id={a.id}").status_code == 200


def test_same_message_whether_the_person_exists_elsewhere_or_not(client, two_events):
    a, _, _, _ = two_events
    login(client, "coord_a")
    other = client.get(f"/api/users/2002/print-count?event_id={a.id}")
    nobody = client.get(f"/api/users/9999/print-count?event_id={a.id}")
    assert other.status_code == nobody.status_code == 404 and other.json() == nobody.json()


def test_signature_routes_are_scoped_to_the_event(client, two_events):
    a, _, _, _ = two_events
    login(client, "dig_a")
    assert client.get(f"/api/events/{a.id}/users/2002/signature/opcional_1").status_code == 404
    assert client.delete(f"/api/events/{a.id}/users/2002/signature/opcional_1").status_code == 404


def test_sync_with_plain_cedula_only_accepts_people_of_the_event(client, two_events, db):
    a, _, _, _ = two_events
    login(client, "dig_a")
    r = client.post(f"/api/events/{a.id}/access-logs/sync", json={"records": [
        {"client_id": "c1", "cedula": "1001"}, {"client_id": "c2", "cedula": "2002"}]})
    assert r.status_code == 200
    res = {x["client_id"]: x["result"] for x in r.json()["results"]}
    assert res == {"c1": "created", "c2": "unknown"}
    assert db.query(EventAttendee).filter_by(event_id=a.id, user_id="2002").count() == 0
    assert db.query(AccessLog).filter_by(event_id=a.id, user_id="2002").count() == 0


def test_member_ids_helper(two_events, db):
    from app.eventpeople import member_ids, person_of_event
    a, b, _, _ = two_events
    assert member_ids(db, a, ["1001", "2002", "", "x"]) == {"1001"}
    assert member_ids(db, a, []) == set()
    assert person_of_event(db, a, "2002") is None and person_of_event(db, b, "2002") is not None
    # un registro de acceso también cuenta como pertenencia
    db.add(AccessLog(tenant_id=a.tenant_id, user_id="2002", record_type="Existente", event_id=a.id))
    db.commit()
    assert member_ids(db, a, ["2002"]) == {"2002"}
