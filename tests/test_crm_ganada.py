"""CRM C4: ganar una oportunidad crea cliente y evento; «Mi día» y tableros (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from datetime import timedelta

from app.models import CrmActivity, CrmOpportunity, Event, EventAttendee, Tenant
from app.timeutil import to_local, utcnow
from tests.crm_helpers import crm_on, new_account, staff_client  # noqa: F401


def _stages(client):
    return {s["name"]: s for s in client.get("/api/crm/pipeline/meta").json()["pipelines"][0]["stages"]}


def _opp(client, account_id, name="Feria 2027", **extra):
    r = client.post("/api/crm/opportunities", json={"account_id": account_id, "name": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _win_by_move(client, o):
    return client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": _stages(client)["Ganada"]["id"]})


def test_winning_by_move_creates_the_client_and_the_event_with_the_same_number(client, factory, crm_on, db):
    staff = staff_client(client, factory)
    acc = new_account(client, "Cámara de Comercio de Bogotá")
    o = _opp(client, acc["id"], "Congreso 2027", event_start="2027-03-15", city="Bogotá")
    r = _win_by_move(client, o)
    assert r.status_code == 200, r.text
    won = r.json()
    assert won["outcome"] == "won" and won["event_id"]
    ev = db.get(Event, won["event_id"])
    assert ev.event_code == str(o["code"]) and ev.name == "Congreso 2027" and ev.status == "creado" and str(ev.start_date) == "2027-03-15" and ev.city == "Bogotá"
    assert ev.commercial_staff_id == staff.id and ev.created_by_id == staff.id and ev.public_slug
    tenant = db.get(Tenant, ev.tenant_id)
    assert tenant.client_code == str(acc["code"]) and tenant.name == "Cámara de Comercio de Bogotá"
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="PRUEBA").count() == 1          # la persona de prueba de siempre
    assert client.get(f"/api/crm/accounts/{acc['id']}").json()["tenant_id"] == tenant.id


def test_an_account_that_is_already_a_client_keeps_its_tenant(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    assert client.post(f"/api/crm/accounts/{acc['id']}/make-client").status_code == 200
    tenants_before = db.query(Tenant).count()
    won = _win_by_move(client, _opp(client, acc["id"])).json()
    assert db.query(Tenant).count() == tenants_before and db.get(Event, won["event_id"]).tenant_id == client.get(f"/api/crm/accounts/{acc['id']}").json()["tenant_id"]


def test_a_taken_event_code_is_a_409_and_nothing_is_created(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    o = _opp(client, acc["id"])
    factory.tenant("otro")
    db.add(Event(tenant_id="otro", event_code=str(o["code"]), name="Ya existía", status="creado"))
    db.commit()
    tenants_before = db.query(Tenant).count()
    r = _win_by_move(client, o)
    assert r.status_code == 409 and str(o["code"]) in r.json()["detail"]
    db.expire_all()
    opp = db.get(CrmOpportunity, o["id"])
    assert opp.outcome == "open" and opp.event_id is None and db.query(Tenant).count() == tenants_before          # todo o nada: ni etapa ni cliente ni evento


def test_win_endpoint_wins_an_open_opportunity_and_a_second_try_is_a_409(client, factory, crm_on, db):
    staff_client(client, factory)
    o = _opp(client, new_account(client)["id"])
    r = client.post(f"/api/crm/opportunities/{o['id']}/win")
    assert r.status_code == 200 and r.json()["outcome"] == "won" and r.json()["event"]["event_code"] == str(o["code"])
    assert client.post(f"/api/crm/opportunities/{o['id']}/win").status_code == 409
    back = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": _stages(client)["Negociación"]["id"]})
    assert back.status_code == 200 and back.json()["outcome"] == "open"          # evento «creado» y sin uso: sale de «ganada» y el evento se archiva (regla del 16-nov-2026)
    assert db.query(Event).filter_by(event_code=str(o["code"])).first().archived_at is not None


def test_win_endpoint_creates_only_the_event_for_an_already_won_opportunity(client, factory, crm_on, db):
    staff_client(client, factory)
    o = _opp(client, new_account(client)["id"])
    opp = db.get(CrmOpportunity, o["id"])
    opp.outcome, opp.closed_at = "won", utcnow()          # como las ganadas de antes de C4 o las importadas
    db.commit()
    r = client.post(f"/api/crm/opportunities/{o['id']}/win")
    assert r.status_code == 200 and r.json()["event_id"]


def test_losing_and_opening_never_create_events(client, factory, crm_on, db):
    staff_client(client, factory)
    st = _stages(client)
    o = _opp(client, new_account(client)["id"])
    client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Perdida"]["id"], "lost_reason": "Precio"})
    client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Negociación"]["id"]})
    assert db.query(Event).count() == 0


def test_an_archived_account_or_archived_client_blocks_winning(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    assert client.post(f"/api/crm/accounts/{acc['id']}/make-client").status_code == 200
    o = _opp(client, acc["id"])
    tenant = db.get(Tenant, client.get(f"/api/crm/accounts/{acc['id']}").json()["tenant_id"])
    tenant.archived_at = utcnow()
    db.commit()
    assert _win_by_move(client, o).status_code == 409 and db.query(Event).count() == 0


# ------------------------------------------------------------------ Mi día
def _act(client, **extra):
    r = client.post("/api/crm/activities", json={"kind": "call", "subject": "Llamar", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_my_day_groups_overdue_today_reminders_and_only_my_own(client, factory, crm_on, db):
    me = staff_client(client, factory)
    acc = new_account(client)
    o = _opp(client, acc["id"], "Sin próxima actividad")
    now = utcnow()
    _act(client, account_id=acc["id"], subject="Vencida", due_at=(now - timedelta(days=2)).isoformat())
    _act(client, account_id=acc["id"], subject="Hoy", due_at=now.isoformat())
    _act(client, account_id=acc["id"], subject="Mañana con aviso", due_at=(now + timedelta(days=3)).isoformat(), remind_at=(now - timedelta(hours=1)).isoformat())
    _act(client, account_id=acc["id"], subject="Lejana", due_at=(now + timedelta(days=30)).isoformat())
    other = factory.staff("comercial", "otra_comercial")
    db.add(CrmActivity(kind="task", subject="Ajena", status="planned", due_at=now - timedelta(days=1), account_id=acc["id"], owner_staff_id=other.id))
    db.commit()
    r = client.get("/api/crm/today")
    assert r.status_code == 200
    d = r.json()
    assert [a["subject"] for a in d["overdue"]] == ["Vencida"] and [a["subject"] for a in d["reminders"]] == ["Mañana con aviso"]
    assert "Hoy" in [a["subject"] for a in d["due_today"]] and "Ajena" not in [a["subject"] for a in d["overdue"] + d["due_today"]]
    assert d["overdue"][0]["account_name"] == acc["name"] and d["overdue_total"] == 1
    assert o["id"] in [x["id"] for x in d["no_next_activity"]]
    assert me.id and d["quote_soon_days"] == 7


def test_my_day_lists_closing_soon_opportunities_and_expiring_quotes(client, factory, crm_on):
    staff_client(client, factory)
    acc = new_account(client)
    soon = (utcnow() + timedelta(days=5)).date().isoformat()
    _opp(client, acc["id"], "Cierra pronto", expected_close=soon)
    _opp(client, acc["id"], "Cierra lejos", expected_close=(utcnow() + timedelta(days=90)).date().isoformat())
    client.post("/api/crm/quotes", json={"account_id": acc["id"], "title": "Por vencer", "valid_until": soon, "lines": [{"name": "x", "qty": "1", "unit_price": "1000"}]})
    d = client.get("/api/crm/today").json()
    assert [o["name"] for o in d["closing_soon"]] == ["Cierra pronto"] and [q["title"] for q in d["quotes_expiring"]] == ["Por vencer"]


# ------------------------------------------------------------------ tableros
def test_dashboards_separate_currencies_and_the_commercial_only_sees_her_own(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    _opp(client, acc["id"], "COP uno", amount="1000000", currency="COP", probability=50)
    _opp(client, acc["id"], "USD uno", amount="500", currency="USD", probability=100)
    other = factory.staff("comercial", "otra_comercial")
    db.add(CrmOpportunity(code=900, name="Ajena", account_id=acc["id"], pipeline_id=client.get("/api/crm/pipeline/meta").json()["pipelines"][0]["id"],
                          stage_id=_stages(client)["Prospecto"]["id"], amount=777, currency="COP", owner_staff_id=other.id, outcome="open"))
    db.commit()
    d = client.get("/api/crm/dashboards?owner_id=" + str(other.id)).json()          # el comercial no puede mirar a otro
    assert d["scope"] == "me" and d["by_owner"] == []
    prospecto = next(s for s in d["stages"] if s["name"] == "Prospecto")
    assert prospecto["count"] == 2 and {t["currency"]: t["amount"] for t in prospecto["totals"]} == {"COP": "1000000.00", "USD": "500.00"}


def test_admin_sees_the_whole_team_by_owner_and_win_rate(client, factory, crm_on, db):
    staff_client(client, factory, "comercial", "comercial_a")
    acc = new_account(client)
    st = _stages(client)
    won = _opp(client, acc["id"], "Ganada")
    lost = _opp(client, acc["id"], "Perdida")
    _win_by_move(client, won)
    client.post(f"/api/crm/opportunities/{lost['id']}/move", json={"stage_id": st["Perdida"]["id"], "lost_reason": "Precio"})
    _opp(client, acc["id"], "Abierta", amount="100")
    admin = staff_client(client, factory, "admin", "admin_crm")
    d = client.get("/api/crm/dashboards?days=30").json()
    assert d["scope"] == "all" and d["win_rate"] == 50 and d["closed"]["won"]["count"] == 1 and d["closed"]["lost"]["count"] == 1 and d["by_owner"]
    assert client.get("/api/crm/dashboards?days=7").json()["days"] == 90          # ventana no permitida → 90
    assert client.get(f"/api/crm/dashboards?owner_id={admin.id}").json()["scope"] == "me"


def test_c4_routes_are_off_with_the_crm_off_and_closed_to_the_coordinator(client, factory, crm_on, monkeypatch):
    staff_client(client, factory, "coordinador", "coord_c4")
    for path in ("/api/crm/today", "/api/crm/dashboards"):
        assert client.get(path).status_code == 403
    monkeypatch.setenv("CRM_ENABLED", "0")
    for path in ("/api/crm/today", "/api/crm/dashboards"):
        assert client.get(path).status_code == 404
    assert client.post("/api/crm/opportunities/1/win").status_code == 404


def test_calendar_lists_my_crm_items_by_day_and_only_mine(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    day = to_local(utcnow()).date()          # el calendario habla en fecha LOCAL (Bogotá)
    _opp(client, acc["id"], "Cierra pronto", expected_close=day.isoformat())
    _act(client, account_id=acc["id"], subject="Llamar", due_at=utcnow().isoformat())
    other = factory.staff("comercial", "otra_cal")
    db.add(CrmActivity(kind="task", subject="Ajena", status="planned", due_at=utcnow(), account_id=acc["id"], owner_staff_id=other.id))
    db.commit()
    d = client.get(f"/api/crm/calendar?start={day.isoformat()}&end={day.isoformat()}").json()
    titles = [i["title"] for i in d["items"]]
    assert "Cierra pronto" in titles and "Llamar" in titles and "Ajena" not in titles
    assert {i["label"] for i in d["items"]} >= {"Cierre esperado", "Llamada"}
    assert all(i["href"].startswith("/crm/") for i in d["items"])
