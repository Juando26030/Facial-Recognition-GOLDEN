"""L1: texto literal de la auditora por variante, marcadores de empresa, registro por lotes idempotente, y que SIN aceptación registrada no hay reconocimiento facial."""
import json
import re
import uuid
from pathlib import Path

import numpy as np
import pytest

from app import company, consent, faces, legal_texts
from app.legal_texts_data import TEXT_PROPIO, TEXT_TERCERO
from app.models import EventAttendee, User
from tests.conftest import accept, login

MD = Path("docs/legal/TEXTOS_AUDITORA_2026-10-05.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def _md_block(heading):
    return re.search(r"```text\n(.*?)\n```", MD[MD.index(heading):], re.S).group(1)


@pytest.fixture()
def company_env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Empresa Prueba S.A.S.", "COMPANY_NIT": "900.000.000-1", "PRIVACY_EMAIL": "privacidad@ejemplo.test", "DOMAIN": "app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)


def test_the_texts_in_the_code_are_the_auditors_literal_ones():
    assert TEXT_TERCERO == _md_block("## VARIANTE 1") and TEXT_PROPIO == _md_block("## VARIANTE 2")


def test_rendering_only_replaces_the_variables_and_hashes_the_exact_text(factory, company_env):
    ev = factory.event("en_proceso", facial_enabled=True, controller_mode="tercero", organizer_name="Org S.A.", organizer_nit="800.1", organizer_privacy_email="dpo@org.test")
    t = legal_texts.render(ev)
    assert t["variant"] == "tercero" and t["version"] == "v1.1_kiosk_tercero" and t["blocked"] == [] and t["adult_checkbox"]
    assert "Org S.A. / 800.1" in t["text"] and "Empresa Prueba S.A.S. / 900.000.000-1" in t["text"] and ev.name in t["text"] and "dpo@org.test" in t["text"]
    assert "https://app.ejemplo.test/privacidad" in t["text"] and "privacidad@ejemplo.test" in t["text"] and "[" not in t["text"].replace("[ BOTÓN", "")
    assert t["hash"] == consent.text_hash(t["text"]) and t["buttons"] == ["ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL", "PREFIERO INGRESAR CON DOCUMENTO / QR"]
    own = legal_texts.render(factory.event("en_proceso", facial_enabled=True, tenant_id="otro"))
    assert own["variant"] == "golden" and own["version"] == "v1.1_kiosk_propio" and own["adult_checkbox"] is None and own["hash"] != t["hash"]
    assert "Declaras bajo la gravedad de juramento que eres mayor de 18 años" in own["text"]      # la declaración de mayoría de edad va DENTRO del texto de la variante 2


def test_unresolved_company_markers_block_the_text_in_production_only(factory, monkeypatch):
    for k in company.NAMES:
        monkeypatch.delenv(k, raising=False)
    ev = factory.event("en_proceso", facial_enabled=True)
    t = legal_texts.render(ev)
    assert "[COMPANY_NAME]" in t["text"] and t["blocked"] == []                       # desarrollo: marcador visible, no bloquea
    monkeypatch.setenv("ENVIRONMENT", "production")
    t = legal_texts.render(ev)
    assert set(t["blocked"]) >= {"[COMPANY_NAME]", "[COMPANY_NIT]", "[PRIVACY_EMAIL]", "[DOMAIN]"}      # producción: no se publica con marcadores
    monkeypatch.setenv("COMPANY_NAME", "X S.A.S.")
    monkeypatch.setenv("COMPANY_NIT", "1")
    monkeypatch.setenv("PRIVACY_EMAIL", "p@x.test")
    monkeypatch.setenv("DOMAIN", "x.test")
    assert legal_texts.render(ev)["blocked"] == []


def _op(client, factory, **ev_kw):
    op = factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso", facial_enabled=True, **ev_kw)
    factory.authorize(ev, op)
    login(client, "9990001")
    return ev


