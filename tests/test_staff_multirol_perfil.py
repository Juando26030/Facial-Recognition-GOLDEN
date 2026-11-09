"""Staff (8-nov-2026): varios roles por cuenta y edición completa del perfil."""
from app.auth import effective_roles, split_roles, all_extra_roles
from app.models import StaffUser
from tests.conftest import login


def test_split_roles_ignores_junk():
    assert split_roles("comercial, admin,,nada,comercial") == ["comercial", "admin"]
    assert split_roles(None) == []


def test_roles_are_a_union_and_admin_extra_only_by_super_admin(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    coord = factory.staff("coordinador", "coord")
    cid = coord.id
    login(client, "adm")
    r = client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["comercial"]})
    assert r.status_code == 200, r.text
    assert r.json()["extra_roles"] == ["comercial"] and r.json()["secondary_role"] == "comercial"
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["comercial", "admin"]}).status_code == 403     # admin extra: solo super_admin
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["bodega"]}).status_code == 400                 # aún no existe
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["coordinador"]}).status_code == 400           # ya es el principal
    client.post("/logout")
    login(client, "sup")
    r = client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["comercial", "admin"]})
    assert r.status_code == 200, r.text
    db.expire_all()
    target = db.get(StaffUser, cid)
    assert effective_roles(target) == {"coordinador", "comercial", "admin"} and all_extra_roles(target) == ["comercial", "admin"]
    client.post("/logout")
    login(client, "adm")
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["comercial"]}).status_code == 403             # un admin no le quita el admin
    client.post("/logout")
    login(client, "sup")
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": []}).json()["extra_roles"] == []


def test_extra_admin_gives_admin_permissions_and_cannot_target_self_or_other_roles(client, factory, db):
    factory.staff("admin", "adm")
    com = factory.staff("comercial", "com", extra_roles="admin")
    dig = factory.staff("digitador", "5551234")
    login(client, "adm")
    assert client.put(f"/api/staff/{dig.id}/roles", json={"extra_roles": ["comercial"]}).status_code == 403          # digitador/cliente no reciben extras
    me = db.query(StaffUser).filter_by(username="adm").one()
    assert client.put(f"/api/staff/{me.id}/roles", json={"extra_roles": []}).status_code == 400                       # ni la propia cuenta
    client.post("/logout")
    login(client, "com")
    assert client.get("/api/staff").status_code == 200                                                               # require_role("admin") pasa por el rol extra
    assert com.id


def test_edit_profile_changes_everything_and_respects_rank(client, factory, db):
    factory.staff("admin", "adm")
    factory.staff("admin", "otro_adm")
    coord = factory.staff("coordinador", "coord", phone="+573001110000")
    otra = factory.staff("coordinador", "otra", phone="+573002220000")
    cid, oid = coord.id, otra.id
    login(client, "adm")
    r = client.patch(f"/api/staff/{cid}/profile", json={"username": "coord.nuevo", "full_name": "Ana Pérez", "email": "ana@example.com", "phone": "+573009998888"})
    assert r.status_code == 200, r.text
    db.expire_all()
    c = db.get(StaffUser, cid)
    assert (c.username, c.full_name, c.email, c.phone) == ("coord.nuevo", "Ana Pérez", "ana@example.com", "+573009998888")
    assert client.patch(f"/api/staff/{cid}/profile", json={"username": "otra"}).status_code == 400                     # usuario repetido
    assert client.patch(f"/api/staff/{cid}/profile", json={"phone": "+573002220000"}).status_code == 400                # celular repetido
    assert client.patch(f"/api/staff/{cid}/profile", json={"phone": ""}).status_code == 400                             # obligatorio
    assert client.patch(f"/api/staff/{cid}/profile", json={"email": "no-es-correo"}).status_code == 400
    assert client.patch(f"/api/staff/{cid}/profile", json={"username": "a b<"}).status_code == 400
    other_admin = db.query(StaffUser).filter_by(username="otro_adm").one()
    assert client.patch(f"/api/staff/{other_admin.id}/profile", json={"full_name": "X"}).status_code == 403            # mismo rango
    me = db.query(StaffUser).filter_by(username="adm").one()
    assert client.patch(f"/api/staff/{me.id}/profile", json={"username": "cambio"}).status_code == 400                  # el propio usuario no
    assert client.patch(f"/api/staff/{me.id}/profile", json={"full_name": "Yo"}).status_code == 200
    assert oid


def test_account_with_extra_admin_is_protected_like_an_admin(client, factory, db):
    """Ronda de seguridad F4: un admin no toca (correo, perfil, clave, desactivar, borrar) a un coordinador con admin sumado."""
    factory.staff("admin", "adm")
    factory.staff("super_admin", "sup")
    coord = factory.staff("coordinador", "coordx")
    cid = coord.id
    login(client, "sup")
    assert client.put(f"/api/staff/{cid}/roles", json={"extra_roles": ["admin"]}).status_code == 200
    client.post("/logout")
    login(client, "adm")
    assert client.patch(f"/api/staff/{cid}/email", json={"email": "otro@example.com"}).status_code == 403
    assert client.patch(f"/api/staff/{cid}/profile", json={"full_name": "Nuevo Nombre"}).status_code == 403
    assert client.put(f"/api/staff/{cid}/password", json={"password": "NuevaClave#2026"}).status_code == 403
    assert client.patch(f"/api/staff/{cid}/deactivate").status_code == 403
    assert client.delete(f"/api/staff/{cid}").status_code == 403
    client.post("/logout")
    login(client, "sup")
    assert client.patch(f"/api/staff/{cid}/profile", json={"full_name": "Nuevo Nombre"}).status_code == 200
