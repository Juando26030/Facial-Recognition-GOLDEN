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
    assert 'id="invTabAlm"' in client.get("/inventario").text and client.get("/inventario/etiquetas").status_code == 200
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
    assert client.patch(f"/api/almacen/units/{other['id']}", json={"serial": "SN-777"}).json()["serial"] == "SN-777"


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
