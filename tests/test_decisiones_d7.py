"""D7 (decisión del dueño, 8-nov-2026): ajuste por ítem «Permitir repetir la entrega a la misma persona». Existentes: permitir; nuevos (alta por la API): NO permitir.
Sin permiso, un segundo intento para la misma persona e ítem es 409 (comprobado con los ítems bloqueados FOR UPDATE)."""
from tests.conftest import login


def _setup(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", auto_register=True)
    factory.person(ev, "1001", "Ana", "Prueba")
    factory.person(ev, "1002", "Beto", "Prueba")
    login(client, "root")
    client.put(f"/api/events/{ev.id}/modules", json={"inventory_enabled": True})
    return ev


def _deliver(client, ev, cedula, *item_ids, qty=1):
    return client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": cedula, "items": [{"item_id": i, "qty": qty} for i in item_ids]})


def test_a_new_item_does_not_allow_repeating_and_the_flag_is_in_the_api(client, factory):
    ev = _setup(client, factory)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Camiseta", "initial_qty": 5}).json()
    assert item["allow_repeat_delivery"] is False
    on = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Agua", "initial_qty": 5, "allow_repeat_delivery": True}).json()
    assert on["allow_repeat_delivery"] is True
    assert {i["name"]: i["allow_repeat_delivery"] for i in client.get(f"/api/events/{ev.id}/inventory").json()} == {"Camiseta": False, "Agua": True}


def test_the_second_delivery_of_the_same_item_to_the_same_person_is_a_409_and_changes_nothing(client, factory, db):
    from app.models import InventoryDelivery
    ev = _setup(client, factory)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Camiseta", "initial_qty": 5}).json()
    assert _deliver(client, ev, "1001", item["id"]).status_code == 200
    again = _deliver(client, ev, "1001", item["id"])
    assert again.status_code == 409 and "Camiseta" in again.json()["detail"] and "no se puede repetir" in again.json()["detail"]
    assert db.query(InventoryDelivery).count() == 1
    assert _deliver(client, ev, "1002", item["id"]).status_code == 200                       # otra persona sí
    stock = {i["name"]: i for i in client.get(f"/api/events/{ev.id}/inventory").json()}
    assert stock["Camiseta"]["delivered"] == 2 and stock["Camiseta"]["available"] == 3


def test_a_combo_with_one_repeated_item_delivers_nothing(client, factory, db):
    from app.models import InventoryDelivery
    ev = _setup(client, factory)
    a = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Camiseta", "initial_qty": 5}).json()["id"]
    b = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Gorra", "initial_qty": 5}).json()["id"]
    assert _deliver(client, ev, "1001", a).status_code == 200
    assert _deliver(client, ev, "1001", a, b).status_code == 409                              # todo o nada
    assert db.query(InventoryDelivery).filter_by(item_id=b).count() == 0


def test_enabling_repeat_lets_the_same_person_receive_it_again_and_disabling_stops_it(client, factory):
    ev = _setup(client, factory)
    item = client.post(f"/api/events/{ev.id}/inventory", json={"name": "Agua", "initial_qty": 10}).json()
    assert _deliver(client, ev, "1001", item["id"]).status_code == 200
    r = client.patch(f"/api/events/{ev.id}/inventory/{item['id']}", json={"allow_repeat_delivery": True})
    assert r.status_code == 200 and r.json()["allow_repeat_delivery"] is True
    assert _deliver(client, ev, "1001", item["id"]).status_code == 200
    client.patch(f"/api/events/{ev.id}/inventory/{item['id']}", json={"allow_repeat_delivery": False})
    assert _deliver(client, ev, "1001", item["id"]).status_code == 409


def test_items_created_before_the_decision_keep_allowing_repeats(client, factory, db):
    """Un ítem ya existente (fila sin la columna nueva -> server_default true) sigue permitiendo repetir."""
    from app.models import InventoryItem
    ev = _setup(client, factory)
    item = InventoryItem(event_id=ev.id, name="Viejo", initial_qty=5)
    db.add(item)
    db.commit()
    assert item.allow_repeat_delivery is True
    assert _deliver(client, ev, "1001", item.id).status_code == 200
    assert _deliver(client, ev, "1001", item.id).status_code == 200


def test_a_garbage_item_id_is_a_400_not_a_500(client, factory):
    ev = _setup(client, factory)
    r = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": "abc", "qty": 1}]})
    assert r.status_code == 400


def test_the_delivery_check_runs_after_the_items_are_locked_for_update():
    src = open("app/routers/areas_inventory.py", encoding="utf-8").read()
    body = src[src.index("def deliver("):src.index("def recent_deliveries")]
    assert body.index(".with_for_update()") < body.index("InventoryDelivery.item_id.in_(list(wanted))") < body.index("db.add(InventoryDelivery(")


def test_parameters_screen_has_the_control_in_the_table_and_the_new_item_form():
    src = open("templates/kiosk_parametros.html", encoding="utf-8").read()
    assert "Repetir la entrega a la misma persona" in src and "item-repeat" in src and 'id="newItemRepeat"' in src
    assert "allow_repeat_delivery: tr.querySelector('.item-repeat').checked" in src and "allow_repeat_delivery: document.getElementById('newItemRepeat').checked" in src
