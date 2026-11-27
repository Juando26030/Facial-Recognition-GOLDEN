"""Compromiso digital del digitador por evento (Fase 4): construido SOBRE el motor de formularios web (kind='pledge'). Ver docs/FASE_4_COMPROMISO.md."""
import io
import json
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text

from app.timeutil import utcnow
from tests.conftest import PASSWORD, login

ROOT = Path(__file__).resolve().parent.parent
CED = "1234567"


@pytest.fixture(autouse=True)
def _pledge_env(monkeypatch):
    from app import pledge
    from app.ttlcache import SlidingLimiter

    monkeypatch.setenv("PLEDGE_ALLOW_DRAFT_TEXT", "1")          # el texto de la auditora aún es borrador: las pruebas lo permiten
    monkeypatch.setattr(pledge, "_limiter", SlidingLimiter())
    yield


def _png(blank=False, size=(600, 200)):
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", size, (0, 0, 0, 0))
    if not blank:
        ImageDraw.Draw(im).line([(20, 150), (200, 40), (380, 160), (560, 50)], fill=(0, 0, 0, 255), width=5)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _values(ced=CED, **over):
    v = {"p_id": ced, "p_name": "Juan Pérez", "p_phone": "300 123 4567", "p_em_name": "María Pérez", "p_em_phone": "3009876543",
         "p_q_med": "Sí", "p_q_med_c": "Asma", "p_q_drug": "No", "p_q_support": "No", "p_q_contract": "Sí", "p_q_attend": "Sí", "p_auth": "true", "p_decl": "true"}
    v.update(over)
    return v


def _setup(client, factory, status="en_proceso"):
    """Coordinador del evento con el enlace del compromiso ya creado. Devuelve (evento, ruta pública, coordinador)."""
    coord = factory.staff("coordinador", "coord1")
    ev = factory.event(status, coordinator=coord)
    login(client, "coord1")
    r = client.post(f"/api/events/{ev.id}/pledge/link")
    assert r.status_code == 200, r.text
    path = urlsplit(r.json()["link"]).path
    client.post("/logout")
    return ev, path, coord


def _send(client, path, values, token=None, sig=None, sid="s1"):
    token = token or client.get(f"{path}/state").json()["token"]
    payload = {"values": values, "t": token, "k": None, "sid": sid}
    return client.post(f"{path}/submit", data={"data": json.dumps(payload)}, files={"file:p_sig": ("firma.png", sig or _png(), "image/png")})


def _staff(db, username):
    from app.models import StaffUser

    db.expire_all()
    return db.query(StaffUser).filter(StaffUser.username == username).first()


def _pledges(db, event_id):
    from app.models import EventStaffPledge

    db.expire_all()
    return db.query(EventStaffPledge).filter(EventStaffPledge.event_id == event_id).order_by(EventStaffPledge.id).all()


# ----------------------------------------------------------------------------------------------------- Camino A
def test_flow_a_creates_account_assignment_and_evidence(client, factory, db):
    from app.auth import verify_password
    from app.models import EventStaffAuthorization
    from app.storage import get_storage

    ev, path, _ = _setup(client, factory)
    r = _send(client, path, _values())
    assert r.status_code == 200 and r.json()["ok"] is True and "redirect" not in r.json()
    s = _staff(db, CED)
    assert s is not None and s.role == "digitador" and s.tenant_id == ev.tenant_id and s.full_name == "Juan Pérez"
    assert verify_password(CED, s.password_hash)                                       # contraseña inicial = cédula (igual que el Excel y la creación a mano)
    assert db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=s.id).first() is not None
    [p] = _pledges(db, ev.id)
    assert p.staff_id == s.id and p.source == "link" and p.superseded_at is None
    assert len(p.content_hash) == 64 and p.text_version and p.ip_masked != CED
    assert p.attendance_confirmed is True and p.understands_terms is True and p.has_health_info is True      # SÍ a la pregunta de salud → aviso
    assert get_storage().exists(p.signature_key) and get_storage().exists(p.doc_key)


