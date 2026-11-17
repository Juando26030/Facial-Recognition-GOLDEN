"""Fase 10 (E): historial de datos modificados por persona (app/person_history.py, tabla person_change_log, migración 0127).
Diff puro, edición desde el directorio (PATCH), edición sin conexión (bandeja), carga masiva, inscripción por formulario, cambio de cédula, persona PRUEBA, permisos de lectura,
hoja «Historial de cambios» del Excel y borrado junto con la persona (supresión / eliminar del evento / evento). Sin datos personales en logs."""
import pytest

from app import person_history as ph
from app import privacy
from app.models import AccessLog, Event, PersonChangeLog, User
from tests.conftest import login


# ------------------------------------------------------------------ diff puro
def test_diff_ignores_empty_equivalents_and_reports_real_changes():
    assert ph.diff({"role": None, "city": ""}, {"role": "  ", "city": None}) == []
    assert ph.diff({"email": "a@x.com"}, {"email": "a@x.com"}) == []
    assert ph.diff({"email": "a@x.com", "opcional_2": "Cali"}, {"email": "b@x.com", "opcional_2": "Bogotá"}) == [("email", "a@x.com", "b@x.com"), ("opcional_2", "Cali", "Bogotá")]


def test_diff_filled_and_cleared_fields_count_and_order_is_stable():
    d = ph.diff({"opcional_10": "a"}, {"role": "Jefe", "opcional_2": "x"})
    assert [k for k, _, _ in d] == ["role", "opcional_2", "opcional_10"]
    assert d[0] == ("role", "", "Jefe") and d[2] == ("opcional_10", "a", "")


def test_diff_trims_long_values():
    [(_, old, new)] = ph.diff({"role": "a"}, {"role": "b" * 900})
    assert old == "a" and len(new) == ph.MAX_VALUE


def test_snapshot_reads_text_fields_and_optionals_only():
    u = User(id="1", tenant_id="acme", first_name="Ana", last_name="P", role="Jefe", email="a@x.com")
    u.set_extras({"opcional_1": "Cali", "otra_cosa": "no"})
    snap = ph.snapshot(u)
    assert snap["first_name"] == "Ana" and snap["opcional_1"] == "Cali" and "otra_cosa" not in snap
    assert not any("face" in k or "birth" in k for k in snap)          # nunca biometría ni fecha de nacimiento


# ------------------------------------------------------------------ edición desde el directorio
def _setup(factory, role="coordinador"):
    coord = factory.staff(role, "coord")
    ev = factory.event("en_proceso", coordinator=coord)
    factory.person(ev, "1001")
    return coord, ev


def test_patch_user_records_one_row_per_changed_field(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    r = client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Gerente", "entity": "ACME"})
    assert r.status_code == 200
    rows = db.query(PersonChangeLog).filter_by(user_id="1001").order_by(PersonChangeLog.field_key).all()
    assert [(x.field_key, x.old_value, x.new_value, x.changed_by_id, x.source, x.event_id) for x in rows] == [
        ("entity", None, "ACME", coord.id, "edit", ev.id), ("role", None, "Gerente", coord.id, "edit", ev.id)]
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Director"})
    last = db.query(PersonChangeLog).filter_by(user_id="1001", field_key="role").order_by(PersonChangeLog.id.desc()).first()
    assert (last.old_value, last.new_value) == ("Gerente", "Director")


def test_patch_without_real_change_leaves_no_history(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"first_name": "Ana"})          # mismo nombre
    assert db.query(PersonChangeLog).count() == 0


def test_extra_field_change_is_recorded(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"extra_fields": {"opcional_1": "Cali"}})
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"extra_fields": {"opcional_1": "Bogotá"}})
    last = db.query(PersonChangeLog).filter_by(field_key="opcional_1").order_by(PersonChangeLog.id.desc()).first()
    assert (last.old_value, last.new_value) == ("Cali", "Bogotá")


