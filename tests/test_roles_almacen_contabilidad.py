"""Fase 5 · roles «almacen» y «contabilidad»: fuera de la escalera de STAFF_ROLES; sirven como rol PRINCIPAL (cuenta solo de almacén o solo de contabilidad) y como extra (se suman a coordinador/comercial y entre ellos). Sin tocar la jerarquía."""
import pytest
from fastapi import HTTPException

from app import auth
from app.auth import EXTRA_ONLY_ROLES, ROLE_HIERARCHY, effective_roles, has_any_role, split_roles, staff_with_role
from app.models import STAFF_ROLES, StaffUser
from app.routers.staff import _rank
from tests.conftest import login


def test_extra_only_roles_are_outside_the_ladder():
    assert "almacen" not in STAFF_ROLES and "contabilidad" not in STAFF_ROLES
    assert STAFF_ROLES == ("cliente", "digitador", "coordinador", "comercial", "admin", "super_admin")
    assert set(EXTRA_ONLY_ROLES) == {"almacen", "contabilidad"} and EXTRA_ONLY_ROLES["almacen"] == "Almacén"
    assert all(ROLE_HIERARCHY[r] < ROLE_HIERARCHY["cliente"] for r in EXTRA_ONLY_ROLES)          # nunca suben ni bajan el rango de la cuenta
    assert {"almacen", "contabilidad"} <= set(auth.EXTRA_ROLE_CHOICES) and {"almacen", "contabilidad"} <= set(auth.EXTRA_ROLE_PRIMARIES) and set(auth.STANDALONE_ROLES) == {"almacen", "contabilidad"}
    assert split_roles("almacen, contabilidad,bodega,almacen") == ["almacen", "contabilidad"]


def test_rank_and_permissions_come_from_the_main_role(factory):
    a = factory.staff("coordinador", "a1", extra_roles="almacen")
    b = factory.staff("comercial", "b1", extra_roles="contabilidad,almacen")
    assert effective_roles(a) == {"coordinador", "almacen"} and _rank(a) == STAFF_ROLES.index("coordinador")
    assert _rank(b) == STAFF_ROLES.index("comercial") and has_any_role(b, "contabilidad") and not has_any_role(a, "contabilidad")
    assert auth.all_extra_roles(b) == ["contabilidad", "almacen"]
    with pytest.raises(HTTPException) as exc:
        auth.require_role("admin")(a)                                              # el extra no da rango de admin
    assert exc.value.status_code == 403
    assert auth.require_role("coordinador")(a) is a
    assert auth.require_role_or_any("admin", ("almacen",))(a) is a
    with pytest.raises(HTTPException):
        auth.require_role_or_any("admin", ("contabilidad",))(a)


def test_admin_gives_the_roles_as_extras_and_only_super_admin_gives_admin(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    cid, mid = coord.id, com.id
    login(client, "adm")
    r = client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["almacen"]})
    assert r.status_code == 200, r.text
    assert r.json()["extra_roles"] == ["almacen"] and r.json()["secondary_role"] is None and r.json()["role"] == "coordinador"
    r = client.put(f"/api/staff/{mid}/roles", json={"extra_roles": ["contabilidad", "almacen"]})
    assert r.status_code == 200 and r.json()["extra_roles"] == ["contabilidad", "almacen"]
    r = client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["comercial", "almacen"]})          # con el par coordinador+comercial el espejo heredado sigue funcionando
    assert r.status_code == 200 and r.json()["secondary_role"] == "comercial" and r.json()["extra_roles"] == ["comercial", "almacen"]
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["almacen", "admin"]}).status_code == 403          # «admin» sigue siendo solo del Super Admin
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["bodega"]}).status_code == 400
    # también son roles principales (cuentas solo de almacén / solo de contabilidad)
    assert client.patch(f"/api/staff/{cid}/role", json={"role": "bodega"}).status_code == 400
    r = client.post("/api/staff", json={"username": "nuevo_alm", "password": "Clave#Segura2026x", "role": "almacen", "full_name": "N", "phone": "+573119998877"})
    assert r.status_code == 200 and r.json()["role"] == "almacen"
    r = client.post("/api/staff", json={"username": "nuevo_con", "password": "Clave#Segura2026x", "role": "contabilidad", "full_name": "C", "phone": "+573119998866"})
    assert r.status_code == 200 and r.json()["role"] == "contabilidad"
    assert client.post("/api/staff", json={"username": "x_bodega", "password": "Clave#Segura2026x", "role": "bodega", "full_name": "N", "phone": "+573119998855"}).status_code == 400
    db.expire_all()
    assert effective_roles(db.get(StaffUser, cid)) == {"coordinador", "comercial", "almacen"}
    # un admin no le quita a alguien un admin sumado, pero sí puede manejar los extras normales de una cuenta sin admin
    client.post("/logout")
    login(client, "sup")
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["almacen", "admin"]}).status_code == 200
    client.post("/logout")
    login(client, "adm")
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": []}).status_code == 403


def test_digitador_and_cliente_do_not_receive_them(client, factory):
    factory.staff("admin", "adm")
    dig = factory.staff("digitador", "7003333")
    login(client, "adm")
    assert client.put(f"/api/staff/{dig.id}/roles", json={"extra_roles": ["almacen"]}).status_code == 403


