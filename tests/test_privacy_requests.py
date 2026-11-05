"""Solicitudes de privacidad: radicado AÑO-CONSECUTIVO, fechas límite en días hábiles, bandera «reclamo en trámite» desde el panel y export-person-data (mapa de datos sin valores)."""
import json
import re
from datetime import date

from app import privacy_requests as pr
from app.models import PrivacyRequest
from tests.conftest import accept, login


def test_radicado_is_year_dash_consecutive_and_restarts_each_year(db):
    assert [pr.next_radicado(db, 2026) for _ in range(3)] == ["2026-0001", "2026-0002", "2026-0003"]
    assert pr.next_radicado(db, 2027) == "2027-0001"
    assert pr.next_radicado(db, 2026) == "2026-0004"
    db.commit()


def test_due_dates_count_business_days_skipping_weekends_and_colombian_holidays():
    received = date(2026, 10, 6)                                                       # martes; el lunes 12 de octubre es festivo
    assert pr.add_business_days(received, 10) == date(2026, 10, 21)                   # consulta: 10 días hábiles
    assert pr.add_business_days(received, 15) == date(2026, 10, 28)                   # reclamo: 15 días hábiles
    assert pr.add_business_days(received, 2) == date(2026, 10, 8)                     # bandera «reclamo en trámite»: máximo 2 días hábiles
    assert pr.add_business_days(date(2026, 10, 9), 1) == date(2026, 10, 13)           # viernes → martes (fin de semana y festivo)


def _admin(client, factory, role="admin"):
    factory.staff(role, "adm")
    login(client, "adm")


def test_only_admins_use_the_panel_and_a_request_needs_its_basic_data(client, factory):
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/privacy-requests").status_code == 403
    client.post("/api/auth/logout")
    _admin(client, factory)
    assert client.post("/api/privacy-requests", json={"channel": "email", "request_type": "reclamo"}).status_code == 400
    assert client.post("/api/privacy-requests", json={"channel": "paloma", "request_type": "reclamo", "holder_name": "Ana", "cedula": "1001"}).status_code == 400


