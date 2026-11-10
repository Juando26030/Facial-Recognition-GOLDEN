"""Fase 10, bloque A (con base de datos): permanencia en zonas, premio por estadía, entregas condicionadas, autoescaneo y calendario de inventario."""
from datetime import date, timedelta

import pytest

from app.models import AreaMovement, EventAttendee, EventInventoryItem, InventoryDelivery
from app.timeutil import utcnow
from tests.conftest import login


def _mv(db, ev, area_id, uid, direction, minutes_ago):
    db.add(AreaMovement(event_id=ev.id, area_id=area_id, user_id=uid, tenant_id=ev.tenant_id, direction=direction, method="cedula", timestamp=utcnow() - timedelta(minutes=minutes_ago)))


@pytest.fixture()
def setup(client, factory, db):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso", coordinator=coord, areas_enabled=True, inventory_enabled=True, start_date=date.today(), end_date=date.today(),
                       event_time_start="00:00", event_time_end="23:59")
    for uid in ("1001", "1002", "1003"):
        factory.person(ev, uid)
    factory.person(ev, "PRUEBA", first_name="Prueba")
    login(client, "coord")
    area = client.post(f"/api/events/{ev.id}/areas", json={"name": "Salón"}).json()
    return ev, area


def _cfg(client, ev, **body):
    return client.put(f"/api/events/{ev.id}/areas-dwell/config", json=body)


def test_stats_need_the_switch_and_config_is_validated(client, setup):
    ev, _ = setup
    assert client.get(f"/api/events/{ev.id}/areas-dwell").status_code == 409
    assert _cfg(client, ev, prize_enabled=True).status_code == 400          # el premio necesita el conteo
    assert _cfg(client, ev, dwell_enabled=True, reference_minutes=0).status_code == 400
    assert _cfg(client, ev, dwell_enabled=True, threshold_pct=150).status_code == 400
    r = _cfg(client, ev, dwell_enabled=True, prize_enabled=True, reference_minutes=100, threshold_pct=80)
    assert r.status_code == 200 and r.json()["effective_reference_minutes"] == 100 and r.json()["prize_enabled"] is True
    assert client.get(f"/api/events/{ev.id}/areas-dwell/config").json()["threshold_pct"] == 80


def test_minutes_accumulate_and_the_test_person_never_counts(client, setup, db):
    ev, area = setup
    _cfg(client, ev, dwell_enabled=True, prize_enabled=True, reference_minutes=100, threshold_pct=80)
    _mv(db, ev, area["id"], "1001", "in", 60); _mv(db, ev, area["id"], "1001", "out", 30)         # 30 min
    _mv(db, ev, area["id"], "1001", "in", 20); _mv(db, ev, area["id"], "1001", "out", 10)         # +10 min
    _mv(db, ev, area["id"], "1002", "in", 200); _mv(db, ev, area["id"], "1002", "out", 100)       # 100 min
    _mv(db, ev, area["id"], "PRUEBA", "in", 500); _mv(db, ev, area["id"], "PRUEBA", "out", 10)
    db.commit()
    d = client.get(f"/api/events/{ev.id}/areas-dwell").json()
    by_id = {r["id"]: r for r in d["rows"]}
    assert set(by_id) == {"1001", "1002"} and by_id["1001"]["minutes"] == 40.0 and by_id["1002"]["meets"] is True and by_id["1001"]["meets"] is False
    assert d["summary"]["people"] == 2 and d["summary"]["qualifying"] == 1
    assert client.get(f"/api/events/{ev.id}/areas-dwell?pct=40&only=cumple").json()["summary"]["qualifying"] == 2


def test_export_csv_and_xlsx_only_those_who_meet(client, setup, db):
    ev, area = setup
    _cfg(client, ev, dwell_enabled=True, reference_minutes=100, threshold_pct=80)
    _mv(db, ev, area["id"], "1002", "in", 200); _mv(db, ev, area["id"], "1002", "out", 100)
    _mv(db, ev, area["id"], "1001", "in", 20); _mv(db, ev, area["id"], "1001", "out", 10)
    db.commit()
    r = client.get(f"/api/events/{ev.id}/areas-dwell/export?fmt=csv&only=cumple")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    assert "1002" in text and "1001" not in text.split("\n", 1)[1]
    x = client.get(f"/api/events/{ev.id}/areas-dwell/export?fmt=xlsx&only=todos")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_apply_certificates_grants_only_to_qualifiers(client, setup, db):
    ev, area = setup
    _cfg(client, ev, dwell_enabled=True, prize_enabled=True, reference_minutes=100, threshold_pct=80)
    _mv(db, ev, area["id"], "1002", "in", 200); _mv(db, ev, area["id"], "1002", "out", 100)
    db.commit()
    r = client.post(f"/api/events/{ev.id}/areas-dwell/apply-certificates", json={})
    assert r.status_code == 200 and r.json()["granted"] == 1
    flags = {a.user_id: a.certificate for a in db.query(EventAttendee).filter_by(event_id=ev.id)}
    assert flags["1002"] is True and not flags["1001"] and not flags["PRUEBA"]


def test_only_coordinador_or_above_and_not_comercial(client, factory, setup):
    ev, _ = setup
    client.post("/logout")
    factory.staff("digitador", "dig")
    login(client, "dig")
    assert client.get(f"/api/events/{ev.id}/areas-dwell/config").status_code == 403
    client.post("/logout")
    factory.staff("comercial", "com")
    login(client, "com")
    assert client.get(f"/api/events/{ev.id}/areas-dwell/config").status_code == 403


