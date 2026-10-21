"""«Deshacer» de la acreditación con el botón de la fila (docs/16, 7a): solo quien acreditó, hasta 15 s después (verificado en el servidor), con el evento abierto."""
from datetime import datetime, timedelta

from app.models import AccessLog
from tests.conftest import login


def _checkin(client, ev, cedula, cid):
    return client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": cedula, "client_id": cid, "confirm": "true"})


def _setup(client, factory, username="dig"):
    ev = factory.event("en_proceso")
    staff = factory.staff("digitador", username)
    factory.authorize(ev, staff)
    factory.person(ev, "1001", "Ana", "Uno")
    login(client, username)
    return ev, staff


def _undo(client, ev, cid):
    return client.post(f"/api/events/{ev.id}/accreditations/undo", json={"client_id": cid})


def test_the_person_who_accredited_can_undo_within_15_seconds(client, factory, db):
    ev, _ = _setup(client, factory)
    assert _checkin(client, ev, "1001", "c-1").json()["result"] == "SÍ"
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 1
    r = _undo(client, ev, "c-1")
    assert r.status_code == 200 and r.json() == {"undone": True, "user_id": "1001"}
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 0          # vuelve a «No registrado»
    assert _undo(client, ev, "c-1").status_code == 404                                         # ya se deshizo
    assert _checkin(client, ev, "1001", "c-2").json()["result"] == "SÍ"                         # y se puede volver a acreditar


def test_after_15_seconds_it_can_no_longer_be_undone_even_by_the_same_person(client, factory, db):
    ev, _ = _setup(client, factory)
    _checkin(client, ev, "1001", "c-old")
    log = db.query(AccessLog).filter_by(event_id=ev.id, client_id="c-old").one()
    log.timestamp = datetime.utcnow() - timedelta(seconds=16)
    db.commit()
    r = _undo(client, ev, "c-old")
    assert r.status_code == 409 and "15 segundos" in r.json()["detail"]
    assert db.query(AccessLog).filter_by(event_id=ev.id, client_id="c-old").count() == 1


def test_only_the_person_who_accredited_can_undo(client, factory, db):
    ev, _ = _setup(client, factory)
    _checkin(client, ev, "1001", "c-mine")
    other = factory.staff("digitador", "otro")
    factory.authorize(ev, other)
    client.post("/logout")
    login(client, "otro")
    r = _undo(client, ev, "c-mine")
    assert r.status_code == 403 and "Solo quien acreditó" in r.json()["detail"]
    assert db.query(AccessLog).filter_by(event_id=ev.id, client_id="c-mine").count() == 1


def test_undo_validations_and_closed_event(client, factory, db):
    ev, _ = _setup(client, factory)
    assert client.post(f"/api/events/{ev.id}/accreditations/undo", json={}).status_code == 400
    assert _undo(client, ev, "no-existe").status_code == 404
    _checkin(client, ev, "1001", "c-z")
    ev.status = "finalizado"
    ev.finalized_at = datetime.utcnow()
    db.commit()
    assert _undo(client, ev, "c-z").status_code == 403                                          # con el evento ya cerrado no se registra ni se deshace
    client.post("/logout")
    assert _undo(client, ev, "c-z").status_code in (401, 403)
