"""Bandeja de salida (B8, rebanada R1): `POST /api/events/{id}/outbox/sync` — altas hechas sin red (sin foto). Idempotente por `op_id`; una cédula que ya existía NO se pisa; un resultado por operación."""
from datetime import datetime, timedelta

from app.models import AccessLog, EventAttendee, User
from tests.conftest import login


def _op(op_id, cedula="2001", first="Nora", last="Sin Red", **fields):
    return {"op_id": op_id, "type": "create_person", "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "fields": {"id": cedula, "first_name": first, "last_name": last, **fields}}


def _setup(client, factory, username="dig"):
    ev = factory.event("en_proceso")
    staff = factory.staff("digitador", username)
    factory.authorize(ev, staff)
    login(client, username)
    return ev


def _sync(client, ev, *ops):
    return client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": list(ops)})


def test_a_new_person_is_created_registered_and_a_replay_never_duplicates(client, factory, db):
    ev = _setup(client, factory)
    r = _sync(client, ev, _op("op-1", entity="ACME", phone="3001112222"))
    assert r.status_code == 200 and r.json()["results"] == [{"op_id": "op-1", "result": "ok"}] and r.json()["ok"] == 1
    u = db.query(User).filter_by(id="2001", tenant_id=ev.tenant_id).one()
    assert (u.first_name, u.last_name, u.entity, u.phone) == ("Nora", "Sin Red", "ACME", "3001112222") and u.face_encoding is None
    logs = db.query(AccessLog).filter_by(event_id=ev.id, user_id="2001").all()
    assert len(logs) == 1 and logs[0].record_type == "Nuevo" and logs[0].client_id == "op-1" and logs[0].registration_method == "tradicional"
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2001").count() == 1
    assert _sync(client, ev, _op("op-1")).json()["results"] == [{"op_id": "op-1", "result": "replayed"}]                         # reenvío del mismo lote
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="2001").count() == 1


def test_an_existing_cedula_is_never_overwritten(client, factory, db):
    ev = _setup(client, factory)
    factory.person(ev, "3001", "Luis", "Original", attend=False)
    r = _sync(client, ev, _op("op-2", cedula="3001", first="Otro", last="Nombre", entity="Nueva Entidad")).json()["results"][0]
    assert r["result"] == "existente" and r["existing_name"] == "Luis Original"                       # el cliente muestra qué había; el dato digitado sin red NO se aplica
    db.expire_all()
    u = db.query(User).filter_by(id="3001", tenant_id=ev.tenant_id).one()
    assert (u.first_name, u.last_name) == ("Luis", "Original") and not u.entity, "no se pisaron el nombre ni la entidad"
    log = db.query(AccessLog).filter_by(event_id=ev.id, user_id="3001").one()
    assert log.record_type == "Existente" and log.client_id == "op-2"
    # ya registrada en este evento: duplicado, no se hace nada más
    r2 = _sync(client, ev, _op("op-3", cedula="3001")).json()["results"][0]
    assert r2["result"] == "duplicado" and db.query(AccessLog).filter_by(event_id=ev.id, user_id="3001").count() == 1


def test_two_ops_for_the_same_new_cedula_in_one_batch_create_one_person(client, factory, db):
    ev = _setup(client, factory)
    res = _sync(client, ev, _op("a", cedula="4001"), _op("b", cedula="4001", first="Dos")).json()["results"]
    assert [x["result"] for x in res] == ["ok", "duplicado"]
    assert db.query(User).filter_by(id="4001", tenant_id=ev.tenant_id).one().first_name == "Nora"


def test_validation_errors_come_back_per_item_without_stopping_the_rest(client, factory, db):
    ev = _setup(client, factory)
    res = _sync(client, ev, _op("e1", cedula="", first="X"), _op("e2", cedula="5002", email="no-es-un-correo"), {"op_id": "e3", "type": "otra", "fields": {}}, _op("ok1", cedula="5003"),
                {"type": "create_person", "fields": {}}).json()["results"]
    by = {r["op_id"]: r for r in res}
    assert by["e1"]["result"] == "error" and "cédula" in by["e1"]["detail"]
    assert by["e3"]["result"] == "error" and by[""]["result"] == "error"
    assert by["ok1"]["result"] == "ok" and db.query(User).filter_by(id="5003", tenant_id=ev.tenant_id).count() == 1
    assert by["e2"]["result"] == "ok"                        # el correo solo se valida si el evento tiene un campo de correo configurado (igual que /register)


def test_required_fields_of_the_event_are_enforced(client, factory, db):
    from app.models import EventFieldConfig
    ev = _setup(client, factory)
    db.add(EventFieldConfig(event_id=ev.id, field_key="phone", required=True, field_type="text_short"))
    db.commit()
    r = _sync(client, ev, _op("p1", cedula="6001")).json()["results"][0]
    assert r["result"] == "error" and "obligatorios" in r["detail"] and db.query(User).filter_by(id="6001", tenant_id=ev.tenant_id).count() == 0
    assert _sync(client, ev, _op("p2", cedula="6001", phone="3000000000")).json()["results"][0]["result"] == "ok"


def test_an_event_that_is_no_longer_in_progress_rejects_new_people_but_keeps_the_error_visible(client, factory, db):
    ev = factory.event("en_proceso")
    staff = factory.staff("digitador", "dig2")
    factory.authorize(ev, staff)
    ev.status, ev.finalized_at = "finalizado", datetime.utcnow() - timedelta(days=1)       # terminó hace 1 día: el digitador aún puede sincronizar (como access-logs/sync) pero no crear personas
    db.commit()
    login(client, "dig2")
    r = _sync(client, ev, _op("late", cedula="7001"))
    assert r.status_code == 200 and r.json()["results"][0]["result"] == "error" and "ya no está abierto" in r.json()["results"][0]["detail"]
    assert db.query(User).filter_by(id="7001", tenant_id=ev.tenant_id).count() == 0


def test_permissions_batch_limits_and_shape(client, factory):
    ev = factory.event("en_proceso")
    factory.staff("digitador", "stranger")
    login(client, "stranger")
    assert _sync(client, ev, _op("x")).status_code == 403                                                  # sin autorización al evento
    ev2 = _setup(client, factory, "dig3")
    assert client.post(f"/api/events/{ev2.id}/outbox/sync", json={"ops": []}).status_code == 400
    assert client.post(f"/api/events/{ev2.id}/outbox/sync", json={}).status_code == 400
    assert _sync(client, ev2, *[_op(f"b{i}", cedula=str(8000 + i)) for i in range(51)]).status_code == 400    # máximo 50 por lote
    assert client.post("/api/events/999999/outbox/sync", json={"ops": [_op("z")]}).status_code == 404
    client.post("/logout")
    assert _sync(client, ev2, _op("anon")).status_code in (401, 403)


def test_a_client_never_sees_personal_data_of_other_people_beyond_the_existing_name(client, factory):
    ev = _setup(client, factory)
    factory.person(ev, "9001", "Ana", "Privada", attend=False)
    r = _sync(client, ev, _op("q", cedula="9001")).json()["results"][0]
    assert set(r) == {"op_id", "result", "existing_name"}                                              # nada de teléfono, correo ni entidad de la persona existente
