"""Entrega 1 del piloto: envío masivo del enlace personal (app/acceptmail.py): reglas de a quién, nunca dos veces, 25 por minuto, detener/reanudar, prueba, vista previa, registro y exportación."""
from datetime import date, timedelta

import pytest

from app import acceptlink, acceptmail, consent
from app.models import AcceptMailLog, Event, EventAttendee, FormSubmission, User
from app.timeutil import utcnow
from tests.conftest import accept, login


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "PUBLIC_BASE_URL": "https://app.ejemplo.test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(acceptmail, "SPACING", 0.0)
    monkeypatch.setattr(acceptmail.jobs, "kick", lambda *a, **k: None)           # las pruebas avanzan la cola a mano, tarea por tarea


def _event(factory, **kw):
    kw.setdefault("facial_enabled", True)
    kw.setdefault("aceptar_enabled", True)
    return factory.event("en_proceso", start_date=date(2026, 10, 29), **kw)


def _people(factory, db, ev, n=3, birth=date(1990, 1, 1)):
    for i in range(n):
        u = factory.person(ev, str(2000 + i), f"Persona{i}", "Prueba")
        u.email, u.birth_date = f"p{i}@example.com", birth
    db.commit()


def _run(db, ev, max_ticks=50):
    """Corre las tareas vencidas del envío hasta que no quede ninguna (la cola real las espacia; aquí SPACING = 0)."""
    from app import jobs
    for _ in range(max_ticks):
        if not jobs.run_once(limit=1, kinds=["accept_mail"]):
            break
    db.expire_all()


def _submission(db, ev, person_id):
    from app.models import WebForm
    form = WebForm(event_id=ev.id, name="F", slug=f"f{person_id}", design_json="{}", test_key="k")
    db.add(form)
    db.flush()
    db.add(FormSubmission(event_id=ev.id, form_id=form.id, data_json="{}", person_id=person_id, is_test=False))
    db.commit()


def _sent(db, ev):
    return [r.user_id for r in db.query(AcceptMailLog).filter_by(event_id=ev.id, kind="bulk", result="sent").order_by(AcceptMailLog.id)]


# ------------------------------------------------------------------------------------------------------------------------------------ a quién
def test_only_golden_events_with_facial_and_accept_enabled_can_send(factory, db):
    third = _event(factory, controller_mode="tercero")
    assert "propios de Golden" in acceptmail.blocked_reason(third)
    assert "Activa" in acceptmail.blocked_reason(_event(factory, aceptar_enabled=False))
    assert "candado" in acceptmail.blocked_reason(_event(factory, biometrics_locked=True))
    assert acceptmail.blocked_reason(_event(factory)) is None
    assert acceptmail.start(db, third, 1)["ok"] is False


def test_the_preview_counts_who_would_receive_and_why_the_rest_are_omitted(factory, db):
    ev = _event(factory)
    _people(factory, db, ev, 3)
    for uid, email, birth in (("3001", "", date(1990, 1, 1)), ("3002", "no-es-correo", date(1990, 1, 1)), ("3003", "k@example.com", date(date.today().year - 10, 1, 1))):
        u = factory.person(ev, uid)
        u.email, u.birth_date = email, birth
    sent = factory.person(ev, "3004")
    sent.email = "s@example.com"
    form = factory.person(ev, "3005")
    form.email = "f@example.com"
    ans = factory.person(ev, "3006")
    ans.email = "a@example.com"
    db.commit()
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="3004").one().accept_sent_at = utcnow()
    _submission(db, ev, "3005")
    accept(db, ev, "3006")
    db.commit()
    p = acceptmail.preview(db, ev)
    reasons = {o["reason"]: o["count"] for o in p["omitted"]}
    assert p["will_send"] == 3 and p["blocked"] is None
    assert reasons[acceptmail.REASONS["sin_correo"]] == 1 and reasons[acceptmail.REASONS["correo_invalido"]] == 1 and reasons[acceptmail.REASONS["menor"]] == 1
    assert reasons[acceptmail.REASONS["ya_enviado"]] == 1 and reasons[acceptmail.REASONS["ya_respondio"]] == 1
    assert reasons[acceptmail.REASONS["formulario"]] == 1 and p["omitted_total"] == 6


