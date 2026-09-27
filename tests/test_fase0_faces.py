"""Reconocimiento facial de la Fase 0: candidatos del EVENTO, matriz en memoria versionada, un solo reconocimiento por persona (token),
cola con tope y columna diferida. El motor dlib se reemplaza por un doble que devuelve el encoding que cada prueba quiere."""
import io
import json
import threading

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import inspect

from app import faces
from app.models import AccessLog, Event, EventAttendee, User
from tests.conftest import login


def _vec(seed: int) -> list:
    return np.random.default_rng(seed).normal(0, 0.1, 128).round(6).tolist()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def scan(monkeypatch):
    """`scan.face = vector` decide qué encoding «ve» el motor en el siguiente escaneo (None = sin rostro)."""
    from app.biometrics import BiometricEngine

    state = type("S", (), {"face": None, "calls": 0})()

    def fake_extract(img, is_registration=False, **kw):
        state.calls += 1
        return state.face

    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(fake_extract))
    return state


def _person_with_face(db, ev, uid, seed, attend=True):
    u = User(id=uid, tenant_id=ev.tenant_id, first_name=f"P{uid}", last_name="X", face_encoding=json.dumps(_vec(seed)))
    db.add(u)
    db.flush()
    if attend:
        db.add(EventAttendee(event_id=ev.id, user_id=uid, tenant_id=ev.tenant_id))
    db.commit()
    return u


def _post_scan(client, ev, **extra):
    return client.post("/api/recognize", data={"event_id": ev.id, **extra}, files={"file": ("s.png", _png(), "image/png")})


def test_recognize_uses_only_people_of_the_event_and_returns_a_match_token(client, factory, db, scan):
    factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    other = factory.event("en_proceso")                                    # mismo cliente, otro evento
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).first())
    _person_with_face(db, ev, "1001", 1)
    _person_with_face(db, other, "2002", 2)                                # no está en el evento que se escanea
    login(client, "9990001")

    scan.face = _vec(1)
    r = _post_scan(client, ev).json()
    assert r["result"] == "MATCH_PENDING" and r["data"]["id"] == "1001" and r["match_token"]

    scan.face = _vec(2)                                                    # una persona del cliente, pero de OTRO evento: no se reconoce
    assert _post_scan(client, ev).json() == {"result": "NO", "details": "Denegado"}

    scan.face = None
    assert _post_scan(client, ev).json()["details"] == "Rostro no detectado"


def test_confirming_with_the_token_does_not_recognize_again_and_registers_once(client, factory, db, scan):
    from app.models import StaffUser
    factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    factory.authorize(ev, db.query(StaffUser).first())
    _person_with_face(db, ev, "1001", 1)
    login(client, "9990001")
    scan.face = _vec(1)
    token = _post_scan(client, ev).json()["match_token"]
    calls = scan.calls

    ok = client.post("/api/recognize", data={"event_id": ev.id, "match_token": token, "confirm": "true"}).json()   # SIN foto
    assert ok["result"] == "SÍ" and ok["data"]["id"] == "1001"
    assert scan.calls == calls                                             # el motor facial no volvió a correr
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 1

    dup = client.post("/api/recognize", data={"event_id": ev.id, "match_token": token}).json()                       # ya registrada: aviso, con token para forzar
    assert dup["result"] == "DUPLICADO" and dup["match_token"]
    forced = client.post("/api/recognize", data={"event_id": ev.id, "match_token": dup["match_token"], "force": "true", "confirm": "true"}).json()
    assert forced["result"] == "SÍ" and scan.calls == calls
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 2


def test_match_token_is_bound_to_event_and_operator_and_expires(client, factory, db, scan, monkeypatch):
    from app.models import StaffUser
    factory.staff("digitador", "9990001")
    factory.staff("digitador", "9990002")
    ev = factory.event("en_proceso")
    for s in db.query(StaffUser).all():
        factory.authorize(ev, s)
    _person_with_face(db, ev, "1001", 1)
    login(client, "9990001")
    scan.face = _vec(1)
    token = _post_scan(client, ev).json()["match_token"]

    client.post("/logout")
    login(client, "9990002")                                               # otro operador no puede usar el token de éste
    assert client.post("/api/recognize", data={"event_id": ev.id, "match_token": token, "confirm": "true"}).status_code == 400
    client.post("/logout")
    login(client, "9990001")
    assert client.post("/api/recognize", data={"event_id": ev.id, "match_token": "basura", "confirm": "true"}).status_code == 400
    monkeypatch.setattr(faces, "MATCH_TOKEN_TTL", -1)                      # vencido
    assert client.post("/api/recognize", data={"event_id": ev.id, "match_token": token, "confirm": "true"}).status_code == 400


