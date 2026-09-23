"""Escarapela digital: la casilla «Enviar ahora» decide si sale el correo (guardar ya no reenvía por sí solo)."""
from tests.conftest import login


def _setup(client, factory, role="digitador"):
    staff = factory.staff(role, "9990001" if role == "digitador" else "coord1")
    ev = factory.event("en_proceso", digital_badge_enabled=True)
    if role == "digitador":
        factory.authorize(ev, staff)
    login(client, staff.username)
    return ev


def _register(client, ev, uid, contact="ana@example.com", send=None):
    data = {"event_id": ev.id, "id": uid, "first_name": "Ana", "last_name": "Mora", "digital_contact": contact}
    if send is not None:
        data["send_digital_now"] = send
    return client.post("/api/register", data=data)


def test_register_sends_when_checkbox_is_checked(client, factory, outbox):
    ev = _setup(client, factory)
    r = _register(client, ev, "1001", send="true")
    assert r.status_code == 200 and r.json()["digital"]["sent"] is True
    assert [m["to"] for m in outbox] == ["ana@example.com"] and "/b/" in outbox[0]["body"]


def test_register_does_not_send_when_checkbox_is_unchecked(client, factory, outbox):
    ev = _setup(client, factory)
    r = _register(client, ev, "1001", send="false")
    assert r.status_code == 200
    assert outbox == []
    assert r.json()["digital"]["sent"] is False and "NO se envió" in r.json()["digital"]["detail"]


def test_register_without_the_field_still_sends_for_old_screens(client, factory, outbox):
    ev = _setup(client, factory)
    _register(client, ev, "1001")            # pantalla vieja en caché: no manda la casilla
    assert len(outbox) == 1


def test_saving_again_does_not_resend_unless_checkbox_is_checked(client, factory, outbox):
    ev = _setup(client, factory, role="coordinador")
    _register(client, ev, "1001", send="true")
    assert len(outbox) == 1
    url = f"/api/users/1001?event_id={ev.id}"
    # editar y guardar dejando la casilla sin marcar: no se reenvía
    assert client.patch(url, json={"role": "Ing", "digital_contact": "ana@example.com", "send_digital_now": False}).status_code == 200
    assert len(outbox) == 1
    # marcada: sí se reenvía
    r = client.patch(url, json={"digital_contact": "ana@example.com", "send_digital_now": True})
    assert len(outbox) == 2 and r.json()["digital"]["sent"] is True


def test_edit_can_save_a_new_email_without_sending(client, factory, outbox, db):
    from app.models import EventAttendee

    ev = _setup(client, factory, role="coordinador")
    _register(client, ev, "1001", contact="uno@example.com", send="false")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"digital_contact": "dos@example.com", "send_digital_now": False})
    assert outbox == []
    assert db.query(EventAttendee).filter_by(user_id="1001").one().digital_contact == "dos@example.com"


def test_directory_exposes_when_it_was_sent(client, factory, outbox):
    ev = _setup(client, factory, role="coordinador")
    _register(client, ev, "1001", send="true")
    _register(client, ev, "1002", contact="beto@example.com", send="false")
    users = {u["id"]: u for u in client.get(f"/api/users?event_id={ev.id}").json()}
    assert users["1001"]["digital_sent_at"] is not None
    assert users["1002"]["digital_sent_at"] is None


def test_invalid_email_is_still_rejected_whatever_the_checkbox(client, factory, outbox):
    ev = _setup(client, factory)
    r = _register(client, ev, "1001", contact="no-es-correo", send="false")
    assert r.status_code == 400 and outbox == []
