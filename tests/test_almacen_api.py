"""Almacén · Pieza 1 (API y páginas): controles del catálogo, unidades con serial, lectura de QR y etiquetas (app/routers/almacen.py).
NECESITAN Postgres (como el resto de las pruebas de API): se corren con `python -m pytest -q tests/test_almacen_api.py`."""
import pytest

from app.models import InventoryProduct, InventoryUnit
from tests.conftest import login


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv("ALMACEN_ENABLED", "1")


def _product(client, name="Portátil Lenovo", tracking="serial", row="portatiles"):
    cat = client.post("/api/inventory/categories", json={"name": f"Equipos {name}"})
    assert cat.status_code == 200, cat.text
    p = client.post("/api/inventory/products", json={"name": name, "unit": "unidad", "category_id": cat.json()["id"]})
    assert p.status_code == 200, p.text
    r = client.patch(f"/api/almacen/products/{p.json()['id']}", json={"tracking": tracking, "checklist_row": row})
    assert r.status_code == 200, r.text
    return r.json()


def test_everything_answers_404_while_the_flag_is_off(client, factory, monkeypatch):
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    factory.staff("admin", "adm")
    login(client, "adm")
    for path in ("/api/almacen/meta", "/api/almacen/products", "/api/almacen/units", "/api/almacen/scan?code=GWAAAAAA", "/inventario/etiquetas"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/almacen/labels", json={"unit_ids": [1]}).status_code == 404
    assert 'id="invTabAlm"' not in client.get("/inventario").text


def test_only_almacen_admin_and_super_admin_can_use_it(client, factory, on):
    factory.staff("coordinador", "alm", extra_roles="almacen")
    factory.staff("coordinador", "coord")
    factory.staff("comercial", "com")
    factory.staff("digitador", "7001234")
    login(client, "alm")
    assert client.get("/api/almacen/meta").status_code == 200
    page = client.get("/inventario").text
    assert 'id="invTabAlm"' in page and 'id="invTabNov"' in page and 'id="invPanelNov"' in page and client.get("/inventario/etiquetas").status_code == 200
    assert 'id="almNovCard"' in page and page.index('id="invPanelNov"') < page.index('id="almNovCard"')          # la búsqueda de novedades vive en su pestaña, no en Almacén
    assert page.index('id="almMvEventSearch"') < page.index('id="almMvEventBox"') and 'id="almSaveBar"' in page and 'id="almMvNovBox"' not in page          # la búsqueda de evento va FUERA del bloque plegable
    client.post("/logout")
    for user in ("coord", "com", "7001234"):
        login(client, user)
        assert client.get("/api/almacen/meta").status_code == 403, user
        assert client.get("/api/almacen/products").status_code == 403, user
        client.post("/logout")
    factory.staff("super_admin", "sup")
    login(client, "sup")
    assert client.get("/api/almacen/meta").status_code == 200


def test_meta_lists_the_43_rows_and_only_inventory_rows_can_be_chosen(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    meta = client.get("/api/almacen/meta").json()
    assert [t["key"] for t in meta["tracking"]] == ["serial", "modelo", "cantidad"] and meta["rows"][0]["label"] == "Teclados"
    prod = _product(client, "Mouse USB", "cantidad", "mouse")
    assert prod["tracking"] == "cantidad" and prod["checklist_row"] == "mouse" and prod["qr_code"].startswith("GW")          # por cantidad: el QR es del producto
    assert client.patch(f"/api/almacen/products/{prod['id']}", json={"checklist_row": "plan_b"}).status_code == 400
    assert client.patch(f"/api/almacen/products/{prod['id']}", json={"checklist_row": "inventada"}).status_code == 400
    assert client.patch(f"/api/almacen/products/{prod['id']}", json={"tracking": "otro"}).status_code == 400
    assert client.patch(f"/api/almacen/products/{prod['id']}", json={"is_consumable": True, "checklist_row": ""}).json()["checklist_row"] is None


def test_units_get_consecutive_numbers_unique_codes_and_never_reuse_a_number(client, factory, db, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    assert p["qr_code"] is None          # con serial el QR va en cada unidad, no en el producto
    made = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 3})
    assert made.status_code == 200, made.text
    units = made.json()["units"]
    assert [u["number"] for u in units] == [1, 2, 3] and len({u["code"] for u in units}) == 3 and units[0]["title"] == "Portátil Lenovo #1" and units[0]["status"] == "disponible"
    assert client.post(f"/api/almacen/units/{units[2]['id']}/archive").status_code == 200
    more = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1}).json()["units"]
    assert more[0]["number"] == 4          # el 3 archivado no se reutiliza
    listed = client.get(f"/api/almacen/units?product_id={p['id']}").json()["units"]
    assert [u["number"] for u in listed] == [1, 2, 4]
    assert len(client.get(f"/api/almacen/units?product_id={p['id']}&include_archived=true").json()["units"]) == 4
    assert client.post(f"/api/almacen/units/{units[2]['id']}/restore").json()["archived"] is False
    assert client.get("/api/almacen/products").json()["products"][0]["units"] == 4