def test_flow_a_reuses_existing_digitador_account(client, factory, db):
    from app.models import EventStaffAuthorization

    ev, path, _ = _setup(client, factory)
    existing = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    assert _send(client, path, _values()).status_code == 200
    db.expire_all()
    from app.models import StaffUser
    assert db.query(StaffUser).filter(StaffUser.username == CED).count() == 1                      # no duplica la cuenta
    assert db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=existing.id).count() == 1
    assert len(_pledges(db, ev.id)) == 1


def test_conflict_repeat_and_success_look_identical(client, factory, db):
    """Quien envía no puede averiguar si una cédula existe, si es de otra clase de cuenta o si ya firmó: misma respuesta y nada guardado."""
    ev, path, _ = _setup(client, factory)
    factory.staff("admin", "9998887", password=PASSWORD)                                           # una cédula que es OTRO tipo de cuenta
    ok = _send(client, path, _values(), sid="a")
    repeat = _send(client, path, _values(), sid="b")                                               # ya firmó
    conflict = _send(client, path, _values(ced="9998887"), sid="c")
    fresh = _send(client, path, _values(ced="7654321"), sid="d")
    for r in (ok, repeat, conflict, fresh):
        assert r.status_code == 200 and r.json() == ok.json()
    assert len(_pledges(db, ev.id)) == 2                                                           # solo las dos válidas
    adm = _staff(db, "9998887")
    assert adm.role == "admin"                                                                     # la cuenta ajena no se tocó
    from app.models import EventStaffAuthorization
    assert db.query(EventStaffAuthorization).filter_by(event_id=ev.id, staff_user_id=adm.id).first() is None


def test_signature_must_be_a_real_drawn_png(client, factory, db):
    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values(), sig=_png(blank=True)).status_code == 422
    assert _send(client, path, _values(), sig=b"no soy un png").status_code == 422
    assert _send(client, path, _values(), sig=_png() + b"\0" * (200 * 1024)).status_code == 422     # pasa de 200 KiB
    assert _pledges(db, ev.id) == []


def test_validation_errors(client, factory, db):
    ev, path, _ = _setup(client, factory)
    r = _send(client, path, _values(p_id="12"))
    assert r.status_code == 422 and "p_id" in r.json()["errors"]
    r = _send(client, path, _values(p_name="<script>x</script>"))
    assert r.status_code == 422 and "p_name" in r.json()["errors"]
    r = _send(client, path, _values(p_decl="false"))
    assert r.status_code == 422 and "p_decl" in r.json()["errors"]
    assert _pledges(db, ev.id) == [] and _staff(db, "12") is None


