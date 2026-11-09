"""Turnos y filas (Fase 8). Escritas sin poder correr la base local: la lógica pura se probó a mano; las de API corren en el CI."""
import io

import pytest

from app import queue_svc, queue_turns as qt
from tests.conftest import login


def _lanes():
    return qt.clean_config({"lanes": [{"letter": "A"}, {"letter": "B"}]})["lanes"]


def test_labels_and_config():
    assert qt.label("A", 1) == "A1"
    assert [l["letter"] for l in qt.clean_config({"lanes": ["a", "b"]})["lanes"]] == ["A", "B"]
    with pytest.raises(qt.QueueError):
        qt.clean_config({"lanes": ["A", "A"]})
    with pytest.raises(qt.QueueError):
        qt.clean_config({"mode": "otro"})


def test_alpha_order_and_round_robin():
    people = [{"user_id": "3", "first_name": "Zoe", "last_name": "Bravo"}, {"user_id": "1", "first_name": "Ana", "last_name": "Alvarez"}, {"user_id": "2", "first_name": "Luis", "last_name": "Castro"}]
    out = qt.assign_numbers(qt.order_people("alpha", people), _lanes())
    assert [(o["user_id"], o["lane"], o["number"]) for o in out] == [("1", "A", 1), ("2", "B", 1), ("3", "A", 2)]


def test_manual_rows_report_problems_without_cedulas():
    rows = [["Cédula", "Orden", "Fila"], ["111", 2, "A"], ["222", 1, "B"], ["111", 3, "A"], ["", 4, "A"], ["333", 5, "Z"]]
    res = qt.parse_manual_rows(rows, _lanes())
    assert [p["user_id"] for p in res["people"]][:2] == ["222", "111"]
    assert res["duplicates"] and res["errors"]


def _setup(client, factory, mode="arrival", lanes=None, **cfg):
    coord = factory.staff("coordinador", tenant_id="acme")
    ev = factory.event(coordinator=coord)
    assert login(client, coord.username).status_code in (200, 302, 303)
    r = client.put(f"/api/events/{ev.id}/queue/config", json={"enabled": True, "config": {"mode": mode, "lanes": lanes or ["A"], **cfg}})
    assert r.status_code == 200, r.text
    return coord, ev


def test_config_requires_lanes_valid(client, factory):
    coord = factory.staff("coordinador", tenant_id="acme")
    ev = factory.event(coordinator=coord)
    login(client, coord.username)
    assert client.put(f"/api/events/{ev.id}/queue/config", json={"enabled": True, "config": {"lanes": ["1"]}}).status_code == 400


def test_arrival_public_flow_and_call(client, factory, db):
    from app.models import AccessLog
    coord, ev = _setup(client, factory, require_registered=True)
    factory.person(ev, "1001", "Ana", "Uno")
    factory.person(ev, "1002", "Luis", "Dos")
    factory.person(ev, "9999", "Fuera", "Evento", attend=False)
    db.add(AccessLog(tenant_id="acme", user_id="1001", event_id=ev.id, record_type="entrada"))
    db.commit()
    pub = client
    # sin acreditar: no hay turno; no confirma nada más
    assert pub.post(f"/turno/{ev.id}/buscar", json={"cedula": "1002"}).status_code == 404
    assert pub.post(f"/turno/{ev.id}/buscar", json={"cedula": "9999"}).status_code == 404
    r = pub.post(f"/turno/{ev.id}/buscar", json={"cedula": "1001"})
    assert r.status_code == 200
    token = r.json()["token"]
    st = pub.get(f"/turno/{ev.id}/{token}/state").json()
    assert st["label"] == "A1" and st["ahead"] == 0 and not st["your_turn"]
    assert "1001" not in str(st) and "name" in st
    # misma cédula: mismo turno
    assert pub.post(f"/turno/{ev.id}/buscar", json={"cedula": "1001"}).json()["token"] == token
    # llamar
    c = client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "A", "desk": "Mesa 1"})
    assert c.status_code == 200 and c.json()["called"] == "A1"
    queue_svc.invalidate(ev.id)
    st = pub.get(f"/turno/{ev.id}/{token}/state").json()
    assert st["your_turn"] is True
    tv = client.get(f"/api/events/{ev.id}/queue/tv").json()
    assert tv["lanes"][0]["serving"]["label"] == "A1" and tv["recent"][0]["label"] == "A1"


def test_prueba_person_never_gets_turn(client, factory, db):
    coord, ev = _setup(client, factory, mode="alpha")
    factory.person(ev, "1001")
    r = client.post(f"/api/events/{ev.id}/queue/assign", json={})
    assert r.status_code == 200 and r.json()["created"] == 1          # la persona «PRUEBA» del evento no cuenta
    assert client.post(f"/turno/{ev.id}/buscar", json={"cedula": "PRUEBA"}).status_code == 404


def test_skip_requeue_and_call_order(client, factory):
    coord, ev = _setup(client, factory, mode="alpha")
    for i, (n, a) in enumerate((("Ana", "Alvarez"), ("Beto", "Benitez"), ("Cami", "Castro")), start=1):
        factory.person(ev, f"10{i}", n, a)
    assert client.post(f"/api/events/{ev.id}/queue/assign", json={}).json()["created"] == 3
    assert client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "A"}).json()["called"] == "A1"
    listing = client.get(f"/api/events/{ev.id}/queue").json()["listing"]
    a2 = next(t for t in listing["waiting"] if t["label"] == "A2")
    assert client.post(f"/api/events/{ev.id}/queue/turns/{a2['id']}/skip").status_code == 200
    assert client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "A"}).json()["called"] == "A3"
    assert client.post(f"/api/events/{ev.id}/queue/turns/{a2['id']}/requeue").status_code == 200
    assert client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "A"}).json()["called"] == "A2"
    assert client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "A"}).json()["called"] is None
    # asignar de nuevo no duplica ni cambia números
    assert client.post(f"/api/events/{ev.id}/queue/assign", json={}).json()["created"] == 0


def test_manual_excel_upload(client, factory):
    from openpyxl import Workbook
    coord, ev = _setup(client, factory, mode="manual", lanes=["A", "B"])
    factory.person(ev, "111")
    factory.person(ev, "222")
    wb = Workbook()
    ws = wb.active
    ws.append(["Cédula", "Orden", "Fila"])
    ws.append(["222", 1, "B"])
    ws.append(["111", 2, "A"])
    ws.append(["555", 3, "A"])            # no está en el evento
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/events/{ev.id}/queue/upload", files={"file": ("t.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2 and r.json()["unknown"] == 1
    assert client.post(f"/api/events/{ev.id}/queue/call", json={"lane": "B"}).json()["called"] == "B1"


def test_public_closed_when_disabled(client, factory):
    ev = factory.event()
    assert client.get(f"/turno/{ev.id}").status_code == 404
    assert client.post(f"/turno/{ev.id}/buscar", json={"cedula": "1"}).status_code == 404


def test_digitador_cannot_configure(client, factory):
    dig = factory.staff("digitador", tenant_id="acme")
    ev = factory.event()
    factory.authorize(ev, dig)
    login(client, dig.username)
    assert client.put(f"/api/events/{ev.id}/queue/config", json={"enabled": True, "config": {}}).status_code == 403