def test_serial_rules_and_batch_limits(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    ok = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1, "serial": "SN-001"})
    assert ok.status_code == 200 and ok.json()["units"][0]["serial"] == "SN-001"
    assert client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1, "serial": "sn-001"}).status_code == 409          # sin distinguir mayúsculas
    assert client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 2, "serial": "SN-002"}).status_code == 400
    assert client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 0}).status_code == 400
    assert client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 101}).status_code == 400
    other = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1}).json()["units"][0]
    assert client.patch(f"/api/almacen/units/{other['id']}", json={"serial": "SN-001"}).status_code == 409
    done = client.patch(f"/api/almacen/units/{other['id']}", json={"serial": "sn-777"}).json()
    assert done["serial"] == "SN-777" and done["code"] == "SN-777"          # un solo dato: el serial es el valor del QR
    assert client.get("/api/almacen/lookup?code=SN-777").status_code == 200          # y se lee con el lector
    assert client.patch(f"/api/almacen/units/{other['id']}", json={"serial": ""}).status_code == 400          # no puede quedar vacío
    assert ok.json()["units"][0]["code"] == "SN-001"


def test_tracking_cannot_change_with_active_units_and_units_need_serial_tracking(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1})
    assert client.patch(f"/api/almacen/products/{p['id']}", json={"tracking": "cantidad"}).status_code == 400
    q = _product(client, "Cable USB", "cantidad", "cable_usb_hp1100")
    assert client.post(f"/api/almacen/products/{q['id']}/units", json={"count": 1}).status_code == 400


def test_only_an_available_unit_can_be_archived(client, factory, db, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    u = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1}).json()["units"][0]
    row = db.query(InventoryUnit).filter_by(id=u["id"]).one()
    row.status = "en_evento"
    db.commit()
    assert client.post(f"/api/almacen/units/{u['id']}/archive").status_code == 400
    row.status = "disponible"
    db.commit()
    assert client.post(f"/api/almacen/units/{u['id']}/archive").json()["archived"] is True


def test_scan_finds_units_and_products_and_explains_what_it_cannot_find(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    u = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1, "serial": "SN-9"}).json()["units"][0]
    q = _product(client, "Cable USB", "cantidad", "cable_usb_hp1100")
    got = client.get(f"/api/almacen/scan?code={u['code'].lower()}%0D%0A").json()          # el lector manda minúsculas o salto de línea según su configuración
    assert got["kind"] == "unit" and got["unit"]["serial"] == "SN-9" and got["product"]["name"] == "Portátil Lenovo"
    got = client.get(f"/api/almacen/scan?code={q['qr_code']}").json()
    assert got["kind"] == "product" and got["product"]["name"] == "Cable USB"
    r = client.get("/api/almacen/scan?code=GWZZZZZZ")
    assert r.status_code == 404 and "no existe" in r.json()["detail"]
    r = client.get("/api/almacen/scan?code=GW-X")
    assert r.status_code == 404 and "lector" in r.json()["detail"]


