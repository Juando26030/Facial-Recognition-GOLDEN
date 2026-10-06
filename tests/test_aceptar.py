"""Camino B (/aceptar/<evento>) y la MEZCLA con el camino A (cédula/QR → pantalla → captura en vivo → vector por tarea) dentro del mismo evento."""
import io
import json
import uuid
from datetime import date

import numpy as np
import pytest
from PIL import Image

from app import consent, faces, legal_texts
from app.models import AuditConsentLog, User, WebAcceptance
from app.storage import get_storage, photo_key
from tests.conftest import login


def _vec(seed):
    return np.random.default_rng(seed).normal(0, 0.1, 128).round(6).tolist()


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901.542.833", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def engine(monkeypatch):
    from app.biometrics import BiometricEngine
    state = type("S", (), {"face": None})()
    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(lambda img, is_registration=False, **kw: state.face))
    return state


def _event(factory, **kw):
    return factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, **kw)


def _post(client, ev, cedula, decision="accept", birth="1990-04-02", selfie=True, text_hash=None, adult=False):
    t = legal_texts.render(ev, web=True)
    files = {"file": ("s.jpg", _png(), "image/jpeg")} if selfie else None
    return client.post(f"/api/aceptar/{ev.event_code}", data={"cedula": cedula, "birth_date": birth, "decision": decision, "text_hash": text_hash or t["hash"], "adult": "true" if adult else "false"}, files=files)


def test_page_and_text_exist_only_when_the_event_enables_it(client, factory, env):
    off = factory.event("en_proceso", facial_enabled=True)
    assert client.get(f"/aceptar/{off.event_code}").status_code == 404 and client.get(f"/api/aceptar/{off.event_code}/text").status_code == 404
    on = _event(factory)
    page = client.get(f"/aceptar/{on.event_code}")
    assert page.status_code == 200 and on.name in page.text and "selfie" in page.text
    t = client.get(f"/api/aceptar/{on.event_code}/text").json()
    assert t["version"] == "v1.1_web" and t["hash"] == legal_texts.render(on, web=True)["hash"] and "capturada en vivo por la cámara" in " ".join(t["body"])      # el texto de la auditora, literal


def test_only_people_already_registered_can_accept_and_nothing_is_revealed(client, factory, db, env):
    ev = _event(factory)
    factory.person(ev, "1001", "Ana", "Mora")
    assert _post(client, ev, "9999").status_code == 404                                                    # no inscrito
    assert _post(client, ev, "1001", text_hash="0" * 64).status_code == 409                                # el texto cambió
    ok = _post(client, ev, "1001")
    assert ok.status_code == 200
    db.query(User).filter_by(id="1001").update({"birth_date": date(1990, 4, 2)})
    db.commit()
    assert _post(client, ev, "1001", birth="1991-01-01").status_code == 404                               # fecha distinta a la ya registrada: mismo mensaje
    assert _post(client, ev, "1001", selfie=False).status_code == 400


def test_accepting_from_the_phone_is_pending_until_staff_verifies_identity(client, factory, db, env, engine):
    ev = _event(factory)
    factory.person(ev, "1001", "Ana", "Mora")
    factory.staff("digitador", "9990001")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).first())
    engine.face = _vec(1)
    r = _post(client, ev, "1001")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    log = db.query(AuditConsentLog).filter_by(user_id="1001").one()
    assert log.consent_version == "v1.1_web" and log.legal_text_hash == legal_texts.render(ev, web=True)["hash"] and log.accepted_biometric and log.confirmed_adult and log.reason == "consent"
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().face_encoding                                      # el vector se calculó DESPUÉS de aceptar, por tarea
    assert db.get(WebAcceptance, (ev.tenant_id, "1001", ev.id)).verified_at is None
    db.refresh(ev)
    faces.clear_cache()
    assert faces.event_index(db, ev).ids == []                                                          # por verificar: todavía NO se reconoce su rostro
    login(client, "9990001")
    st = client.get(f"/api/events/{ev.id}/consent-status/1001").json()
    assert st["accepted"] and st["verify"] is True and st["face"] == "ready"
    people = {p["n"]: p for p in client.get(f"/api/events/{ev.id}/local-roster").json()["people"]}
    assert people["Ana Mora"]["v"] == 1 and people["Ana Mora"]["a"] == 0                               # aparece en el roster de contingencia, marcada «por verificar»
    assert client.post(f"/api/events/{ev.id}/web-acceptance/1001/verify").json() == {"verified": True}
    db.refresh(ev)
    assert faces.event_index(db, ev).ids == ["1001"]                                                    # verificada: desde aquí entra por rostro
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json()["verify"] is False
    people = {p["n"]: p for p in client.get(f"/api/events/{ev.id}/local-roster").json()["people"]}
    assert people["Ana Mora"]["v"] == 0 and people["Ana Mora"]["a"] == 1


