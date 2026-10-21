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


def test_the_door_no_longer_asks_for_a_movement_check_and_the_parameters_keep_the_supervision_warning(client, factory, db, monkeypatch):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, face_door_enabled=True)
    st = factory.staff("digitador", "puerta1")
    factory.authorize(ev, st)
    factory.person(ev, "1001", "Ana", "Prueba")
    monkeypatch.setattr(faces, "recognize", lambda db, event, raw, ungated=False: ("MATCH", [("1001", 0.30)]))
    login(client, "puerta1")
    r = client.post("/api/door-face", data={"event_id": str(ev.id)}, files={"file": ("f.jpg", _img(), "image/jpeg")})      # un solo fotograma, sin reto
    assert r.json()["result"] == "OK"
    assert client.get(f"/api/events/{ev.id}/door-face/challenge").status_code == 404
    assert not hasattr(liveness, "movement_ok")
    client.cookies.clear()
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert "Sin prueba de vida: requiere supervisión constante" in page and "siempre una persona frente a la pantalla de la puerta" in page and "ccFaceDoorLive" not in page
    assert "LIVENESS" not in client.get(f"/kiosk/{ev.id}/rostro").text

