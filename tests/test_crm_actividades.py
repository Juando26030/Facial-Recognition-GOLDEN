"""CRM C2: actividades y la próxima actividad de una oportunidad (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from app.models import CrmOpportunity
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401


def _opp(client, account_id, name="Evento anual"):
    r = client.post("/api/crm/opportunities", json={"account_id": account_id, "name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _next(db, opp_id):
    db.expire_all()
    return db.get(CrmOpportunity, opp_id).next_activity_at


def test_scheduling_sets_the_next_activity_to_the_earliest_planned_one(client, factory, crm_on, db):
    staff_client(client, factory)
    opp = _opp(client, new_account(client)["id"])
    assert opp["no_next_activity"] is True
    late = client.post("/api/crm/activities", json={"kind": "call", "subject": "Llamar", "due_at": "2026-12-20T15:00:00Z", "opportunity_id": opp["id"]}).json()
    early = client.post("/api/crm/activities", json={"kind": "meeting", "subject": "Reunión", "due_at": "2026-12-10T15:00:00Z", "opportunity_id": opp["id"]}).json()
    assert _next(db, opp["id"]).isoformat() == "2026-12-10T15:00:00"
    assert client.post(f"/api/crm/activities/{early['id']}/complete", json={"result": "meeting_held"}).json()["status"] == "done"
    assert _next(db, opp["id"]).isoformat() == "2026-12-20T15:00:00"
    assert client.post(f"/api/crm/activities/{late['id']}/cancel").status_code == 200
    assert _next(db, opp["id"]) is None
    assert client.get(f"/api/crm/opportunities/{opp['id']}").json()["no_next_activity"] is True


def test_editing_and_deleting_keep_the_copy_in_step(client, factory, crm_on, db):
    staff_client(client, factory)
    opp = _opp(client, new_account(client)["id"])
    a = client.post("/api/crm/activities", json={"kind": "task", "subject": "Enviar portafolio", "due_at": "2026-12-10T15:00:00Z", "opportunity_id": opp["id"]}).json()
    r = client.put(f"/api/crm/activities/{a['id']}", json={"due_at": "2026-12-05T08:00:00Z", "updated_at": a["updated_at"]})
    assert r.status_code == 200 and _next(db, opp["id"]).isoformat() == "2026-12-05T08:00:00"
    assert client.put(f"/api/crm/activities/{a['id']}", json={"subject": "x", "updated_at": a["updated_at"]}).status_code == 409          # versión vieja
    assert client.delete(f"/api/crm/activities/{a['id']}").status_code == 200 and _next(db, opp["id"]) is None


def test_the_account_is_completed_from_the_contact_or_the_opportunity_and_links_must_agree(client, factory, crm_on):
    staff_client(client, factory)
    a1, a2 = new_account(client, "Empresa Uno"), new_account(client, "Empresa Dos")
    c1 = new_contact(client, a1["id"])
    r = client.post("/api/crm/activities", json={"kind": "call", "subject": "Hola", "contact_id": c1["id"]})
    assert r.status_code == 200 and r.json()["account_id"] == a1["id"]
    assert client.post("/api/crm/activities", json={"kind": "call", "subject": "Hola", "contact_id": c1["id"], "account_id": a2["id"]}).status_code == 400
    assert client.post("/api/crm/activities", json={"kind": "call", "subject": "Sin liga"}).status_code == 400
    assert client.post("/api/crm/activities", json={"kind": "visita", "subject": "x", "account_id": a1["id"]}).status_code == 400
    assert client.post("/api/crm/activities", json={"kind": "call", "subject": "x", "opportunity_id": 999999}).status_code == 400


def test_a_note_is_born_done_and_a_closed_activity_cannot_be_closed_again(client, factory, crm_on):
    staff_client(client, factory)
    acc = new_account(client)
    note = client.post("/api/crm/activities", json={"kind": "note", "subject": "Habló del presupuesto", "account_id": acc["id"]}).json()
    assert note["status"] == "done" and note["done_at"]
    assert client.post(f"/api/crm/activities/{note['id']}/complete", json={}).status_code == 409
    assert client.post(f"/api/crm/activities/{note['id']}/cancel").status_code == 409


def test_the_list_needs_one_link_and_shows_pending_first(client, factory, crm_on):
    staff_client(client, factory)
    acc = new_account(client)
    assert client.get("/api/crm/activities").status_code == 400
    done = client.post("/api/crm/activities", json={"kind": "call", "subject": "Vieja", "due_at": "2026-01-10T10:00:00Z", "account_id": acc["id"]}).json()
    client.post(f"/api/crm/activities/{done['id']}/complete", json={"result": "no_answer"})
    client.post("/api/crm/activities", json={"kind": "call", "subject": "Nueva", "due_at": "2026-12-10T10:00:00Z", "account_id": acc["id"]})
    items = client.get(f"/api/crm/activities?account_id={acc['id']}").json()["items"]
    assert [i["subject"] for i in items] == ["Nueva", "Vieja"] and items[1]["result_label"] == "Sin respuesta"
    assert client.get(f"/api/crm/activities?account_id={acc['id']}&status=done").json()["total"] == 1
    assert client.get("/api/crm/activities?account_id=99999999999").json()["items"] == []


def test_only_the_author_or_an_admin_deletes_an_activity(client, factory, crm_on):
    staff_client(client, factory, "comercial", "autor")
    acc = new_account(client)
    a = client.post("/api/crm/activities", json={"kind": "call", "subject": "x", "account_id": acc["id"]}).json()
    client.post("/logout")
    staff_client(client, factory, "comercial", "otro")
    assert client.delete(f"/api/crm/activities/{a['id']}").status_code == 403
    client.post("/logout")
    staff_client(client, factory, "admin", "adm_act")
    assert client.delete(f"/api/crm/activities/{a['id']}").status_code == 200
