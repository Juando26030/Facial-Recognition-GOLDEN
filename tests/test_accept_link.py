"""B2a/B2e/B2c/B2b: enlace personal de autorización, fecha de nacimiento antes de la cámara, fuente de la foto (selfie o cliente) y correo de constancia."""
import io
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app import acceptlink, consent, consent_receipt, legal_texts
from app.models import AuditConsentLog, EventAttendee, User, WebAcceptance
from app.storage import get_storage, photo_key
from tests.conftest import login


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


def _vec(seed):
    return np.random.default_rng(seed).normal(0, 0.1, 128).round(6).tolist()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "ejemplo.test",
                 "PUBLIC_BASE_URL": "https://app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def engine(monkeypatch):
    from app.biometrics import BiometricEngine
    state = type("S", (), {"face": _vec(1)})()
    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(lambda img, is_registration=False, **kw: state.face))
    return state


def _setup(factory, db, uid="1001", trusted=False, email="ana@example.com", birth=date(1990, 4, 2), **event_kw):
    event_kw.setdefault("facial_enabled", True)
    event_kw.setdefault("aceptar_enabled", True)
    ev = factory.event("en_proceso", start_date=date(2026, 10, 29), **event_kw)
    u = factory.person(ev, uid, "Ana", "Mora")
    u.email, u.birth_date = email, birth
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=uid).one()
    token = acceptlink.issue(db, att, trusted)
    db.commit()
    return ev, u, token


def _accept(client, ev, token, birth="1990-04-02", selfie=True, decision="accept", channel="web", cedula=""):
    t = legal_texts.render(ev, web=True)
    data = {"birth_date": birth, "decision": decision, "text_hash": t["hash"], "channel": channel}
    if token:
        data["token"] = token
    else:
        data["cedula"] = cedula
    return client.post(f"/api/aceptar/{ev.event_code}", data=data, files={"file": ("s.jpg", _png(), "image/jpeg")} if selfie else None)


# ------------------------------------------------------------------------------------------------------------------------------------ B2a: la página y el enlace
def test_the_personal_page_has_no_document_field_and_a_wrong_token_or_event_is_a_404(client, factory, db):
    ev, _u, token = _setup(factory, db)
    page = client.get(f"/aceptar/{ev.event_code}/{token}")
    assert page.status_code == 200 and 'id="cedula"' not in page.text and 'id="birth"' in page.text and f'"{token}"' in page.text.replace("&#34;", '"')
    assert 'id="cedula"' in client.get(f"/aceptar/{ev.event_code}").text                                  # el portal general sí pide el documento
    bad = client.get(f"/aceptar/{ev.event_code}/nope")
    assert bad.status_code == 404 and "no es válido" in bad.text
    other = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True)
    assert client.get(f"/aceptar/{other.event_code}/{token}").status_code == 404                           # el enlace de un evento no vale en otro
    off = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=False)
    assert client.get(f"/aceptar/{off.event_code}/{token}").status_code == 404
    locked = factory.event("en_proceso", facial_enabled=False, aceptar_enabled=True, biometrics_locked=True)
    assert client.get(f"/aceptar/{locked.event_code}/{token}").status_code == 404


def test_the_token_is_unique_per_person_stable_and_regenerating_revokes_the_old_one(factory, db):
    ev, u, token = _setup(factory, db)
    other = factory.person(ev, "2002", "Beto", "Paz")
    att1 = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    att2 = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2002").one()
    assert acceptlink.issue(db, att1) == token and acceptlink.issue(db, att2) != token                      # estable por persona y distinto entre personas
    assert acceptlink.url(ev, token) == f"https://app.ejemplo.test/aceptar/{ev.event_code}/{token}"
    new = acceptlink.regenerate(db, att1)
    db.commit()
    assert new != token and other is not None


def test_trusted_only_goes_up(factory, db):
    ev, _u, _t = _setup(factory, db)
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    acceptlink.issue(db, att, trusted=True)
    acceptlink.issue(db, att, trusted=False)
    assert att.accept_trusted is True