def test_recognize_without_photo_or_token_is_rejected(client, factory, db, scan):
    from app.models import StaffUser
    factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    factory.authorize(ev, db.query(StaffUser).first())
    login(client, "9990001")
    assert client.post("/api/recognize", data={"event_id": ev.id}).status_code == 422


def test_busy_face_queue_answers_503_with_retry_after(client, factory, db, scan, monkeypatch):
    from app.models import StaffUser
    factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    factory.authorize(ev, db.query(StaffUser).first())
    login(client, "9990001")
    monkeypatch.setattr(faces, "_gate", threading.BoundedSemaphore(1))
    monkeypatch.setattr(faces, "FACE_QUEUE_TIMEOUT", 0.05)
    faces._gate.acquire()                                                  # alguien ya ocupa el único lugar
    r = _post_scan(client, ev)
    assert r.status_code == 503 and r.headers["retry-after"] == "3"


def test_matrix_is_rebuilt_only_when_faces_version_changes(client, factory, db, scan):
    ev = factory.event("en_proceso")
    _person_with_face(db, ev, "1001", 1)
    db.refresh(ev)
    v0 = ev.faces_version
    first = faces.event_index(db, ev)
    assert first.ids == ["1001"] and faces.event_index(db, ev) is first          # sin cambios: la misma matriz en memoria

    _person_with_face(db, ev, "1002", 2)                                          # rostro nuevo en el evento: sube la versión
    db.refresh(ev)
    assert ev.faces_version > v0
    second = faces.event_index(db, ev)
    assert second is not first and sorted(second.ids) == ["1001", "1002"]

    user = db.query(User).filter_by(id="1002").first()
    user.face_encoding = json.dumps(_vec(9))                                      # rostro cambiado: sube otra vez
    db.commit()
    db.refresh(ev)
    third = faces.event_index(db, ev)
    assert third is not second and third.best(_vec(9))[1] < 1e-4


def test_people_without_face_do_not_bump_the_version_and_removal_does(factory, db):
    ev = factory.event("en_proceso")
    db.refresh(ev)
    v0 = ev.faces_version
    factory.person(ev, "3003")                                                    # persona sin rostro que entra al evento
    db.refresh(ev)
    assert ev.faces_version == v0
    _person_with_face(db, ev, "1001", 1)
    db.refresh(ev)
    v1 = ev.faces_version
    assert v1 > v0
    db.delete(db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").first())   # sale del evento
    db.commit()
    db.refresh(ev)
    assert ev.faces_version > v1 and faces.event_index(db, ev).ids == []


def test_face_encoding_column_is_deferred_so_listing_people_does_not_decrypt_or_load_it(factory, db):
    ev = factory.event("en_proceso")
    _person_with_face(db, ev, "1001", 1)
    db.expire_all()
    u = db.query(User).filter_by(id="1001").first()
    assert "face_encoding" in inspect(u).unloaded                                 # no se cargó
    assert u.face_encoding                                                        # pero se puede pedir cuando de verdad hace falta
    assert isinstance(db.query(Event).first().faces_version, int)


# ------------------------------- cálculo en procesos aparte -------------------------------
def test_face_work_runs_in_a_separate_process_and_survives_a_crash(monkeypatch):
    import os
    from tests import _fake_face_worker
    monkeypatch.setattr(faces, "FACE_PROCESSES", 1)
    monkeypatch.setattr(faces, "face_worker", _fake_face_worker)
    faces._reset_pool()
    try:
        faces.warmup()
        first = faces.extract(np.zeros((6, 4, 3), dtype=np.uint8), jitters=7)
        assert first[:2] == [6.0, 7.0] and int(first[2]) != os.getpid()      # lo calculó OTRO proceso (el web no retiene el GIL)
        with pytest.raises(faces.Busy):                                                       # el hijo muere: 503 para ese escaneo…
            faces.extract(np.zeros((2, 2, 3), dtype=np.uint8), crash=True)
        again = faces.extract(np.zeros((3, 3, 3), dtype=np.uint8), jitters=1)               # …y el motor se reinicia solo para el siguiente
        assert again[:2] == [3.0, 1.0]
    finally:
        faces.shutdown()


def test_face_work_in_the_same_process_when_processes_are_zero(monkeypatch):
    import os

    from tests import _fake_face_worker
    monkeypatch.setattr(faces, "FACE_PROCESSES", 0)
    monkeypatch.setattr(faces, "face_worker", _fake_face_worker)
    assert int(faces.extract(np.zeros((2, 2, 3), dtype=np.uint8))[2]) == os.getpid()