# ----------------------------------------------------------------------------------------------------- datos sensibles
def test_sensitive_answers_are_encrypted_and_kept_out_of_data_json(client, factory, db, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("FACE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    row = db.execute(text("SELECT data_json, sensitive_json FROM form_submissions WHERE event_id = :e"), {"e": ev.id}).one()
    assert row.sensitive_json.startswith("enc1:") and "María" not in row.sensitive_json           # cifrado en reposo
    assert "María" not in row.data_json and "3009876543" not in row.data_json and "p_q_med" not in row.data_json
    assert "Juan" in row.data_json                                                                # lo no sensible sí queda en el envío


def test_health_detail_is_audited_and_never_for_the_commercial(client, factory, db):
    from app.models import AuditAction

    ev, path, coord = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    pid = _pledges(db, ev.id)[0].id
    url = f"/api/events/{ev.id}/pledge/{pid}/health"
    comm = factory.staff("comercial", "com1")
    ev.commercial_staff_id = comm.id
    db.commit()
    login(client, "com1")
    assert client.get(url).status_code == 403 and client.get(f"/api/events/{ev.id}/pledge").status_code == 403
    assert client.get(f"/api/events/{ev.id}/pledge/state").status_code == 403 and client.get(f"/api/events/{ev.id}/pledge/{pid}/document").status_code == 403
    client.post("/logout")
    factory.staff("digitador", "dig_x"); factory.authorize(ev, _staff(db, "dig_x"))
    login(client, "dig_x")
    assert client.get(url).status_code == 403
    client.post("/logout")
    login(client, "coord1")
    r = client.get(url)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    labels = {i["label"]: i["value"] for i in r.json()["items"]}
    assert "María Pérez" in labels.values() and "Sí" in labels.values()
    db.expire_all()
    a = db.query(AuditAction).filter(AuditAction.action == "pledge_health_view").one()
    assert a.actor_id == coord.id and "María" not in (a.detail or "") and "María" not in (a.entity_name or "")      # quién y cuándo, sin datos
    client.post("/logout")
    factory.staff("admin", "adm1")
    login(client, "adm1")
    assert client.get(url).status_code == 200


def test_state_flags_alerts_without_health_details(client, factory, db):
    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values(p_q_contract="No", p_q_attend="No")).status_code == 200      # respuestas críticas: no bloquean, avisan
    login(client, "coord1")
    r = client.get(f"/api/events/{ev.id}/pledge/state")
    [acc] = r.json()["accounts"]
    assert acc["signed"] and acc["blocked"] is False and acc["attendance_confirmed"] is False and acc["understands_terms"] is False and acc["has_health_info"] is True
    assert "María" not in r.text and "p_q_med" not in r.text                                       # ningún detalle sensible en el listado


def test_signed_document_has_no_sensitive_data(client, factory, db):
    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    pid = _pledges(db, ev.id)[0].id
    login(client, "coord1")
    r = client.get(f"/api/events/{ev.id}/pledge/{pid}/document")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert CED in r.text and "Juan" in r.text and "data:image/png;base64," in r.text and _pledges(db, ev.id)[0].content_hash in r.text
    assert "María" not in r.text and "3009876543" not in r.text                                    # contacto de emergencia y salud nunca van en el documento


def test_pledge_form_is_hidden_from_the_normal_forms_api(client, factory, db):
    ev, path, _ = _setup(client, factory)
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/forms").json() == []
    from app.models import WebForm
    fid = db.query(WebForm).filter_by(event_id=ev.id).one().id
    assert client.get(f"/api/events/{ev.id}/forms/{fid}").status_code == 404


# ----------------------------------------------------------------------------------------------------- enlace
def test_link_lifecycle_regenerate_and_revoke(client, factory, db):
    ev, path, _ = _setup(client, factory)
    assert client.get(f"{path}/state").status_code == 200
    login(client, "coord1")
    new = urlsplit(client.post(f"/api/events/{ev.id}/pledge/link", json={"regenerate": True}).json()["link"]).path
    assert new != path and re.fullmatch(r"/f/\d+/c[a-z0-9]{24}", new)                              # 144 bits, no adivinable
    client.post("/logout")
    assert client.get(f"{path}/state").status_code == 404 and client.get(f"{new}/state").status_code == 200
    login(client, "coord1")
    r = client.delete(f"/api/events/{ev.id}/pledge/link")
    assert r.status_code == 200 and r.json()["link"] is None
    client.post("/logout")
    assert client.get(f"{new}/state").status_code == 404


def test_link_is_valid_until_the_event_ends(client, factory, db):
    ev, path, _ = _setup(client, factory)
    ev.status = "finalizado"
    db.commit()
    assert client.get(f"{path}/state").status_code == 404
    r = _send(client, path, _values(), token="x")
    assert r.status_code in (403, 404, 409)
    assert _pledges(db, ev.id) == []
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/pledge/link").status_code == 400                     # tampoco se puede publicar uno nuevo


def test_not_publishable_without_approved_text(client, factory, db, monkeypatch):
    from app import pledge, pledge_texts

    assert pledge_texts.APPROVED is True and "BORRADOR" not in pledge_texts.SENSITIVE_AUTH_TEXT     # 25-nov-2026: la auditora aprobó el texto (Juan David)
    monkeypatch.setattr(pledge_texts, "APPROVED", False)                                           # el mecanismo de bloqueo sigue probado por si cambia el texto
    ev, path, _ = _setup(client, factory)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("PLEDGE_ALLOW_DRAFT_TEXT", raising=False)
    monkeypatch.delenv("DEPLOY_ENV", raising=False)
    assert pledge.text_available() is False
    r = client.get(f"{path}/state")
    assert r.status_code != 200 or r.json().get("stage") != "form"                                # «no disponible»: no muestra el formulario
    assert _send(client, path, _values(), token="x").status_code in (403, 404, 409)
    assert _pledges(db, ev.id) == []
    monkeypatch.setenv("PLEDGE_REQUIRE_SENSITIVE_AUTH", "0")                                       # sin datos sensibles no hace falta el texto de la auditora
    assert pledge.text_available() is True and "p_q_med" not in pledge.build_design(None, ev)["fields"]
    monkeypatch.setenv("PLEDGE_REQUIRE_SENSITIVE_AUTH", "1")
    monkeypatch.setenv("PLEDGE_ALLOW_DRAFT_TEXT", "1")
    assert pledge.text_available() is True
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    monkeypatch.delenv("PLEDGE_ALLOW_DRAFT_TEXT")
    assert pledge.text_available() is True


def test_rate_limit_per_link_and_ip(client, factory, db, monkeypatch):
    from app import pledge

    ev, path, _ = _setup(client, factory)
    monkeypatch.setattr(pledge, "LINK_MAX_PER_HOUR", 3)
    codes = [_send(client, path, _values(p_id="55500%02d" % i), sid=f"s{i}").status_code for i in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
    from app.models import WebForm
    form = db.query(WebForm).filter_by(event_id=ev.id).one()
    monkeypatch.setattr(pledge, "LINK_MAX_PER_HOUR", 1000)
    monkeypatch.setattr(pledge, "IP_MAX_PER_10MIN", 1)
    pledge._limiter = type(pledge._limiter)()
    assert pledge.throttle(form, "1.2.3.4") is True and pledge.throttle(form, "1.2.3.4") is False and pledge.throttle(form, "5.6.7.8") is True


# ----------------------------------------------------------------------------------------------------- repetir la firma
def test_resign_only_when_the_coordinator_allows_it(client, factory, db):
    from app.models import AuditAction

    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values(), sid="a").status_code == 200
    assert _send(client, path, _values(p_name="Otro Nombre"), sid="b").status_code == 200           # sin permiso: se ignora, no cambia nada
    first = _pledges(db, ev.id)
    assert len(first) == 1 and _staff(db, CED).full_name == "Juan Pérez"
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/pledge/{first[0].id}/allow-resign").status_code == 200
    client.post("/logout")
    assert _send(client, path, _values(p_q_attend="No"), sid="c").status_code == 200
    rows = _pledges(db, ev.id)
    assert len(rows) == 2 and rows[0].superseded_at is not None and rows[1].superseded_at is None and rows[1].attendance_confirmed is False   # la anterior queda de historial
    actions = [a.action for a in db.query(AuditAction).order_by(AuditAction.id)]
    assert "pledge_resign_allowed" in actions and actions.count("pledge_signed") == 2
    assert all(CED not in (a.detail or "") and CED not in (a.entity_name or "") for a in db.query(AuditAction))     # la auditoría no lleva datos personales


# ----------------------------------------------------------------------------------------------------- Camino B/C: puerta antes de la fila de espera
def test_login_gate_pledge_before_the_waiting_queue(client, factory, db, monkeypatch):
    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "1")
    ev, path, _ = _setup(client, factory)
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    factory.authorize(ev, dig)
    r = login(client, CED, CED)
    assert r.status_code == 303 and r.headers["location"].startswith(path + "?t=")                 # al formulario del compromiso, NO a /ingreso/espera
    link = r.headers["location"]
    tok = link.split("?t=")[1]
    st = client.get(f"{path}/state", params={"t": tok}).json()
    assert st.get("stage") == "form" and st["prefill"]["p_id"] == CED and "p_id" in st["readonly"]   # ya identificada: no vuelve a pedir la cédula
    db.expire_all()
    assert _staff(db, CED).login_req_status is None                                                # todavía no hay solicitud de ingreso
    r = _send(client, path, _values(), token=tok)
    assert r.status_code == 200 and r.json()["redirect"] == "/ingreso/espera"                      # firmado: ahora sí, a la fila de espera
    assert _staff(db, CED).login_req_status == "pending" or _staff(db, CED).login_req_status is not None
    [p] = _pledges(db, ev.id)
    assert p.source == "session" and p.staff_id == dig.id


