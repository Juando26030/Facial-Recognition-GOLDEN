"""Fase 3, oleada catálogos (7-nov-2026): zonas, ítems de inventario, librería de colores y de plantillas de escarapela. Archivar = ocultar y restaurar (admin+); borrado definitivo solo super_admin,
de lo ya archivado y sin historial; el historial (movimientos, entregas) se conserva; todo deja rastro en audit_actions."""
import inspect

import pytest

from app.models import AuditAction, EventArea, InventoryItem, SavedBadgeTemplate, SavedColor
from tests.conftest import login


def _setup(client, factory, role="admin"):
    ev = factory.event()
    factory.person(ev, "1001")
    factory.staff(role, "actor")
    login(client, "actor")
    return ev


def _area(client, ev, name="VIP"):
    return client.post(f"/api/events/{ev.id}/areas", json={"name": name}).json()["id"]


def _item(client, ev, name="Gaseosa", qty=10):
    return client.post(f"/api/events/{ev.id}/inventory", json={"name": name, "initial_qty": qty}).json()["id"]


def _ids(r):
    return {x["id"] for x in r.json()}


def test_sources_guard_roles():
    from app.routers import areas_inventory as ai, badges, events
    for fn in (ai.archive_area, ai.restore_area, ai.archive_item, ai.restore_item):
        assert "ARCHIVE_ROLE" in inspect.getsource(fn)
    for fn in (ai.delete_area, ai.delete_item):
        assert "HARD_DELETE_ROLE" in inspect.getsource(fn)
    for fn in (events.archive_saved_color, events.restore_saved_color, badges.archive_saved_badge_template, badges.restore_saved_badge_template):
        assert 'require_role("coordinador")' in inspect.getsource(fn)          # cambio 7-nov: coordinador+ (incluye comercial)
    for fn in (events.delete_saved_color, badges.delete_saved_badge_template):
        assert 'require_role("super_admin")' in inspect.getsource(fn)


def test_area_archive_hides_restore_and_admin_sees_archived(client, factory):
    ev = _setup(client, factory)
    aid = _area(client, ev)
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/archive").status_code == 200
    assert aid not in _ids(client.get(f"/api/events/{ev.id}/areas"))
    assert aid in _ids(client.get(f"/api/events/{ev.id}/areas", params={"include_archived": "true"}))
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/archive").status_code == 400
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/restore").status_code == 200
    assert aid in _ids(client.get(f"/api/events/{ev.id}/areas"))
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/restore").status_code == 400


def test_archived_area_rejects_movements_and_edits_but_keeps_history(client, factory):
    ev = _setup(client, factory)
    aid = _area(client, ev)
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/movement", json={"cedula": "1001", "direction": "in", "confirm": True}).json()["result"] in ("OK", "FOUND_PENDING")
    client.post(f"/api/events/{ev.id}/areas/{aid}/archive")
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/movement", json={"cedula": "1001", "direction": "out"}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}/areas/{aid}", json={"name": "Otra"}).status_code == 400
    assert client.get(f"/api/events/{ev.id}/areas-report").status_code == 200          # el reporte conserva la zona archivada


def test_area_name_clash_with_archived_one(client, factory):
    ev = _setup(client, factory)
    aid = _area(client, ev, "VIP")
    client.post(f"/api/events/{ev.id}/areas/{aid}/archive")
    r = client.post(f"/api/events/{ev.id}/areas", json={"name": "vip"})
    assert r.status_code == 400 and "archivada" in r.json()["detail"]


@pytest.mark.parametrize("role,expected", [("digitador", 403), ("cliente", 403), ("coordinador", 200), ("comercial", 200), ("admin", 200), ("super_admin", 200)])
def test_archive_is_coordinador_plus(client, factory, role, expected):
    ev = factory.event()
    factory.staff("super_admin", "boss")
    factory.staff(role, "actor")
    login(client, "boss")
    aid, iid = _area(client, ev), _item(client, ev)
    login(client, "actor")
    assert client.post(f"/api/events/{ev.id}/areas/{aid}/archive").status_code == expected
    assert client.post(f"/api/events/{ev.id}/inventory/{iid}/archive").status_code == expected
    if expected == 200:          # y quien archiva también restaura
        assert client.post(f"/api/events/{ev.id}/areas/{aid}/restore").status_code == 200
        assert client.post(f"/api/events/{ev.id}/inventory/{iid}/restore").status_code == 200