def test_labels_carry_only_the_code_and_cover_units_and_non_serial_products(client, factory, db, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    units = client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 2, "serial": None}).json()["units"]
    q = _product(client, "Impresora HP P1102w", "modelo", "impresora_hp_p1102w")
    db.query(InventoryProduct).filter_by(id=q["id"]).update({"qr_code": None})          # un producto viejo sin código: se le asigna al imprimir
    db.commit()
    r = client.post("/api/almacen/labels", json={"unit_ids": [u["id"] for u in units], "product_ids": [q["id"]]})
    assert r.status_code == 200, r.text
    labels = r.json()["labels"]
    assert [l["title"] for l in labels] == ["Portátil Lenovo #1", "Portátil Lenovo #2", "Impresora HP P1102w"]
    assert all(l["code"].startswith("GW") and len(l["code"]) == 8 for l in labels) and labels[2]["subtitle"] == "Por modelo"
    assert client.post("/api/almacen/labels", json={"product_ids": [p["id"]]}).status_code == 400          # un producto con serial se imprime unidad por unidad
    assert client.post("/api/almacen/labels", json={}).status_code == 400
    assert client.post("/api/almacen/labels", json={"unit_ids": [999999]}).status_code == 404


def test_a_product_with_units_cannot_be_deleted_only_archived(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    client.post(f"/api/almacen/products/{p['id']}/units", json={"count": 1})
    assert client.post(f"/api/inventory/products/{p['id']}/archive").status_code == 200
    r = client.delete(f"/api/inventory/products/{p['id']}")
    assert r.status_code == 400 and "unidades con serial" in r.json()["detail"]


# ---------------------------------------------------------------- Pieza 2: salidas, entradas, alistado y fotos
def _units(client, product_id, n):
    r = client.post(f"/api/almacen/products/{product_id}/units", json={"count": n})
    assert r.status_code == 200, r.text
    return r.json()["units"]


def _assign(client, event_id, product_id, qty):
    r = client.put(f"/api/events/{event_id}/inventory-plan", json={"lines": [{"product_id": product_id, "assigned": qty}]})
    assert r.status_code == 200, r.text


def _move(client, mode, code, event_id=None, **extra):
    return client.post("/api/almacen/move", json={"mode": mode, "code": code, "event_id": event_id, **extra})


def test_serial_units_leave_and_come_back_and_the_event_is_deduced_on_entry(client, factory, db, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client)
    us = _units(client, p["id"], 3)
    _assign(client, ev.id, p["id"], 3)
    for u in us:
        r = _move(client, "salida", u["code"], ev.id)
        assert r.status_code == 200, r.text
    assert r.json()["line"] == {"needed": 3, "assigned": 3, "out": 3, "returned": 0, "consumed": 0, "pending": 3}
    assert {u.status for u in db.query(InventoryUnit).all()} == {"en_evento"}
    assert client.get(f"/api/almacen/events/{ev.id}/board").json()["outside"].__len__() == 3
    r = _move(client, "salida", us[0]["code"], ev.id)
    assert r.status_code == 400 and "ya está en el evento" in r.json()["detail"]
    r = _move(client, "entrada", us[0]["code"])          # sin evento: el sistema sabe dónde estaba
    assert r.status_code == 200, r.text
    assert r.json()["line"]["returned"] == 1 and r.json()["unit"]["status"] == "disponible"
    assert _move(client, "entrada", us[0]["code"]).status_code == 400          # ya está en bodega
    board = client.get(f"/api/almacen/events/{ev.id}/board").json()
    row = next(x for x in board["board"] if x["key"] == "portatiles")
    assert (row["needed"], row["out"], row["returned"], row["pending"]) == (3, 3, 1, 2) and len(board["outside"]) == 2


def test_the_event_can_go_in_process_once_the_scans_match_what_it_asked(client, factory, db, on):
    from app import inventory_svc
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client)
    us = _units(client, p["id"], 2)
    _assign(client, ev.id, p["id"], 2)
    assert _move(client, "salida", us[0]["code"], ev.id).status_code == 200
    from fastapi import HTTPException
    db.expire_all()
    with pytest.raises(HTTPException):
        inventory_svc.assert_can_enter_in_progress(db, db.get(type(ev), ev.id))          # falta sacar 1: la puerta de siempre sigue cerrada
    assert _move(client, "salida", us[1]["code"], ev.id).status_code == 200
    db.expire_all()
    inventory_svc.assert_can_enter_in_progress(db, db.get(type(ev), ev.id))          # salió = asignado: pasa