def test_session_flow_cannot_sign_for_someone_else(client, factory, db, monkeypatch):
    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "1")
    ev, path, _ = _setup(client, factory)
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    factory.authorize(ev, dig)
    tok = login(client, CED, CED).headers["location"].split("?t=")[1]
    r = _send(client, path, _values(ced="7654321"), token=tok)                                     # intenta firmar con otra cédula
    assert r.status_code in (200, 403)
    assert _pledges(db, ev.id) == [] and _staff(db, "7654321") is None


def test_approval_is_blocked_without_the_pledge(client, factory, db, monkeypatch):
    from app import login_control

    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "1")
    ev, path, coord = _setup(client, factory)
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    factory.authorize(ev, dig)
    dig.login_req_hash, dig.login_req_at, dig.login_req_status = "h" * 64, utcnow(), login_control.PENDING       # solicitud pendiente pese a todo
    db.commit()
    login(client, "coord1")
    url = f"/api/events/{ev.id}/staff-users/{dig.id}/login-request"
    r = client.post(url, json={"allow": True})
    assert r.status_code == 409 and "compromiso" in r.json()["detail"]                             # el servidor lo niega aunque la interfaz lo ofreciera
    assert client.post(url, json={"allow": False}).status_code == 200                              # negar sí se puede
    client.post("/logout")
    assert _send(client, path, _values(), sid="z").status_code == 200
    db.expire_all()
    dig.login_req_hash, dig.login_req_at, dig.login_req_status = "h" * 64, utcnow(), login_control.PENDING
    db.commit()
    login(client, "coord1")
    assert client.post(url, json={"allow": True}).status_code == 200                               # firmado: ya se puede autorizar


