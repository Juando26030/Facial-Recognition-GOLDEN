"""Fase 5 · inventario con catálogo: lógica pura y regla de cuadre (app/inventory.py), catálogo del Super Admin y líneas por evento (app/routers/inventory.py)."""
import pytest

from app import inventory as inv
from app.models import Event, EventInventoryItem, InventoryCategory, InventoryProduct
from tests.conftest import login


def R(name="Cable", assigned=0, out=0, returned=0, consumed=0, category_id=1, product_id=None):
    return inv.Row(name=name, assigned=assigned, out=out, returned=returned, consumed=consumed, category_id=category_id, product_id=product_id)


# ------------------------------------------------------------ lógica pura
def codes(rep):
    return sorted((i.level, i.code) for i in rep.issues)


def test_empty_inventory_always_balances():
    for stage in inv.STAGES:
        assert inv.check_balance([], stage).balanced
    assert inv.can_enter_in_progress([]).ok


def test_always_errors_returned_plus_consumed_over_out_and_out_over_assigned():
    rep = inv.check_balance([R(assigned=5, out=3, returned=2, consumed=2)], "creado")
    assert ("error", "over_returned") in codes(rep) and not rep.ok
    rep = inv.check_balance([R(assigned=2, out=3)], "creado")
    assert ("error", "over_assigned") in codes(rep)
    assert inv.check_balance([R(assigned=5, out=3, returned=1, consumed=2)], "creado").ok


def test_creado_allows_uncategorized_with_a_warning():
    rep = inv.check_balance([R(assigned=2, category_id=None)], "creado")
    assert rep.ok and codes(rep) == [("warn", "uncategorized")]


def test_en_proceso_needs_category_and_exact_sum():
    assert inv.can_enter_in_progress([R(assigned=4, out=4)]).ok
    rep = inv.can_enter_in_progress([R(assigned=4, out=4, category_id=None)])
    assert ("error", "uncategorized") in codes(rep)
    rep = inv.can_enter_in_progress([R(assigned=4, out=3)])
    assert codes(rep) == [("error", "short_out")] and "faltan 1" in rep.errors[0].message
    rep = inv.can_enter_in_progress([R(assigned=4, out=5)])
    assert ("error", "over_assigned") in codes(rep)


def test_cierre_unaccounted_is_a_warning_not_a_block():
    rep = inv.check_balance([R(assigned=4, out=4, returned=1, consumed=1)], "cierre")
    assert rep.ok and codes(rep) == [("warn", "unaccounted")] and not rep.balanced
    assert inv.check_balance([R(assigned=4, out=4, returned=3, consumed=1)], "cierre").balanced


def test_dict_rows_invalid_quantities_and_unknown_stage():
    rep = inv.check_balance([{"name": "X", "assigned": 1, "out": -1}], "creado")
    assert ("error", "invalid_qty") in codes(rep)
    with pytest.raises(inv.InventoryError):
        inv.check_balance([], "nada")
    assert inv.stage_for_status("finalizado") == "cierre" and inv.stage_for_status("en_proceso") == "en_proceso" and inv.stage_for_status("x") == "creado"


def test_blocking_message_and_summary():
    rep = inv.can_enter_in_progress([R(name="A", assigned=2, out=1), R(name="B", assigned=2, out=0)])
    msg = inv.blocking_message(rep, limit=1)
    assert "«A»" in msg and "y 1 más" in msg
    assert inv.summary([R(assigned=5, out=4, returned=1, consumed=1), R(assigned=2, out=2)]) == {"assigned": 7, "out": 6, "returned": 1, "consumed": 1, "pending": 4}


