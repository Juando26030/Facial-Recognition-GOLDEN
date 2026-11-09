"""Fase 5 (E): historial de cambios del evento por campo y correo de aviso de campos clave (app/event_history.py, app/routers/event_history.py).
Diff puro (bordes: sin cambios, campos nuevos, vacíos, fecha/hora, sensibles, recorte), historial al editar, correo solo si el campo es obligatorio y a los destinatarios correctos
(uno por destinatario por guardado), permisos de lectura y privacidad (sin datos de asistentes)."""
import pytest

from app import event_history as eh
from app import event_template as et
from app import jobs
from app.models import EventChangeLog, Job
from tests.conftest import login


@pytest.fixture()
def mails(monkeypatch):
    sent = []

    def fake(to, subject, body, attachments=None, html=None, reply_to=None):
        sent.append({"to": to, "subject": subject, "body": body, "html": html})
        return {"sent": True, "detail": "prueba"}

    monkeypatch.setattr("app.event_history.send_mail", fake)
    return sent


TPL = et.default_template()


# ------------------------------------------------------------------ diff puro
def test_no_changes_gives_empty_diff():
    snap = {"name": "Feria", "start_date": "2026-12-01", "event_time_start": "09:00"}
    assert eh.diff_event(snap, dict(snap), TPL) == []


def test_empty_values_are_all_the_same_empty():
    assert eh.diff_event({"notes": None, "city": ""}, {"notes": "  ", "city": None}, TPL) == []
    assert eh.diff_event({"x": []}, {"x": {}}, TPL) == []


def test_changed_field_reports_label_old_new_and_required_flag():
    [c] = eh.diff_event({"name": "Feria"}, {"name": "Feria 2"}, TPL)
    assert (c["key"], c["label"], c["old"], c["new"], c["required"]) == ("name", "Nombre del evento", "Feria", "Feria 2", True)


def test_optional_field_is_not_required_and_a_filled_new_field_is_a_change():
    [c] = eh.diff_event({}, {"notes": "Llevar sillas"}, TPL)
    assert c["required"] is False and c["old"] is None and c["new"] == "Llevar sillas"
    [c] = eh.diff_event({"notes": "x"}, {}, TPL)
    assert c["new"] is None and c["old"] == "x"


def test_dates_and_times_are_normalised_and_shown_readable():
    assert eh.diff_event({"event_time_start": "9:00"}, {"event_time_start": "09:00"}, TPL) == []          # 9:00 == 09:00
    [c] = eh.diff_event({"start_date": "2026-12-01"}, {"start_date": "2026-12-02"}, TPL)
    assert c["old"] == "01/12/2026" and c["new"] == "02/12/2026"
    from datetime import date
    assert eh.diff_event({"start_date": date(2026, 12, 1)}, {"start_date": "2026-12-01"}, TPL) == []
    [c] = eh.diff_event({"event_time_end": "17:00"}, {"event_time_end": "18:30"}, TPL)
    assert (c["old"], c["new"]) == ("17:00", "18:30")


def test_booleans_numbers_and_json_values():
    [c] = eh.diff_event({"sw_facial_enabled": False}, {"sw_facial_enabled": True}, TPL)
    assert (c["old"], c["new"], c["source"]) == ("No", "Sí", "switch")
    assert eh.diff_event({"c_a": 5}, {"c_a": 5.0}, None) == []
    assert eh.diff_event({"c_a": {"b": 1, "a": 2}}, {"c_a": {"a": 2, "b": 1}}, None) == []


def test_sensitive_contact_values_are_hidden_and_long_values_truncated():
    tpl = {"fields": [{"key": "c_contacto", "type": "contact", "title": "Contacto", "required": True}, {"key": "c_largo", "type": "text_long", "title": "Largo", "required": False}]}
    [c] = eh.diff_event({"c_contacto": {"name": "Ana", "phone": "3001112233"}}, {"c_contacto": {"name": "Ana", "phone": "3009998877"}}, tpl)
    assert c["old"] == c["new"] == eh.HIDDEN and "300" not in str(c)
    [c] = eh.diff_event({"c_largo": ""}, {"c_largo": "x" * 1000}, tpl)
    assert len(c["new"]) == eh.MAX_VALUE and c["new"].endswith("…")


def test_unknown_keys_use_a_readable_label_and_state_has_its_source():
    [c] = eh.diff_event({"state_id": "Creado"}, {"state_id": "En proceso"}, TPL)
    assert c["label"] == "Estado" and c["source"] == "state" and c["required"] is False
    [c] = eh.diff_event({}, {"c_zzz": "v"}, TPL)
    assert c["label"] == "c_zzz"


