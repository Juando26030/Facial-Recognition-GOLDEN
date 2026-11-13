"""Fase 9-A · alerta de borrado masivo (9-nov-2026): umbrales, ventana por cuenta, borrados esperados, rollback, correo sin datos personales y pantalla de destinatarios."""
import pytest

from app import jobs, mass_delete
from app.models import AlertRecipient, EventAttendee, MassDeleteLog, SystemAlert, User
from tests.conftest import login

CFG = dict(mass_delete.DEFAULTS)


# ------------------------------------------------------------------ parte pura
def test_clean_settings_clamps_and_keeps_defaults_on_garbage():
    out = mass_delete.clean_settings({"enabled": False, "per_action": 1, "window_count": "x", "window_minutes": 999})
    assert out == {"enabled": False, "per_action": 5, "window_count": 200, "window_minutes": 60}
    assert mass_delete.clean_settings({}) == CFG


def test_decide_by_action_window_or_disabled():
    assert mass_delete.decide(50, 50, CFG) == "action"
    assert mass_delete.decide(30, 200, CFG) == "window"
    assert mass_delete.decide(30, 80, CFG) == ""
    assert mass_delete.decide(500, 500, {**CFG, "enabled": False}) == ""


# ------------------------------------------------------------------ con base de datos
@pytest.fixture
def mails(monkeypatch):
    sent = []
    fake = lambda to, subject, body, attachments=None, html=None, reply_to=None: sent.append({"to": to, "subject": subject, "body": body}) or {"sent": True, "detail": "prueba"}          # noqa: E731
    monkeypatch.setattr("app.mailer.send_mail", fake)
    monkeypatch.setattr("app.notifications.send_mail", fake)          # el correo de la campana importa send_mail al cargar el módulo
    return sent


@pytest.fixture
def world(db, factory):
    admin = factory.staff("admin", username="adm", email="adm@golden.test")
    ev = factory.event()
    users = [User(id=f"9{n:05d}", tenant_id=ev.tenant_id, first_name=f"Nombre{n}", last_name="Prueba") for n in range(120)]
    db.add_all(users)
    db.flush()
    db.add_all([EventAttendee(event_id=ev.id, user_id=u.id, tenant_id=ev.tenant_id) for u in users])
    db.add(AlertRecipient(kind="email", email="uno@golden.test", active=True))
    db.add(AlertRecipient(kind="email", email="dos@golden.test", active=False))
    db.commit()
    return admin, ev


def _delete_attendees(db, admin, ev, n):
    mass_delete.set_actor(db, admin)
    ids = [r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == ev.id).limit(n).all()]
    db.query(EventAttendee).filter(EventAttendee.event_id == ev.id, EventAttendee.user_id.in_(ids)).delete(synchronize_session=False)
    db.commit()


def test_big_single_delete_sends_mail_to_active_recipients_without_personal_data(db, world, mails):
    admin, ev = world
    _delete_attendees(db, admin, ev, 60)
    assert [m["to"] for m in mails] == ["uno@golden.test"]
    body = mails[0]["body"]
    assert "adm (admin)" in body and "60" in body and "registros de asistentes" in body
    assert "Nombre" not in body and "9000" not in body
    assert db.query(SystemAlert).filter_by(kind="mass_delete").count() == 1


def test_small_delete_does_not_alert(db, world, mails):
    admin, ev = world
    _delete_attendees(db, admin, ev, 20)
    assert mails == [] and db.query(SystemAlert).count() == 0


def test_window_rule_adds_up_two_medium_deletes_of_the_same_account(db, world, mails):
    admin, ev = world
    mass_delete.save_settings(db, {**CFG, "per_action": 100, "window_count": 40})
    db.commit()
    _delete_attendees(db, admin, ev, 25)
    assert mails == []
    _delete_attendees(db, admin, ev, 25)
    assert len(mails) == 1 and "últimos" in mails[0]["body"]
    assert db.query(MassDeleteLog).count() == 2


def test_expected_purge_does_not_alert(db, world, mails):
    admin, ev = world
    with mass_delete.expected(db):
        _delete_attendees(db, admin, ev, 80)
    assert mails == [] and db.query(SystemAlert).count() == 0


def test_disabled_does_not_alert(db, world, mails):
    admin, ev = world
    mass_delete.save_settings(db, {**CFG, "enabled": False})
    db.commit()
    _delete_attendees(db, admin, ev, 80)
    assert mails == []


def test_rollback_leaves_no_alert(db, world, mails):
    admin, ev = world
    mass_delete.set_actor(db, admin)
    db.query(EventAttendee).filter(EventAttendee.event_id == ev.id).delete(synchronize_session=False)
    db.rollback()
    db.commit()
    assert mails == [] and db.query(SystemAlert).count() == 0 and db.query(EventAttendee).filter_by(event_id=ev.id).count() == 120


def test_staff_recipient_gets_bell_and_mail(db, world, mails, factory):
    from app.models import Notification
    admin, ev = world
    boss = factory.staff("super_admin", username="boss", email="boss@golden.test")
    db.add(AlertRecipient(kind="staff", staff_user_id=boss.id, active=True))
    db.commit()
    _delete_attendees(db, admin, ev, 70)
    assert db.query(Notification).filter_by(staff_user_id=boss.id, kind="system_alert").count() == 1
    assert sorted(m["to"] for m in mails) == ["boss@golden.test", "uno@golden.test"]


def test_job_kind_is_registered_in_the_general_queue():
    assert "system_alert_mail" in jobs.GENERAL_KINDS and jobs.HANDLER_MODULES["system_alert_mail"] == "app.mass_delete"


