"""Fase 4: entrega de credenciales del personal por CORREO (app/staff_credentials.py, app/routers/staff_credentials.py) y hoja impresa.
Reglas: un solo correo por creación/restablecimiento/asignación (idempotente), NUNCA lleva contraseña, digitador vs. resto, sin correo no se encola, reenvío con tope de 3 al día y auditoría
sin datos personales, solo sus eventos, interruptor del evento, asunto sin inyección de cabeceras y nombres escapados."""
from datetime import datetime

from app import jobs, staff_credentials as sc
from app.models import AuditAction, Job, StaffUser
from tests.conftest import login

SECRET = "Clave-segura-123"


def _jobs(db):
    db.expire_all()
    return db.query(Job).filter(Job.kind == sc.KIND).count()


def _no_secret(mail, *secrets):
    blob = (mail["subject"] + mail["body"] + (mail["html"] or "")).lower()
    for secret in secrets:
        assert secret.lower() not in blob


# ------------------------------------------------------------------ contenido (puro)
def _render(**kw):
    base = dict(mode="created", name="Ana", username="1012345", role="coordinador", pw="cedula", must_change=True, url="https://app.example.com/login")
    base.update(kw)
    return sc.render(base.pop("mode"), **base)


def test_non_digitador_mail_says_initial_password_is_the_document_and_must_change():
    mail = _render()
    assert "tu contraseña inicial es tu número de documento" in mail["text"].lower()
    assert "cambiarla en tu primer ingreso" in mail["text"] and "1012345" in mail["text"] and "https://app.example.com/login" in mail["html"]


def test_given_password_mode_does_not_claim_it_is_the_document():
    text = _render(pw="given")["text"].lower()
    assert "número de documento" not in text and "te la comunicó" in text


def test_digitador_mail_uses_the_cedula_and_the_coordinator_authorizes():
    mail = _render(role="digitador", must_change=False, event={"name": "Feria", "date": "01/12/2026", "place": "Bogotá", "coordinator": "Luis"})
    text = mail["text"]
    assert "ingresa con tu cédula" in text.lower() and "coordinador del evento te autorizará" in text and "cambiarla" not in text
    assert all(x in text for x in ("Feria", "01/12/2026", "Bogotá", "Luis"))


def test_names_are_escaped_and_subject_is_a_single_line():
    mail = _render(name="<script>alert(1)</script>", event={"name": "<b>X</b>", "date": "", "place": "", "coordinator": ""})
    assert "<script>" not in mail["html"] and "&lt;script&gt;" in mail["html"] and "&lt;b&gt;X&lt;/b&gt;" in mail["html"]
    assert "\n" not in mail["subject"] and "\r" not in mail["subject"]