# ------------------------------------------------------------------------------------------------------------------------------------ B2e: la fecha antes de la cámara
def test_birth_date_is_checked_before_the_text_and_the_camera_and_a_minor_never_gets_them(client, factory, db, engine):
    ev, u, token = _setup(factory, db, birth=None)
    url = f"/api/aceptar/{ev.event_code}/check"
    assert client.post(url, data={"token": token}).status_code == 400                                       # sin fecha no se avanza
    ok = client.post(url, data={"token": token, "birth_date": "1990-04-02"}).json()
    assert ok == {"status": "ok", "selfie": True}
    minor_birth = date(date.today().year - 12, 1, 1).isoformat()
    m = client.post(url, data={"token": token, "birth_date": minor_birth}).json()
    assert m["status"] == "minor" and "No puedes usar el reconocimiento facial" in m["message"]
    db.expire_all()
    u = db.query(User).filter_by(id="1001").one()
    assert u.is_biometric_enabled is False and u.face_encoding is None and not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    sub = _accept(client, ev, token, birth=minor_birth)
    assert sub.json()["status"] == "minor" and db.query(AuditConsentLog).filter_by(user_id="1001").count() == 0     # nada registrado


def test_a_known_birth_date_must_match_and_the_answer_does_not_reveal_who_is_enrolled(client, factory, db):
    ev, _u, token = _setup(factory, db)
    r = client.post(f"/api/aceptar/{ev.event_code}/check", data={"token": token, "birth_date": "1991-01-01"})
    assert r.status_code == 404 and "No encontramos tu inscripción" in r.json()["detail"]
    ghost = client.post(f"/api/aceptar/{ev.event_code}/check", data={"cedula": "9999", "birth_date": "1990-04-02"})
    assert ghost.status_code == 404 and ghost.json()["detail"] == r.json()["detail"]


# ------------------------------------------------------------------------------------------------------------------------------------ verificación
def test_a_trusted_link_acceptance_is_born_verified_and_enters_the_matrix(client, factory, db, engine):
    ev, _u, token = _setup(factory, db, trusted=True)
    r = _accept(client, ev, token)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["verified"] is True
    db.expire_all()
    wa = db.get(WebAcceptance, (ev.tenant_id, "1001", ev.id))
    assert wa.verified_at is not None and wa.verified_via == "link"
    assert "1001" in consent.accepted_user_ids(db, ev.tenant_id, ev.id)                                    # entra a la matriz sin que el personal confirme
    assert db.query(User).filter_by(id="1001").one().face_encoding                                         # el vector se calculó (tarea inline)
    log = db.query(AuditConsentLog).filter_by(user_id="1001").one()
    assert log.reason == "consent" and log.ip_or_device_id == "web-link"


def test_an_untrusted_link_from_an_open_form_stays_pending_verification(client, factory, db, engine):
    ev, _u, token = _setup(factory, db, trusted=False)
    r = _accept(client, ev, token)
    assert r.json()["verified"] is False
    db.expire_all()
    wa = db.get(WebAcceptance, (ev.tenant_id, "1001", ev.id))
    assert wa.verified_at is None and wa.verified_via is None
    assert "1001" not in consent.accepted_user_ids(db, ev.tenant_id, ev.id)                                # "por verificar": todavía no se reconoce


def test_the_document_flow_never_verifies_even_if_the_person_has_a_trusted_link(client, factory, db, engine):
    ev, _u, _token = _setup(factory, db, trusted=True)
    r = _accept(client, ev, "", cedula="1001")
    assert r.json()["verified"] is False and db.get(WebAcceptance, (ev.tenant_id, "1001", ev.id)).verified_at is None


# ------------------------------------------------------------------------------------------------------------------------------------ B2c: fuente de la foto
def test_source_b_needs_the_selfie_and_source_a_does_not(client, factory, db, engine):
    ev, _u, token = _setup(factory, db, trusted=True)
    assert _accept(client, ev, token, selfie=False).status_code == 400 and db.query(AuditConsentLog).count() == 0
    assert client.get(f"/aceptar/{ev.event_code}/{token}").text.count("const needSelfie = true") == 1
    evA, _uA, tokenA = _setup(factory, db, uid="3003", trusted=True, client_photos_before=True)
    assert client.post(f"/api/aceptar/{evA.event_code}/check", data={"token": tokenA, "birth_date": "1990-04-02"}).json()["selfie"] is False
    assert "const needSelfie = false" in client.get(f"/aceptar/{evA.event_code}/{tokenA}").text
    get_storage().put(photo_key(evA.tenant_id, "3003"), b"foto-del-cliente")                                # el cliente ya la entregó (carga masiva)
    r = _accept(client, evA, tokenA, selfie=False)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert db.query(AuditConsentLog).filter_by(user_id="3003", reason="consent").count() == 1             # aceptó sin selfie


