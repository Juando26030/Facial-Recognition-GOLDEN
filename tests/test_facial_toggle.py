"""Interruptor manual de reconocimiento facial en Parámetros del Evento (2026-09-27, pedido explícito):
antes `facial_enabled` solo se prendía sola al subir un roster con zip de fotos y nunca se apagaba."""
from app.models import User
from tests.conftest import login


def test_coordinador_can_turn_facial_on_and_off_at_any_time(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=False)
    login(client, "coord1")

    on = client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": True})
    assert on.status_code == 200 and on.json() == {"facial_enabled": True}

    off = client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": False})
    assert off.status_code == 200 and off.json() == {"facial_enabled": False}


def test_turning_it_off_does_not_erase_existing_faces(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    factory.person(ev, "1001")
    db.query(User).filter_by(id="1001").update({"face_encoding": "[[0.1, 0.2]]"})
    db.commit()
    login(client, "coord1")

    assert client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": False}).status_code == 200
    assert db.query(User).filter_by(id="1001").first().face_encoding == "[[0.1, 0.2]]"


def test_comercial_and_digitador_cannot_toggle_it(client, factory):
    factory.staff("comercial", "com1")
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff("digitador", "dig1"))
    for username in ("com1", "dig1"):
        login(client, username)
        assert client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": True}).status_code == 403
        client.post("/logout")