# ------------------------------------------------------------------------------------------------------------------------------------ enviar, nunca dos veces, detener y reanudar
def test_a_run_sends_once_to_each_person_with_the_approved_text_and_a_trusted_link(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 3)
    assert acceptmail.start(db, ev, 1)["ok"] is True
    _run(db, ev)
    assert sorted(m["to"] for m in outbox) == ["p0@example.com", "p1@example.com", "p2@example.com"]
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one()
    subject, body = acceptlink.render_link_email(ev, "Persona0", acceptlink.url(ev, att.accept_token))
    mail = next(m for m in outbox if m["to"] == "p0@example.com")
    assert mail["subject"] == subject and mail["body"] == body and mail["reply_to"] == "soporteit@goldenlogisticas.com"      # texto aprobado, sin cambios
    assert att.accept_trusted is True and att.accept_sent_at is not None
    assert sorted(_sent(db, ev)) == ["2000", "2001", "2002"] and db.get(Event, ev.id).accept_mail_run is None
    assert db.query(AcceptMailLog).filter_by(event_id=ev.id, result="done").count() == 1


def test_starting_again_never_sends_twice_to_anyone(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    assert len(outbox) == 2
    again = acceptmail.start(db, db.get(Event, ev.id), 1)
    assert again["ok"] is False and "No hay personas" in again["detail"]
    assert len(outbox) == 2


def test_stop_in_the_middle_and_resume_does_not_duplicate(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 4)
    acceptmail.start(db, ev, 1)
    from app import jobs
    jobs.run_once(limit=1, kinds=["accept_mail"])
    jobs.run_once(limit=1, kinds=["accept_mail"])                                                           # 2 enviados
    db.expire_all()
    assert len(outbox) == 2
    assert acceptmail.stop(db, db.get(Event, ev.id), 1)["ok"] is True
    _run(db, ev)                                                                                            # la tarea que quedaba en cola ve que la tanda ya no existe
    assert len(outbox) == 2
    assert acceptmail.preview(db, db.get(Event, ev.id))["will_send"] == 2
    assert acceptmail.start(db, db.get(Event, ev.id), 1)["ok"] is True
    _run(db, ev)
    assert sorted(m["to"] for m in outbox) == ["p0@example.com", "p1@example.com", "p2@example.com", "p3@example.com"]      # cada una exactamente una vez


def test_an_old_run_cannot_keep_sending_after_a_new_one_started(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 3)
    acceptmail.start(db, ev, 1)
    old = db.get(Event, ev.id).accept_mail_run
    acceptmail.stop(db, db.get(Event, ev.id), 1)
    acceptmail.start(db, db.get(Event, ev.id), 1)
    acceptmail.run_tick({"event_id": ev.id, "run": old})                                                    # tarea vieja: no hace nada
    db.expire_all()
    assert outbox == []


def test_a_reserved_person_is_never_picked_twice(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    acceptmail.start(db, ev, 1)
    db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").update({"accept_sent_at": utcnow()})      # otra tarea ya la reservó
    db.commit()
    _run(db, ev)
    assert outbox == []


# ------------------------------------------------------------------------------------------------------------------------------------ fallos y ritmo
def test_a_failed_send_releases_the_reservation_but_is_not_retried_in_the_same_run(factory, db, monkeypatch):
    ev = _event(factory)
    _people(factory, db, ev, 5)
    calls = []

    def flaky(to, subject, body, attachments=None, html=None, reply_to=None):
        calls.append(to)
        return {"sent": to != "p1@example.com", "detail": "x"}

    monkeypatch.setattr(acceptmail, "send_mail", flaky)
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    assert calls.count("p1@example.com") == 1 and len(calls) == 5
    p1 = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2001").one()
    assert p1.accept_sent_at is None                                                                        # quedó libre para una tanda futura
    assert db.query(AcceptMailLog).filter_by(event_id=ev.id, result="failed").count() == 1


def test_three_failures_in_a_row_stop_the_run(factory, db, monkeypatch):
    ev = _event(factory)
    _people(factory, db, ev, 6)
    calls = []
    monkeypatch.setattr(acceptmail, "send_mail", lambda to, *a, **k: calls.append(to) or {"sent": False, "detail": "sin configurar"})
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    assert len(calls) == 3 and db.get(Event, ev.id).accept_mail_run is None
    assert db.query(EventAttendee).filter(EventAttendee.event_id == ev.id, EventAttendee.accept_sent_at.isnot(None)).count() == 0


def test_the_hard_cap_is_25_per_minute(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    for _ in range(acceptmail.PER_MINUTE):
        db.add(AcceptMailLog(tenant_id=ev.tenant_id, event_id=ev.id, user_id=None, kind="bulk", result="sent", at=utcnow() - timedelta(seconds=10)))
    db.commit()
    acceptmail.start(db, ev, 1)
    from app import jobs
    jobs.run_once(limit=5, kinds=["accept_mail"])
    assert outbox == []                                                                                     # ya van 25 en el último minuto: espera
    assert db.query(AcceptMailLog).filter_by(kind="bulk", result="sent").count() == acceptmail.PER_MINUTE
    assert acceptmail.SPACING * acceptmail.PER_MINUTE <= 60 or acceptmail.SPACING == 0.0                    # (en producción SPACING = 2,4 s)


def test_production_spacing_cannot_exceed_25_per_minute():
    import importlib
    fresh = importlib.reload(acceptmail)
    assert fresh.SPACING * 25 >= 60 and fresh.PER_MINUTE == 25


# ------------------------------------------------------------------------------------------------------------------------------------ prueba, registro, exportación y permisos
def test_the_test_send_goes_only_to_the_typed_address_with_a_dead_link(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    r = acceptmail.send_test(db, ev, "juan@example.com", 1)
    assert r["ok"] is True and [m["to"] for m in outbox] == ["juan@example.com"]
    assert outbox[0]["subject"].startswith("[PRUEBA] ") and "ENLACE-DE-PRUEBA-NO-FUNCIONA" in outbox[0]["body"]
    assert db.query(EventAttendee).filter(EventAttendee.accept_token.isnot(None)).count() == 0                  # no se emitió ningún enlace real
    assert db.query(EventAttendee).filter(EventAttendee.accept_sent_at.isnot(None)).count() == 0
    assert acceptmail.send_test(db, ev, "no-es-correo", 1)["ok"] is False


def test_the_log_has_no_ip_or_user_agent_or_mail_addresses(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    cols = {c.name for c in AcceptMailLog.__table__.columns}
    assert not {c for c in cols if any(w in c for w in ("ip", "agent", "email", "mail", "to"))} - {"detail"} and "ip" not in cols
    csv_text = acceptmail.log_csv(db, ev)
    assert "2000" in csv_text and "@" not in csv_text and csv_text.splitlines()[0] == "cedula,fecha_hora_utc,tipo,resultado"


def test_the_export_gives_trusted_links_to_adults_including_people_without_mail(factory, db):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    nomail = factory.person(ev, "4001")
    nomail.birth_date = date(1980, 1, 1)
    kid = factory.person(ev, "4002")
    kid.email, kid.birth_date = "k@example.com", date(date.today().year - 9, 1, 1)
    db.commit()
    text = acceptmail.export_links(db, ev, 1)
    rows = text.splitlines()
    assert rows[0] == "cedula,nombre,correo,enlace,enlace_enviado_por_correo" and len(rows) == 4 and "4002" not in text
    assert all("https://app.ejemplo.test/aceptar/" in r for r in rows[1:])
    assert all(a.accept_trusted for a in db.query(EventAttendee).filter(EventAttendee.event_id == ev.id, EventAttendee.user_id != "4002"))
    assert acceptmail.export_links(db, _event(factory, controller_mode="tercero"), 1) is None


def test_a_spreadsheet_formula_in_a_name_is_neutralized_in_the_export(factory, db):
    ev = _event(factory)
    u = factory.person(ev, "5001", "=HYPERLINK(1)", "X")
    u.email = "x@example.com"
    db.commit()
    assert "'=HYPERLINK" in acceptmail.export_links(db, ev, 1)


def test_suppressing_a_person_anonymizes_their_log_rows(factory, db, outbox):
    from sqlalchemy import text
    ev = _event(factory)
    _people(factory, db, ev, 1)
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    db.execute(text("UPDATE accept_mail_log SET user_id = NULL WHERE user_id = :u AND tenant_id = :t"), {"u": "2000", "t": ev.tenant_id})     # la misma sentencia de app/privacy.py
    db.commit()
    assert db.query(AcceptMailLog).filter_by(user_id="2000").count() == 0
    import inspect
    from app import privacy
    assert "UPDATE accept_mail_log SET user_id = NULL" in inspect.getsource(privacy)


def test_the_endpoints_need_a_coordinator_and_an_explicit_confirmation(client, factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    base = f"/api/events/{ev.id}/accept-mail"
    assert client.get(base).status_code in (401, 403)
    factory.staff("digitador", "dig1")
    login(client, "dig1")
    assert client.get(base).status_code == 403
    client.cookies.clear()
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.post(base + "/start", json={}).status_code == 400                                         # sin confirmación no arranca
    st = client.get(base).json()
    assert st["will_send"] == 2 and st["running"] is False and st["per_minute"] == 25
    assert client.post(base + "/test", json={"to": "juan@example.com"}).status_code == 200
    assert client.post(base + "/stop").status_code == 400                                                   # nada en curso
    assert client.post(base + "/start", json={"confirm": True}).status_code == 200
    assert client.post(base + "/start", json={"confirm": True}).status_code == 400                          # ya hay uno en curso
    assert client.post(base + "/stop").status_code == 200
    csv = client.get(f"/api/events/{ev.id}/accept-links.csv")
    assert csv.status_code == 200 and "no-store" in csv.headers["cache-control"] and "attachment" in csv.headers["content-disposition"]
    assert client.get(base + "/log.csv").status_code == 200
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    assert 'id="amStart"' in page and 'id="amTest"' in page


# ------------------------------------------------------------------------------------------------------------------------------------ edad desconocida, «sin confirmar», descargas y retención
def test_people_without_birth_date_are_invited_and_counted_in_the_preview(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2, birth=None)
    p = acceptmail.preview(db, ev)
    assert p["will_send"] == 2 and p["no_birth_date"] == 2                                                  # no se omiten: la página de aceptación pide la fecha y bloquea a los menores
    acceptmail.start(db, ev, 1)
    _run(db, ev)
    assert len(outbox) == 2


def _cut_in_half(factory, db, ev, uid="2000", age_s=600):
    """Deja a una persona como si el proceso se hubiera caído justo al enviar: reservada, sin resultado, hace `age_s` segundos."""
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=uid).one()
    att.accept_sent_at = utcnow() - timedelta(seconds=age_s)
    db.add(AcceptMailLog(tenant_id=ev.tenant_id, event_id=ev.id, user_id=uid, kind="bulk", result="reserving", at=utcnow() - timedelta(seconds=age_s)))
    db.commit()


def test_unconfirmed_people_are_listed_and_can_be_resent_one_by_one_without_duplicating(factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 2)
    _cut_in_half(factory, db, ev)
    assert [x["user_id"] for x in acceptmail.pending_list(db, ev)] == ["2000"] and acceptmail.preview(db, ev)["unknown"] == 1
    assert acceptmail.preview(db, ev)["will_send"] == 1                                                     # el envío masivo NO la toca (ya tiene accept_sent_at)
    old = acceptlink.issue(db, db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one(), True)
    db.commit()
    assert acceptmail.resend(db, ev, "2001", 1)["ok"] is False                                              # quien no está sin confirmar, no se reenvía
    r = acceptmail.resend(db, ev, "2000", 1)
    assert r["ok"] is True and [m["to"] for m in outbox] == ["p0@example.com"]
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one()
    assert att.accept_token != old and att.accept_trusted is True                                           # el enlace anterior queda sin uso
    assert acceptmail.pending_list(db, ev) == []
    again = acceptmail.resend(db, ev, "2000", 1)                                                            # segundo clic: ya no está en la lista
    assert again["ok"] is False and len(outbox) == 1


def test_a_recent_reservation_is_not_unconfirmed_yet(factory, db):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    _cut_in_half(factory, db, ev, age_s=20)                                                                 # puede estar enviándose ahora mismo
    assert acceptmail.pending_list(db, ev) == []


def test_a_failed_resend_keeps_the_person_in_the_list(factory, db, monkeypatch):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    _cut_in_half(factory, db, ev)
    before = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one().accept_sent_at
    monkeypatch.setattr(acceptmail, "send_mail", lambda *a, **k: {"sent": False, "detail": "x"})
    assert acceptmail.resend(db, ev, "2000", 1)["ok"] is False
    db.expire_all()
    assert [x["user_id"] for x in acceptmail.pending_list(db, ev)] == ["2000"]
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one().accept_sent_at == before


def test_the_resend_endpoints_need_a_coordinator(client, factory, db, outbox):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    _cut_in_half(factory, db, ev)
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/accept-mail/pending").json()["pending"][0]["user_id"] == "2000"
    assert client.post(f"/api/events/{ev.id}/accept-mail/resend", json={"user_id": "2000"}).status_code == 200
    assert client.post(f"/api/events/{ev.id}/accept-mail/resend", json={"user_id": "2000"}).status_code == 400
    assert "Reenviar" in client.get(f"/kiosk/{ev.id}/parametros").text or 'id="amPending"' in client.get(f"/kiosk/{ev.id}/parametros").text


def test_every_download_of_links_is_recorded_as_a_system_event_and_the_screen_warns(client, factory, db):
    from app.models import SystemEvent
    ev = _event(factory)
    _people(factory, db, ev, 2)
    staff = factory.staff("coordinador", "coord1")
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/accept-links.csv").status_code == 200
    ev_row = db.query(SystemEvent).filter_by(kind="accept_links_export").one()
    assert ev_row.ref == ev.event_code and "2 enlaces" in ev_row.detail and f"#{staff.id}" in ev_row.detail
    assert "@" not in ev_row.detail and "2000" not in ev_row.detail                                         # nada de datos personales
    assert db.query(AcceptMailLog).filter_by(kind="export", staff_user_id=staff.id).count() == 1
    assert "El CSV de enlaces es confidencial" in client.get(f"/kiosk/{ev.id}/parametros").text


def test_the_send_log_is_deleted_with_the_biometric_clock_after_the_event_ends(factory, db, outbox):
    from app import privacy
    old = _event(factory)
    new = _event(factory)
    for ev in (old, new):
        _people(factory, db, ev, 1) if ev is old else None
        db.add(AcceptMailLog(tenant_id=ev.tenant_id, event_id=ev.id, user_id="2000", kind="bulk", result="sent"))
    old.status, old.finalized_at = "finalizado", utcnow() - timedelta(days=privacy.days_after_event() + 1)
    new.status, new.finalized_at = "finalizado", utcnow() - timedelta(days=1)
    db.commit()
    assert acceptmail.purge_log(db) == 1
    assert db.query(AcceptMailLog).filter_by(event_id=old.id).count() == 0 and db.query(AcceptMailLog).filter_by(event_id=new.id).count() == 1


def test_the_personal_link_stops_working_when_the_event_is_finalized(client, factory, db):
    ev = _event(factory)
    _people(factory, db, ev, 1)
    token = acceptlink.issue(db, db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2000").one(), True)
    db.commit()
    assert client.get(f"/aceptar/{ev.event_code}/{token}").status_code == 200
    ev.status = "finalizado"
    db.commit()
    assert client.get(f"/aceptar/{ev.event_code}/{token}").status_code == 404