def test_session_flow_accepts_a_short_document_but_the_public_link_does_not():
    from types import SimpleNamespace

    from app import pledge

    form = SimpleNamespace()
    clean = {pledge.FID_ID: "1234"}
    assert pledge.FID_ID not in pledge.extra_errors(form, clean, {"pc": 7})                        # cuenta ya creada a mano o por Excel: se acepta
    assert pledge.FID_ID in pledge.extra_errors(form, clean, {})                                   # enlace público: mínimo 5
    assert pledge.FID_ID in pledge.extra_errors(form, {pledge.FID_ID: "12"}, {"pc": 7})            # nunca menos de 3 (el mínimo de un usuario)


def test_deleting_temporary_users_also_deletes_signed_accounts_and_keeps_the_evidence(client, factory, db):
    from app.models import EventStaffPledge, StaffUser

    ev, path, coord = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    db.expire_all()
    acct = db.query(StaffUser).filter_by(username=CED).one()
    acct_id = acct.id
    assert _pledges(db, ev.id)
    login(client, "coord1")
    r = client.post(f"/api/events/{ev.id}/staff-users/purge-temporary")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1 and r.json()["kept_archived"] == 0                              # firmó y aun así se elimina
    db.expire_all()
    assert db.get(StaffUser, acct_id) is None
    rows = db.query(EventStaffPledge).filter_by(event_id=ev.id).all()
    assert len(rows) == 1 and rows[0].staff_id is None and rows[0].content_hash                    # la evidencia queda en el evento, sin la cuenta


def test_pledge_not_required_does_not_change_login(client, factory, db, monkeypatch):
    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "1")
    coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=coord)                                            # pledge_enabled sigue en falso
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    factory.authorize(ev, dig)
    r = login(client, CED, CED)
    assert r.status_code == 303 and r.headers["location"] == "/ingreso/espera"


def test_new_events_require_the_pledge_by_default_with_the_link_ready(client, factory, db):
    from tests.test_coordinador_crea_eventos import _payload

    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    eid = client.post("/api/events", json=_payload(coord.id)).json()["id"]
    state = client.get(f"/api/events/{eid}/pledge").json()
    assert state["enabled"] is True and state["link_active"] is True and state["link"]        # exigido por defecto y con el enlace ya publicado
    assert client.put(f"/api/events/{eid}/pledge/enabled", json={"enabled": False}).json()["enabled"] is False          # se puede apagar