def test_clean_qty_name_unit_sku():
    assert inv.clean_qty(None, "x") == 0 and inv.clean_qty("7", "x") == 7 and inv.clean_qty(3.0, "x") == 3
    for bad in (-1, "a", 2.5, True, inv.MAX_QTY + 1):
        with pytest.raises(inv.InventoryError):
            inv.clean_qty(bad, "x")
    assert inv.clean_name("  Cable   HDMI ") == "Cable HDMI"
    for bad in ("", "  ", "<b>x</b>", "x" * 81, 5):
        with pytest.raises(inv.InventoryError):
            inv.clean_name(bad)
    assert inv.clean_unit(None) == "unidad" and inv.clean_unit(" kg ") == "kg"
    assert inv.clean_sku("") is None and inv.same_name(" Cable ", "cable")


def test_product_fields_and_attrs():
    fields = inv.clean_product_fields([{"label": "Marca"}, {"label": "Voltaje (V)", "kind": "number"}])
    assert [f["key"] for f in fields] == ["marca", "voltaje_v"] and fields[1]["kind"] == "number"
    assert inv.load_fields(inv.dump_fields(fields)) == fields and inv.dump_fields([]) is None and inv.load_fields("basura") == []
    with pytest.raises(inv.InventoryError):
        inv.clean_product_fields([{"label": "A"}, {"label": "a"}])
    with pytest.raises(inv.InventoryError):
        inv.clean_product_fields([{"label": "A", "kind": "foto"}])
    with pytest.raises(inv.InventoryError):
        inv.clean_product_fields([{"label": str(i)} for i in range(7)])
    assert inv.clean_attrs({"marca": " Dell ", "voltaje_v": "110,5"}, fields) == {"marca": "Dell", "voltaje_v": 110.5}
    with pytest.raises(inv.InventoryError):
        inv.clean_attrs({"otro": "x"}, fields)
    with pytest.raises(inv.InventoryError):
        inv.clean_attrs({"voltaje_v": "mucho"}, fields)


# ------------------------------------------------------------ catálogo (API)
def _catalog_with(client, cat="Equipos", prod="Computador"):
    c = client.post("/api/inventory/categories", json={"name": cat})
    assert c.status_code == 200, c.text
    p = client.post("/api/inventory/products", json={"name": prod, "unit": "unidad", "category_id": c.json()["id"], "sku": "PC-1", "fields": [{"label": "Marca"}]})
    assert p.status_code == 200, p.text
    return c.json(), p.json()


def test_admin_almacen_and_super_admin_edit_the_catalog_and_viewers_only_read_it(client, factory):
    """Fase 10 (10-nov-2026, decisión de Juan David): Admin y Almacén también crean, renombran y archivan; antes era solo del Super Admin."""
    factory.staff("super_admin", "sup")
    factory.staff("admin", "adm")
    factory.staff("coordinador", "alm", extra_roles="almacen")
    factory.staff("coordinador", "coord")
    factory.staff("digitador", "7001234")
    login(client, "adm")
    made = client.post("/api/inventory/categories", json={"name": "X"})
    assert made.status_code == 200
    assert client.patch(f"/api/inventory/categories/{made.json()['id']}", json={"name": "X2"}).status_code == 200
    assert client.get("/api/inventory/catalog?include_archived=true").status_code == 200
    assert client.post(f"/api/inventory/categories/{made.json()['id']}/archive").status_code == 200
    client.post("/logout")
    login(client, "alm")
    cat = client.post("/api/inventory/categories", json={"name": "Equipos"}).json()
    prod = client.post("/api/inventory/products", json={"name": "Computador", "unit": "unidad", "category_id": cat["id"], "sku": "PC-1", "fields": [{"label": "Marca"}]})
    assert prod.status_code == 200 and prod.json()["category_name"] == "Equipos" and prod.json()["fields"][0]["key"] == "marca"
    prod = prod.json()
    assert client.patch(f"/api/inventory/products/{prod['id']}", json={"name": "Portátil"}).status_code == 200
    assert client.post(f"/api/inventory/products/{prod['id']}/archive").status_code == 200
    assert client.post(f"/api/inventory/products/{prod['id']}/restore").status_code == 200
    client.post("/logout")
    login(client, "sup")
    assert client.post("/api/inventory/categories", json={"name": "Y"}).status_code == 200
    client.post("/logout")
    login(client, "coord")
    got = client.get("/api/inventory/catalog").json()
    assert [p["name"] for p in got["products"]] == ["Portátil"] and got["categories"][0]["products"] == 1
    assert client.post("/api/inventory/categories", json={"name": "Z"}).status_code == 403
    assert client.patch(f"/api/inventory/products/{prod['id']}", json={"name": "Otro"}).status_code == 403
    assert client.get("/api/inventory/catalog?include_archived=true").status_code == 403
    client.post("/logout")
    login(client, "7001234")
    assert client.get("/api/inventory/catalog").status_code == 403