def test_coordinador_lists_archived(client, factory):
    ev = _setup(client, factory, "coordinador")
    assert client.get(f"/api/events/{ev.id}/areas", params={"include_archived": "true"}).status_code == 200
    assert client.get(f"/api/events/{ev.id}/inventory", params={"include_archived": "true"}).status_code == 200


@pytest.mark.parametrize("role", ["digitador", "cliente"])
def test_digitador_and_cliente_cannot_list_archived(client, factory, role):
    ev = factory.event()
    s = factory.staff(role, "actor")
    factory.authorize(ev, s)
    login(client, "actor")
    assert client.get(f"/api/events/{ev.id}/areas", params={"include_archived": "true"}).status_code == 403
    assert client.get(f"/api/events/{ev.id}/inventory", params={"include_archived": "true"}).status_code == 403


def test_area_hard_delete_rules(client, factory, db):
    ev = factory.event()
    factory.person(ev, "1001")
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "sup")
    vacia, usada = _area(client, ev, "Vacia"), _area(client, ev, "Usada")
    client.post(f"/api/events/{ev.id}/areas/{usada}/movement", json={"cedula": "1001", "direction": "in", "confirm": True})
    login(client, "adm")
    assert client.delete(f"/api/events/{ev.id}/areas/{vacia}").status_code == 403
    login(client, "sup")
    assert client.delete(f"/api/events/{ev.id}/areas/{vacia}").status_code == 400          # primero archivar
    client.post(f"/api/events/{ev.id}/areas/{vacia}/archive")
    client.post(f"/api/events/{ev.id}/areas/{usada}/archive")
    assert client.delete(f"/api/events/{ev.id}/areas/{usada}").status_code == 400          # con movimientos solo se archiva
    assert client.delete(f"/api/events/{ev.id}/areas/{vacia}").status_code == 200
    db.expire_all()
    assert db.get(EventArea, vacia) is None and db.get(EventArea, usada) is not None


def test_item_archive_blocks_delivery_but_keeps_stock_history(client, factory):
    ev = _setup(client, factory)
    iid = _item(client, ev)
    ok = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": iid, "qty": 1}]})
    assert ok.status_code == 200
    assert client.post(f"/api/events/{ev.id}/inventory/{iid}/archive").json()["delivered"] == 1
    assert iid not in _ids(client.get(f"/api/events/{ev.id}/inventory"))
    listed = client.get(f"/api/events/{ev.id}/inventory", params={"include_archived": "true"}).json()
    assert [x for x in listed if x["id"] == iid][0]["archived"] is True
    blocked = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": iid, "qty": 1}]})
    assert blocked.status_code == 400 and "archivado" in blocked.json()["detail"]
    assert client.patch(f"/api/events/{ev.id}/inventory/{iid}", json={"initial_qty": 50}).status_code == 400
    assert client.get(f"/api/events/{ev.id}/inventory-report").status_code == 200
    assert client.post(f"/api/events/{ev.id}/inventory/{iid}/restore").status_code == 200
    assert client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": iid, "qty": 1}]}).status_code == 200


def test_item_hard_delete_rules(client, factory, db):
    ev = factory.event()
    factory.person(ev, "1001")
    factory.staff("super_admin", "sup")
    login(client, "sup")
    libre, entregado = _item(client, ev, "Libre"), _item(client, ev, "Entregado")
    client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": entregado, "qty": 1}]})
    assert client.delete(f"/api/events/{ev.id}/inventory/{libre}").status_code == 400          # primero archivar
    client.post(f"/api/events/{ev.id}/inventory/{libre}/archive")
    client.post(f"/api/events/{ev.id}/inventory/{entregado}/archive")
    assert client.delete(f"/api/events/{ev.id}/inventory/{entregado}").status_code == 400      # con entregas solo se archiva
    assert client.delete(f"/api/events/{ev.id}/inventory/{libre}").status_code == 200
    db.expire_all()
    assert db.get(InventoryItem, libre) is None and db.get(InventoryItem, entregado) is not None


