"""CRM C2: leads y conversión (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from app.models import CrmAccount, CrmContact, CrmOpportunity
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def _lead(client, **extra):
    body = {"first_name": "Lucía", "last_name": "Ficticia", "company_name": "Empresa Inventada SAS", "email": "lucia@ejemplo.test", "phone": "3000000000", "source": "web"}
    body.update(extra)
    r = client.post("/api/crm/leads", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_a_lead_needs_some_identity_and_a_valid_email(client, factory, crm_on):
    staff_client(client, factory)
    assert _lead(client)["status"] == "nuevo"
    assert client.post("/api/crm/leads", json={"source": "web"}).status_code == 400
    assert client.post("/api/crm/leads", json={"first_name": "Ana", "email": "no-es-correo"}).status_code == 400


def test_a_repeated_email_is_a_409_unless_the_duplicate_is_confirmed(client, factory, crm_on):
    staff_client(client, factory)
    _lead(client)
    assert client.post("/api/crm/leads", json={"first_name": "Otra", "email": "LUCIA@ejemplo.test"}).status_code == 409
    assert client.post("/api/crm/leads", json={"first_name": "Otra", "email": "LUCIA@ejemplo.test", "confirm_duplicate": True}).status_code == 200


def test_convert_creates_account_contact_and_optionally_an_opportunity_in_one_step(client, factory, crm_on, db):
    staff_client(client, factory)
    lead = _lead(client)
    r = client.post(f"/api/crm/leads/{lead['id']}/convert", json={"create_opportunity": True, "name": "Congreso 2027", "amount": "3000000"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["account_created"] is True and out["contact_id"] and out["opportunity_id"] and out["opportunity_code"] >= 1
    assert db.get(CrmAccount, out["account_id"]).name == "Empresa Inventada SAS"
    assert db.get(CrmContact, out["contact_id"]).email == "lucia@ejemplo.test"
    got = client.get(f"/api/crm/leads/{lead['id']}").json()
    assert got["status"] == "convertido" and got["converted_account_id"] == out["account_id"] and got["converted_opportunity_id"] == out["opportunity_id"]
    assert client.post(f"/api/crm/leads/{lead['id']}/convert", json={}).status_code == 409          # no se convierte dos veces


def test_convert_into_an_existing_account_and_a_failure_leaves_nothing_behind(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client, "Cuenta Existente")
    lead = _lead(client)
    bad = client.post(f"/api/crm/leads/{lead['id']}/convert", json={"account_id": acc["id"], "create_opportunity": True, "name": "x", "amount": "-1"})
    assert bad.status_code == 400
    assert client.get(f"/api/crm/leads/{lead['id']}").json()["status"] == "nuevo"
    assert db.query(CrmContact).filter_by(account_id=acc["id"]).count() == 0 and db.query(CrmOpportunity).count() == 0
    ok = client.post(f"/api/crm/leads/{lead['id']}/convert", json={"account_id": acc["id"]})
    assert ok.status_code == 200 and ok.json()["account_created"] is False and ok.json()["opportunity_id"] is None
    assert client.post(f"/api/crm/leads/{_lead(client, email='otro@ejemplo.test')['id']}/convert", json={"account_id": 999999}).status_code == 400


def test_discard_archive_and_restore(client, factory, crm_on):
    staff_client(client, factory, "admin", "adm_lead")
    lead = _lead(client)
    assert client.post(f"/api/crm/leads/{lead['id']}/discard").json()["status"] == "descartado"
    assert client.post(f"/api/crm/leads/{lead['id']}/archive").json()["archived"] is True
    assert client.post(f"/api/crm/leads/{lead['id']}/restore").json()["archived"] is False


def test_erasing_a_lead_needs_an_admin_the_exact_name_and_a_reason(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_lead")
    lead = _lead(client)
    assert client.get(f"/api/crm/leads/{lead['id']}/erase-preview").status_code == 403
    client.post("/logout")
    staff_client(client, factory, "admin", "adm_lead2")
    preview = client.get(f"/api/crm/leads/{lead['id']}/erase-preview").json()
    assert "counts" in preview
    url = f"/api/crm/leads/{lead['id']}/erase"
    assert client.post(url, json={"reason": "solicitud del titular", "confirm_name": "Otro Nombre"}).status_code == 400
    assert client.post(url, json={"reason": "", "confirm_name": "Lucía Ficticia"}).status_code == 400
    ok = client.post(url, json={"reason": "solicitud del titular", "confirm_name": "Lucía Ficticia"})
    assert ok.status_code == 200 and "counts" in ok.json()
    assert client.get(f"/api/crm/leads/{lead['id']}").status_code == 404


def test_erasing_a_contact_removes_leads_with_the_same_email_and_only_flags_the_rest(client, factory, crm_on):
    staff_client(client, factory, "admin", "adm_cross")
    acc = new_account(client)
    contact = new_contact(client, acc["id"], first_name="Lucía", last_name="Ficticia", email="lucia@ejemplo.test")
    same = _lead(client)
    homonym = _lead(client, email="otra@ejemplo.test")
    r = client.post(f"/api/crm/contacts/{contact['id']}/erase", json={"reason": "solicitud del titular", "confirm_name": "Lucía Ficticia"})
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["leads"] == 1
    assert client.get(f"/api/crm/leads/{same['id']}").status_code == 404
    assert client.get(f"/api/crm/leads/{homonym['id']}").status_code == 200          # el homónimo no se borra solo; queda para revisión