def test_rejecting_or_being_a_minor_from_the_phone_stores_no_face(client, factory, db, env, engine):
    ev = _event(factory)
    factory.person(ev, "1001", "Ana", "Mora")
    factory.person(ev, "2002", "Beto", "Menor")
    engine.face = _vec(1)
    assert _post(client, ev, "1001", decision="reject", selfie=False).json()["status"] == "rejected"
    assert consent.latest(db, ev.tenant_id, "1001", ev.id).reason == "rejection" and not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    year = date.today().year - 12
    assert _post(client, ev, "2002", birth=f"{year}-01-01").json()["status"] == "minor"
    db.expire_all()
    u = db.query(User).filter_by(id="2002").one()
    assert u.is_biometric_enabled is False and u.face_encoding is None and not get_storage().exists(photo_key(ev.tenant_id, "2002"))
    assert db.query(AuditConsentLog).filter_by(user_id="2002").count() == 0


def test_one_event_mixing_path_a_path_b_and_people_with_no_face_at_all(client, factory, db, env, engine):
    """Persona A (cédula en puerta → pantalla → captura en vivo → vector), persona B (celular, verificada en puerta) y persona C (sin previo ni aceptación) en el MISMO evento."""
    ev = _event(factory)
    for uid, n in (("1001", "A"), ("2002", "B"), ("3003", "C")):
        factory.person(ev, uid, n, "X")
    op = factory.staff("digitador", "9990001")
    factory.authorize(ev, op)
    t = legal_texts.render(ev)
    # B: desde el celular, antes del evento
    engine.face = _vec(2)
    assert _post(client, ev, "2002").status_code == 200
    # A: en la puerta
    login(client, "9990001")
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json()["face"] == "none"
    assert client.post(f"/api/events/{ev.id}/consents", json={"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"]}]}).status_code == 200
    engine.face = _vec(1)
    assert client.post(f"/api/events/{ev.id}/enroll-face", data={"user_id": "1001"}, files={"file": ("w.jpg", _png(), "image/jpeg")}).json()["queued"] is True
    client.post(f"/api/events/{ev.id}/web-acceptance/2002/verify")
    db.refresh(ev)
    faces.clear_cache()
    assert sorted(faces.event_index(db, ev).ids) == ["1001", "2002"]                                    # C no está: no hay rostro suyo

    def scan(seed):
        engine.face = _vec(seed)
        return client.post("/api/recognize", data={"event_id": ev.id}, files={"file": ("s.png", _png(), "image/png")}).json()
    assert scan(1)["data"]["id"] == "1001" and scan(2)["data"]["id"] == "2002"
    c = scan(3)
    assert c["result"] == "NO" and c["details"].startswith("No te encontramos en la lista con reconocimiento facial")      # C: a la acreditación con cédula o QR
    # C sigue entrando por cédula sin restricción
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "3003", "confirm": "true"}).status_code == 200


def test_the_door_is_never_blocked_while_the_vector_is_still_being_computed(client, factory, db, env, engine, monkeypatch):
    from app import jobs
    ev = _event(factory)
    factory.person(ev, "1001", "Ana", "Mora")
    op = factory.staff("digitador", "9990001")
    factory.authorize(ev, op)
    monkeypatch.setattr(jobs, "kick", lambda: None)                                                       # la tarea queda en cola
    engine.face = _vec(1)
    assert _post(client, ev, "1001").status_code == 200
    login(client, "9990001")
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json()["face"] == "pending"
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "confirm": "true"}).status_code == 200      # entra por cédula mientras tanto