def test_diff_follows_template_order():
    after = {"notes": "n", "name": "Z", "city": "C"}
    assert [c["key"] for c in eh.diff_event({}, after, TPL)] == ["name", "city", "notes"]


# ------------------------------------------------------------------ correo (puro)
def test_mail_groups_all_changes_in_one_message_and_escapes():
    from datetime import datetime
    mail = eh.render_mail("Feria <b>", [{"label": "Lugar", "old": "A", "new": "B"}, {"label": "Ciudad", "old": None, "new": "Cali"}], "Ana", datetime(2026, 12, 1, 15, 0), "https://app.example.com/kiosk/1")
    assert mail["subject"] == "Cambio en el evento Feria <b>: 2 campos" and "Lugar: A → B" in mail["text"] and "(vacío) → Cali" in mail["text"]
    assert "10:00" in mail["text"] and "&lt;b&gt;" in mail["html"] and "https://app.example.com/kiosk/1" in mail["html"]
    one = eh.render_mail("F", [{"label": "Lugar", "old": "A", "new": "B"}], "Ana", None)
    assert one["subject"] == "Cambio en el evento F: Lugar"


# ------------------------------------------------------------------ al editar
def _setup(factory, **ev):
    admin = factory.staff("admin", "adm", email="adm@ejemplo.com")
    coord = factory.staff("coordinador", "coo", email="coo@ejemplo.com")
    com = factory.staff("comercial", "com", email="com@ejemplo.com")
    event = factory.event("creado", coordinator=coord, commercial=com, **ev)
    return admin, coord, com, event


def _rows(db, event):
    db.expire_all()
    return db.query(EventChangeLog).filter_by(event_id=event.id).order_by(EventChangeLog.id).all()


def test_editing_writes_one_row_per_changed_field_only(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory, location="Sala A")
    login(client, "adm")
    r = client.patch(f"/api/events/{ev.id}", json={"location": "Sala B", "notes": "Hola", "name": ev.name})
    assert r.status_code == 200
    rows = _rows(db, ev)
    assert {(x.field_key, x.old_value, x.new_value) for x in rows} == {("location", "Sala A", "Sala B"), ("notes", None, "Hola")}
    assert all(x.changed_by_id == admin.id and x.source == "edit" and x.changed_at for x in rows)
    r = client.patch(f"/api/events/{ev.id}", json={"location": "Sala B"})
    assert r.status_code == 200 and len(_rows(db, ev)) == 2          # no cambió nada: no escribe


def test_state_change_and_extra_and_assignment_are_logged(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory)
    otro = factory.staff("coordinador", "coo2", email="coo2@ejemplo.com")
    login(client, "adm")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso", "coordinator_staff_id": otro.id}).status_code == 200
    got = {x.field_key: x for x in _rows(db, ev)}
    assert got["coordinator_staff_id"].new_value == otro.full_name and got["coordinator_staff_id"].old_value == coord.full_name
    assert got["state_id"].source == "state" and got["state_id"].new_value


def test_attendee_data_is_never_in_the_history(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory)
    factory.person(ev, "1001")
    login(client, "adm")
    client.patch(f"/api/events/{ev.id}", json={"notes": "x"})
    assert "1001" not in str([(x.field_key, x.old_value, x.new_value) for x in _rows(db, ev)])


# ------------------------------------------------------------------ correos clave
def _mail_jobs(db):
    db.expire_all()
    return db.query(Job).filter(Job.kind == eh.KIND).count()


def test_required_field_change_mails_commercial_and_coordinator_once_each(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory)
    login(client, "adm")
    client.patch(f"/api/events/{ev.id}", json={"location": "Sala B", "city": "Cali", "notes": "x"})          # lugar y ciudad son obligatorios; observaciones no
    jobs.drain()
    assert sorted(m["to"] for m in mails) == ["com@ejemplo.com", "coo@ejemplo.com"]          # UN correo por destinatario aunque cambiaron dos campos
    for m in mails:
        assert m["subject"].startswith(f"Cambio en el evento {ev.name}: 2 campos") and "Lugar" in m["body"] and "Ciudad" in m["body"] and "Observaciones" not in m["body"]


def test_optional_field_change_sends_nothing(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory)
    login(client, "adm")
    client.patch(f"/api/events/{ev.id}", json={"notes": "solo observaciones"})
    jobs.drain()
    assert _mail_jobs(db) == 0 and mails == [] and len(_rows(db, ev)) == 1