def test_test_person_leaves_no_history(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/PRUEBA?event_id={ev.id}", json={"role": "Otro"})
    assert db.query(PersonChangeLog).filter_by(user_id="PRUEBA").count() == 0


def test_cedula_correction_moves_history_and_logs_the_change(client, factory, db):
    admin = factory.staff("admin", "adm")
    ev = factory.event("en_proceso", coordinator=admin)
    factory.person(ev, "1001")
    login(client, "adm")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Jefe"})
    assert client.put(f"/api/users/1001/cedula?event_id={ev.id}", json={"new_id": "2002"}).status_code == 200
    assert db.query(PersonChangeLog).filter_by(user_id="1001").count() == 0
    keys = {x.field_key for x in db.query(PersonChangeLog).filter_by(user_id="2002")}
    assert keys == {"role", "id"}


# ------------------------------------------------------------------ lectura y permisos
def test_history_endpoint_lists_changes_with_who_and_when(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Gerente"})
    d = client.get(f"/api/events/{ev.id}/users/1001/change-history").json()
    assert d["count"] == 1 and d["items"][0]["label"] == "Cargo" and d["items"][0]["new"] == "Gerente" and d["items"][0]["by"] == coord.full_name and d["items"][0]["at_local"]


def test_digitador_and_other_events_cannot_read_history(client, factory, db):
    coord, ev = _setup(factory)
    dig = factory.staff("digitador", "dig")
    factory.authorize(ev, dig)
    login(client, "dig")
    assert client.get(f"/api/events/{ev.id}/users/1001/change-history").status_code == 403
    client.post("/logout")
    login(client, "coord")
    assert client.get(f"/api/events/{ev.id}/users/9999/change-history").status_code == 404


# ------------------------------------------------------------------ bandeja sin conexión
def test_outbox_edit_records_history_with_outbox_source(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    r = client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [{"op_id": "op-1", "type": "edit_person", "fields": {"id": "1001", "role": "Analista"}}]})
    assert r.json()["results"][0]["result"] == "ok"
    row = db.query(PersonChangeLog).filter_by(user_id="1001", field_key="role").one()
    assert row.source == "outbox" and row.new_value == "Analista"
    client.post(f"/api/events/{ev.id}/outbox/sync", json={"ops": [{"op_id": "op-1", "type": "edit_person", "fields": {"id": "1001", "role": "Analista"}}]})          # reenvío: no duplica
    assert db.query(PersonChangeLog).filter_by(user_id="1001", field_key="role").count() == 1


# ------------------------------------------------------------------ carga masiva y formulario
def test_bulk_reload_records_changes_of_existing_people(client, factory, db):
    from tests._golden_load import HEAD, xlsx_bytes
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("creado", coordinator=coord)
    u = db.query(User).filter_by(id="1001").first() or factory.person(ev, "1001", first_name="Ana", last_name="Prueba")
    u.role, u.email = "Cargo viejo", "viejo@x.com"
    db.commit()
    new_row = [{"id": "1001", "nombres": "Ana", "apellidos": "Prueba", "cargo": "Gerente", "correo": "viejo@x.com"}.get(str(h).lower(), "") for h in HEAD]
    login(client, "coord")
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("base.xlsx", xlsx_bytes(rows=[new_row]), "application/octet-stream")})
    assert r.status_code == 200, r.text
    rows = db.query(PersonChangeLog).filter_by(user_id="1001").all()
    assert ("role", "Cargo viejo", "Gerente", "bulk") in [(x.field_key, x.old_value, x.new_value, x.source) for x in rows]


def test_form_feed_records_filled_blanks_for_existing_person(db, factory):
    from app import formsvc
    coord, ev = _setup(factory)
    u = db.query(User).filter_by(id="1001").one()
    before = ph.snapshot(u)
    u.phone = "3001112233"
    assert ph.record(db, u, before, event_id=ev.id, staff_id=None, source="form") == 1
    db.commit()
    row = db.query(PersonChangeLog).one()
    assert (row.field_key, row.old_value, row.new_value, row.changed_by_id, row.source) == ("phone", None, "3001112233", None, "form")
    assert formsvc.person_history is ph


# ------------------------------------------------------------------ Excel
def test_excel_has_history_sheet_only_when_there_are_changes(client, factory, db, tmp_path):
    from openpyxl import load_workbook
    from app.reports import ReportManager
    coord, ev = _setup(factory)
    out = tmp_path / "a.xlsx"
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(out))
    assert load_workbook(out).sheetnames == ["Portada", "Reporte", "Gráficos", "Personas registradas", "Personas no registradas"]
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Gerente"})
    out2 = tmp_path / "b.xlsx"
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(out2))
    wb = load_workbook(out2)
    assert wb.sheetnames == ["Portada", "Reporte", "Gráficos", "Historial de cambios", "Personas registradas", "Personas no registradas"]
    rows = list(wb["Historial de cambios"].iter_rows(values_only=True))
    assert rows[0][:5] == ("Cédula", "Nombre", "Campo", "Valor anterior", "Valor nuevo") and rows[1][0] == "1001" and rows[1][2] == "Cargo" and rows[1][4] == "Gerente"


# ------------------------------------------------------------------ borrado
def test_history_goes_with_the_person_on_delete_and_suppression(client, factory, db):
    coord, ev = _setup(factory)
    factory.person(ev, "2002", first_name="Luis")
    login(client, "coord")
    for uid in ("1001", "2002"):
        client.patch(f"/api/users/{uid}?event_id={ev.id}", json={"role": "Jefe"})
    assert db.query(PersonChangeLog).count() == 2
    assert client.delete(f"/api/users/1001?event_id={ev.id}").status_code == 200
    assert db.query(PersonChangeLog).filter_by(user_id="1001").count() == 0 and db.query(PersonChangeLog).filter_by(user_id="2002").count() == 1
    privacy.erase_person(db, ev, "2002", "all")
    assert db.query(PersonChangeLog).count() == 0


def test_biometric_revocation_keeps_no_biometrics_in_history(client, factory, db):
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Jefe"})
    privacy.erase_person(db, ev, "1001", "biometric")          # revocar lo biométrico no toca el historial de texto, que no tiene biometría
    cols = {c.name for c in PersonChangeLog.__table__.columns}
    assert not any(w in c for c in cols for w in ("face", "encoding", "photo", "vector"))
    assert db.query(PersonChangeLog).filter_by(user_id="1001").count() == 1


def test_history_goes_with_the_event(client, factory, db):
    factory.staff("super_admin", "root")
    coord, ev = _setup(factory)
    login(client, "coord")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Jefe"})
    client.post("/logout")
    login(client, "root")
    ev.status = "finalizado"          # solo se archivan eventos finalizados y solo se borran los ya archivados
    db.commit()
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200
    assert client.delete(f"/api/events/{ev.id}").status_code == 200
    assert db.query(PersonChangeLog).count() == 0
