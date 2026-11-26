"""Subcategorías de zonas e inventario (0140): límites por persona (el del grupo manda), reingresos, estadísticas y reportes."""
from tests.conftest import login


def _setup(client, factory, people=("1001", "1002")):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    for p in people:
        factory.person(ev, p, f"P{p}", "Prueba")
    login(client, "root")
    client.put(f"/api/events/{ev.id}/modules", json={"inventory_enabled": True, "areas_enabled": True})
    return ev


def _area(client, ev, name, **kw):
    r = client.post(f"/api/events/{ev.id}/areas", json={"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, ev, name, qty=10, **kw):
    r = client.post(f"/api/events/{ev.id}/inventory", json={"name": name, "initial_qty": qty, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _move(client, ev, area_id, cedula, direction="in"):
    return client.post(f"/api/events/{ev.id}/areas/{area_id}/movement", json={"cedula": cedula, "direction": direction}).json()


def _deliver(client, ev, cedula, *lines):
    return client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": cedula, "items": [{"item_id": i, "qty": q} for i, q in lines]})


# ------------------------------------------------------------------------------------------ estructura

def test_subcategories_are_one_level_and_the_group_cannot_receive_movements(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A")
    a = _area(client, ev, "Entrada A", parent_id=salon["id"])
    assert a["parent_id"] == salon["id"]
    deep = client.post(f"/api/events/{ev.id}/areas", json={"name": "Puerta 1", "parent_id": a["id"]})
    assert deep.status_code == 400 and "un nivel" in deep.json()["detail"]
    groups = {x["name"]: x for x in client.get(f"/api/events/{ev.id}/areas").json()}
    assert groups["Salón A"]["is_group"] is True and groups["Entrada A"]["is_group"] is False
    r = client.post(f"/api/events/{ev.id}/areas/{salon['id']}/movement", json={"cedula": "1001", "direction": "in"})
    assert r.status_code == 400 and "subcategor" in r.json()["detail"]


def test_a_group_cannot_become_a_subcategory_and_limits_are_validated(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A")
    _area(client, ev, "Entrada A", parent_id=salon["id"])
    otro = _area(client, ev, "Salón B")
    r = client.patch(f"/api/events/{ev.id}/areas/{salon['id']}", json={"parent_id": otro["id"]})
    assert r.status_code == 400
    assert client.patch(f"/api/events/{ev.id}/areas/{otro['id']}", json={"max_per_person": 0}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}/areas/{otro['id']}", json={"max_per_person": ""}).json()["max_per_person"] is None


# ------------------------------------------------------------------------------------------ zonas

def test_group_without_reentry_blocks_the_other_subcategory(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A", allow_reentry=False)
    a = _area(client, ev, "Entrada A", parent_id=salon["id"])
    b = _area(client, ev, "Entrada B", parent_id=salon["id"])
    assert _move(client, ev, a["id"], "1001")["result"] == "OK"
    blocked = _move(client, ev, b["id"], "1001")
    assert blocked["result"] == "ALREADY_ENTERED" and "Salón A" in blocked["details"]
    assert _move(client, ev, b["id"], "1002")["result"] == "OK"          # otra persona sí


def test_group_with_reentry_counts_two_entries_for_one_person(client, factory):
    from app import subcat
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A", allow_reentry=True)
    a = _area(client, ev, "Entrada A", parent_id=salon["id"])
    b = _area(client, ev, "Entrada B", parent_id=salon["id"])
    assert _move(client, ev, a["id"], "1001")["result"] == "OK"
    assert _move(client, ev, b["id"], "1001")["result"] == "OK"
    data = client.get(f"/api/events/{ev.id}/stats/data", params={"variable": f"zona:{salon['id']}"}).json()
    labels = {x["label"]: x["count"] for x in data["buckets"]}
    assert labels["TOTAL «Salón A»: personas únicas"] == 1 and labels["TOTAL «Salón A»: entradas"] == 2
    assert labels["Entrada A (personas únicas)"] == 1 and labels["Entrada B (personas únicas)"] == 1
    keys = [v["label"] for v in client.get(f"/api/events/{ev.id}/stats/variables").json() if v["key"].startswith("zona:")]
    assert f"Zona: Salón A{subcat.SEP}Entrada A" in keys


def test_group_entry_limit_predominates_over_the_subcategory_limit(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A", max_per_person=2)
    a = _area(client, ev, "Entrada A", parent_id=salon["id"], max_per_person=5)
    b = _area(client, ev, "Entrada B", parent_id=salon["id"])
    assert _move(client, ev, a["id"], "1001")["result"] == "OK"
    assert _move(client, ev, a["id"], "1001", "out")["result"] == "OK"
    assert _move(client, ev, b["id"], "1001")["result"] == "OK"
    third = _move(client, ev, a["id"], "1001", "in")
    assert third["result"] == "LIMIT" and "Salón A" in third["details"]       # 2 en el grupo aunque A permita 5


def test_subcategory_own_limit_applies(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A")
    a = _area(client, ev, "Entrada A", parent_id=salon["id"], max_per_person=1)
    assert _move(client, ev, a["id"], "1001")["result"] == "OK"
    _move(client, ev, a["id"], "1001", "out")
    assert _move(client, ev, a["id"], "1001")["result"] == "LIMIT"


def test_zone_stats_exclude_the_test_person_and_respect_the_toggle(client, factory):
    ev = _setup(client, factory)
    suelta = _area(client, ev, "VIP")
    off = _area(client, ev, "Backstage", stats_enabled=False)
    _move(client, ev, suelta["id"], "1001")
    keys = [v["key"] for v in client.get(f"/api/events/{ev.id}/stats/variables").json()]
    assert f"zona:{suelta['id']}" in keys and f"zona:{off['id']}" not in keys
    assert client.get(f"/api/events/{ev.id}/stats/data", params={"variable": f"zona:{off['id']}"}).status_code == 400
    data = client.get(f"/api/events/{ev.id}/stats/data", params={"variable": f"zona:{suelta['id']}"}).json()
    assert {x["label"]: x["count"] for x in data["buckets"]} == {"Personas únicas": 1, "Entradas": 1}


def test_archiving_a_group_archives_its_subcategories_and_restore_needs_the_parent(client, factory):
    ev = _setup(client, factory)
    salon = _area(client, ev, "Salón A")
    a = _area(client, ev, "Entrada A", parent_id=salon["id"])
    assert client.post(f"/api/events/{ev.id}/areas/{salon['id']}/archive").status_code == 200
    rows = {x["name"]: x for x in client.get(f"/api/events/{ev.id}/areas", params={"include_archived": True}).json()}
    assert rows["Entrada A"]["archived"] is True
    assert client.post(f"/api/events/{ev.id}/areas/{a['id']}/restore").status_code == 400
    assert client.post(f"/api/events/{ev.id}/areas/{salon['id']}/restore").status_code == 200
    assert client.post(f"/api/events/{ev.id}/areas/{a['id']}/restore").status_code == 200


# ------------------------------------------------------------------------------------------ inventario

def test_group_limit_applies_across_subcategories(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0, max_per_person=1)
    ham = _item(client, ev, "Hamburguesa", parent_id=comida["id"], qty=10)
    perro = _item(client, ev, "Perro", parent_id=comida["id"], qty=10)
    assert _deliver(client, ev, "1001", (ham["id"], 1)).status_code == 200
    r = _deliver(client, ev, "1001", (perro["id"], 1))
    assert r.status_code == 409 and "Comida" in r.json()["detail"]
    assert "Esta persona ya recibió «Comida»: Hamburguesa" in r.json()["detail"] and "Solo se permite 1 por persona" in r.json()["detail"]      # 26-nov-2026: dice qué recibió
    assert _deliver(client, ev, "1002", (perro["id"], 1)).status_code == 200


def test_subcategory_can_allow_two_while_group_allows_two(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0, max_per_person=2)
    perro = _item(client, ev, "Perro", parent_id=comida["id"], qty=10, allow_multiple=True, allow_repeat_delivery=True, max_per_person=2)
    assert _deliver(client, ev, "1001", (perro["id"], 2)).status_code == 200
    assert _deliver(client, ev, "1001", (perro["id"], 1)).status_code == 409


def test_group_limit_counts_a_combo_in_the_same_request(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0, max_per_person=1)
    ham = _item(client, ev, "Hamburguesa", parent_id=comida["id"])
    perro = _item(client, ev, "Perro", parent_id=comida["id"])
    r = _deliver(client, ev, "1001", (ham["id"], 1), (perro["id"], 1))
    assert r.status_code == 409
    stock = {i["name"]: i for i in client.get(f"/api/events/{ev.id}/inventory").json()}
    assert stock["Comida"]["delivered"] == 0


def test_group_cannot_be_delivered_and_its_totals_sum_the_subcategories(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0)
    ham = _item(client, ev, "Hamburguesa", parent_id=comida["id"], qty=10)
    _item(client, ev, "Perro", parent_id=comida["id"], qty=5)
    assert _deliver(client, ev, "1001", (comida["id"], 1)).status_code == 400
    assert _deliver(client, ev, "1001", (ham["id"], 1)).status_code == 200
    stock = {i["name"]: i for i in client.get(f"/api/events/{ev.id}/inventory").json()}
    assert stock["Comida"]["is_group"] and stock["Comida"]["initial_qty"] == 15 and stock["Comida"]["delivered"] == 1 and stock["Comida"]["available"] == 14


def test_inventory_stats_group_and_subcategories(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0)
    ham = _item(client, ev, "Hamburguesa", parent_id=comida["id"], qty=10)
    perro = _item(client, ev, "Perro", parent_id=comida["id"], qty=10, stats_enabled=False)
    _deliver(client, ev, "1001", (ham["id"], 1))
    _deliver(client, ev, "1002", (perro["id"], 1))
    data = client.get(f"/api/events/{ev.id}/stats/data", params={"variable": f"inv:{comida['id']}"}).json()
    labels = {x["label"]: x["count"] for x in data["buckets"]}
    assert labels["Hamburguesa (unidades entregadas)"] == 1 and "Perro (unidades entregadas)" not in labels
    assert labels["TOTAL «Comida»: unidades"] == 2 and labels["TOTAL «Comida»: personas atendidas"] == 2


def test_delivery_report_and_recent_list_use_the_group_label(client, factory):
    ev = _setup(client, factory)
    comida = _item(client, ev, "Comida", qty=0)
    ham = _item(client, ev, "Hamburguesa", parent_id=comida["id"])
    _deliver(client, ev, "1001", (ham["id"], 1))
    assert client.get(f"/api/events/{ev.id}/inventory/deliveries").json()[0]["item"] == "Comida › Hamburguesa"
    assert client.get(f"/api/events/{ev.id}/inventory-report").status_code == 200
    assert client.get(f"/api/events/{ev.id}/areas-report").status_code == 200