def test_actor_is_not_notified_and_missing_emails_are_skipped(client, factory, db, mails):
    factory.staff("admin", "adm", email="adm@ejemplo.com")
    coord = factory.staff("coordinador", "coo")                          # sin correo
    com = factory.staff("comercial", "com", email="com@ejemplo.com")
    ev = factory.event("creado", coordinator=coord, commercial=com)
    login(client, "com")
    assert client.patch(f"/api/events/{ev.id}", json={"location": "Sala C"}).status_code == 200          # la comercial edita: no se avisa a sí misma; el coordinador no tiene correo
    jobs.drain()
    assert mails == [] and _mail_jobs(db) == 0 and len(_rows(db, ev)) == 1


def test_same_person_as_commercial_and_coordinator_gets_a_single_mail(client, factory, db, mails):
    factory.staff("admin", "adm", email="adm@ejemplo.com")
    both = factory.staff("coordinador", "doble", email="doble@ejemplo.com", secondary_role="comercial")
    ev = factory.event("creado", coordinator=both, commercial=both)
    login(client, "adm")
    client.patch(f"/api/events/{ev.id}", json={"location": "Sala D"})
    jobs.drain()
    assert [m["to"] for m in mails] == ["doble@ejemplo.com"]


def test_recipients_helper_excludes_inactive_and_actor(factory, db):
    admin, coord, com, ev = _setup(factory)
    assert eh.recipients(db, ev, admin) == [com.id, coord.id]
    assert eh.recipients(db, ev, com) == [coord.id]
    coord.is_active = False
    db.commit()
    assert eh.recipients(db, ev, admin) == [com.id]


def test_job_payload_has_only_ids(client, factory, db, mails):
    admin, coord, com, ev = _setup(factory)
    login(client, "adm")
    client.patch(f"/api/events/{ev.id}", json={"location": "Sala Secreta"})
    db.expire_all()
    for j in db.query(Job).filter(Job.kind == eh.KIND):
        assert "Sala" not in j.payload_json and "@" not in j.payload_json


# ------------------------------------------------------------------ lectura y permisos
def test_history_read_paginates_filters_and_shows_who(client, factory, db):
    admin, coord, com, ev = _setup(factory)
    login(client, "adm")
    for i in range(3):
        client.patch(f"/api/events/{ev.id}", json={"location": f"Sala {i}", "notes": f"n{i}"})
    r = client.get(f"/api/events/{ev.id}/change-history?per_page=4")
    body = r.json()
    assert r.status_code == 200 and body["total"] == 6 and len(body["items"]) == 4 and body["items"][0]["changed_by"] == admin.full_name
    assert {f["key"] for f in body["fields"]} == {"location", "notes"} and body["items"][0]["changed_at"].endswith("Z") and "/" in body["items"][0]["changed_at_local"]
    only = client.get(f"/api/events/{ev.id}/change-history?field=notes&page=2&per_page=2").json()
    assert only["total"] == 3 and len(only["items"]) == 1 and only["items"][0]["field_key"] == "notes"


def test_who_can_read_the_history(client, factory, db):
    admin, coord, com, ev = _setup(factory)
    dig = factory.staff("digitador", "dig")
    cli = factory.staff("cliente", "cli")
    factory.authorize(ev, dig)
    factory.authorize(ev, cli)
    url = f"/api/events/{ev.id}/change-history"
    assert client.get(url).status_code in (401, 403)
    for user in ("coo", "com", "adm"):
        client.post("/logout")
        login(client, user)
        assert client.get(url).status_code == 200, user
    for user in ("dig", "cli"):          # digitador y cliente: nunca (si el ingreso de un digitador exige autorización, ni siquiera llega a tener sesión)
        client.post("/logout")
        login(client, user)
        assert client.get(url).status_code in (401, 403), user


def test_route_is_gated_by_coordinator_role_and_event_access():
    import inspect

    from app.routers import event_history as router
    src = inspect.getsource(router.get_change_history)
    assert 'require_role("coordinador")' in src and "get_event_for_staff(event_id, db, staff)" in src


def test_recipients_include_every_almacen_and_contabilidad_account(factory, db):
    """Plan de la Fase 5: el aviso de campos clave también llega a almacén y contabilidad (rol principal o sumado), con correo y sin repetir."""
    com = factory.staff("comercial", "com_r", email="com_r@example.com")
    solo_alm = factory.staff("almacen", "alm_r", email="alm_r@example.com")
    conta_extra = factory.staff("coordinador", "con_r", email="con_r@example.com", extra_roles="contabilidad")
    factory.staff("contabilidad", "sinmail_r")
    ev = factory.event("creado", coordinator=conta_extra, commercial=com)
    got = eh.recipients(db, ev, None)
    assert got == [com.id, conta_extra.id, solo_alm.id]          # la coordinadora que además es contabilidad no se repite; quien no tiene correo no entra
    assert eh.recipients(db, ev, solo_alm) == [com.id, conta_extra.id]
