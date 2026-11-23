"""CRM C1b-1: contactos, único principal y regla del contacto principal (CRM → cliente, un solo sentido); crear cliente desde /clientes (D2) y editar contacto en /clientes (D3). Necesitan PostgreSQL."""
from app import models as m
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def _primary_ids(db, account_id):
    return [c.id for c in db.query(m.CrmContact).filter_by(account_id=account_id, is_primary=True)]


def test_first_contact_is_primary_and_a_second_is_not(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client)
    c1 = new_contact(client, a["id"], "Ana", "Pérez")
    c2 = new_contact(client, a["id"], "Beto", "Gómez")
    assert c1["is_primary"] is True and c2["is_primary"] is False and _primary_ids(db, a["id"]) == [c1["id"]]
    assert db.query(m.CrmChangeLog).count() == 0                                                   # altas: sin historial


def test_make_primary_swaps_without_ever_having_two(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client)
    c1 = new_contact(client, a["id"], "Ana", "Pérez")
    c2 = new_contact(client, a["id"], "Beto", "Gómez")
    assert client.post(f"/api/crm/contacts/{c2['id']}/make-primary").json()["is_primary"] is True
    assert _primary_ids(db, a["id"]) == [c2["id"]]
    c3 = new_contact(client, a["id"], "Carla", "Ruiz", make_primary=True)
    assert _primary_ids(db, a["id"]) == [c3["id"]]
    flips = {(r.entity_id, r.old_value, r.new_value) for r in db.query(m.CrmChangeLog).filter_by(entity="contact", field_key="is_primary")}
    assert flips == {(c1["id"], "True", "False"), (c2["id"], "False", "True"), (c2["id"], "True", "False")}          # cada cambio de principal queda en el historial; el alta de Carla no


def test_contact_needs_a_name_and_a_valid_email(client, factory, crm_on):
    staff_client(client, factory)
    a = new_account(client)
    assert client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"email": "a@b.co"}).status_code == 400
    assert client.post(f"/api/crm/accounts/{a['id']}/contacts", json={"first_name": "Ana", "email": "mal"}).status_code == 400
    assert client.post("/api/crm/accounts/99999/contacts", json={"first_name": "Ana"}).status_code == 404


def test_update_contact_version_normalized_columns_and_history(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client)
    c = new_contact(client, a["id"], "Ana", "Pérez", email="ana@x.co")
    assert client.put(f"/api/crm/contacts/{c['id']}", json={"last_name": "Gómez"}).status_code == 400
    ok = client.put(f"/api/crm/contacts/{c['id']}", json={"last_name": "Gómez", "email": "Ana.G@X.co", "updated_at": c["updated_at"]})
    assert ok.status_code == 200 and ok.json()["full_name"] == "Ana Gómez"
    assert client.put(f"/api/crm/contacts/{c['id']}", json={"last_name": "Pisada", "updated_at": c["updated_at"]}).status_code == 409
    row = db.get(m.CrmContact, c["id"])
    assert row.full_name_norm == "ana gomez" and row.email_norm == "ana.g@x.co"
    assert {r.field_key for r in db.query(m.CrmChangeLog).filter_by(entity="contact")} == {"last_name", "email"}


def test_archiving_the_primary_removes_the_flag_and_blocks_promoting_it(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client)
    c1 = new_contact(client, a["id"])
    assert client.post(f"/api/crm/contacts/{c1['id']}/archive").json()["archived"] is True
    assert _primary_ids(db, a["id"]) == [] and client.post(f"/api/crm/contacts/{c1['id']}/make-primary").status_code == 400
    assert client.get(f"/api/crm/accounts/{a['id']}/contacts").json() == []
    assert len(client.get(f"/api/crm/accounts/{a['id']}/contacts", params={"archived": "true"}).json()) == 1
    assert client.post(f"/api/crm/contacts/{c1['id']}/archive").status_code == 400
    assert client.post(f"/api/crm/contacts/{c1['id']}/restore").status_code == 200


# ------------------------------------------------------------------ regla del contacto principal
def _client_account(client, factory, db, name="Cliente Uno"):
    a = new_account(client, name)
    r = client.post(f"/api/crm/accounts/{a['id']}/make-client")
    assert r.status_code == 200, r.text
    return r.json()


def test_primary_is_mirrored_to_the_tenant_mobile_first(client, factory, crm_on, db):
    staff_client(client, factory)
    a = _client_account(client, factory, db)
    new_contact(client, a["id"], "Ana", "Pérez", email="ana@x.co", phone="6015551234", mobile="3001234567")
    t = db.get(m.Tenant, a["tenant_id"])
    assert (t.contact_name, t.contact_phone, t.contact_email) == ("Ana Pérez", "3001234567", "ana@x.co")
    b = new_contact(client, a["id"], "Beto", "Gómez", phone="6019998888")
    assert db.get(m.Tenant, a["tenant_id"]).contact_name == "Ana Pérez"                      # un contacto que no es principal no copia nada
    client.post(f"/api/crm/contacts/{b['id']}/make-primary")
    db.expire_all()
    t = db.get(m.Tenant, a["tenant_id"])
    assert (t.contact_name, t.contact_phone, t.contact_email) == ("Beto Gómez", "6019998888", None)          # fijo si no hay celular; el correo también se reemplaza


