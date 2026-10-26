"""Grupo A (26-oct-2026): quitar un registro por todos los caminos (A2) y no acreditar con un obligatorio vacío (A3). Datos ficticios."""
import pathlib

from app.models import AccessLog, AreaMovement, EventAttendee, EventFieldConfig, PersonChange, PrintJob, PrintLog, User
from app.routers import api
from app.timeutil import utcnow
from tests.conftest import login


def _ev(factory, db, **kw):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", **kw)
    factory.person(ev, "1001", "Cristian", "Prueba")
    factory.person(ev, "1002", "Beto", "Prueba")
    return ev


def _require(db, ev, key="entity"):
    db.add(EventFieldConfig(event_id=ev.id, field_key=key, required=True, field_type="text_short"))
    db.commit()


def _checkin(client, ev, cedula, **extra):
    return client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": cedula, **extra})


# ---------------------------------------------------------------------------------------------------- A2
def test_removing_a_person_with_print_history_and_jobs_leaves_nothing_behind(client, factory, db):
    ev = _ev(factory, db, auto_register=True)
    login(client, "root")
    assert _checkin(client, ev, "1001").json()["result"] == "SÍ"                                   # autoregistro
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_at=utcnow()))  # autoimpresión
    db.add(PrintJob(event_id=ev.id, attendee_id=att.id, request_id="r-a2", status="printed", created_at=utcnow()))
    db.add(PersonChange(tenant_id=ev.tenant_id, event_id=ev.id, user_id="1001", kind="registration_status", old_value="No registrado", new_value="Registrado"))
    db.commit()
    r = client.delete(f"/api/users/1001?event_id={ev.id}")
    assert r.status_code == 200 and r.json()["fully_deleted"] is True                              # antes: error del servidor (el historial de impresión apuntaba a la persona)
    db.expire_all()
    for model in (EventAttendee, AccessLog, PrintLog, PersonChange):
        assert db.query(model).filter(model.user_id == "1001").count() == 0, model.__name__
    assert db.query(PrintJob).filter_by(event_id=ev.id).count() == 0 and db.get(User, ("1001", ev.tenant_id)) is None
    assert db.query(AreaMovement).count() == 0


def test_a_person_in_another_event_keeps_the_user_and_the_other_event_untouched(client, factory, db):
    ev = _ev(factory, db, auto_register=True)
    other = factory.event("en_proceso"); factory.person(other, "1001", "Cristian", "Prueba")
    login(client, "root")
    _checkin(client, ev, "1001")
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=other.id, printed_at=utcnow())); db.commit()
    r = client.delete(f"/api/users/1001?event_id={ev.id}")
    assert r.status_code == 200 and r.json()["fully_deleted"] is False
    assert db.query(PrintLog).filter_by(event_id=other.id, user_id="1001").count() == 1 and db.query(EventAttendee).filter_by(event_id=other.id).count() == 1


def test_back_to_not_registered_works_even_if_a_required_field_is_empty_and_undo_works(client, factory, db):
    ev = _ev(factory, db, auto_register=True)
    login(client, "root")
    _checkin(client, ev, "1001")
    _require(db, ev)                                                                               # el campo se volvió obligatorio DESPUÉS de acreditar
    r = client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "no_registrado"})
    assert r.status_code == 200 and not api._already_checked_in(db, ev.id, "1001")
    db.query(EventFieldConfig).delete(); db.commit()
    assert _checkin(client, ev, "1002", client_id="cid-1").json()["result"] == "SÍ"
    assert client.post(f"/api/events/{ev.id}/accreditations/undo", json={"client_id": "cid-1"}).status_code == 200
    assert not api._already_checked_in(db, ev.id, "1002")


def test_the_edit_modal_saves_the_data_first_and_then_the_status():
    js = pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    i_data, i_status = js.index("const res = dataChanged ? await fetch(withEvent(`/api/users/${currentId}`)"), js.index("if (res.ok && !(await applyStatus())) return;")
    assert i_data < i_status                                                                       # el estado ya no cambia si los datos no se pudieron guardar


# ---------------------------------------------------------------------------------------------------- A3
def test_scan_row_and_autoregister_do_not_accredit_with_an_empty_required_field(client, factory, db):
    ev = _ev(factory, db, auto_register=True)
    _require(db, ev)
    login(client, "root")
    r = _checkin(client, ev, "1001").json()                                                        # escaneo con autoregistro
    assert r["result"] == "MISSING_REQUIRED" and r["missing"][0]["key"] == "entity" and r["details"].startswith("Falta el campo obligatorio")
    r = _checkin(client, ev, "1001", confirm="true").json()                                        # el «✅ Acreditar» de la fila
    assert r["result"] == "MISSING_REQUIRED"
    assert not api._already_checked_in(db, ev.id, "1001")
    r = client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "missing_required"
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"entity": "Golden"}).status_code == 200      # se completa en «Editar persona»…
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"}).status_code == 200      # …y queda acreditada
    assert _checkin(client, ev, "1002", force="true").json()["result"] == "MISSING_REQUIRED"


def test_offline_accreditation_is_not_blocked_and_shows_up_to_complete(client, factory, db):
    ev = _ev(factory, db)
    _require(db, ev)
    login(client, "root")
    h = api.roster_fingerprint(api.roster_salt(ev), "1001")
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json={"records": [{"client_id": "k-1", "h": h, "timestamp": "2026-10-26T10:00:00Z", "method": "qr"}]})
    assert r.status_code == 200 and api._already_checked_in(db, ev.id, "1001")                     # sin conexión: se acredita igual
    lst = client.get(f"/api/events/{ev.id}/incomplete-registrations").json()
    assert lst["count"] == 1 and lst["people"][0]["id"] == "1001" and lst["people"][0]["missing"][0]["key"] == "entity"
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"entity": "Golden"})
    assert client.get(f"/api/events/{ev.id}/incomplete-registrations").json()["count"] == 0


def test_without_required_fields_nothing_changes(client, factory, db):
    ev = _ev(factory, db, auto_register=True)
    login(client, "root")
    assert _checkin(client, ev, "1001").json()["result"] == "SÍ"
    assert client.get(f"/api/events/{ev.id}/incomplete-registrations").json() == {"count": 0, "people": []}


def test_the_page_opens_edit_on_the_first_missing_field():
    js = pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    assert "data.result === 'MISSING_REQUIRED'" in js and "buildEditModal(person, { missing: data.missing || [], method })" in js and "Falta el campo obligatorio" in js
    assert "/incomplete-registrations" in js
    assert "MISSING_REQUIRED" in pathlib.Path("static/js/app.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- A1, A4, A5, A6 (las piezas; el comportamiento se prueba en Chrome con celular y tablet simulados)
def test_touch_mode_shows_three_searches_numeric_keyboard_and_reader_only_option():
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    assert "body.touch-mode #searchNombre,body.touch-mode #searchEntidad,body.touch-mode #clearFiltersBtn" not in sp
    assert "readerOnly" in sp and "el.dataset.origInputmode || 'numeric'" in sp and "sp-kbd" in sp
    assert "const MOBILE = platform === 'Android' || platform === 'iOS';" in sp and "if (MOBILE) return;" in sp
    reg = pathlib.Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert 'class="gw-modal-head" style="position:sticky' in reg
    assert 'class="gw-modal-head" style="position:sticky' in pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    assert "gw_recent_" in pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