def test_pledge_does_not_lock_the_event_when_the_text_is_not_approved(client, factory, db, monkeypatch):
    from app import pledge

    coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=coord)
    ev.pledge_enabled = True
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)
    factory.authorize(ev, dig)
    db.commit()
    assert pledge.missing_for_login(db, dig) is None                                               # sin formulario publicado no hay nada que firmar
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/pledge/link").status_code == 200
    db.expire_all()
    assert pledge.missing_for_login(db, dig).id == ev.id                                           # con el enlace publicado sí se exige
    monkeypatch.setattr(pledge, "text_available", lambda: False)
    assert pledge.missing_for_login(db, dig) is None                                               # texto aún no aprobado: no se bloquea el ingreso


# ----------------------------------------------------------------------------------------------------- retención
def test_sensitive_purge_30_days_after_the_event(client, factory, db):
    from app import formsvc
    from app.models import FormSubmission

    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    now = utcnow()
    assert formsvc.purge_sensitive(db, now=now) == 0                                               # evento en proceso: nada
    ev.status = "finalizado"
    db.commit()
    ev.finalized_at = now - timedelta(days=29)
    db.commit()
    assert formsvc.purge_sensitive(db, now=now) == 0
    ev.finalized_at = now - timedelta(days=31)
    db.commit()
    assert formsvc.purge_sensitive(db, now=now) == 1 and formsvc.purge_sensitive(db, now=now) == 0   # idempotente
    db.expire_all()
    sub = db.query(FormSubmission).filter_by(event_id=ev.id).one()
    assert sub.sensitive_json is None and "Juan" in sub.data_json                                  # lo sensible se borra; el resto de la evidencia queda
    [p] = _pledges(db, ev.id)
    assert p.health_purged_at is not None and p.content_hash and p.doc_key
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/pledge/{p.id}/health").status_code in (404, 410)


def test_sensitive_purge_hard_cap_180_days(client, factory, db):
    from app import formsvc
    from app.models import FormSubmission

    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    sub = db.query(FormSubmission).filter_by(event_id=ev.id).one()
    sub.created_at = utcnow() - timedelta(days=181)
    db.commit()
    assert formsvc.purge_sensitive(db) == 1


# ----------------------------------------------------------------------------------------------------- piezas puras
def test_signature_problem_unit():
    from app import pledge

    assert pledge.signature_problem(_png()) is None
    assert pledge.signature_problem(_png(blank=True)) is not None
    assert pledge.signature_problem(_png(size=(50, 20))) is not None
    assert pledge.signature_problem(b"GIF89a....") is not None
    assert pledge.signature_problem(b"\x89PNG\r\n\x1a\n" + b"0" * 10) is not None


def test_design_is_a_valid_engine_design_with_literal_text():
    from app import formlib, pledge, pledge_texts as T
    from app.models import Event

    ev = Event(name="Feria", tenant_id="acme")
    d = pledge.build_design(None, ev)
    assert formlib.sanitize_design(d, set()) == d                                                  # idempotente: lo valida el MISMO sanitizador del motor
    assert d["fields"]["p_sig"]["capture"] == "signature" and d["fields"]["p_sig"]["accept"] == ["png"]
    assert all(d["fields"][f].get("sensitive") for f in pledge.SENSITIVE_FIDS)
    assert not any(d["fields"][f].get("sensitive") for f in (pledge.FID_ID, pledge.FID_NAME, pledge.FID_PHONE, pledge.FID_CONTRACT, pledge.FID_ATTEND))
    blob = json.dumps(d, ensure_ascii=False)
    assert T.DECLARATION in d["fields"]["p_decl"]["label"] and T.Q_CONTRACT in blob and T.Q_ATTENDANCE in blob
    assert pledge.content_hash(d, {"p_id": "1"}, 1, "1", "a" * 64) != pledge.content_hash(d, {"p_id": "2"}, 1, "1", "a" * 64)


def test_mask_url_hides_the_pledge_link_secret():
    from app import obs

    out = obs.mask_url("/f/12/cabcdefghijklmnopqrstuvwx/state?t=zzz")
    assert "cabcdefghijklmnopqrstuvwx" not in out and "zzz" not in out