def test_changing_the_main_role_keeps_or_clears_extras_coherently(client, factory, db):
    factory.staff("super_admin", "sup")
    coord = factory.staff("coordinador", "coord", extra_roles="almacen")
    cid = coord.id
    login(client, "sup")
    assert client.patch(f"/api/staff/{cid}/role", json={"role": "comercial"}).json()["extra_roles"] == ["almacen"]          # el extra sigue valiendo para el nuevo principal
    assert client.patch(f"/api/staff/{cid}/role", json={"role": "admin"}).json()["extra_roles"] == []                       # admin como principal no lleva extras


def test_staff_with_role_returns_active_accounts_with_that_role(db, factory):
    a = factory.staff("coordinador", "a", email="a@example.com", extra_roles="almacen")
    b = factory.staff("comercial", "b", email="b@example.com", extra_roles="contabilidad,almacen")
    factory.staff("coordinador", "c", extra_roles="contabilidad")
    d = factory.staff("coordinador", "d", extra_roles="almacen")
    d.is_active = False
    e = factory.staff("comercial", "e", extra_roles="almacen")
    from app.timeutil import utcnow
    e.archived_at = utcnow()
    db.commit()
    assert [s.username for s in staff_with_role(db, "almacen")] == ["a", "b"]
    assert [s.username for s in staff_with_role(db, "contabilidad")] == ["b", "c"]
    assert [s.username for s in staff_with_role(db, "coordinador")] == ["a", "c"]          # también sirve con los roles de siempre
    assert staff_with_role(db, "nadie") == [] and [s.email for s in staff_with_role(db, "almacen") if s.email] == ["a@example.com", "b@example.com"]
    assert a.id and b.id


def test_login_and_pages_work_with_extra_only_roles(client, factory):
    factory.staff("coordinador", "alm", extra_roles="almacen")
    r = login(client, "alm")
    assert r.status_code in (200, 302, 303)
    assert client.get("/configuracion").status_code == 200
    assert client.get("/calendario").status_code == 200
    assert client.get("/api/staff").status_code == 403                                  # no administra cuentas
    assert client.get("/admin/staff").status_code in (302, 303, 307)                    # la página de cuentas lo devuelve al inicio


def test_they_do_not_open_attendee_data(client, factory):
    factory.staff("comercial", "conta", extra_roles="contabilidad")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "conta")
    # el extra no agrega nada: lo que ya NO podía una comercial pura sigue igual (p. ej. no es admin) y las rutas de cuentas siguen cerradas
    assert client.get("/api/staff").status_code == 403
    assert client.put("/api/staff/1/roles", json={"extra_roles": ["almacen"]}).status_code == 403


# ---------------------------------------------------------------- cuentas solo de almacén / solo de contabilidad (decisión de Juan David, 9-nov-2026)
@pytest.mark.parametrize("role", ["almacen", "contabilidad"])
def test_standalone_account_lands_on_inventory_and_nothing_else(client, factory, role):
    factory.staff(role, "solo")
    login(client, "solo")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/inventario"
    assert client.get("/inventario").status_code == 200
    assert client.get("/clientes", follow_redirects=False).status_code in (302, 303, 307)          # sin panel de clientes
    assert client.get("/eventos", follow_redirects=False).status_code in (302, 303, 307)
    assert client.get("/api/staff").status_code == 403
    assert client.get("/api/inventory/events").status_code == 200


def test_standalone_almacen_edits_and_contabilidad_only_reads(client, factory, db):
    from app.models import InventoryProduct
    ev = factory.event("creado")
    prod = InventoryProduct(name="Carpa", unit="und")
    db.add(prod)
    db.commit()
    factory.staff("almacen", "alm")
    factory.staff("contabilidad", "con")
    login(client, "con")
    assert client.get(f"/api/events/{ev.id}/inventory-plan").status_code == 200
    r = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod.id, "assigned": 3}]})
    assert r.status_code == 403
    client.post("/logout")
    login(client, "alm")
    r = client.put(f"/api/events/{ev.id}/inventory-plan", json={"lines": [{"product_id": prod.id, "assigned": 3}]})
    assert r.status_code == 200, r.text
    assert any(e["id"] == ev.id for e in client.get("/api/inventory/events").json()["events"])


def test_roles_mix_freely_over_a_standalone_account(client, factory, db):
    factory.staff("admin", "adm")
    alm = factory.staff("almacen", "alm2")
    login(client, "adm")
    r = client.put(f"/api/staff/{alm.id}/roles", json={"extra_roles": ["contabilidad", "comercial"]})
    assert r.status_code == 200 and sorted(r.json()["extra_roles"]) == ["comercial", "contabilidad"]
    db.expire_all()
    got = db.get(StaffUser, alm.id)
    assert effective_roles(got) == {"almacen", "contabilidad", "comercial"} and not auth.is_inventory_only(got)          # con comercial ya tiene panel
    assert client.put(f"/api/staff/{alm.id}/roles", json={"extra_roles": ["almacen"]}).status_code == 400          # no se repite el principal
    assert client.put(f"/api/staff/{alm.id}/roles", json={"extra_roles": ["admin"]}).status_code == 403          # admin sigue siendo del Super Admin
    assert auth.is_inventory_only({"almacen", "contabilidad"}) and not auth.is_inventory_only({"almacen", "coordinador"})


def test_admin_cannot_promote_or_manage_beyond_rank_with_standalone_roles(client, factory):
    factory.staff("coordinador", "coord")
    alm = factory.staff("almacen", "alm3")
    login(client, "coord")
    assert client.put(f"/api/staff/{alm.id}/roles", json={"extra_roles": ["contabilidad"]}).status_code == 403          # solo admin+ da roles
