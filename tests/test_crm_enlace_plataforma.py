"""CRM ↔ plataforma (16-nov-2026): un evento creado en Eventos tiene su cuenta y su oportunidad ganada; sacar una oportunidad de «ganada» archiva su evento «creado» y volver a ganarla lo restaura
(con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from app.models import CrmAccount, CrmOpportunity, Event
from tests.conftest import login
from tests.crm_helpers import crm_on, new_account, staff_client  # noqa: F401


def _stages(client):
    return {s["name"]: s for s in client.get("/api/crm/pipeline/meta").json()["pipelines"][0]["stages"]}


def _event_payload(tenant_id, coord_id, code="EV-ENL-1", **extra):
    base = {"tenant_id": tenant_id, "event_code": code, "name": "Feria del Libro", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
            "start_date": "2027-04-01", "end_date": "2027-04-02", "setup_date": "2027-03-31", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord_id}
    base.update(extra)
    return base


def test_event_created_in_eventos_gets_a_won_opportunity_linked_to_the_client_account(client, factory, crm_on, db):
    me = staff_client(client, factory)
    coord = factory.staff("coordinador", "coord_enl")
    login(client, me.username)
    tenant = client.post("/api/tenants", json={"name": "Editorial Andina"}).json()
    r = client.post("/api/events", json=_event_payload(tenant["id"], coord.id))
    assert r.status_code == 200, r.text
    event_id = r.json()["id"]
    opp = db.query(CrmOpportunity).filter_by(event_id=event_id).one()
    assert opp.outcome == "won" and opp.name == "Feria del Libro" and opp.owner_staff_id == me.id
    assert db.get(CrmAccount, opp.account_id).tenant_id == tenant["id"]
    assert db.query(CrmOpportunity).filter_by(event_id=event_id).count() == 1


def test_client_without_a_numeric_code_does_not_block_creating_the_event(client, factory, crm_on, db):
    me = staff_client(client, factory)
    coord = factory.staff("coordinador", "coord_enl2")
    factory.tenant("acme")          # código «Cacme»: de antes del CRM, sin número consecutivo → queda para el emparejamiento
    login(client, me.username)
    r = client.post("/api/events", json=_event_payload("acme", coord.id, code="EV-ENL-2"))
    assert r.status_code == 200, r.text
    assert db.query(CrmOpportunity).filter_by(event_id=r.json()["id"]).count() == 0


def test_crm_off_creates_no_opportunity(client, factory, db):
    me = staff_client(client, factory)
    coord = factory.staff("coordinador", "coord_enl3")
    factory.tenant("acme")
    login(client, me.username)
    r = client.post("/api/events", json=_event_payload("acme", coord.id, code="EV-ENL-3"))
    assert r.status_code == 200 and db.query(CrmOpportunity).count() == 0


def test_leaving_won_archives_the_created_event_and_winning_again_restores_it(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    o = client.post("/api/crm/opportunities", json={"account_id": acc["id"], "name": "Congreso 2027"}).json()
    won = client.post(f"/api/crm/opportunities/{o['id']}/win")
    assert won.status_code == 200, won.text
    event_id = won.json()["event"]["id"] if "event" in won.json() and "id" in won.json()["event"] else won.json()["event_id"]
    back = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": _stages(client)["Negociación"]["id"]})
    assert back.status_code == 200 and back.json()["outcome"] == "open"
    db.expire_all()
    assert db.get(Event, event_id).archived_at is not None
    again = client.post(f"/api/crm/opportunities/{o['id']}/win")
    assert again.status_code == 200, again.text
    db.expire_all()
    ev = db.get(Event, event_id)
    assert ev.archived_at is None and db.query(Event).count() == 1          # el MISMO evento vuelve; no se crea otro


def test_event_already_in_process_blocks_leaving_won(client, factory, crm_on, db):
    staff_client(client, factory)
    o = client.post("/api/crm/opportunities", json={"account_id": new_account(client)["id"], "name": "Feria"}).json()
    client.post(f"/api/crm/opportunities/{o['id']}/win")
    ev = db.query(Event).filter_by(event_code=str(o["code"])).one()
    ev.status = "en_proceso"
    db.commit()
    r = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": _stages(client)["Negociación"]["id"]})
    assert r.status_code == 409 and "en proceso" in r.json()["detail"]
    db.expire_all()
    assert db.get(Event, ev.id).archived_at is None