def test_exceeding_what_was_asked_only_warns_and_keeps_needed_intact(client, factory, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client, "Cable USB", "cantidad", "cable_usb_hp1100")
    code = p["qr_code"]
    _assign(client, ev.id, p["id"], 5)
    assert _move(client, "salida", code, ev.id, qty=5).status_code == 200
    r = _move(client, "salida", code, ev.id, qty=2)
    assert r.status_code == 200, r.text          # no se bloquea: se registra y avisa que falta asignar
    assert "Falta asignar" in r.json()["warning"] and r.json()["movement"]["extra"] == 2
    assert _move(client, "salida", code, ev.id, qty=1).status_code == 200          # sigue sin bloquear
    r = _move(client, "salida", code, ev.id, qty=2, reason="El cliente sumó dos puestos")
    assert r.status_code == 200, r.text
    r = _move(client, "salida", code, ev.id, qty=1, plan_b=True)
    assert r.status_code == 200, r.text
    row = next(x for x in client.get(f"/api/almacen/events/{ev.id}/board").json()["board"] if x["key"] == "cable_usb_hp1100")
    assert (row["needed"], row["out"], row["extra"], row["plan_b"]) == (5, 11, 6, True)
    plan = client.get(f"/api/events/{ev.id}/inventory-plan").json()
    assert [l for l in plan["lines"] if l["product_id"] == p["id"]][0]["assigned"] == 11          # el cuadre de siempre se mantiene


def test_a_product_the_event_never_asked_for_leaves_with_a_warning_not_a_block(client, factory, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client, "Pulpos", "cantidad", "pulpos")
    r = _move(client, "salida", p["qr_code"], ev.id, qty=2)
    assert r.status_code == 200 and "el evento no lo pidió" in r.json()["warning"]
    assert _move(client, "salida", p["qr_code"], ev.id, qty=2, reason="Faltan tomas en la sala").status_code == 200


def test_quantity_entries_cannot_exceed_what_is_pending_and_consumables_do_not_return(client, factory, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="en_proceso")
    login(client, "adm")
    cab = _product(client, "Cable de red", "cantidad", "cables_red_utp")
    _assign(client, ev.id, cab["id"], 10)
    assert _move(client, "salida", cab["qr_code"], ev.id, qty=10).status_code == 200
    assert _move(client, "entrada", cab["qr_code"], ev.id, qty=11).status_code == 400
    assert _move(client, "entrada", cab["qr_code"], ev.id, qty=4).status_code == 200
    assert _move(client, "entrada", cab["qr_code"], qty=1).status_code == 400          # por cantidad siempre hace falta el evento
    cinta = _product(client, "Cinta gaffer", "cantidad", "cinta_gaffer")
    client.patch(f"/api/almacen/products/{cinta['id']}", json={"is_consumable": True})
    _assign(client, ev.id, cinta["id"], 3)
    r = _move(client, "salida", cinta["qr_code"], ev.id, qty=3)
    assert r.status_code == 200 and r.json()["line"]["consumed"] == 3 and r.json()["line"]["pending"] == 0
    assert _move(client, "entrada", cinta["qr_code"], ev.id, qty=1).status_code == 400


def test_exits_need_an_open_event_and_a_finished_event_still_takes_returns(client, factory, db, on):
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)
    us = _units(client, p["id"], 2)
    ev = factory.event(status="creado")
    _assign(client, ev.id, p["id"], 2)
    assert _move(client, "salida", us[0]["code"], ev.id).status_code == 200
    from app.models import Event
    db.query(Event).filter(Event.id == ev.id).update({"status": "finalizado"})
    db.commit()
    assert _move(client, "salida", us[1]["code"], ev.id).status_code == 400
    assert _move(client, "entrada", us[0]["code"]).status_code == 200


def test_a_unit_in_another_event_is_rejected_naming_that_event(client, factory, on):
    factory.staff("admin", "adm")
    e1, e2 = factory.event(status="creado"), factory.event(status="creado")
    login(client, "adm")
    p = _product(client)
    u = _units(client, p["id"], 1)[0]
    _assign(client, e1.id, p["id"], 1)
    _assign(client, e2.id, p["id"], 1)
    assert _move(client, "salida", u["code"], e1.id).status_code == 200
    r = _move(client, "salida", u["code"], e2.id)
    assert r.status_code == 400 and e1.name in r.json()["detail"]