def test_source_a_without_a_client_photo_accepts_and_leaves_the_capture_for_the_door(client, factory, db, engine):
    ev, _u, token = _setup(factory, db, trusted=True, client_photos_before=True)
    r = _accept(client, ev, token, selfie=False)
    assert r.status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().face_encoding is None and not get_storage().exists(photo_key(ev.tenant_id, "1001"))


def test_the_selfie_reference_is_released_in_the_page_after_a_successful_send(client, factory, db):
    ev, _u, token = _setup(factory, db)
    html = client.get(f"/aceptar/{ev.event_code}/{token}").text
    assert "$('selfie').value = ''" in html and "fd.delete('file')" in html and "id=\"step3\" hidden" in html          # la cámara/selfie aparece solo tras aceptar y no queda colgada


# ------------------------------------------------------------------------------------------------------------------------------------ canales
def test_every_channel_leaves_its_label_and_the_receipt_uses_the_four_fixed_phrases(client, factory, db, engine, outbox):
    ev, _u, token = _setup(factory, db, trusted=True)
    assert 'channel = "qr"' in client.get(f"/aceptar/{ev.event_code}?c=qr").text and 'channel = "web"' in client.get(f"/aceptar/{ev.event_code}").text
    assert 'channel = "link"' in client.get(f"/aceptar/{ev.event_code}/{token}").text
    for uid, channel, label in (("1001", "link", "web-link"), ("2002", "qr", "web-qr"), ("3003", "web", "web-portal")):
        if uid != "1001":
            factory.person(ev, uid, "Pers", uid)
            u = db.query(User).filter_by(id=uid).one()
            u.email, u.birth_date = f"p{uid}@example.com", date(1990, 4, 2)
            db.commit()
        r = _accept(client, ev, token if channel == "link" else "", cedula=uid, channel=channel)
        assert r.status_code == 200, r.text
        assert db.query(AuditConsentLog).filter_by(user_id=uid).one().ip_or_device_id == label
    phrases = {m["to"]: m["body"] for m in outbox if "autorización para entrar" in m["subject"]}
    assert "Canal de autorización: Enlace único enviado a este correo" in phrases["ana@example.com"]
    assert "Canal de autorización: Escaneo de código QR en la entrada" in phrases["p2002@example.com"]
    assert "Canal de autorización: Portal web del evento" in phrases["p3003@example.com"]
    assert consent_receipt.channel_of("tablet-1") == "door" and consent_receipt.channel_of("staff:7") == "door"
    assert set(consent_receipt.CHANNELS.values()) == {"Enlace único enviado a este correo", "Portal web del evento", "Escaneo de código QR en la entrada", "En la puerta, con el personal de acreditación"}


# ------------------------------------------------------------------------------------------------------------------------------------ B2b: la constancia
def _entry(ev, version="v1.1_web", hash_=None, ts=None):
    return SimpleNamespace(consent_timestamp_utc=ts or datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc), consent_version=version, legal_text_hash=hash_ or legal_texts.render(ev, web=True)["hash"],
                           reason="consent", accepted_biometric=True)


