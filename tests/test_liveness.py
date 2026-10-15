"""B2d (calidad de la selfie en el servidor) y prueba de movimiento de la puerta (opción A): reglas puras, el flujo de la puerta y el de /aceptar."""
import io
from datetime import date

import pytest
from PIL import Image

from app import acceptlink, appmode, faces, legal_texts, liveness
from app.models import AccessLog, AuditConsentLog, EventAttendee, SystemEvent
from app.storage import get_storage, photo_key
from tests.conftest import login

GOOD = {"faces": 1, "face_h": 0.5, "yaw": 0.0, "sharp": 100.0, "luma": 120.0, "encoding": [0.0] * 128}


def _img():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 120, 120)).save(buf, "JPEG")
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------------------------------------------ reglas puras
@pytest.mark.parametrize("change, words", [
    ({"faces": 0}, "No encontramos tu cara"), ({"faces": 2}, "más de una persona"), ({"face_h": 0.1}, "muy pequeña"),
    ({"luma": 20}, "muy oscura"), ({"luma": 240}, "demasiada luz"), ({"sharp": 3}, "borrosa"),
])
def test_selfie_problems_say_why_in_plain_words(change, words):
    assert words in liveness.selfie_problem({**GOOD, **change})


def test_a_good_selfie_has_no_problem():
    assert liveness.selfie_problem(GOOD) is None


def _turned(yaw, enc=None):
    return {**GOOD, "yaw": yaw, "encoding": enc if enc is not None else [0.0] * 128}


@pytest.mark.parametrize("front, turned, direction, ok", [
    (0.0, 0.30, "izquierda", True),
    (0.0, -0.30, "derecha", True),
    (0.0, -0.30, "izquierda", False),           # giró al lado contrario
    (0.0, 0.05, "izquierda", False),            # casi no giró (una foto plana inclinada)
    (0.30, 0.60, "izquierda", False),           # el primer fotograma no estaba de frente
])
def test_the_movement_must_go_to_the_requested_side(front, turned, direction, ok):
    assert liveness.movement_ok(_turned(front), _turned(turned), direction) is ok


def test_the_two_frames_must_be_the_same_person_and_have_one_face():
    assert liveness.movement_ok(_turned(0.0), _turned(0.3, [1.0] * 128), "izquierda") is False          # otra cara en el segundo fotograma
    assert liveness.movement_ok(_turned(0.0), {**_turned(0.3), "faces": 2}, "izquierda") is False


def test_the_challenge_is_signed_short_lived_and_bound_to_event_and_station():
    c = liveness.make_challenge(7, 3)
    assert c["direction"] in ("izquierda", "derecha") and c["direction"].upper() in c["text"]
    assert liveness.read_challenge(c["token"], 7, 3) == c["direction"]
    assert liveness.read_challenge(c["token"], 8, 3) is None and liveness.read_challenge(c["token"], 7, 4) is None
    assert liveness.read_challenge("falso", 7, 3) is None


# ------------------------------------------------------------------------------------------------------------------------------------ puerta con prueba de movimiento
@pytest.fixture()
def door(client, factory, db):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, face_door_enabled=True)
    assert ev.face_door_liveness is True                                                                  # encendida por defecto
    st = factory.staff("digitador", "puerta1")
    factory.authorize(ev, st)
    factory.person(ev, "1001", "Ana", "Prueba")
    login(client, "puerta1")
    return ev


def _frames(monkeypatch, front_yaw, turn_yaw):
    seq = iter([_turned(front_yaw), _turned(turn_yaw)])
    monkeypatch.setattr(faces, "analyze", lambda image, **kw: next(seq))
    monkeypatch.setattr(faces, "recognize", lambda db, event, raw, ungated=False: ("MATCH", [("1001", 0.30)]))


def _scan(client, ev, challenge, with_turn=True):
    files = {"file": ("f.jpg", _img(), "image/jpeg")}
    if with_turn:
        files["turn"] = ("g.jpg", _img(), "image/jpeg")
    return client.post("/api/door-face", data={"event_id": str(ev.id), "challenge": challenge}, files=files)


