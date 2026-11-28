"""Llamado de asistencia del personal temporal del evento (28-nov-2026): API (app/routers/staff_attendance.py) y pestañas de «Usuarios del evento»."""
from pathlib import Path

from app.models import AuditAction, EventStaffAttendance, EventStaffAuthorization
from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def _team(factory, db, ev):
    a = factory.staff("digitador", "1010101", full_name="Ana Pérez")
    b = factory.staff("digitador", "1020202", full_name="Carlos Ruiz")
    c = factory.staff("digitador", "1030303", full_name="Cliente Temp", client_temp=True)
    for s in (a, b, c):
        db.add(EventStaffAuthorization(event_id=ev.id, staff_user_id=s.id))
    db.commit()
    return a, b, c


def test_coordinator_marks_attendance_one_option_at_a_time_and_can_clear_it(client, factory, db):
    coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=coord)
    a, b, c = _team(factory, db, ev)
    login(client, "coord1")
    r = client.get(f"/api/events/{ev.id}/staff-attendance")
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["username"] for x in d["rows"]] == ["1010101", "1020202"], "digitadores del evento; el cliente temporal no hace llamado"
    assert d["counts"]["unmarked"] == 2 and all(x["status"] is None for x in d["rows"])
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{a.id}", json={"status": "late"}).status_code == 200
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{a.id}", json={"status": "on_time"}).status_code == 200, "cambiar de opción reemplaza la marca"
    db.expire_all()
    marks = db.query(EventStaffAttendance).filter_by(event_id=ev.id).all()
    assert len(marks) == 1 and marks[0].status == "on_time" and marks[0].marked_by_id == coord.id
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{b.id}", json={"status": "absent"}).status_code == 200
    d = client.get(f"/api/events/{ev.id}/staff-attendance").json()
    assert d["counts"] == {"on_time": 1, "late": 0, "absent": 1, "unmarked": 0}
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{a.id}", json={"status": None}).status_code == 200
    db.expire_all()
    assert db.query(EventStaffAttendance).filter_by(event_id=ev.id).count() == 1, "quitar la marca borra la fila"


def test_attendance_validates_status_person_role_and_leaves_an_audit_without_cedulas(client, factory, db):
    ev = factory.event("en_proceso")
    other = factory.event("en_proceso")
    a, b, c = _team(factory, db, ev)
    stranger = factory.staff("digitador", "9990009", full_name="Otra Persona")
    db.add(EventStaffAuthorization(event_id=other.id, staff_user_id=stranger.id))
    db.commit()
    factory.staff("super_admin", "boss")
    login(client, "boss")
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{a.id}", json={"status": "volando"}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{stranger.id}", json={"status": "late"}).status_code == 404, "alguien de OTRO evento no se marca aquí"
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{c.id}", json={"status": "late"}).status_code == 404, "el cliente temporal tampoco"
    assert client.put(f"/api/events/{ev.id}/staff-attendance/{a.id}", json={"status": "late"}).status_code == 200
    audit = db.query(AuditAction).filter_by(action="attendance").one()
    assert "1010101" not in (audit.detail or "") and "Ana" in (audit.entity_name or "")


def test_users_page_has_two_tabs_and_the_creation_groups_start_closed():
    html = (ROOT / "templates/kiosk_usuarios.html").read_text(encoding="utf-8")
    assert 'id="tab_cuentas"' in html and 'id="tab_asistencia"' in html and 'Llamado de asistencia' in html
    for gid in ("grpNueva", "grpExistente", "grpExcel", "pledgePanel"):
        tag = html[html.index(f'id="{gid}"') - 40: html.index(f'id="{gid}"') + 200]
        assert "<details" in tag and " open" not in tag.split(">")[0], f"{gid} debe estar cerrado al entrar"
    # nada se perdió: los ids que usa usuarios.js siguen
    for needle in ('id="tempUserForm"', 'id="assignExistingForm"', 'id="importStaffForm"', 'id="tempUsersList"', 'id="approveAllBtn"', 'id="staffMailToggle"', 'id="purgeTempBtn"'):
        assert needle in html, needle
    js = (ROOT / "static/js/usuarios-asistencia.js").read_text(encoding="utf-8")
    assert "staff-attendance" in js and "data-was" in js
