"""Persona de prueba de cada evento (5-nov-2026) y puertas del estado «creado»:
- todo evento creado por la API trae a «PRUEBA» (todos los campos dicen «prueba»), visible en el Directorio con la marca `test`;
- no cuenta en reportes, estadísticas, ruleta, contadores ni en «¿tiene gente cargada?»;
- es la ÚNICA persona que se acredita/imprime con el evento en «creado»; a los demás ni acreditar, ni «Editar → Registrado», ni imprimir."""
from app import testperson
from app.models import Event, EventAttendee, User
from app.reports import _event_directory_users as report_people
from app.routers.analytics import registro_dashboard
from app.routers.stats import _event_directory_users as stats_people
from tests.conftest import login


def _create(client, coord_id, name="Evento con prueba", code="PRB1"):
    r = client.post("/api/events", json={"tenant_id": "acme", "event_code": code, "name": name, "location": "L", "address": "D", "country": "CO",
                                         "city": "Bogotá", "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31",
                                         "event_time_start": "08:00", "event_time_end": "18:00", "setup_time_start": "06:00",
                                         "setup_time_end": "07:00", "coordinator_staff_id": coord_id})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _admin(client, factory):
    factory.tenant("acme")
    s = factory.staff("admin", "root")
    login(client, "root")
    return s.id


def test_new_event_comes_with_the_test_person_and_it_is_idempotent(client, factory, db):
    sid = _admin(client, factory)
    a, b = _create(client, sid, code="PRB1"), _create(client, sid, "Otro", "PRB2")
    u = db.query(User).filter_by(id=testperson.TEST_ID, tenant_id="acme").one()
    assert u.first_name == "Prueba" and u.last_name == "Prueba"
    assert all("prueba" in str(v).lower() for v in (u.role, u.entity, u.phone, u.email, u.opt_1)), "todos los campos dicen «prueba»"
    for ev in (a, b):
        assert db.query(EventAttendee).filter_by(event_id=ev, user_id=testperson.TEST_ID).count() == 1
    assert db.query(User).filter_by(id=testperson.TEST_ID, tenant_id="acme").count() == 1
    testperson.ensure_for_event(db, db.get(Event, a))
    db.commit()
    assert db.query(EventAttendee).filter_by(event_id=a, user_id=testperson.TEST_ID).count() == 1
    rows = client.get(f"/api/users?event_id={a}").json()
    assert [r["id"] for r in rows] == ["PRUEBA"] and rows[0]["test"] is True


def test_the_test_person_never_counts_in_reports_stats_or_the_event_state(client, factory, db):
    sid = _admin(client, factory)
    ev_id = _create(client, sid)
    ev = db.get(Event, ev_id)
    assert report_people(db, ev_id, "acme") == [] and stats_people(db, ev_id, "acme") == []
    assert registro_dashboard(db, ev)["total"] == 0
    # aun acreditada con el evento en proceso, no se cuenta (ni en reportes, ni estadísticas, ni «devolver a creado»)
    ev.status = "en_proceso"
    db.commit()
    r = client.post("/api/checkin-cedula", data={"event_id": ev_id, "cedula": "PRUEBA", "confirm": "true"})
    assert r.status_code == 200 and r.json()["result"] == "SÍ"
    assert report_people(db, ev_id, "acme") == [] and stats_people(db, ev_id, "acme") == []
    dash = registro_dashboard(db, db.get(Event, ev_id))
    assert dash["total"] == 0 and dash["done"] == 0
    info = client.get(f"/api/events/{ev_id}/revert-to-created").json()
    assert info["attendees"] == 0 and info["access_logs"] == 0


def test_in_created_only_the_test_person_can_be_accredited_edited_or_printed(client, factory, db):
    _admin(client, factory)
    ev = factory.event("creado")
    testperson.ensure_for_event(db, ev)
    factory.person(ev, "1001", first_name="Ana")
    db.commit()
    # acreditar por cédula
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "confirm": "true"}).status_code == 403
    ok = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "PRUEBA", "confirm": "true"})
    assert ok.status_code == 200 and ok.json()["result"] == "SÍ"
    # «Editar → Estado de registro → Guardar» (el hueco que se cerró)
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"}).status_code == 403
    assert client.patch(f"/api/events/{ev.id}/users/PRUEBA/status", json={"status": "no_registrado"}).status_code == 200
    assert client.patch(f"/api/events/{ev.id}/users/PRUEBA/status", json={"status": "registrado"}).status_code == 200
    # imprimir
    assert client.get(f"/api/users/1001/badge-print-data?event_id={ev.id}").status_code == 403
    assert client.post(f"/api/users/1001/print-log?event_id={ev.id}").status_code == 403
    assert client.get(f"/api/users/PRUEBA/badge-print-data?event_id={ev.id}").status_code == 200
    assert client.post(f"/api/users/PRUEBA/print-log?event_id={ev.id}").status_code == 200
    # editar los datos sigue siendo posible (no es registrar), también el correo ficticio de la prueba
    assert client.patch(f"/api/users/PRUEBA?event_id={ev.id}", json={"entity": "Otra prueba", "email": "prueba@prueba.com"}).status_code == 200


def test_when_the_event_is_in_progress_everyone_registers_and_prints_as_always(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    factory.person(ev, "1001", first_name="Ana")
    db.commit()
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"}).status_code == 200
    assert client.get(f"/api/users/1001/badge-print-data?event_id={ev.id}").status_code == 200
    assert client.post(f"/api/users/1001/print-log?event_id={ev.id}").status_code == 200