def test_catalog_rules_duplicates_archive_restore_delete(client, factory, db):
    factory.staff("super_admin", "sup")
    login(client, "sup")
    cat, prod = _catalog_with(client)
    assert client.post("/api/inventory/categories", json={"name": " equipos "}).status_code == 400          # sin distinguir mayúsculas
    assert client.post("/api/inventory/products", json={"name": "computador"}).status_code == 400
    assert client.post("/api/inventory/products", json={"name": "Mesa", "category_id": 99999}).status_code == 400
    assert client.post("/api/inventory/products", json={"name": ""}).status_code == 400
    loose = client.post("/api/inventory/products", json={"name": "Mesa"}).json()                            # sin categoría: permitido
    assert loose["category_id"] is None
    assert client.post(f"/api/inventory/categories/{cat['id']}/archive").status_code == 400                # tiene productos activos
    assert client.post(f"/api/inventory/products/{prod['id']}/archive").status_code == 200
    assert client.patch(f"/api/inventory/products/{prod['id']}", json={"name": "Z"}).status_code == 400      # archivado no se edita
    assert client.post(f"/api/inventory/categories/{cat['id']}/archive").status_code == 200
    names = [p["name"] for p in client.get("/api/inventory/catalog").json()["products"]]
    assert names == ["Mesa"]
    assert len(client.get("/api/inventory/catalog?include_archived=true").json()["products"]) == 2
    r = client.post(f"/api/inventory/products/{prod['id']}/restore").json()
    assert r["archived"] is False and r["category_id"] is None                                               # su categoría sigue archivada: vuelve «sin categorizar»
    assert db.get(InventoryCategory, cat["id"]).archived_at is not None
    assert client.delete(f"/api/inventory/products/{loose['id']}").status_code == 400                       # sin archivar
    client.post(f"/api/inventory/products/{loose['id']}/archive")
    assert client.delete(f"/api/inventory/products/{loose['id']}").json() == {"deleted": True}
    assert db.get(InventoryProduct, loose["id"]) is None


# ------------------------------------------------------------ inventario del evento (API)
def _setup(client, factory, db):
    factory.staff("super_admin", "sup")
    login(client, "sup")
    cat, prod = _catalog_with(client)
    cat2 = client.post("/api/inventory/categories", json={"name": "Papelería"}).json()
    prod2 = client.post("/api/inventory/products", json={"name": "Resma", "unit": "paquete", "category_id": cat2["id"]}).json()
    client.post("/logout")
    return prod, prod2


def test_plan_lists_catalog_and_saves_by_role(client, factory, db):
    prod, prod2 = _setup(client, factory, db)
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("creado", coordinator=coord)
    login(client, "coord")
    plan = client.get(f"/api/events/{ev.id}/inventory-plan").json()
    assert [l["name"] for l in plan["lines"]] == ["Computador", "Resma"] and plan["can_edit_plan"] and not plan["can_edit_movement"]
    r = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [
        {"product_id": prod["id"], "assigned": 3, "attrs": {"marca": "Dell"}, "notes": "con cargador"}, {"product_id": prod2["id"], "assigned": 0}]})
    assert r.status_code == 200, r.text
    line = [l for l in r.json()["lines"] if l["name"] == "Computador"][0]
    assert line["assigned"] == 3 and line["attrs"] == {"marca": "Dell"} and line["notes"] == "con cargador"
    assert db.query(EventInventoryItem).filter_by(event_id=ev.id).count() == 1                              # la línea en cero y vacía no se crea
    # el coordinador NO registra lo que sale
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "out": 1}]}).status_code == 403
    # ni mandar el mismo valor cambia nada
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 4, "out": 0}]}).status_code == 200
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": 99999, "assigned": 1}]}).status_code == 404
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": -1}]}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "attrs": {"inventado": "x"}}]}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"]}, {"product_id": prod["id"]}]}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": "x"}).status_code == 400


