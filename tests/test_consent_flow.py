"""L1: texto literal de la auditora por variante, marcadores de empresa, registro por lotes idempotente, y que SIN aceptación registrada no hay reconocimiento facial."""
import json
import re
import uuid
from pathlib import Path

import numpy as np
import pytest

from app import company, consent, faces, legal_texts
from app.models import AuditConsentLog
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
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json() == {"accepted": False, "last": None, "mode": "once", "blocked": False}
    eid = str(uuid.uuid4())
    body = {"entries": [{"id": eid, "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "device": "tablet-1"}]}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).json() == {"inserted": 1, "duplicated": 0, "unknown": 0}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).json() == {"inserted": 0, "duplicated": 1, "unknown": 0}          # el reintento (o la sincronización) no duplica
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json()["accepted"] is True
    rej = {"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "reject", "adult": False, "text_hash": t["hash"], "version": t["version"]}]}
    client.post(f"/api/events/{ev.id}/consents", json=rej)
    assert client.get(f"/api/events/{ev.id}/consent-status/1001").json() == {"accepted": False, "last": "rejection", "mode": "once", "blocked": False}      # el último registro manda
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


# ----------------------------------------------------------------------------------------------------------- camino 2 (un clic y rostro) y regla A
def _scan_fixture(monkeypatch):
    from app.biometrics import BiometricEngine
    state = type("S", (), {"face": None})()
    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(lambda img, is_registration=False, **kw: state.face))
    return state


def _png():
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


def _scan(client, ev, **extra):
    return client.post("/api/recognize", data={"event_id": ev.id, **extra}, files={"file": ("s.png", _png(), "image/png")}).json()


def _precalc_event(client, factory, db, company_env):
    ev = _op(client, factory, controller_mode="tercero", organizer_name="Org", organizer_nit="1", organizer_privacy_email="o@o.test", precalculo_autorizado=True)
    for uid, seed in (("1001", 1), ("2002", 2)):
        db.add(User(id=uid, tenant_id=ev.tenant_id, first_name=uid, last_name="X", face_encoding=json.dumps(_vec(seed))))
        db.flush()
        db.add(EventAttendee(event_id=ev.id, user_id=uid, tenant_id=ev.tenant_id))
    db.commit()
    return ev


def test_click_lets_the_precalculated_vector_match_and_only_then_records_the_acceptance(client, factory, db, monkeypatch, company_env):
    scan = _scan_fixture(monkeypatch)
    ev = _precalc_event(client, factory, db, company_env)
    scan.face = _vec(1)
    assert _scan(client, ev)["result"] == "NO"                                           # sin clic: la compuerta sigue cerrada aunque haya vector
    tok = client.post(f"/api/events/{ev.id}/consent-click").json()["click_token"]
    assert consent.latest(db, ev.tenant_id, "1001", ev.id) is None                       # el clic solo no atribuye nada a nadie
    scan.face = None
    _scan(client, ev, click_token=tok)
    assert db.query(AuditConsentLog).count() == 0                                # sin coincidencia no se guarda nada
    scan.face = _vec(1)
    assert _scan(client, ev, click_token=tok)["data"]["id"] == "1001"
    row = consent.latest(db, ev.tenant_id, "1001", ev.id)
    assert row.consent_version == "v1.1_kiosk_clic" and row.legal_text_hash == legal_texts.render(ev)["hash"] and row.reason == "consent" and row.confirmed_adult
    assert consent.latest(db, ev.tenant_id, "2002", ev.id) is None
    db.refresh(ev)
    assert faces.event_index(db, ev).ids == ["1001"]                                     # desde ahora se reconoce sin clic
    assert _scan(client, ev)["data"]["id"] == "1001"


def test_a_forged_or_other_events_click_token_does_not_open_the_gate(client, factory, db, monkeypatch, company_env):
    scan = _scan_fixture(monkeypatch)
    ev = _precalc_event(client, factory, db, company_env)
    scan.face = _vec(2)
    assert _scan(client, ev, click_token="basura")["result"] == "NO"
    plain = factory.event("en_proceso", facial_enabled=True)
    assert client.post(f"/api/events/{plain.id}/consent-click").status_code in (403, 409)


def test_someone_who_rejected_is_never_matched_even_with_a_click(client, factory, db, monkeypatch, company_env):
    scan = _scan_fixture(monkeypatch)
    ev = _precalc_event(client, factory, db, company_env)
    t = legal_texts.render(ev)
    r = client.post(f"/api/events/{ev.id}/consents", json={"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "reject", "adult": True, "text_hash": t["hash"], "version": t["version"]}]})
    assert r.status_code == 200
    assert db.query(User).filter_by(id="1001").first().face_encoding is None            # regla A: el rechazo borra su vector pre-calculado
    tok = client.post(f"/api/events/{ev.id}/consent-click").json()["click_token"]
    scan.face = _vec(1)
    assert _scan(client, ev, click_token=tok)["result"] == "NO"
    db.add(User(id="3003", tenant_id=ev.tenant_id, first_name="n", last_name="X", face_encoding=json.dumps(_vec(1))))   # aunque el vector reapareciera
    db.flush()
    db.add(EventAttendee(event_id=ev.id, user_id="3003", tenant_id=ev.tenant_id))
    consent.record(db, tenant_id=ev.tenant_id, user_id="3003", event_id=ev.id, version="v", legal_text_hash="d" * 64, accepted=False, adult=True, reason="rejection")
    db.commit()
    assert "3003" not in faces.event_index(db, ev, ungated=True).ids


def test_rejecting_keeps_the_vector_if_the_person_accepted_in_another_event(client, factory, db, company_env):
    ev = _op(client, factory)
    other = factory.event("en_proceso", facial_enabled=True)
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="A", last_name="B", face_encoding=json.dumps(_vec(1))))
    db.commit()
    accept(db, other, "1001")
    t = legal_texts.render(ev)
    client.post(f"/api/events/{ev.id}/consents", json={"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "reject", "adult": True, "text_hash": t["hash"], "version": t["version"]}]})
    assert db.query(User).filter_by(id="1001").first().face_encoding                     # sigue sirviendo en el otro evento


def test_only_a_super_admin_can_authorize_precalculation_and_only_with_the_annex(client, factory):
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso", facial_enabled=True, controller_mode="tercero")
    login(client, "adm")
    assert client.put(f"/api/events/{ev.id}/precalculo-autorizado", json={"enabled": True, "anexo_ref": "A-1", "anexo_fecha": "2026-10-01"}).status_code == 403
    client.post("/api/auth/logout")
    factory.staff("super_admin", "sup")
    login(client, "sup")
    url = f"/api/events/{ev.id}/precalculo-autorizado"
    assert client.put(url, json={"enabled": True}).status_code == 400                    # sin referencia ni fecha del anexo
    assert client.put(url, json={"enabled": True, "anexo_ref": "A-1", "anexo_fecha": "2026-10-01"}).json()["precalculo_autorizado"] is True
    own = factory.event("en_proceso", facial_enabled=True)
    assert client.put(f"/api/events/{own.id}/precalculo-autorizado", json={"enabled": True, "anexo_ref": "A", "anexo_fecha": "2026-10-01"}).status_code == 400      # evento propio: no aplica


def test_offline_entries_use_the_roster_fingerprint_not_the_cedula(client, factory, db, company_env):
    from app.routers.api import roster_fingerprint, roster_salt
    ev = _op(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    t = legal_texts.render(ev)
    h = roster_fingerprint(roster_salt(ev), "1001")
    e = {"id": str(uuid.uuid4()), "h": h, "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "at": "2026-10-06T15:00:00Z"}
    ghost = {**e, "id": str(uuid.uuid4()), "h": "0" * 16}
    r = client.post(f"/api/events/{ev.id}/consents", json={"entries": [e, ghost]}).json()
    assert r == {"inserted": 1, "duplicated": 0, "unknown": 1}
    assert client.post(f"/api/events/{ev.id}/consents", json={"entries": [e]}).json()["duplicated"] == 1
    assert consent.has_acceptance(db, ev.tenant_id, "1001", ev.id) and consent.latest(db, ev.tenant_id, "1001", ev.id).consent_timestamp_utc.year == 2026


def test_kiosk_pages_render_the_gate_and_the_config(client, factory):
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "adm")
    reg = client.get(f"/kiosk/{ev.id}/registro")
    assert reg.status_code == 200 and "bioIdent" in reg.text and "consent-gate.js" in reg.text and "bioGateAccept" not in reg.text      # la casilla del digitador ya no cuenta como aceptación
    par = client.get(f"/kiosk/{ev.id}/parametros")
    assert par.status_code == 200 and "ccMode" in par.text and "id=\"pcSave\"" not in par.text                  # el pre-cálculo solo lo ve un super_admin en evento de tercero
