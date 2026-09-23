"""Ciclo de vida del evento, los dos gates de acceso y el registro básico (Sprint 4, ítem 4)."""
from datetime import datetime

from tests.conftest import login


# ------------------------------- gates de acceso -------------------------------
def test_digitador_needs_authorization_and_event_in_progress(client, factory):
    digi = factory.staff("digitador", "9990001")
    running = factory.event("en_proceso")
    created = factory.event("creado")
    finished = factory.event("finalizado")
    login(client, "9990001")
    assert client.get(f"/api/users?event_id={running.id}").status_code == 403        # sin autorización
    for ev in (running, created, finished):
        factory.authorize(ev, digi)
    assert client.get(f"/api/users?event_id={running.id}").status_code == 200
    assert client.get(f"/api/users?event_id={created.id}").status_code == 403        # autorizado, pero "todavía no comenzó"
    assert client.get(f"/api/users?event_id={finished.id}").status_code == 403


def test_coordinator_can_open_any_event_but_nobody_registers_outside_in_progress(client, factory):
    factory.staff("admin", "root")
    created = factory.event("creado")
    finished = factory.event("finalizado")
    login(client, "root")
    for ev in (created, finished):
        assert client.get(f"/api/users?event_id={ev.id}").status_code == 200          # ver sí
        r = client.post("/api/register", data={"event_id": ev.id, "id": "1", "first_name": "A", "last_name": "B"})
        assert r.status_code == 403                                                    # registrar no, ni siquiera admin
        assert "No se puede registrar" in r.json()["detail"]


def test_event_cannot_go_back_to_created_once_it_has_people(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    login(client, "root")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "creado"}).status_code == 200   # vacío: se puede
    client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso"})
    factory.person(ev)
    back = client.patch(f"/api/events/{ev.id}", json={"status": "creado"})
    assert back.status_code == 400 and "no se puede devolver" in back.json()["detail"]
    assert client.patch(f"/api/events/{ev.id}", json={"status": "finalizado"}).status_code == 200
    assert client.patch(f"/api/events/{ev.id}", json={"status": "inventado"}).status_code == 400


# ------------------------------- registro -------------------------------
def test_manual_register_then_duplicate_warning(client, factory):
    factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff("digitador", "9990002"))
    login(client, "9990002")
    data = {"event_id": ev.id, "id": "555", "first_name": "Luz", "last_name": "Mora"}
    first = client.post("/api/register", data=data)
    assert first.status_code == 200 and "registrado" in first.json()["message"].lower()
    again = client.post("/api/register", data=data)
    assert again.json().get("result") == "DUPLICADO"


def test_checkin_by_cedula_falls_back_to_name_then_not_found(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", "Ana", "Prueba", attend=False)
    login(client, "root")
    ok = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001"}).json()
    assert ok["result"] == "SÍ" and ok["data"]["first_name"] == "Ana"
    # cédula que no existe + nombre que sí: no acredita solo, propone a la persona por nombre
    by_name = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "9999", "first_name": "Ana", "last_name": "Prueba"}).json()
    assert by_name["result"] == "NO_MATCH" and [m["id"] for m in by_name["name_matches"]] == ["1001"]
    nothing = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "9999", "first_name": "Zzz", "last_name": "Qqq"}).json()
    assert nothing["result"] == "NO_MATCH" and nothing["name_matches"] == []


def test_checkin_needs_confirmation_when_auto_register_is_off(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=False)
    factory.person(ev, "1001", attend=False)
    login(client, "root")
    pending = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001"}).json()
    assert pending["result"] == "FOUND_PENDING"
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "confirm": "true"}).json()["result"] == "SÍ"
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "confirm": "true"}).json()["result"] == "DUPLICADO"


# ------------------------------- digitador edita (2026-09-23) -------------------------------
def test_digitador_can_edit_and_mark_registered_but_not_undo_or_delete(client, factory):
    digi = factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso")
    factory.authorize(ev, digi)
    factory.person(ev, "1001", attend=True)
    login(client, "9990001")
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "Ingeniera"}).status_code == 200
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"}).status_code == 200
    assert client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "no_registrado"}).status_code == 403
    assert client.delete(f"/api/users/1001?event_id={ev.id}").status_code == 403
    assert client.put(f"/api/users/1001/cedula?event_id={ev.id}", json={"new_id": "2002"}).status_code == 403
    users = client.get(f"/api/users?event_id={ev.id}").json()
    assert users[0]["role"] == "Ingeniera" and users[0]["status"] != "No registrado"


def test_cliente_cannot_edit_people(client, factory):
    cli = factory.staff("cliente", "cli")
    ev = factory.event("en_proceso")
    factory.authorize(ev, cli)
    factory.person(ev, "1001")
    login(client, "cli")
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"role": "x"}).status_code == 403


# ------------------------------- reporte en hora local -------------------------------
def test_registration_report_shows_local_time_not_utc(factory, db, tmp_path):
    import openpyxl
    from app.models import AccessLog
    from app.reports import ReportManager

    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    # 15:00 UTC = 10:00 en Bogotá (UTC-5, sin horario de verano)
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, record_type="Nuevo",
                     registration_method="tradicional", timestamp=datetime(2026, 1, 15, 15, 0, 5)))
    db.commit()
    path = str(tmp_path / "r.xlsx")
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, path)
    rows = list(openpyxl.load_workbook(path).active.iter_rows(values_only=True))
    header = next(r for r in rows if r and "Hora de Registro" in r)
    row = next(r for r in rows[rows.index(header) + 1:] if r[0] == "1001")
    assert row[header.index("Fecha de Registro")] == "2026-01-15"
    assert row[header.index("Hora de Registro")] == "10:00:05"