def test_almacen_registers_movement_and_the_save_rejects_impossible_numbers(client, factory, db):
    prod, _ = _setup(client, factory, db)
    factory.staff("coordinador", "alm", extra_roles="almacen")
    ev = factory.event("creado")
    login(client, "alm")
    plan = client.get(f"/api/events/{ev.id}/inventory-plan").json()
    assert plan["can_edit_plan"] and plan["can_edit_movement"]
    ok = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 5, "out": 5}]})
    assert ok.status_code == 200 and ok.json()["balance"]["ok"]
    bad = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "returned": 4, "consumed": 4}]})
    assert bad.status_code == 400 and "supera" in bad.json()["detail"]
    bad = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 2}]})          # asignado por debajo de lo que salió
    assert bad.status_code == 400
    db.expire_all()
    row = db.query(EventInventoryItem).filter_by(event_id=ev.id).one()
    assert (row.qty_assigned, row.qty_out, row.qty_returned) == (5, 5, 0)                                    # lo rechazado no guardó nada
    good = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "returned": 3, "consumed": 2}]})
    assert good.json()["totals"]["pending"] == 0


def test_contabilidad_is_read_only_and_cannot_use_other_areas(client, factory, db):
    prod, _ = _setup(client, factory, db)
    factory.staff("comercial", "conta", extra_roles="contabilidad")
    ev = factory.event("creado")
    login(client, "conta")
    plan = client.get(f"/api/events/{ev.id}/inventory-plan").json()
    assert plan["can_edit_movement"] is False
    # comercial puede pedir cantidades (rol principal), pero no mover almacén
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "out": 1}]}).status_code == 403
    assert client.get("/api/staff").status_code == 403                                                       # no administra cuentas
    assert client.post("/api/inventory/categories", json={"name": "Y"}).status_code == 403


def test_digitador_cannot_open_the_event_inventory(client, factory):
    factory.staff("digitador", "7002222")
    login(client, "7002222")
    ev = factory.event("creado")
    assert client.get(f"/api/events/{ev.id}/inventory-plan").status_code == 403


def test_scope_enforcement_does_not_hide_events_from_almacen(client, factory, db, monkeypatch):
    prod, _ = _setup(client, factory, db)
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    factory.staff("coordinador", "alm", extra_roles="almacen")
    factory.staff("coordinador", "otro")
    ev = factory.event("creado")                                   # sin coordinador: un coordinador puro no lo ve con el alcance encendido
    login(client, "otro")
    assert client.get(f"/api/events/{ev.id}/inventory-plan").status_code == 404
    client.post("/logout")
    login(client, "alm")
    assert client.get(f"/api/events/{ev.id}/inventory-plan").status_code == 200