def test_the_receipt_follows_the_approved_structure_with_the_literal_text_as_an_annex_at_the_end(factory, db):
    ev, u, _t = _setup(factory, db, digital_badge_enabled=True)
    mail = consent_receipt.render(ev, u, _entry(ev), "link", "https://app.ejemplo.test/b/TOKEN")
    text, html = mail["text"], mail["html"]
    assert mail["subject"] == f"Tu autorización para entrar con reconocimiento facial — {ev.name}"
    for fragment in ("Hola Ana:", f"Recibimos tu autorización para usar tu rostro como método de ingreso rápido a {ev.name}.", "🎫 Tu escarapela virtual: https://app.ejemplo.test/b/TOKEN",
                     "Detalles de tu autorización (Constancia de Habeas Data)", "- Titular: Ana Mora, documento terminado en ***001", f"- Evento: {ev.name} - 29/10/2026",
                     "- Canal de autorización: Enlace único enviado a este correo", "- Fecha y hora: 09/10/2026 10:30 (Hora de Colombia)",
                     "- Responsable del tratamiento: Golden Eventos y Logística S.A.S., NIT 901.542.833-2", "7 días después de finalizado el evento", "Este correo no incluye tu foto por seguridad.",
                     "¿Cambiaste de opinión?", "soporteit@goldenlogisticas.com", "Revocarlo no afecta tu acceso", "https://app.ejemplo.test/privacidad"):
        assert fragment in text, fragment
    t = legal_texts.render(ev, web=True)
    short = t["hash"][:12]
    anexo = text.index("Anexo: Texto literal que aprobaste")
    assert text.index("¿Cambiaste de opinión?") < anexo and text.index("Constancia de Habeas Data") < anexo                 # la letra chica va AL FINAL, separada
    assert f"(Versión: v1.1_web | Identificador de seguridad: {short})" in text
    assert t["title"] in text[anexo:] and all(p in text[anexo:] for p in t["body"])                                 # texto literal, sin reescribir, solo dentro del anexo
    assert all(p not in text[:anexo] for p in t["body"])
    assert "<hr" in html and html.index("¿Cambiaste de opinión?") < html.index("Anexo: Texto literal") and "Ana Mora" in html and "attachment" not in html.lower()
    plain = consent_receipt.render(ev, u, _entry(ev), "door", "")
    assert "🎫" not in plain["text"] and "En la puerta, con el personal de acreditación" in plain["text"]       # sin escarapela virtual no se menciona


def test_if_the_text_changed_since_the_acceptance_the_annex_says_so_instead_of_showing_another_text(factory, db):
    ev, u, _t = _setup(factory, db)
    mail = consent_receipt.render(ev, u, _entry(ev, hash_="0" * 64), "web", "")
    assert "ya no es el vigente" in mail["text"] and legal_texts.render(ev, web=True)["body"][0] not in mail["text"]


def test_the_receipt_goes_out_in_the_background_with_the_privacy_mailbox_as_reply_to_and_never_twice(client, factory, db, engine, outbox):
    ev, _u, token = _setup(factory, db, trusted=True)
    assert _accept(client, ev, token).status_code == 200
    mails = [m for m in outbox if "autorización para entrar" in m["subject"]]
    assert len(mails) == 1 and mails[0]["to"] == "ana@example.com" and mails[0]["reply_to"] == "soporteit@goldenlogisticas.com"
    from app import jobs
    entry = db.query(AuditConsentLog).filter_by(user_id="1001").one()
    consent_receipt.enqueue(db, entry.id, ev.tenant_id, ev.id, "1001", "link")                                  # el mismo registro otra vez: no duplica
    db.commit()
    jobs.drain()
    assert len([m for m in outbox if "autorización para entrar" in m["subject"]]) == 1


def test_no_receipt_without_an_email_for_a_third_party_event_or_after_the_person_was_removed(client, factory, db, engine, outbox):
    ev, _u, token = _setup(factory, db, trusted=True, email=None)
    assert _accept(client, ev, token).status_code == 200 and not [m for m in outbox if "autorización para entrar" in m["subject"]]
    tercero = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True, controller_mode="tercero", organizer_name="Org", organizer_nit="1", organizer_privacy_email="o@o.test")
    u = factory.person(tercero, "7007", "Eva", "Paz")
    u.email, u.birth_date = "eva@example.com", date(1990, 4, 2)
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=tercero.id, user_id="7007").one()
    tk = acceptlink.issue(db, att, True)
    db.commit()
    assert _accept(client, tercero, tk).status_code == 200 and not [m for m in outbox if m["to"] == "eva@example.com"]