def test_front_end_pieces_follow_the_rules():
    for rel in ("static/js/usuarios-compromiso.js", "static/js/form-render.js", "static/js/pledge-doc.js"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"\bonclick\s*=", src) and not re.search(r"(?<![.\w])(alert|confirm|prompt)\(", src), rel
    tpl = (ROOT / "templates/kiosk_usuarios.html").read_text(encoding="utf-8")
    assert "usuarios-compromiso.js" in tpl and "gw-pledge.css" in tpl and "url_for('static'" in tpl
    css = (ROOT / "static/css/gw-pledge.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)                                              # solo tokens --gw-*


def test_recreated_account_can_sign_after_its_old_evidence_is_kept(client, factory, db):
    """Bug 9-nov: la firma de una cuenta eliminada se conserva con la cédula; al crear de nuevo la cuenta, firmar daba «Ya estás inscrito»."""
    from app.models import EventStaffPledge

    ev, path, coord = _setup(client, factory)
    assert _send(client, path, _values()).status_code == 200
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/staff-users/purge-temporary").json()["deleted"] == 1
    client.post("/logout")
    dig = factory.staff("digitador", CED, password=CED, tenant_id=ev.tenant_id)           # misma cédula, cuenta nueva y sin firma
    factory.authorize(ev, dig)
    r = _send(client, path, _values(), sid="otra")
    assert r.status_code == 200 and not r.json().get("already"), r.text
    db.expire_all()
    rows = db.query(EventStaffPledge).filter_by(event_id=ev.id).order_by(EventStaffPledge.id).all()
    assert len(rows) == 2 and rows[0].staff_id is None and rows[1].staff_id == dig.id             # la evidencia vieja sigue, la nueva firma es de la cuenta nueva


def test_pledge_keeps_which_health_questions_were_yes_for_the_alert(client, factory, db):
    ev, path, _ = _setup(client, factory)
    assert _send(client, path, _values(p_q_med="Sí", p_q_drug="No", p_q_support="Sí", p_q_support_c="Familiar enfermo", p_q_attend="No")).status_code == 200
    [p] = _pledges(db, ev.id)
    assert p.health_flags == "med,support" and p.has_health_info and p.attendance_confirmed is False
    login(client, "coord1")
    acct = client.get(f"/api/events/{ev.id}/pledge/state").json()["accounts"][0]
    assert acct["health_flags"] == ["med", "support"] and acct["attendance_confirmed"] is False


def test_which_field_appears_and_is_required_only_when_the_answer_is_yes(client, factory, db):
    """25-nov-2026: en cada pregunta de salud, «¿Cuál?» solo aparece (y es obligatorio) si respondió Sí; se guarda cifrado con lo sensible."""
    from app import formlib, pledge

    ev, path, _ = _setup(client, factory)
    design = pledge.build_design(None, ev)
    for q, c in (("p_q_med", "p_q_med_c"), ("p_q_drug", "p_q_drug_c"), ("p_q_support", "p_q_support_c")):
        f = design["fields"][c]
        assert f["required"] and f["sensitive"] and f["show_if"]["field"] == q and f["show_if"]["value"] == "Sí"
        assert c in pledge.SENSITIVE_FIDS
        no = {q: "No"}
        yes = {q: "Sí"}
        assert c not in formlib.visible_ids(design, no)
        assert c in formlib.visible_ids(design, yes)
    r = _send(client, path, _values(p_q_med="Sí", p_q_med_c="", p_q_drug="No", p_q_support="No"))
    assert r.status_code == 422 and "p_q_med_c" in r.json()["errors"]                          # Sí sin escribir cuál: se pide
    assert _send(client, path, _values(p_q_med="No", p_q_med_c="", p_q_drug="No", p_q_support="No")).status_code == 200      # No: no se pide


def test_excel_exports_answers_and_staff_list(client, factory, db):
    """27-nov-2026: «Respuestas del compromiso» (con lo sensible, solo coordinador/admin, auditado sin datos) y «Lista de usuarios» con el formato de Golden."""
    from openpyxl import load_workbook

    from app.models import AuditAction

    ev, path, coord = _setup(client, factory)
    assert _send(client, path, _values(p_q_contract="No")).status_code == 200
    factory.staff("digitador", "7654321")
    factory.authorize(ev, _staff(db, "7654321"))                                    # asignado sin firmar
    comm = factory.staff("comercial", "com2")
    ev.commercial_staff_id = comm.id
    db.commit()
    url = f"/api/events/{ev.id}/pledge/export.xlsx"
    login(client, "com2")
    assert client.get(url).status_code == 403                                     # la comercial pura nunca ve lo sensible
    client.post("/logout")
    login(client, "coord1")
    r = client.get(url)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store" and "Respuestas del compromiso" in r.headers["content-disposition"].replace("%20", " ")
    ws = load_workbook(io.BytesIO(r.content)).active
    head = [ws.cell(5, i).value for i in range(1, ws.max_column + 1)]
    rows = [[ws.cell(r_, i).value for i in range(1, ws.max_column + 1)] for r_ in range(6, ws.max_row + 1)]
    byname = {row[2]: dict(zip(head, row)) for row in rows}
    j = byname["Juan Pérez"]
    assert j["Cédula"] == int(CED) and j["Nombre del familiar"] == "María Pérez" and j["Teléfono del familiar"] == "3009876543"
    assert j["¿Cuál? (condición médica)"] == "Asma" and "condición médica" in j["Alertas"] and "contrato" in j["Alertas"] and j["Estado"] == "Firmado"
    pending = [row for row in rows if row[1] == 7654321]
    assert pending and dict(zip(head, pending[0]))["Estado"] == "Sin firmar"
    db.expire_all()
    a = db.query(AuditAction).filter(AuditAction.action == "pledge_export").one()
    assert a.actor_id == coord.id and "María" not in (a.detail or "") and "Asma" not in (a.detail or "")
    r = client.get(f"/api/events/{ev.id}/staff-users/export.xlsx")
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    ids = [ws.cell(i, 3).value for i in range(4, ws.max_row + 1)]
    assert int(CED) in ids and 7654321 in ids and ws["B2"].value and ws["A3"].value.startswith(f"[{ev.event_code}]")
    assert "María" not in str([c.value for row in ws.iter_rows() for c in row])          # el listado no lleva nada sensible


def test_public_link_prefills_masked_by_cedula_and_restores_real_values(client, factory, db):
    """27-nov-2026: quien ya firmó en otro evento escribe solo su cédula; el navegador recibe datos ocultos en parte y, si los deja así, el servidor guarda los reales."""
    from app import pledge

    ev1, path1, _ = _setup(client, factory)
    assert _send(client, path1, _values()).status_code == 200                           # primera firma: Juan Pérez / María Pérez
    coord2 = factory.staff("coordinador", "coord2")
    ev2 = factory.event("en_proceso", coordinator=coord2)
    login(client, "coord2")
    path2 = urlsplit(client.post(f"/api/events/{ev2.id}/pledge/link").json()["link"]).path
    client.post("/logout")
    tok = client.get(f"{path2}/state").json()["token"]
    assert client.get(f"{path2}/state").json()["pledge_prefill"] is True
    r = client.post(f"{path2}/pledge-prefill", json={"id": "999999999", "t": tok})
    assert r.status_code == 200 and r.json()["found"] is False and r.json()["values"] == {}          # cédula desconocida
    r = client.post(f"{path2}/pledge-prefill", json={"id": CED, "t": tok})
    body = r.json()
    assert r.status_code == 200 and body["found"] is True
    shown = body["values"]
    assert "*" in shown["p_name"] and "Juan" not in r.text and "María" not in r.text       # nada real sale al navegador
    assert shown["p_em_name"] != "María Pérez" and body["token"] != tok
    values = _values(p_name=shown["p_name"], p_phone=shown["p_phone"], p_em_name=shown["p_em_name"], p_em_phone=shown["p_em_phone"], p_q_med="No")
    # con un token SIN la cédula atada, lo enmascarado no se acepta
    assert _send(client, path2, values, token=tok, sid="s2").status_code == 422
    assert _send(client, path2, values, token=body["token"], sid="s3").status_code == 200
    db.expire_all()
    real = pledge.previous_by_cedula(db, CED)
    assert real["p_name"] == "Juan Pérez" and real["p_em_name"] == "María Pérez" and "*" not in real["p_phone"]      # se guardaron los reales
    assert pledge.previous_by_cedula(db, "123") == {}