def test_endpoints_text_status_and_idempotent_batch(client, factory, db, company_env):
    ev = _op(client, factory)
    t = client.get(f"/api/events/{ev.id}/consent-text").json()
    assert t["hash"] == legal_texts.render(ev)["hash"] and t["mode"] == "once"
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json() == {"accepted": False, "last": None, "mode": "once"}
    eid = str(uuid.uuid4())
    body = {"entries": [{"id": eid, "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "device": "tablet-1"}]}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).json() == {"inserted": 1, "duplicated": 0}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).json() == {"inserted": 0, "duplicated": 1}          # el reintento (o la sincronización) no duplica
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json()["accepted"] is True
    rej = {"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "reject", "adult": False, "text_hash": t["hash"], "version": t["version"]}]}
    client.post(f"/api/events/{ev.id}/consents", json=rej)
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json() == {"accepted": False, "last": "rejection", "mode": "once"}      # el último registro manda
    no_adult = {"entries": [{"id": str(uuid.uuid4()), "user_id": "2002", "decision": "accept", "adult": False, "text_hash": t["hash"], "version": t["version"]}]}
    client.post(f"/api/events/{ev.id}/consents", json=no_adult)
    assert client.get(f"/api/events/{ev.id}/consent-status/2002").json()["accepted"] is False          # sin la declaración de mayoría de edad NO cuenta como aceptación
    assert client.post(f"/api/events/{ev.id}/consents", json={"entries": [{"id": "x", "user_id": "1", "decision": "accept", "text_hash": t["hash"]}]}).status_code == 400


def test_text_endpoint_refuses_in_production_with_unresolved_markers(client, factory, monkeypatch):
    ev = _op(client, factory)
    for k in company.NAMES:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(f"/api/events/{ev.id}/consent-text").status_code == 503


def test_consent_config_validation(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "root")
    url = f"/api/events/{ev.id}/consent-config"
    assert client.put(url, json={"controller_mode": "tercero"}).status_code == 400                       # tercero sin organizador
    assert client.put(url, json={"controller_mode": "otro"}).status_code == 400
    assert client.put(url, json={"consent_prompt_mode": "siempre"}).status_code == 400
    ok = client.put(url, json={"controller_mode": "tercero", "organizer_name": "Org", "organizer_nit": "1", "organizer_privacy_email": "o@o.test", "consent_prompt_mode": "every_scan"})
    assert ok.status_code == 200 and ok.json()["consent_prompt_mode"] == "every_scan"


def _vec(seed):
    return np.random.default_rng(seed).normal(0, 0.1, 128).round(6).tolist()


def test_a_vector_without_a_registered_acceptance_is_not_used_for_recognition(factory, db):
    ev = factory.event("en_proceso", facial_enabled=True)
    for uid, seed in (("1001", 1), ("2002", 2)):
        db.add(User(id=uid, tenant_id=ev.tenant_id, first_name=uid, last_name="X", face_encoding=json.dumps(_vec(seed))))
        db.flush()
        db.add(EventAttendee(event_id=ev.id, user_id=uid, tenant_id=ev.tenant_id))
    db.commit()
    faces.clear_cache()
    assert faces.event_index(db, ev).ids == []                                   # tiene vector (carga masiva) pero nadie aceptó: no se reconoce
    accept(db, ev, "1001")
    db.refresh(ev)
    assert faces.event_index(db, ev).ids == ["1001"]                              # solo quien aceptó
    consent.record(db, tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, version="v", legal_text_hash="c" * 64, accepted=False, adult=True, reason="revocation")
    db.commit()
    db.refresh(ev)
    assert faces.event_index(db, ev).ids == []                                   # revocó: el reconocimiento deja de usarla en el acto


def test_roster_carries_the_acceptance_flag_and_the_text_without_biometrics(client, factory, db, company_env):
    ev = _op(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    factory.person(ev, "2002", "Luis", "Gómez")
    accept(db, ev, "1001")
    body = client.get(f"/api/events/{ev.id}/local-roster").json()
    flags = {p["n"]: p["a"] for p in body["people"]}
    assert flags == {"Ana Mora": 1, "Luis Gómez": 0}
    c = body["consent"]
    assert c["hash"] == legal_texts.render(ev)["hash"] and c["mode"] == "once" and c["buttons"][1].startswith("PREFIERO")
