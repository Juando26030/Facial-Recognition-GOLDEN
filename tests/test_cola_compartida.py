"""Cola compartida de recién registrados (solo servidor): `recent_at` = hora del SERVIDOR de la última alta/acreditación de cada persona (EventAttendee.last_action_at)."""
from datetime import datetime, timedelta

from app.models import EventAttendee
from app.timeutil import utcnow
from tests.conftest import login

FAR_PAST = "2020-01-01T00:00:00Z"


def _setup(client, factory, people=("1001",), **event_kw):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", **event_kw)
    for i, uid in enumerate(people):
        factory.person(ev, uid, f"Persona{i}", f"Apellido{i}")
    login(client, "root")
    return ev


def _row(client, ev, uid):
    rows = client.get(f"/api/users?event_id={ev.id}").json()
    return next(r for r in rows if r["id"] == uid)


def _parse(value):
    assert value.endswith("Z")
    return datetime.fromisoformat(value[:-1])


def _recent(value, seconds=60):
    return abs(utcnow() - _parse(value)) < timedelta(seconds=seconds)


def test_recent_at_is_null_at_the_start(client, factory):
    ev = _setup(client, factory)
    assert _row(client, ev, "1001")["recent_at"] is None


def test_recent_at_is_filled_when_a_person_is_created(client, factory):
    ev = _setup(client, factory, people=())
    r = client.post("/api/register", data={"event_id": ev.id, "id": "3001", "first_name": "Nueva", "last_name": "Persona"})
    assert r.status_code == 200
    assert _recent(_row(client, ev, "3001")["recent_at"])


def test_recent_at_is_filled_on_accreditation_with_server_time_not_the_clients(client, factory):
    ev = _setup(client, factory, auto_register=True)
    r = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "client_id": "k-1", "confirm": "true", "timestamp": FAR_PAST, "when": FAR_PAST})
    assert r.json()["result"] == "SÍ"
    assert _recent(_row(client, ev, "1001")["recent_at"])          # aunque el cliente mande otra hora


def test_status_change_to_registered_sets_it(client, factory):
    ev = _setup(client, factory)
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado", "timestamp": FAR_PAST}).status_code == 200
    assert _recent(_row(client, ev, "1001")["recent_at"])


def test_offline_sync_uses_the_reception_time_not_the_device_time(client, factory):
    ev = _setup(client, factory)
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "s1", "cedula": "1001", "timestamp": utcnow().replace(microsecond=0).isoformat() + "Z"}]})
    assert r.json()["results"][0]["result"] == "created"
    first = _row(client, ev, "1001")["recent_at"]
    assert _recent(first)
    # un segundo lote con una hora de dispositivo muy vieja: la hora que cuenta sigue siendo la de recepción
    client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "s2", "cedula": "1001", "timestamp": FAR_PAST}]})
    second = _row(client, ev, "1001")["recent_at"]
    assert _recent(second) and _parse(second) >= _parse(first)


def test_outbox_create_person_sets_it(client, factory):
    ev = _setup(client, factory, people=())
    op = {"op_id": "op-1", "type": "create_person", "timestamp": FAR_PAST, "fields": {"id": "4001", "first_name": "Nora", "last_name": "Sin Red"}}
    r = client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [op]})
    assert r.json()["results"][0]["result"] == "ok"
    assert _recent(_row(client, ev, "4001")["recent_at"])


def test_editing_person_data_does_not_move_it(client, factory, db):
    ev = _setup(client, factory, auto_register=True)
    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "confirm": "true"})
    before = _row(client, ev, "1001")["recent_at"]
    old = _parse(before) - timedelta(hours=1)                      # se retrasa a mano para que cualquier cambio se note
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").update({"last_action_at": old})
    db.commit()
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Ingeniera"}).status_code == 200
    assert _parse(_row(client, ev, "1001")["recent_at"]) == old


def test_changes_returns_the_person_just_accredited_and_the_etag_moves(client, factory):
    ev = _setup(client, factory, people=("1001", "1002"), auto_register=True)
    first = client.get(f"/api/users?event_id={ev.id}")
    cursor = client.get(f"/api/users/changes?event_id={ev.id}").json()["cursor"]
    assert client.get(f"/api/users/changes?event_id={ev.id}&cursor={cursor}").json()["users"] == []
    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1002", "confirm": "true"})
    changed = client.get(f"/api/users/changes?event_id={ev.id}&cursor={cursor}").json()["users"]
    assert [u["id"] for u in changed] == ["1002"] and _recent(changed[0]["recent_at"])
    assert client.get(f"/api/users?event_id={ev.id}").headers["ETag"] != first.headers["ETag"]