def test_accepting_at_the_door_also_sends_the_receipt(client, factory, db, engine, outbox):
    factory.staff("digitador", "dig1")
    ev, u, _t = _setup(factory, db)
    login(client, "dig1")
    from app.models import EventStaffAuthorization
    from app.models import StaffUser
    st = db.query(StaffUser).filter_by(username="dig1").one()
    db.add(EventStaffAuthorization(event_id=ev.id, staff_user_id=st.id))
    db.commit()
    t = legal_texts.render(ev)
    body = {"entries": [{"id": "6f1b7a0e-5d1c-4c1e-9d55-2b7c4f3f9a10", "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"], "device": "tablet-1"}]}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).status_code == 200
    mails = [m for m in outbox if "autorización para entrar" in m["subject"]]
    assert len(mails) == 1 and "En la puerta, con el personal de acreditación" in mails[0]["body"]


# ------------------------------------------------------------------------------------------------------------------------------------ envío desde la inscripción y paso guiado
def test_the_form_inscription_sends_an_untrusted_personal_link_once(factory, db, outbox):
    from app import formsvc
    ev, u, _t = _setup(factory, db, accept_link_email=True)
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    att.accept_token, att.accept_trusted = None, False
    db.commit()
    sub = SimpleNamespace(id=1)
    formsvc._send_accept_link(db, ev, sub, "1001")
    db.commit()
    mails = [m for m in outbox if "autoriza el uso de tu rostro" in m["subject"]]
    assert len(mails) == 1 and mails[0]["to"] == "ana@example.com" and "/aceptar/" in mails[0]["body"] and "voluntario" in mails[0]["body"] and mails[0]["reply_to"] == "soporteit@goldenlogisticas.com"
    db.expire_all()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    assert att.accept_token in mails[0]["body"] and att.accept_trusted is False and att.accept_sent_at is not None
    formsvc._send_accept_link(db, ev, sub, "1001")
    assert len([m for m in outbox if "autoriza el uso de tu rostro" in m["subject"]]) == 1                      # una sola vez
    kid = factory.person(ev, "5005", "Nico", "Menor")
    kid.email, kid.birth_date = "n@example.com", date(date.today().year - 10, 1, 1)
    db.commit()
    formsvc._send_accept_link(db, ev, sub, "5005")
    assert not [m for m in outbox if m["to"] == "n@example.com"]                                              # a un menor conocido no se le invita


def test_the_guided_step_stores_the_link_switch_and_explains_the_photo_source(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    url = f"/api/events/{ev.id}/biometric-setup"
    bad = client.put(url, json={"facial_enabled": True, "accept_link_email": True})
    assert bad.status_code == 400 and "necesita la aceptación desde el celular" in bad.json()["detail"]
    ok = client.put(url, json={"facial_enabled": True, "aceptar_enabled": True, "accept_link_email": True, "client_photos_before": False})
    assert ok.status_code == 200 and ok.json()["config"]["accept_link_email"] is True
    door = " ".join(ok.json()["door"])
    assert "selfie" in door and "«por verificar»" in door and "constancia" in door
    a = client.put(url, json={"client_photos_before": True}).json()
    assert "Fuente de la foto: cada persona se toma una selfie" not in " ".join(a["door"]) and "Las fotos que cargues se guardan cifradas" in " ".join(a["door"])
    locked = client.put(url, json={"biometrics_locked": True}).json()["config"]
    assert locked["accept_link_email"] is False and locked["aceptar_enabled"] is False
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert 'id="ccAcceptLink"' in page and 'id="bsSourceSelfie"' in page and 'id="bsPhotos"' in page


def test_the_poster_qr_carries_its_channel(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, aceptar_enabled=True)
    login(client, "coord1")
    assert "qr.addData(aceptarUrl + '?c=qr')" in client.get(f"/kiosk/{ev.id}/parametros").text


def test_the_mailer_passes_reply_to_to_graph_and_smtp(monkeypatch):
    from app import mailer
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode()) if req.data else None
        return _Resp()

    monkeypatch.setattr(mailer, "_graph_token", lambda: "tok")
    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "GRAPH_SENDER"):
        monkeypatch.setenv(k, "x")
    assert mailer.send_mail("a@b.co", "s", "b", reply_to="soporteit@goldenlogisticas.com")["sent"] is True
    assert captured["body"]["message"]["replyTo"] == [{"emailAddress": {"address": "soporteit@goldenlogisticas.com"}}]