# ------------------------------------------------------------------ pantalla / API
def test_only_admin_plus_manage_recipients(client, factory):
    factory.staff("coordinador", username="coo")
    login(client, "coo")
    assert client.get("/api/system-alerts").status_code == 403
    assert client.post("/api/system-alerts/test").status_code == 403


def test_admin_adds_validates_toggles_deletes_and_sends_test(client, db, factory, mails):
    factory.staff("admin", username="adm2", email="adm2@golden.test")
    login(client, "adm2")
    assert client.post("/api/system-alerts/test").status_code == 422                      # sin destinatarios
    assert client.post("/api/system-alerts/recipients", json={"email": "no-es-correo"}).status_code == 422
    r = client.post("/api/system-alerts/recipients", json={"email": "Nuevo@Golden.test"})
    assert r.status_code == 200
    assert client.post("/api/system-alerts/recipients", json={"email": "nuevo@golden.test"}).status_code == 409
    assert client.post("/api/system-alerts/test").json() == {"sent_to": 1}
    assert [m["to"] for m in mails] == ["nuevo@golden.test"]
    rid = r.json()["id"]
    assert client.patch(f"/api/system-alerts/recipients/{rid}", json={"active": False}).json()["active"] is False
    assert client.post("/api/system-alerts/test").status_code == 422
    assert client.delete(f"/api/system-alerts/recipients/{rid}").json() == {"ok": True}
    data = client.get("/api/system-alerts").json()
    # prueba + aviso de «pausó un destinatario» + aviso de «quitó un destinatario» (F5-9 E: cambiar la configuración siempre deja rastro)
    assert data["recipients"] == [] and data["settings"]["per_action"] == 50 and len(data["recent"]) == 3
    assert [m["to"] for m in mails].count("nuevo@golden.test") == 2          # la prueba y el aviso de pausa (le llegó antes de pausarse)


def test_staff_without_email_cannot_be_added_and_settings_are_saved_clamped(client, db, factory):
    factory.staff("admin", username="adm3", email="a3@golden.test")
    nomail = factory.staff("coordinador", username="coo2")
    login(client, "adm3")
    assert client.post("/api/system-alerts/recipients", json={"staff_user_id": nomail.id}).status_code == 422
    out = client.put("/api/system-alerts/settings", json={"enabled": True, "per_action": 2, "window_count": 300, "window_minutes": 15}).json()["settings"]
    assert out == {"enabled": True, "per_action": 5, "window_count": 300, "window_minutes": 15}


def test_privacy_purges_are_marked_as_expected():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "app" / "privacy.py").read_text(encoding="utf-8")
    assert "@mass_delete.expected_call\ndef purge_event" in src and "@mass_delete.expected_call\ndef purge_expired" in src


# ------------------------------------------------------------------ F5-9 E: no se puede silenciar ni esquivar la alerta
def test_one_by_one_deletes_add_up_in_the_window(db, world, mails):
    """Borrar de a 9 (debajo de EVALUATE_FROM) en muchas peticiones ya no esquiva la regla de la ventana."""
    admin, ev = world
    mass_delete.save_settings(db, {**CFG, "per_action": 100, "window_count": 40})
    db.commit()
    for _ in range(4):
        _delete_attendees(db, admin, ev, 9)
    assert mails == []
    _delete_attendees(db, admin, ev, 9)                                   # 45 en la ventana
    assert len(mails) == 1 and "últimos" in mails[0]["body"]
    assert db.query(MassDeleteLog).count() == 5


def test_old_mass_delete_log_rows_are_pruned(db, world, mails):
    from datetime import timedelta

    from app.timeutil import utcnow
    admin, ev = world
    db.add(MassDeleteLog(created_at=utcnow() - timedelta(days=3), actor_id=admin.id, label="EventAttendee", rows=5))
    db.commit()
    _delete_attendees(db, admin, ev, 1)
    assert db.query(MassDeleteLog).count() == 1


def test_disabling_alerts_or_removing_recipients_warns_current_recipients(client, db, factory, mails):
    factory.staff("admin", username="adm4", email="a4@golden.test")
    db.add(AlertRecipient(kind="email", email="vigia@golden.test", active=True))
    db.commit()
    login(client, "adm4")
    assert client.put("/api/system-alerts/settings", json={"enabled": False, "per_action": 50, "window_count": 200, "window_minutes": 10}).status_code == 200
    assert [m["to"] for m in mails] == ["vigia@golden.test"] and "adm4" in mails[0]["body"] and "enabled" in mails[0]["body"]
    rid = db.query(AlertRecipient.id).filter_by(email="vigia@golden.test").scalar()
    assert client.delete(f"/api/system-alerts/recipients/{rid}").json() == {"ok": True}
    assert [m["to"] for m in mails] == ["vigia@golden.test", "vigia@golden.test"]
    assert "vigia@" not in mails[1]["body"]                                   # el correo va enmascarado en el aviso
    assert db.query(SystemAlert).filter_by(kind="alert_config").count() == 2
    from app.models import AuditAction
    assert db.query(AuditAction).filter_by(entity="system_alerts").count() == 1


def test_saving_same_settings_does_not_warn(client, db, factory, mails):
    factory.staff("admin", username="adm5", email="a5@golden.test")
    db.add(AlertRecipient(kind="email", email="vigia2@golden.test", active=True))
    db.commit()
    login(client, "adm5")
    client.put("/api/system-alerts/settings", json=dict(CFG))
    assert mails == []