def test_in_progress_gate_follows_the_balance_rule(client, factory, db, monkeypatch):
    prod, prod2 = _setup(client, factory, db)
    factory.staff("coordinador", "alm", extra_roles="almacen")
    ev = factory.event("creado")
    eid = ev.id
    login(client, "alm")
    assert client.patch(f"/api/events/{eid}", json={"status": "en_proceso"}).status_code == 200            # sin líneas de inventario no estorba
    ev2 = factory.event("creado")
    e2 = ev2.id
    client.put(f"/api/events/{e2}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 4, "out": 3}]})
    r = client.patch(f"/api/events/{e2}", json={"status": "en_proceso"})
    assert r.status_code == 400 and "faltan 1" in r.json()["detail"]
    db.expire_all()
    assert db.get(Event, e2).status == "creado"
    client.put(f"/api/events/{e2}/inventory-plan", json={"lines": [{"product_id": prod["id"], "out": 4}]})
    assert client.patch(f"/api/events/{e2}", json={"status": "en_proceso"}).status_code == 200
    # el interruptor lo apaga
    ev3 = factory.event("creado")
    e3 = ev3.id
    client.put(f"/api/events/{e3}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 2}]})
    assert client.patch(f"/api/events/{e3}", json={"status": "en_proceso"}).status_code == 400
    monkeypatch.setenv("INVENTORY_BALANCE_GATE", "0")
    assert client.patch(f"/api/events/{e3}", json={"status": "en_proceso"}).status_code == 200


def test_archived_event_and_cleanup(client, factory, db):
    from app.routers.areas_inventory import delete_event_modules
    from app.timeutil import utcnow
    prod, _ = _setup(client, factory, db)
    factory.staff("admin", "adm")
    ev = factory.event("creado")
    login(client, "adm")
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 1}]}).status_code == 200
    ev.archived_at = utcnow()
    db.commit()
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 2}]}).status_code == 400
    delete_event_modules(db, ev.id)
    db.commit()
    assert db.query(EventInventoryItem).filter_by(event_id=ev.id).count() == 0


# ------------------------------------------------------------ pantallas
def test_config_inventory_tab_for_admin_plus_and_inventory_page_for_managers(client, factory):
    factory.staff("super_admin", "sup")
    factory.staff("admin", "adm")
    factory.staff("coordinador", "coord9")
    factory.staff("coordinador", "alm9", extra_roles="almacen")
    login(client, "coord9")
    assert 'id="tab_inventario"' not in client.get("/configuracion").text
    assert 'id="invProdForm"' not in client.get("/inventario").text
    client.post("/logout")
    for who in ("adm", "sup"):
        login(client, who)
        html = client.get("/configuracion").text
        assert 'id="tab_inventario"' in html and 'id="invProdForm"' in html and "inventory-catalog-admin.js" in html
        client.post("/logout")
    login(client, "alm9")
    page = client.get("/inventario").text
    assert 'id="invProdForm"' in page and "inventory-catalog-admin.js" in page and "Administrar catálogo" in page
    client.post("/logout")
    login(client, "sup")
    assert "event-inventory-plan.js" in client.get("/eventos/nuevo").text
    for name in ("inventory-catalog-admin.js", "event-inventory-plan.js"):
        assert client.get(f"/static/js/{name}").status_code == 200


def test_delete_product_assigned_to_events_names_them_and_needs_force(client, factory, db):
    """Un producto archivado pero asignado a un evento: «¿Dónde está?» lo dice, el borrado normal lo niega con los nombres y con force=1 lo quita de los eventos y se elimina."""
    prod, _ = _setup(client, factory, db)
    ev = factory.event("creado")
    login(client, "sup")
    assert client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod["id"], "assigned": 2}]}).status_code == 200
    client.post(f"/api/inventory/products/{prod['id']}/archive")
    use = client.get(f"/api/inventory/products/{prod['id']}/usage").json()
    assert [e["id"] for e in use["events"]] == [ev.id] and use["events"][0]["qty_assigned"] == 2 and use["movements"] == 0
    r = client.delete(f"/api/inventory/products/{prod['id']}")
    assert r.status_code == 409 and ev.name in r.json()["detail"]
    assert db.get(InventoryProduct, prod["id"]) is not None
    assert client.delete(f"/api/inventory/products/{prod['id']}?force=1").json() == {"deleted": True}
    assert db.get(InventoryProduct, prod["id"]) is None
    assert db.query(EventInventoryItem).filter_by(event_id=ev.id).count() == 0