def test_a_claim_gets_a_radicado_a_deadline_and_the_in_progress_flag_with_its_history(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    r = client.post("/api/privacy-requests", json={"channel": "email", "request_type": "reclamo", "holder_name": "Ana Mora", "cedula": "1001", "event_id": ev.id}).json()
    assert r["radicado"].endswith("-0001") and r["radicado"][:4] == str(date.today().year) and r["status"] == "recibida" and r["claim_flag"] is False
    assert r["claim_flag_due"] is not None and r["due_date"] > r["claim_flag_due"]
    assert client.get("/api/privacy-requests/claim/1001").json() == {"claim_in_progress": False, "radicado": None}
    on = client.put(f"/api/privacy-requests/{r['id']}/claim-flag", json={"active": True}).json()
    assert on["claim_flag"] is True and on["status"] == "en_tramite"
    assert client.get("/api/privacy-requests/claim/1001").json() == {"claim_in_progress": True, "radicado": r["radicado"]}
    done = client.put(f"/api/privacy-requests/{r['id']}/status", json={"status": "resuelta"}).json()
    assert done["claim_flag"] is False and done["status"] == "resuelta"                                 # resuelto el reclamo, la leyenda se quita sola
    assert client.put(f"/api/privacy-requests/{r['id']}/claim-flag", json={"active": True}).status_code == 400      # cerrada: no se reactiva
    actions = [h["action"] for h in done["history"]]
    assert any("Radicada" in a for a in actions) and any("ACTIVADA" in a for a in actions) and any("resuelta" in a for a in actions) and all(h["by"] for h in done["history"])
    second = client.post("/api/privacy-requests", json={"channel": "presencial", "request_type": "consulta", "holder_name": "Luis", "cedula": "2002"}).json()
    assert second["radicado"].endswith("-0002") and second["claim_flag_due"] is None                  # una consulta no lleva bandera
    assert client.put("/api/privacy-requests/9999/status", json={"status": "resuelta"}).status_code == 404


def test_overdue_requests_and_late_flags_are_marked(db):
    req = pr.create(db, channel="email", holder_name="Ana", cedula="1001", request_type="reclamo", tenant_id=None, event_id=None, staff_id=1, received=date(2026, 9, 1))
    db.commit()
    d = pr.as_dict(db.query(PrivacyRequest).one(), today=date(2026, 10, 6))
    assert d["overdue"] is True and d["claim_flag_overdue"] is True and req.radicado == "2026-0001"
    pr.set_claim_flag(req, True, 1)
    assert pr.as_dict(req, today=date(2026, 10, 6))["claim_flag_overdue"] is False


def test_export_person_data_is_a_map_of_what_exists_with_no_values_and_no_cedula(db, factory, capsys, monkeypatch):
    from app import ops_runner
    from app.models import AccessLog, EventAttendee, User
    ev = factory.event("en_proceso", facial_enabled=True)
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="Ana", last_name="Mora", email="ana@x.test", phone="3001112233", face_encoding="[[0.1]]"))
    db.flush()
    db.add(EventAttendee(event_id=ev.id, user_id="1001", tenant_id=ev.tenant_id))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, record_type="Existente", client_id="c1"))
    db.commit()
    accept(db, ev, "1001")
    pr.create(db, channel="email", holder_name="Ana Mora", cedula="1001", request_type="reclamo", tenant_id=ev.tenant_id, event_id=ev.id, staff_id=1)
    db.commit()
    monkeypatch.setenv("EXPORT_CEDULA", "1001")
    assert ops_runner.main("export-person-data") == 0
    out = capsys.readouterr().out
    line0 = next(l for l in out.splitlines() if l.startswith('{"ops"'))
    line0 = re.sub(r'"fecha": "[^"]*"', '"fecha": "-"', line0)
    line0 = re.sub(r"\d{4}-\d{2}-\d{2}[T ][\d:.+Z-]+", "-", line0)                                   # cualquier otra hora ISO: sus microsegundos al azar a veces contienen «0.1»                                 # las fechas llevan microsegundos al azar («0.1» sale cuando el segundo termina en 0)
    assert "1001" not in line0 and "Ana" not in line0 and "ana@x.test" not in line0 and "3001112233" not in line0 and "0.1" not in line0          # ni valores personales ni la cédula ni el vector
    line = next(l for l in out.splitlines() if l.startswith('{"ops"'))                               # el resto pueden ser líneas de log de otras pruebas
    data = json.loads(json.loads(line)["results"]["export-person-data"]["detail"])
    assert data["personas"][0]["campos_con_dato"] == ["first_name", "last_name", "phone", "email"] and data["personas"][0]["tiene_vector_facial"] is True
    assert data["eventos_inscrito"] == 1 and data["ingresos"] == 1 and len(data["consentimientos"]) == 1 and data["consentimientos"][0]["acepto"] is True
    assert data["solicitudes_de_privacidad"] and data["suprimida"] is False


def test_export_person_data_needs_a_cedula(monkeypatch, capsys):
    from app import ops_runner
    monkeypatch.delenv("EXPORT_CEDULA", raising=False)
    assert ops_runner.main("export-person-data") == 1


def test_parameters_page_shows_the_requests_panel_only_to_admins(client, factory):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    login(client, "coord")
    assert "id=\"prTabla\"" not in client.get(f"/kiosk/{ev.id}/parametros").text
    client.post("/api/auth/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert "id=\"prTabla\"" in client.get(f"/kiosk/{ev.id}/parametros").text


def test_the_2026_holiday_list_matches_the_official_one():
    expected = {date(2026, m, d) for m, d in [(1, 1), (1, 12), (3, 23), (4, 2), (4, 3), (5, 1), (5, 18), (6, 8), (6, 15), (6, 29), (7, 20), (8, 7), (8, 17), (10, 12), (11, 2), (11, 16), (12, 8), (12, 25)]}
    assert pr.holidays_for_year(2026) == expected


def test_there_is_a_holiday_list_loaded_for_the_current_year(monkeypatch):
    """Si esta prueba falla (p. ej. al llegar 2027), falta cargar los festivos del año nuevo en HOLIDAYS_CO / app/privacy_requests.py: sin ellos los plazos de consultas y reclamos se contarían mal."""
    monkeypatch.delenv("HOLIDAYS_CO", raising=False)
    assert pr.holidays_for_year(date.today().year), f"No hay festivos cargados para {date.today().year}: actualiza HOLIDAYS_CO"