def test_a_person_who_turns_to_the_requested_side_enters(client, db, door, monkeypatch):
    ch = client.get(f"/api/events/{door.id}/door-face/challenge").json()
    _frames(monkeypatch, 0.0, 0.3 if ch["direction"] == "izquierda" else -0.3)
    r = _scan(client, door, ch["token"])
    assert r.json()["result"] == "OK"
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=door.id).count() == 1


def test_a_flat_photo_that_does_not_turn_never_enters(client, db, door, monkeypatch):
    ch = client.get(f"/api/events/{door.id}/door-face/challenge").json()
    _frames(monkeypatch, 0.0, 0.02)                                                                        # la foto plana inclinada: la nariz no se mueve respecto de los ojos
    r = _scan(client, door, ch["token"])
    assert r.json() == {"result": "NO_LIVE", "message": liveness.FAIL_MSG}
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=door.id).count() == 0
    assert db.query(SystemEvent).filter_by(kind="door_face", detail="no_live").count() == 1
    assert client.get(f"/api/events/{door.id}/door-face/stats").json()["no_live"] == 1


def test_without_a_valid_challenge_or_second_frame_the_door_refuses(client, db, door, monkeypatch):
    _frames(monkeypatch, 0.0, 0.3)
    assert _scan(client, door, "falso").status_code == 400
    ch = client.get(f"/api/events/{door.id}/door-face/challenge").json()
    assert _scan(client, door, ch["token"], with_turn=False).status_code == 400
    db.expire_all()
    assert db.query(AccessLog).filter_by(event_id=door.id).count() == 0


def test_the_door_screen_asks_for_the_turn_after_the_front_frame(client, door):
    page = client.get(f"/kiosk/{door.id}/rostro").text
    assert "const LIVENESS = true" in page and "door-face/challenge" in page and "fd.append('turn'" in page
    assert page.index("const blob = await frame()") < page.index("ch.text")                              # la indicación aparece DESPUÉS del fotograma de frente


# ------------------------------------------------------------------------------------------------------------------------------------ B2d en /aceptar
def _accept_setup(factory, db):
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, start_date=date(2026, 10, 29))
    u = factory.person(ev, "1001", "Ana", "Mora")
    u.birth_date = date(1990, 4, 2)
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = acceptlink.issue(db, att, True)
    db.commit()
    return ev, token


def _submit(client, ev, token):
    t = legal_texts.render(ev, web=True)
    return client.post(f"/api/aceptar/{ev.event_code}", data={"token": token, "cedula": "1001", "decision": "accept", "text_hash": t["hash"], "channel": "link"},
                       files={"file": ("s.jpg", _img(), "image/jpeg")})


def test_a_bad_selfie_is_rejected_with_the_reason_and_nothing_is_recorded(client, factory, db, monkeypatch):
    ev, token = _accept_setup(factory, db)
    monkeypatch.setattr(faces, "analyze", lambda image, **kw: {**GOOD, "faces": 2})
    r = _submit(client, ev, token)
    assert r.status_code == 400 and "más de una persona" in r.json()["detail"]
    db.expire_all()
    assert db.query(AuditConsentLog).count() == 0 and not get_storage().exists(photo_key(ev.tenant_id, "1001"))


def test_a_good_selfie_is_accepted(client, factory, db, monkeypatch):
    ev, token = _accept_setup(factory, db)
    r = _submit(client, ev, token)
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_the_selfie_submit_runs_in_the_biometric_service():
    assert "/api/aceptar/{code}" in appmode.BIOMETRIC_PATHS
    assert appmode.route_allowed("/api/aceptar/{code}", mode="biometria") and appmode.route_allowed("/api/aceptar/{code}/check", mode="publico")


def test_parameters_show_the_liveness_switch(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, face_door_enabled=True)
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert 'id="ccFaceDoorLive" checked' in page and "Sin prueba de vida" not in page
    off = client.put(f"/api/events/{ev.id}/biometric-setup", json={"facial_enabled": True, "aceptar_enabled": True, "face_door_enabled": True, "face_door_liveness": False})
    assert off.status_code == 200 and off.json()["config"]["face_door_liveness"] is False
    assert "Sin prueba de vida: requiere supervisión constante" in client.get(f"/kiosk/{ev.id}/parametros").text