def test_login_url_is_never_plain_http(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://app.example.com/")
    assert sc.login_url() == "https://app.example.com/login"
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:5000")
    assert sc.login_url() == "http://localhost:5000/login"          # desarrollo local
    monkeypatch.delenv("PUBLIC_BASE_URL")
    monkeypatch.setenv("DEPLOY_ENV", "production")
    assert sc.login_url() == ""


# ------------------------------------------------------------------ cuentas del personal (creación y restablecimiento)
def _create_admin_account(client, **extra):
    body = {"username": "coord.nuevo", "password": SECRET, "full_name": "Coord Nuevo", "role": "coordinador", "phone": "3001112233", **extra}
    return client.post("/api/staff", json=body)


def test_creating_an_account_queues_exactly_one_mail_without_the_password(client, factory, db, outbox):
    factory.staff("admin", "adm")
    login(client, "adm")
    r = _create_admin_account(client, email="Coord@Ejemplo.com")
    assert r.status_code == 200 and r.json()["credentials_mail"] == "queued"
    assert _jobs(db) == 1 and len(outbox) == 1
    mail = outbox[0]
    assert mail["to"] == "coord@ejemplo.com" and "coord.nuevo" in mail["body"] and "cambiarla" in mail["body"]
    _no_secret(mail, SECRET)
    assert db.query(StaffUser).filter_by(username="coord.nuevo").one().must_change_password is True


def test_enqueue_is_idempotent_for_the_same_action(client, factory, db, outbox):
    factory.staff("admin", "adm")
    login(client, "adm")
    _create_admin_account(client, email="c@ejemplo.com")
    target = db.query(StaffUser).filter_by(username="coord.nuevo").one()
    assert sc.enqueue(db, target, "created") is True          # mismo (cuenta, modo, evento): no duplica
    db.commit()
    assert _jobs(db) == 1


def test_account_without_email_queues_nothing_and_says_so(client, factory, db, outbox):
    factory.staff("admin", "adm")
    login(client, "adm")
    r = _create_admin_account(client)
    assert r.status_code == 200 and r.json()["credentials_mail"] == "no_email"
    assert _jobs(db) == 0 and outbox == []


def test_password_reset_queues_one_mail_per_reset_without_the_password(client, factory, db, outbox):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com", email="com@ejemplo.com")
    login(client, "adm")
    r = client.put(f"/api/staff/{com.id}/password", json={"new_password": SECRET})
    assert r.status_code == 200 and r.json()["credentials_mail"] == "queued" and "correo" in r.json()["message"]
    assert len(outbox) == 1
    _no_secret(outbox[0], SECRET)
    client.put(f"/api/staff/{com.id}/password", json={"new_password": "Otra-clave-456"})
    assert len(outbox) == 2          # un restablecimiento distinto = un correo distinto
    _no_secret(outbox[1], "Otra-clave-456")


def test_password_reset_without_email_tells_to_hand_the_sheet(client, factory, db, outbox):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com")
    login(client, "adm")
    r = client.put(f"/api/staff/{com.id}/password", json={"new_password": SECRET})
    assert r.json()["credentials_mail"] == "no_email" and "hoja impresa" in r.json()["message"] and outbox == []


def test_digitador_reset_mail_says_cedula_and_never_a_password(client, factory, db, outbox):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    dig = factory.staff("digitador", "1098765", email="d@ejemplo.com")
    factory.authorize(ev, dig)
    login(client, "coord")
    assert client.put(f"/api/staff/{dig.id}/password", json={"use_username": True}).status_code == 200
    assert len(outbox) == 1 and "ingresa con tu cédula" in outbox[0]["body"].lower()
    assert "cambiarla" not in outbox[0]["body"]


# ------------------------------------------------------------------ digitadores del evento
def _create_dig(client, ev, **extra):
    return client.post(f"/api/events/{ev.id}/staff-users", json={"username": "1055000111", "full_name": "Pedro Pérez", "role": "digitador", **extra})


def test_creating_a_digitador_with_email_sends_one_mail_with_the_event(client, factory, db, outbox):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    login(client, "coord")
    r = _create_dig(client, ev, email="pedro@ejemplo.com")
    assert r.status_code == 200 and r.json()["credentials_mail"] == "queued" and r.json()["has_email"] is True
    assert len(outbox) == 1 and ev.name in outbox[0]["body"] and coord.full_name in outbox[0]["body"] and "autorizará" in outbox[0]["body"]
    _no_secret(outbox[0], "contraseña inicial es")


def test_creating_a_digitador_without_email_or_with_switch_off_queues_nothing(client, factory, db, outbox):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    login(client, "coord")
    assert _create_dig(client, ev).json()["credentials_mail"] == "no_email"
    assert client.patch(f"/api/events/{ev.id}/staff-mail", json={"enabled": False}).json() == {"enabled": False}
    r = _create_dig(client, ev, username="1055000222", email="otro@ejemplo.com")
    assert r.json()["credentials_mail"] == "disabled" and _jobs(db) == 0 and outbox == []
    assert db.query(AuditAction).filter_by(entity="event_staff_mail_enabled").count() == 1


def test_invalid_email_is_rejected(client, factory):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    login(client, "coord")
    assert _create_dig(client, ev, email="no-es-correo").status_code == 400


def test_assigning_an_existing_digitador_sends_one_mail_and_not_twice(client, factory, db, outbox):
    factory.staff("admin", "adm")
    ev = factory.event()
    dig = factory.staff("digitador", "1077000", email="d@ejemplo.com", tenant_id="acme")
    login(client, "adm")
    assert client.post(f"/api/events/{ev.id}/staff-users/assign-existing", json={"staff_id": dig.id}).status_code == 200
    assert client.post(f"/api/events/{ev.id}/staff-users/assign-existing", json={"staff_id": dig.id}).status_code == 200          # ya estaba: no hay segundo correo
    assert len(outbox) == 1 and ev.name in outbox[0]["body"]


def test_a_queued_mail_is_skipped_if_the_switch_is_turned_off_or_the_account_is_archived(client, factory, db, outbox, monkeypatch):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    dig = factory.staff("digitador", "1066000", email="d@ejemplo.com")
    factory.authorize(ev, dig)
    monkeypatch.setattr(jobs, "kick", lambda *a, **k: None)          # el trabajo queda en cola
    assert sc.enqueue(db, dig, "assigned", event=ev) is True
    db.commit()
    ev.staff_mail_enabled = False
    db.commit()
    jobs.drain()
    assert outbox == []
    ev.staff_mail_enabled = True
    dig.archived_at = datetime(2026, 1, 1)
    db.commit()
    assert sc.enqueue(db, dig, "resend", event=ev, nonce="x") is True
    db.commit()
    jobs.drain()
    assert outbox == []


# ------------------------------------------------------------------ reenviar: tope, auditoría, permisos
def _event_with_dig(factory, email="d@ejemplo.com"):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event(coordinator=coord)
    dig = factory.staff("digitador", "1044000", email=email)
    factory.authorize(ev, dig)
    return coord, ev, dig


def test_resend_is_limited_to_three_per_day_and_audited_without_personal_data(client, factory, db, outbox):
    coord, ev, dig = _event_with_dig(factory)
    login(client, "coord")
    url = f"/api/events/{ev.id}/staff-users/{dig.id}/resend-credentials"
    for i in range(3):
        r = client.post(url)
        assert r.status_code == 200 and r.json()["remaining_today"] == 2 - i
    assert client.post(url).status_code == 429
    assert len(outbox) == 3
    rows = db.query(AuditAction).filter_by(action=sc.RESEND_ACTION).all()
    assert len(rows) == 3
    for row in rows:
        assert row.entity_id == str(dig.id) and "ejemplo.com" not in (row.detail or "") and dig.username not in (row.detail or "") and row.entity_name is None


def test_resend_without_email_is_a_clear_400(client, factory, db, outbox):
    coord, ev, dig = _event_with_dig(factory, email=None)
    login(client, "coord")
    r = client.post(f"/api/events/{ev.id}/staff-users/{dig.id}/resend-credentials")
    assert r.status_code == 400 and "hoja impresa" in r.json()["detail"] and outbox == [] and db.query(AuditAction).filter_by(action=sc.RESEND_ACTION).count() == 0


def test_resend_permissions(client, factory, db, outbox):
    coord, ev, dig = _event_with_dig(factory)
    factory.staff("comercial", "com")
    url = f"/api/events/{ev.id}/staff-users/{dig.id}/resend-credentials"
    login(client, "com")
    assert client.post(url).status_code == 403
    client.cookies.clear()
    login(client, "1044000")          # el propio digitador
    assert client.post(url).status_code == 403
    assert outbox == []


def test_resend_on_someone_elses_event_or_a_person_not_in_it_is_404(client, factory, db, outbox, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    coord, ev, dig = _event_with_dig(factory)
    factory.staff("coordinador", "intruso")
    other = factory.event(coordinator=coord)
    client.cookies.clear()
    login(client, "intruso")
    assert client.post(f"/api/events/{ev.id}/staff-users/{dig.id}/resend-credentials").status_code == 404
    client.cookies.clear()
    login(client, "coord")
    assert client.post(f"/api/events/{other.id}/staff-users/{dig.id}/resend-credentials").status_code == 404          # no está asignado a ese evento
    assert outbox == []


def test_account_resend_only_for_accounts_that_have_not_chosen_a_password(client, factory, db, outbox):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com", email="com@ejemplo.com", must_change_password=True)
    chosen = factory.staff("comercial", "com2", email="c2@ejemplo.com")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.post(f"/api/staff/{com.id}/resend-credentials").status_code == 403          # un coordinador solo administra digitadores
    client.cookies.clear()
    login(client, "adm")
    assert client.post(f"/api/staff/{com.id}/resend-credentials").status_code == 200
    assert len(outbox) == 1 and "cambiarla" in outbox[0]["body"]
    assert client.post(f"/api/staff/{chosen.id}/resend-credentials").status_code == 400
    assert coord.id != com.id


def test_set_email_of_an_event_digitador(client, factory, db):
    coord, ev, dig = _event_with_dig(factory, email=None)
    login(client, "coord")
    assert client.patch(f"/api/events/{ev.id}/staff-users/{dig.id}/email", json={"email": "mal"}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}/staff-users/{dig.id}/email", json={"email": "Bien@Ejemplo.com"}).json() == {"has_email": True}
    db.expire_all()
    assert db.get(StaffUser, dig.id).email == "bien@ejemplo.com"
    assert client.get(f"/api/events/{ev.id}/staff-users").json()[0]["has_email"] is True


# ------------------------------------------------------------------ hoja impresa
def test_printable_sheet_lists_the_digitadores_without_passwords(client, factory, db):
    coord, ev, dig = _event_with_dig(factory)
    login(client, "coord")
    r = client.get(f"/kiosk/{ev.id}/usuarios/hoja")
    assert r.status_code == 200
    assert "1044000" in r.text and "Usuario (cédula)" in r.text and "no hay contraseña" in r.text.lower()
    assert "kiosk-printing" not in r.text and "onclick" not in r.text


def test_printable_sheet_is_closed_to_comercial_and_digitador(client, factory):
    coord, ev, dig = _event_with_dig(factory)
    factory.staff("comercial", "com")
    login(client, "com")
    assert client.get(f"/kiosk/{ev.id}/usuarios/hoja").status_code == 302
    client.cookies.clear()
    login(client, "1044000")
    assert client.get(f"/kiosk/{ev.id}/usuarios/hoja").status_code == 302