def test_editing_the_primary_updates_the_tenant_but_never_the_other_way(client, factory, crm_on, db):
    staff_client(client, factory)
    a = _client_account(client, factory, db)
    c = new_contact(client, a["id"], "Ana", "Pérez", mobile="3001112222")
    client.put(f"/api/crm/contacts/{c['id']}", json={"mobile": "3009998888", "updated_at": c["updated_at"]})
    db.expire_all()
    assert db.get(m.Tenant, a["tenant_id"]).contact_phone == "3009998888"
    t = db.get(m.Tenant, a["tenant_id"])
    t.contact_name = "Escrito a mano"
    db.commit()
    assert db.get(m.CrmContact, c["id"]).first_name == "Ana"                                  # el contacto del CRM no se entera


def test_losing_the_primary_keeps_the_copied_values(client, factory, crm_on, db):
    staff_client(client, factory)
    a = _client_account(client, factory, db)
    c = new_contact(client, a["id"], "Ana", "Pérez", email="ana@x.co")
    client.post(f"/api/crm/contacts/{c['id']}/archive")
    db.expire_all()
    assert db.get(m.Tenant, a["tenant_id"]).contact_email == "ana@x.co"


def test_account_without_tenant_copies_nothing(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client)
    new_contact(client, a["id"], "Ana", "Pérez")
    assert db.query(m.Tenant).count() == 0


# ------------------------------------------------------------------ D3: /clientes solo lectura con principal
def test_tenant_contact_fields_are_locked_when_the_account_has_a_primary(client, factory, crm_on, db):
    staff_client(client, factory)
    a = _client_account(client, factory, db)
    tid = a["tenant_id"]
    assert client.patch(f"/api/tenants/{tid}", json={"contact_name": "Libre"}).status_code == 200          # sin principal: se edita aquí
    new_contact(client, a["id"], "Ana", "Pérez", email="ana@x.co")
    r = client.patch(f"/api/tenants/{tid}", json={"contact_name": "Otro", "contact_phone": "1"})
    assert r.status_code == 409 and "CRM" in r.json()["detail"]
    assert client.patch(f"/api/tenants/{tid}", json={"name": "Cliente Renombrado"}).status_code == 200      # el nombre del cliente sí
    assert client.patch(f"/api/tenants/{tid}", json={"name": "Cliente Renombrado 2", "contact_name": "Ana Pérez", "contact_email": "ana@x.co"}).status_code == 200          # mismos valores: no cuenta


def test_lock_does_not_apply_with_the_crm_off(client, factory, crm_on, db, monkeypatch):
    staff_client(client, factory)
    a = _client_account(client, factory, db)
    new_contact(client, a["id"], "Ana", "Pérez")
    monkeypatch.setenv("CRM_ENABLED", "0")
    assert client.patch(f"/api/tenants/{a['tenant_id']}", json={"contact_name": "Libre otra vez"}).status_code == 200


# ------------------------------------------------------------------ D2: cliente nuevo desde /clientes
def test_new_tenant_gets_its_crm_account_with_the_same_number_and_primary_contact(client, factory, crm_on, db):
    staff_client(client, factory)
    t = client.post("/api/tenants", json={"name": "Nuevo Cliente", "contact_name": "Ana Pérez", "contact_email": "ana@x.co", "contact_phone": "3001234567"}).json()
    assert t["client_code"] == "1001"
    acc = db.query(m.CrmAccount).filter_by(tenant_id=t["id"]).one()
    assert acc.code == 1001 and acc.name == "Nuevo Cliente" and acc.name_norm == "nuevo cliente"
    c = db.query(m.CrmContact).filter_by(account_id=acc.id).one()
    assert (c.first_name, c.last_name, c.is_primary, c.email_norm) == ("Ana", "Pérez", True, "ana@x.co")
    assert new_account(client, "Siguiente")["code"] == 1002                                      # un solo número por cliente


def test_new_tenant_without_a_contact_name_creates_no_contact(client, factory, crm_on, db):
    staff_client(client, factory)
    client.post("/api/tenants", json={"name": "Sin Contacto", "contact_phone": "3001234567"})
    assert db.query(m.CrmAccount).count() == 1 and db.query(m.CrmContact).count() == 0


def test_new_tenant_with_the_crm_off_is_unchanged(client, factory, db, monkeypatch):
    monkeypatch.delenv("CRM_ENABLED", raising=False)
    staff_client(client, factory)
    t = client.post("/api/tenants", json={"name": "Clásico"}).json()
    assert len(t["client_code"]) == 8 and db.query(m.CrmAccount).count() == 0


# ------------------------------------------------------------------ convertir en cliente
def test_make_client_uses_the_accounts_own_number(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client, "Convertible")
    new_contact(client, a["id"], "Ana", "Pérez", email="ana@x.co")
    r = client.post(f"/api/crm/accounts/{a['id']}/make-client").json()
    t = db.get(m.Tenant, r["tenant_id"])
    assert t.client_code == "1001" and r["is_client"] is True and t.contact_email == "ana@x.co"
    assert client.post(f"/api/crm/accounts/{a['id']}/make-client").status_code == 409
    assert new_account(client, "Después")["code"] == 1002                                      # convertir NO gasta números
    assert db.query(m.AuditAction).filter_by(action="make_client").count() == 1


def test_make_client_refuses_when_another_tenant_already_has_that_code(client, factory, crm_on, db):
    staff_client(client, factory)
    a = new_account(client, "Choque")
    other = factory.tenant("viejo")
    other.client_code = str(a["code"])
    db.commit()
    assert client.post(f"/api/crm/accounts/{a['id']}/make-client").status_code == 409