def test_void_only_the_last_movement_and_it_restores_everything(client, factory, db, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client)
    u = _units(client, p["id"], 1)[0]
    _assign(client, ev.id, p["id"], 1)
    out = _move(client, "salida", u["code"], ev.id).json()["movement"]
    back = _move(client, "entrada", u["code"]).json()["movement"]
    r = client.post(f"/api/almacen/movements/{out['id']}/void")
    assert r.status_code == 400 and "posterior" in r.json()["detail"]
    assert client.post(f"/api/almacen/movements/{back['id']}/void").status_code == 200
    assert db.query(InventoryUnit).first().status == "en_evento"
    assert client.post(f"/api/almacen/movements/{out['id']}/void").status_code == 200
    db.expire_all()
    assert db.query(InventoryUnit).first().status == "disponible"
    row = next(x for x in client.get(f"/api/almacen/events/{ev.id}/board").json()["board"] if x["key"] == "portatiles")
    assert (row["out"], row["returned"]) == (0, 0)
    assert client.post(f"/api/almacen/movements/{out['id']}/void").status_code == 400          # ya anulado


def test_checklist_rows_save_done_and_notes_including_manual_rows(client, factory, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/portatiles", json={"done": True, "notes": "Revisados"}).status_code == 200
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/plan_b", json={"done": True}).status_code == 200
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/no_existe", json={"done": True}).status_code == 400
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/portatiles", json={}).status_code == 400
    board = client.get(f"/api/almacen/events/{ev.id}/board").json()
    assert {r["key"]: (r["done"], r["notes"]) for r in board["board"] if r["done"]} == {"portatiles": (True, "Revisados"), "plan_b": (True, "")}
    assert board["summary"]["done"] == 2 and len(board["board"]) == 43


def test_movements_follow_the_same_permissions_and_the_flag(client, factory, on, monkeypatch):
    factory.staff("coordinador", "coord")
    ev = factory.event(status="creado")
    login(client, "coord")
    assert client.post("/api/almacen/move", json={"mode": "salida", "code": "GWAAAAAA", "event_id": ev.id}).status_code == 403
    assert client.get(f"/api/almacen/events/{ev.id}/board").status_code == 403
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/portatiles", json={"done": True}).status_code == 403
    client.post("/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    assert client.post("/api/almacen/move", json={"mode": "salida", "code": "GWAAAAAA", "event_id": ev.id}).status_code == 404


def test_product_photo_upload_replace_serve_and_delete(client, factory, on):
    import io
    from PIL import Image
    factory.staff("admin", "adm")
    login(client, "adm")
    p = _product(client)

    def png(color):
        b = io.BytesIO()
        Image.new("RGB", (800, 600), color).save(b, format="PNG")
        return b.getvalue()

    assert client.get(f"/api/almacen/products/{p['id']}/photo").status_code == 404
    r = client.post(f"/api/almacen/products/{p['id']}/photo", files={"file": ("equipo.png", png((200, 0, 0)), "image/png")})
    assert r.status_code == 200 and r.json()["has_photo"] and r.json()["photo_url"]
    got = client.get(f"/api/almacen/products/{p['id']}/photo")
    assert got.status_code == 200 and got.headers["content-type"].startswith("image/jpeg")
    first = r.json()["photo_url"]
    r2 = client.post(f"/api/almacen/products/{p['id']}/photo", files={"file": ("otra.png", png((0, 0, 200)), "image/png")})
    assert r2.status_code == 200 and r2.json()["photo_url"] != first
    bad = client.post(f"/api/almacen/products/{p['id']}/photo", files={"file": ("virus.png", b"no soy una foto", "image/png")})
    assert bad.status_code == 400
    assert client.delete(f"/api/almacen/products/{p['id']}/photo").json()["has_photo"] is False
    assert client.get(f"/api/almacen/products/{p['id']}/photo").status_code == 404


def test_the_catalog_admin_carries_the_warehouse_fields_and_the_alm_tab_has_no_create_form(client, factory, on, monkeypatch):
    factory.staff("admin", "adm")
    login(client, "adm")
    page = client.get("/inventario").text
    assert 'id="almCatBox"' in page and 'id="almUnitsCard"' in page and "almacen-catalog.js" in page          # crear tipo, objetos y QR viven en «Administrar catálogo»
    assert 'id="almNewForm"' not in page and 'id="almProducts"' not in page                                   # y ya no hay un segundo formulario en la pestaña Almacén
    assert 'id="almMvScan"' in page and 'id="almMvQrBtn"' in page and 'id="almMvEventSearch"' in page and 'id="almScan"' not in page and 'id="almMvEventBox"' in page and 'id="invProdSearch"' in page and 'id="invProdFormBox"' in page          # bloques plegables y buscador de tipos and 'invCatForm' not in page
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    off = client.get("/inventario").text
    assert 'id="almCatBox"' not in off and "almacen-catalog.js" not in off and 'id="invProdForm"' in off and 'invCatForm' in off          # sin el interruptor el catálogo queda como siempre


# ------------------------------------------------------------------ Pieza 3: novedades y bloqueo
def _png():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (400, 300), (180, 20, 20)).save(b, format="PNG")
    return b.getvalue()


def _report(client, code, text="Pantalla rota", files=None, qty=None):
    files = [("files", ("dano.png", _png(), "image/png"))] if files is None else files
    data = {"code": code, "description": text}
    if qty:
        data["qty"] = str(qty)
    return client.post("/api/almacen/novelties", data=data, files=files)


def _resolve(client, nid, note="Cambiaron la pantalla", files=None):
    files = [("files", ("listo.png", _png(), "image/png"))] if files is None else files
    return client.post(f"/api/almacen/novelties/{nid}/resolve", data={"note": note}, files=files)


def test_reporting_a_novelty_needs_files_blocks_the_unit_until_almacen_resolves_it(client, factory, on):
    factory.staff("admin", "adm")
    ev = factory.event(status="creado")
    login(client, "adm")
    p = _product(client)
    u = _units(client, p["id"], 1)[0]
    _assign(client, ev.id, p["id"], 1)
    assert _report(client, u["code"], "ab").status_code == 400          # el texto es obligatorio
    sin = _report(client, u["code"], files=[("files", ("", b"", "application/octet-stream"))])
    assert sin.status_code == 400 and "al menos un archivo" in sin.json()["detail"]          # el archivo es obligatorio
    assert _report(client, u["code"], files=[("files", ("virus.exe", b"MZ", "application/octet-stream"))]).status_code == 400
    r = _report(client, u["code"], files=[("files", ("a.png", _png(), "image/png")), ("files", ("b.png", _png(), "image/png")), ("files", ("acta.pdf", b"%PDF-1.4 x", "application/pdf"))])
    assert r.status_code == 200, r.text
    nov = r.json()["novelty"]
    assert [f["kind"] for f in nov["files"]] == ["reporte"] * 3 and nov["files"][2]["name"] == "acta.pdf"
    assert client.get(nov["files"][0]["url"]).headers["content-type"].startswith("image/jpeg")
    assert client.get(nov["files"][2]["url"]).headers["content-type"] == "application/pdf"
    assert _report(client, u["code"], "Otra cosa").status_code == 400          # ya tiene una abierta
    flagged = next(x for x in client.get(f"/api/almacen/units?product_id={p['id']}").json()["units"] if x["id"] == u["id"])
    assert flagged["has_novelty"] is True          # la tabla de objetos muestra el aviso ⚠ «presenta una novedad»
    blocked = _move(client, "salida", u["code"], ev.id)
    assert blocked.status_code == 400 and "novedad" in blocked.text and "Pantalla rota" in blocked.text
    nid = nov["id"]
    assert _resolve(client, nid, note="").status_code == 400          # la nota es obligatoria
    assert _resolve(client, nid, files=[("files", ("", b"", "application/octet-stream"))]).status_code == 400          # y los archivos también
    ok = _resolve(client, nid)
    assert ok.status_code == 200 and ok.json()["novelty"]["resolved"]
    assert [f["kind"] for f in ok.json()["novelty"]["files"]] == ["reporte"] * 3 + ["resolucion"]
    assert _resolve(client, nid, note="otra vez").status_code == 400
    assert _move(client, "salida", u["code"], ev.id).status_code == 200          # ya se puede asignar a un evento
    assert next(x for x in client.get(f"/api/almacen/units?product_id={p['id']}").json()["units"] if x["id"] == u["id"])["has_novelty"] is False
    assert client.get("/api/almacen/novelties?state=abiertas").json()["open_count"] == 0
    assert [n["id"] for n in client.get("/api/almacen/novelties?state=resueltas").json()["novelties"]] == [nid]


def test_a_unit_with_an_open_novelty_stays_blocked_when_it_comes_back_and_void_still_works(client, factory, db, on):
    from app.models import InventoryNovelty
    factory.staff("admin", "adm")
    ev = factory.event(status="en_proceso")
    login(client, "adm")
    p = _product(client)
    u = _units(client, p["id"], 1)[0]
    _assign(client, ev.id, p["id"], 1)
    assert _move(client, "salida", u["code"], ev.id).status_code == 200
    assert _report(client, u["code"]).status_code == 200          # se daña en el evento: sigue «en evento» pero con novedad
    back = _move(client, "entrada", u["code"], ev.id)
    assert back.status_code == 200, back.text
    assert next(x for x in client.get(f"/api/almacen/units?product_id={p['id']}").json()["units"] if x["id"] == u["id"])["status"] == "novedad"          # vuelve, pero bloqueado
    assert db.query(InventoryNovelty).count() == 1


def test_consumables_carry_no_novelties_and_quantity_ones_reserve_pieces(client, factory, on):
    factory.staff("admin", "adm")
    login(client, "admin" if False else "adm")
    cons = _product(client, "Cinta", "cantidad", "cinta")
    client.patch(f"/api/almacen/products/{cons['id']}", json={"is_consumable": True, "checklist_row": ""})
    assert _report(client, cons["qr_code"], "Se mojó").status_code == 400


def test_novelties_follow_the_permissions_and_the_flag(client, factory, on, monkeypatch):
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/almacen/novelties").status_code == 403
    assert _report(client, "GWAAAAAA", "algo").status_code == 403
    client.post("/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.get("/api/almacen/novelties?state=rara").status_code == 400
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    assert client.get("/api/almacen/novelties").status_code == 404


# ------------------------------------------------------------------ Pieza 4: Excel del checklist
def test_the_checklist_downloads_as_the_geyl_xlsx_with_the_event_data(client, factory, on):
    import io
    from openpyxl import load_workbook
    factory.staff("admin", "adm")
    ev = factory.event(status="en_proceso")
    login(client, "adm")
    p = _product(client)
    us = _units(client, p["id"], 2)
    _assign(client, ev.id, p["id"], 2)
    assert _move(client, "salida", us[0]["code"], ev.id).status_code == 200
    assert client.put(f"/api/almacen/events/{ev.id}/checklist/portatiles", json={"done": True, "notes": "Revisados"}).status_code == 200
    r = client.get(f"/api/almacen/events/{ev.id}/checklist.xlsx")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and ".xlsx" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Hoja1"]
    assert wb.sheetnames[:2] == ["Hoja1", "Instrucciones Básicas"] and ws["B2"].value == ev.event_code and ws["B54"].value
    assert (ws["B14"].value, ws["C14"].value, ws["D14"].value) == (2, 1, "SÍ") and "Revisados" in ws["E14"].value


def test_the_xlsx_follows_the_permissions_and_the_flag(client, factory, on, monkeypatch):
    factory.staff("coordinador", "coord")
    ev = factory.event(status="creado")
    login(client, "coord")
    assert client.get(f"/api/almacen/events/{ev.id}/checklist.xlsx").status_code == 403
    client.post("/logout")
    factory.staff("admin", "adm")
    login(client, "adm")
    assert client.get("/api/almacen/events/999999/checklist.xlsx").status_code == 404
    monkeypatch.delenv("ALMACEN_ENABLED", raising=False)
    assert client.get(f"/api/almacen/events/{ev.id}/checklist.xlsx").status_code == 404