def test_inventory_item_with_dwell_requirement_blocks_those_who_do_not_qualify(client, setup, db):
    ev, area = setup
    _cfg(client, ev, dwell_enabled=True, prize_enabled=True, reference_minutes=100, threshold_pct=80)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Medalla", "initial_qty": 5, "requires_dwell": True}).json()
    assert item["requires_dwell"] is True
    _mv(db, ev, area["id"], "1002", "in", 200); _mv(db, ev, area["id"], "1002", "out", 100)
    db.commit()
    body = lambda cedula: {"cedula": cedula, "items": [{"item_id": item["id"], "qty": 1}]}
    assert client.post(f"/api/events/{ev.id}/inventory/deliver", json=body("1001")).status_code == 409
    assert client.post(f"/api/events/{ev.id}/inventory/deliver", json=body("1002")).status_code == 200
    assert db.query(InventoryDelivery).filter_by(event_id=ev.id).count() == 1
    # sin el premio activo la condición no se exige
    _cfg(client, ev, prize_enabled=False)
    assert client.post(f"/api/events/{ev.id}/inventory/deliver", json=body("1001")).status_code == 200


def test_areas_autoscan_registers_without_confirming(client, setup):
    ev, area = setup
    body = {"cedula": "1001", "direction": "in"}
    first = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json=body).json()
    assert first["result"] == "FOUND_PENDING"
    _cfg(client, ev, areas_autoscan=True)
    second = client.post(f"/api/events/{ev.id}/areas/{area['id']}/movement", json=body).json()
    assert second["result"] == "OK" and second["direction"] == "in"


def test_kiosk_pages_expose_the_autoscan_flags(client, setup):
    ev, _ = setup
    _cfg(client, ev, inventory_autoscan=True, areas_autoscan=True)
    assert "window.AUTOSCAN = true" in client.get(f"/kiosk/{ev.id}/inventario").text
    assert "Escaneo automático activo" in client.get(f"/kiosk/{ev.id}/areas").text
    assert 'id="dwellBox"' in client.get(f"/kiosk/{ev.id}/parametros").text


# ---------------------------------------------------------------- inventario: catálogo y calendario
def _catalog(client):
    cat = client.post("/api/inventory/categories", json={"name": "Audio"}).json()
    cat2 = client.post("/api/inventory/categories", json={"name": "Luces"}).json()
    prod = client.post("/api/inventory/products", json={"name": "Parlante", "category_id": cat["id"], "stock": 6}).json()
    return cat, cat2, prod


def test_overview_calendar_and_manage(client, factory, db):
    factory.staff("super_admin", "sup")
    factory.staff("admin", "adm")
    factory.staff("coordinador", "alm", extra_roles="almacen")
    factory.staff("coordinador", "coord2")
    today = date.today()
    e1 = factory.event("creado", start_date=today, end_date=today + timedelta(days=2), setup_date=today - timedelta(days=1))
    e2 = factory.event("creado", start_date=today + timedelta(days=2), end_date=today + timedelta(days=3))
    login(client, "sup")
    cat, cat2, prod = _catalog(client)
    db.add(EventInventoryItem(event_id=e1.id, product_id=prod["id"], qty_assigned=4))
    db.add(EventInventoryItem(event_id=e2.id, product_id=prod["id"], qty_assigned=3))
    db.commit()
    ov = client.get("/api/inventory/overview").json()
    p = ov["products"][0]
    assert p["in_use"] == 4 and p["available"] == 2 and ov["can_manage"] and ov["can_edit_catalog"]
    cal = client.get(f"/api/inventory/calendar?start={today}&end={today + timedelta(days=4)}").json()
    assert {e["id"] for e in cal["events"]} == {e1.id, e2.id}
    assert cal["daily"][str(today + timedelta(days=2))][str(prod["id"])] == 7          # 4 + 3: se cruzan ese día
    assert cal["events"][0]["lines"][0]["assigned"] in (3, 4)
    assert client.get(f"/api/inventory/calendar?start={today}&end={today + timedelta(days=400)}").status_code == 400
    assert client.get("/api/inventory/calendar?start=mal&end=peor").status_code == 400
    client.post("/logout")
    for who, ok in (("adm", True), ("alm", True), ("coord2", False)):
        login(client, who)
        r = client.patch(f"/api/inventory/products/{prod['id']}/manage", json={"stock": 9, "category_id": cat2["id"]})
        assert (r.status_code == 200) is ok, (who, r.text)
        client.post("/logout")
    login(client, "adm")
    assert client.get("/api/inventory/overview").json()["products"][0]["stock"] == 9
    assert client.post("/api/inventory/products", json={"name": "Otro"}).status_code == 403          # crear sigue siendo del Super Admin
    assert client.patch(f"/api/inventory/products/{prod['id']}/manage", json={"name": "x"}).status_code == 400


def test_calendar_hides_event_names_the_account_cannot_see_but_counts_them(client, factory, db, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    factory.staff("super_admin", "sup")
    other = factory.staff("coordinador", "coord3")
    mine = factory.event("creado", coordinator=other, start_date=date.today(), end_date=date.today())
    theirs = factory.event("creado", start_date=date.today(), end_date=date.today())          # sin coordinador: coord3 no pertenece
    login(client, "sup")
    _, _, prod = _catalog(client)
    db.add(EventInventoryItem(event_id=mine.id, product_id=prod["id"], qty_assigned=1))
    db.add(EventInventoryItem(event_id=theirs.id, product_id=prod["id"], qty_assigned=2))
    db.commit()
    client.post("/logout")
    login(client, "coord3")
    cal = client.get(f"/api/inventory/calendar?start={date.today()}&end={date.today()}").json()
    assert [e["id"] for e in cal["events"]] == [mine.id]
    assert cal["daily"][str(date.today())][str(prod["id"])] == 3          # la disponibilidad cuenta todos los eventos
