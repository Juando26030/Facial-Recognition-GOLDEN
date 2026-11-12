"""CRM C2: oportunidades y tablero (con base de datos; SIN EJECUTAR hasta que Juan David las corra)."""
from sqlalchemy import event

from app.database import engine
from app.models import CrmChangeLog, CrmOpportunity
from tests.crm_helpers import crm_on, new_account, staff_client  # noqa: F401


def _stages(client):
    return {s["name"]: s for s in client.get("/api/crm/pipeline/meta").json()["pipelines"][0]["stages"]}


def _opp(client, account_id, name="Feria 2027", **extra):
    r = client.post("/api/crm/opportunities", json={"account_id": account_id, "name": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_takes_the_next_event_number_starts_in_the_first_open_stage_and_defaults_the_owner(client, factory, crm_on):
    staff = staff_client(client, factory)
    acc = new_account(client)
    a, b = _opp(client, acc["id"], "Uno"), _opp(client, acc["id"], "Dos", amount="2500000", currency="usd", probability=30)
    assert (a["code"], b["code"]) == (1, 2)          # contador `event` sembrado en 0: primer número libre = 1
    assert a["stage_name"] == "Prospecto" and a["outcome"] == "open" and a["owner_staff_id"] == staff.id and a["amount"] == "0.00" and a["currency"] == "COP"
    assert b["amount"] == "2500000.00" and b["currency"] == "USD" and b["probability"] == 30 and b["own_probability"] == 30 and a["probability"] == 10


def test_creating_needs_an_account_a_name_and_valid_values(client, factory, crm_on):
    staff_client(client, factory)
    acc = new_account(client)
    for body in ({"name": "x"}, {"account_id": acc["id"]}, {"account_id": acc["id"], "name": "x", "amount": "-5"}, {"account_id": acc["id"], "name": "x", "currency": "EUR"},
                 {"account_id": acc["id"], "name": "x", "probability": 101}, {"account_id": acc["id"], "name": "x", "expected_close": "20/11/2026"}, {"account_id": 999999, "name": "x"},
                 {"account_id": acc["id"], "name": "x", "owner_staff_id": 999999}, {"account_id": acc["id"], "name": "x", "primary_contact_id": 999999}):
        assert client.post("/api/crm/opportunities", json=body).status_code == 400, body


def test_a_missing_event_counter_is_a_409_not_a_500(client, factory, crm_on, db):
    from tests.crm_helpers import seed_counters
    staff_client(client, factory)
    acc = new_account(client)
    seed_counters(db, ready=False, account=1000)
    r = client.post("/api/crm/opportunities", json={"account_id": acc["id"], "name": "x"})
    assert r.status_code == 409 and "contador" in r.json()["detail"].lower()


def test_moving_to_won_closes_it_and_moving_back_reopens_it(client, factory, crm_on):
    staff_client(client, factory)
    st = _stages(client)
    o = _opp(client, new_account(client)["id"])
    won = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Ganada"]["id"], "updated_at": o["updated_at"]}).json()
    assert won["outcome"] == "won" and won["closed_at"] and won["stage_name"] == "Ganada" and won["event_id"] is not None          # desde C4 ganar crea el cliente y el evento (tests/test_crm_ganada.py)
    back = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Negociación"]["id"]}).json()
    assert back["outcome"] == "open" and back["closed_at"] is None
    lost = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Perdida"]["id"], "lost_reason": "Precio"}).json()
    assert lost["outcome"] == "lost" and lost["lost_reason"] == "Precio"
    assert client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Perdida"]["id"]}).status_code == 409          # ya está ahí
    assert client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": 999999}).status_code == 400


def test_a_stale_version_is_a_409_and_the_other_side_wins(client, factory, crm_on):
    staff_client(client, factory)
    st = _stages(client)
    o = _opp(client, new_account(client)["id"])
    ok = client.put(f"/api/crm/opportunities/{o['id']}", json={"city": "Medellín", "updated_at": o["updated_at"]})
    assert ok.status_code == 200 and ok.json()["city"] == "Medellín"
    stale = client.put(f"/api/crm/opportunities/{o['id']}", json={"city": "Cali", "updated_at": o["updated_at"]})
    assert stale.status_code == 409 and "modific" in stale.json()["detail"]
    assert client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": st["Calificado"]["id"], "updated_at": o["updated_at"]}).status_code == 409
    assert client.put(f"/api/crm/opportunities/{o['id']}", json={"city": "Cali"}).status_code == 400          # falta la versión


def test_free_text_stays_out_of_the_history_but_the_other_fields_are_recorded(client, factory, crm_on, db):
    staff_client(client, factory)
    o = _opp(client, new_account(client)["id"])
    client.put(f"/api/crm/opportunities/{o['id']}", json={"description": "Habló con Pedro Gómez", "next_step": "Llamar a Pedro", "city": "Bogotá", "updated_at": o["updated_at"]})
    rows = {r.field_key: r for r in db.query(CrmChangeLog).filter_by(entity="opportunity", entity_id=o["id"]).all()}
    assert set(rows) == {"description", "next_step", "city"}
    assert rows["description"].old_value is None and rows["description"].new_value is None and rows["next_step"].new_value is None and rows["city"].new_value == "Bogotá"
    shown = client.get(f"/api/crm/opportunities/{o['id']}/history").json()
    assert {r["field"] for r in shown} == {"description", "next_step", "city"} and "Pedro" not in str(shown)


def test_the_board_sums_per_stage_and_currency_with_the_weighted_amount(client, factory, crm_on):
    staff_client(client, factory)
    st = _stages(client)
    acc = new_account(client)
    _opp(client, acc["id"], "A", amount="1000000", stage_id=st["Cotización enviada"]["id"])                          # 65 % de la etapa
    _opp(client, acc["id"], "B", amount="500000", probability=20, stage_id=st["Cotización enviada"]["id"])          # 20 % propio
    _opp(client, acc["id"], "C", amount="1000", currency="USD", stage_id=st["Cotización enviada"]["id"])
    board = client.get("/api/crm/opportunities/board").json()
    col = next(c for c in board["columns"] if c["name"] == "Cotización enviada")
    totals = {t["currency"]: t for t in col["totals"]}
    assert col["count"] == 3 and totals["COP"]["amount"] == "1500000.00" and totals["COP"]["weighted"] == "750000.00" and totals["USD"]["amount"] == "1000.00" and totals["USD"]["weighted"] == "650.00"
    assert [c["name"] for c in board["columns"]] == list(st) and next(c for c in board["columns"] if c["name"] == "Prospecto")["totals"] == []
    cards = {c["name"]: c for c in col["cards"]}
    assert cards["A"]["probability"] == 65 and cards["B"]["probability"] == 20 and cards["A"]["account_name"] == acc["name"] and cards["A"]["no_next_activity"] is True


def test_the_board_gives_50_per_column_and_see_more_continues_the_same_column(client, factory, crm_on, db):
    staff = staff_client(client, factory)
    st = _stages(client)
    acc = new_account(client)
    from app.models import CrmOpportunity as O
    from app.timeutil import utcnow
    from datetime import timedelta
    base = utcnow()
    for i in range(55):
        db.add(O(code=5000 + i, account_id=acc["id"], pipeline_id=client.get("/api/crm/pipeline/meta").json()["pipelines"][0]["id"], stage_id=st["Prospecto"]["id"], name=f"Op {i:02d}", owner_staff_id=staff.id, stage_entered_at=base - timedelta(minutes=i)))
    db.commit()
    first = next(c for c in client.get("/api/crm/opportunities/board").json()["columns"] if c["name"] == "Prospecto")
    assert first["count"] == 55 and len(first["cards"]) == 50 and first["has_more"] is True and first["cards"][0]["name"] == "Op 00"
    more = client.get(f"/api/crm/opportunities/board?stage_id={st['Prospecto']['id']}&offset=50").json()
    assert len(more["columns"]) == 1 and [c["name"] for c in more["columns"][0]["cards"]] == [f"Op {i:02d}" for i in range(50, 55)] and more["columns"][0]["has_more"] is False
    assert client.get("/api/crm/opportunities/board?stage_id=999999").status_code == 404


def test_the_board_filters_and_the_closed_columns_only_show_recent_closings(client, factory, crm_on, db):
    me = staff_client(client, factory, "comercial", "yo")
    st = _stages(client)
    a1, a2 = new_account(client, "Cámara Ficticia"), new_account(client, "Hotel Ejemplo")
    _opp(client, a1["id"], "Congreso médico", amount="100", currency="USD")
    other = _opp(client, a2["id"], "Boda", amount="900", expected_close="2027-03-01")
    client.put(f"/api/crm/opportunities/{other['id']}", json={"owner_staff_id": None, "updated_at": other["updated_at"]})
    def names(**q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return sorted(c["name"] for col in client.get(f"/api/crm/opportunities/board?{qs}").json()["columns"] for c in col["cards"])
    assert names(q="camara") == ["Congreso médico"]          # por la cuenta, sin tildes
    assert names(q="boda") == ["Boda"] and names(q=other["code"]) == ["Boda"]
    assert names(currency="USD") == ["Congreso médico"] and names(close_from="2027-01-01") == ["Boda"] and names(close_to="2026-12-31") == []
    assert names(owner_id=me.id) == ["Congreso médico"] and names(no_activity="true") == ["Boda", "Congreso médico"]
    assert client.get("/api/crm/opportunities/board?currency=EUR").status_code == 400 and client.get("/api/crm/opportunities/board?close_from=ayer").status_code == 400
    old = _opp(client, a1["id"], "Cerrada hace tiempo")
    client.post(f"/api/crm/opportunities/{old['id']}/move", json={"stage_id": st["Ganada"]["id"]})
    from datetime import timedelta
    from app.timeutil import utcnow
    row = db.get(CrmOpportunity, old["id"])
    row.closed_at = utcnow() - timedelta(days=200)
    db.commit()
    assert "Cerrada hace tiempo" not in names()
    assert [o["name"] for o in client.get("/api/crm/opportunities?outcome=won").json()["items"]] == ["Cerrada hace tiempo"]          # la lista trae todo


def test_the_board_and_the_detail_cost_a_fixed_number_of_statements(client, factory, crm_on, db):
    staff_client(client, factory)
    acc = new_account(client)
    for i in range(30):
        _opp(client, acc["id"], f"Op {i}", amount="1000")
    seen = []
    def listener(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        client.get("/api/crm/opportunities/board")
        board_n = len(seen)
        seen.clear()
        client.get(f"/api/crm/opportunities/{_opp(client, acc['id'], 'Detalle')['id']}")
        detail_n = len(seen)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    print(f"sentencias SELECT: tablero={board_n} ficha={detail_n}")          # se anotan en docs/crm/CONSULTAS_POR_PANTALLA.md
    assert board_n <= 6 and detail_n <= 10          # el tablero no crece con las oportunidades (30 aquí): sesión + 2 del tablero + el catálogo


def test_archive_restore_is_admin_only_and_hides_the_opportunity_from_the_board(client, factory, crm_on):
    staff_client(client, factory, "comercial", "com_arch")
    o = _opp(client, new_account(client)["id"])
    assert client.post(f"/api/crm/opportunities/{o['id']}/archive").status_code == 403 and client.get("/api/crm/opportunities/board?archived=true").status_code == 403
    client.post("/logout")
    staff_client(client, factory, "admin", "adm_arch")
    assert client.post(f"/api/crm/opportunities/{o['id']}/archive").json()["archived"] is True
    assert sum(c["count"] for c in client.get("/api/crm/opportunities/board").json()["columns"]) == 0
    assert sum(c["count"] for c in client.get("/api/crm/opportunities/board?archived=true").json()["columns"]) == 1
    assert client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": 1}).status_code == 400          # archivada: no se mueve
    assert client.post(f"/api/crm/opportunities/{o['id']}/restore").json()["archived"] is False


def test_a_coordinator_cannot_use_the_opportunity_api(client, factory, crm_on):
    staff_client(client, factory, "coordinador", "coord_opp")
    assert client.get("/api/crm/opportunities").status_code == 403 and client.get("/api/crm/opportunities/board").status_code == 403