def test_colors_archive_restore_delete(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    login(client, "adm")
    cid = client.post("/api/colors", json={"name": "Rojo Golden", "hex": "#C0392B"}).json()["id"]
    assert client.delete(f"/api/colors/{cid}").status_code == 403
    assert client.post(f"/api/colors/{cid}/archive").status_code == 200
    assert cid not in _ids(client.get("/api/colors"))
    assert cid in _ids(client.get("/api/colors", params={"include_archived": "true"}))
    assert client.post("/api/colors", json={"name": "rojo golden", "hex": "#000000"}).status_code == 400
    assert client.post(f"/api/colors/{cid}/restore").status_code == 200
    client.post(f"/api/colors/{cid}/archive")
    login(client, "sup")
    assert client.delete(f"/api/colors/{cid}").status_code == 200
    db.expire_all()
    assert db.get(SavedColor, cid) is None


def test_saved_badge_template_archive_hides_and_blocks_import(client, factory, db):
    ev = factory.event()
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    saved = SavedBadgeTemplate(tenant_id=ev.tenant_id, name="Base", width_mm=62, height_mm=99.8)
    db.add(saved)
    db.commit()
    login(client, "adm")
    assert client.delete(f"/api/saved-badge-templates/{saved.id}").status_code == 403
    assert client.post(f"/api/saved-badge-templates/{saved.id}/archive").status_code == 200
    assert saved.id not in _ids(client.get(f"/api/events/{ev.id}/saved-badge-templates"))
    assert saved.id in _ids(client.get(f"/api/events/{ev.id}/saved-badge-templates", params={"include_archived": "true"}))
    assert client.post(f"/api/events/{ev.id}/badge-template/import/{saved.id}").status_code == 400
    assert client.post(f"/api/saved-badge-templates/{saved.id}/restore").status_code == 200
    client.post(f"/api/saved-badge-templates/{saved.id}/archive")
    login(client, "sup")
    assert client.delete(f"/api/saved-badge-templates/{saved.id}").status_code == 200
    db.expire_all()
    assert db.get(SavedBadgeTemplate, saved.id) is None


def test_actions_are_logged(client, factory, db):
    ev = _setup(client, factory)
    aid, iid = _area(client, ev, "Zona privada"), _item(client, ev)
    client.post(f"/api/events/{ev.id}/areas/{aid}/archive")
    client.post(f"/api/events/{ev.id}/areas/{aid}/restore")
    client.post(f"/api/events/{ev.id}/inventory/{iid}/archive")
    db.expire_all()
    rows = db.query(AuditAction).order_by(AuditAction.id).all()
    assert [(r.action, r.entity) for r in rows] == [("archive", "event_area"), ("restore", "event_area"), ("archive", "inventory_item")]
    assert all(r.actor_role == "admin" for r in rows)


@pytest.mark.parametrize("role,expected", [("digitador", 403), ("cliente", 403), ("coordinador", 200), ("comercial", 200)])
def test_colors_archive_restore_and_list_archived_by_role(client, factory, role, expected):
    factory.staff("admin", "adm")
    factory.staff(role, "actor")
    login(client, "adm")
    cid = client.post("/api/colors", json={"name": "Azul", "hex": "#0000FF"}).json()["id"]
    login(client, "actor")
    assert client.post(f"/api/colors/{cid}/archive").status_code == expected
    assert client.get("/api/colors", params={"include_archived": "true"}).status_code == (expected if role in ("digitador", "cliente") else 200)
    if expected == 200:
        assert client.post(f"/api/colors/{cid}/restore").status_code == 200
        assert client.delete(f"/api/colors/{cid}").status_code == 403          # el borrado definitivo sigue siendo solo de super_admin


@pytest.mark.parametrize("role,expected", [("digitador", 403), ("cliente", 403), ("coordinador", 200), ("comercial", 200)])
def test_saved_badge_template_archive_restore_by_role(client, factory, db, role, expected):
    ev = factory.event()
    factory.staff(role, "actor")
    saved = SavedBadgeTemplate(tenant_id=ev.tenant_id, name="Base", width_mm=62, height_mm=99.8)
    db.add(saved)
    db.commit()
    login(client, "actor")
    assert client.post(f"/api/saved-badge-templates/{saved.id}/archive").status_code == expected
    if expected == 200:
        assert client.post(f"/api/saved-badge-templates/{saved.id}/restore").status_code == 200
        assert client.delete(f"/api/saved-badge-templates/{saved.id}").status_code == 403
