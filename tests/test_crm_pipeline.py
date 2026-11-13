"""CRM C2: embudos y etapas (con base de datos; SIN EJECUTAR hasta que Juan David las corra). Solo admin edita; el CRM apagado responde 404."""
from tests.crm_helpers import crm_on, staff_client  # noqa: F401


def _admin(client, factory):
    return staff_client(client, factory, "admin", "adm_pipe")


def _default(client):
    pipes = client.get("/api/crm/pipelines").json()["pipelines"]
    return next(p for p in pipes if p["is_default"])


def test_the_seeded_pipeline_has_seven_stages_with_won_and_lost_last(client, factory, crm_on):
    _admin(client, factory)
    p = _default(client)
    assert p["name"] == "Eventos" and [s["kind"] for s in p["stages"]] == ["open"] * 5 + ["won", "lost"]
    assert [s["position"] for s in p["stages"]] == list(range(7))


def test_a_commercial_can_read_the_meta_but_not_edit_pipelines(client, factory, crm_on):
    staff_client(client, factory, "comercial")
    meta = client.get("/api/crm/pipeline/meta")
    assert meta.status_code == 200 and meta.json()["pipelines"][0]["name"] == "Eventos" and meta.json()["currencies"] == ["COP", "USD"]
    assert client.get("/api/crm/pipelines").status_code == 403
    assert client.post("/api/crm/pipelines", json={"name": "Otro"}).status_code == 403


def test_everything_is_404_while_the_crm_is_off(client, factory):
    staff_client(client, factory, "admin", "adm_off")
    for url in ("/api/crm/pipelines", "/api/crm/pipeline/meta", "/api/crm/opportunities", "/api/crm/opportunities/board", "/api/crm/leads", "/api/crm/activities?lead_id=1"):
        assert client.get(url).status_code == 404, url


def test_a_new_pipeline_comes_with_open_won_and_lost_and_a_unique_name(client, factory, crm_on):
    _admin(client, factory)
    r = client.post("/api/crm/pipelines", json={"name": "Alianzas"})
    assert r.status_code == 200
    made = next(p for p in client.get("/api/crm/pipelines").json()["pipelines"] if p["name"] == "Alianzas")
    assert [s["kind"] for s in made["stages"]] == ["open", "won", "lost"]
    assert client.post("/api/crm/pipelines", json={"name": "alianzas"}).status_code == 409
    assert client.post("/api/crm/pipelines", json={"name": "  "}).status_code == 400


def test_stages_can_be_added_renamed_and_reordered_with_closed_ones_staying_last(client, factory, crm_on):
    _admin(client, factory)
    p = _default(client)
    new = client.post(f"/api/crm/pipelines/{p['id']}/stages", json={"name": "Visita técnica", "probability": 40}).json()
    p = _default(client)
    assert [s["kind"] for s in p["stages"]][-2:] == ["won", "lost"] and p["stages"][5]["name"] == "Visita técnica"
    ids = [s["id"] for s in p["stages"] if s["kind"] == "open"]
    ids.reverse()
    assert client.post(f"/api/crm/pipelines/{p['id']}/stages/reorder", json={"stage_ids": ids}).status_code == 200
    p = _default(client)
    assert [s["id"] for s in p["stages"] if s["kind"] == "open"] == ids and [s["kind"] for s in p["stages"]][-2:] == ["won", "lost"]
    r = client.put(f"/api/crm/stages/{new['id']}", json={"name": "Prospecto", "probability": 40})
    assert r.status_code == 409          # el nombre ya existe en el embudo
    assert client.put(f"/api/crm/stages/{new['id']}", json={"name": "Visita", "probability": 150}).status_code == 400
    assert client.post(f"/api/crm/pipelines/{p['id']}/stages/reorder", json={"stage_ids": ids[:-1]}).status_code == 400          # faltan etapas


def test_the_pipeline_keeps_a_won_and_a_lost_stage_and_a_stage_with_open_deals_cannot_be_archived(client, factory, crm_on, db):
    from tests.crm_helpers import new_account
    _admin(client, factory)
    p = _default(client)
    won = next(s for s in p["stages"] if s["kind"] == "won")
    assert client.post(f"/api/crm/stages/{won['id']}/archive").status_code == 400          # quedaría sin etapa ganada
    first = p["stages"][0]
    acc = new_account(client)
    client.post("/api/crm/opportunities", json={"account_id": acc["id"], "name": "Evento", "stage_id": first["id"]})
    r = client.post(f"/api/crm/stages/{first['id']}/archive")
    assert r.status_code == 409 and "oportunidades abiertas" in r.json()["detail"]
    spare = next(s for s in p["stages"] if s["name"] == "Negociación")
    assert client.post(f"/api/crm/stages/{spare['id']}/archive").status_code == 200
    assert client.post(f"/api/crm/stages/{spare['id']}/restore").status_code == 200


def test_the_default_pipeline_is_switchable_and_cannot_be_archived(client, factory, crm_on):
    _admin(client, factory)
    old = _default(client)
    assert client.post(f"/api/crm/pipelines/{old['id']}/archive").status_code == 400
    other = client.post("/api/crm/pipelines", json={"name": "Alianzas"}).json()
    assert client.post(f"/api/crm/pipelines/{other['id']}/default").status_code == 200
    assert _default(client)["id"] == other["id"]
    assert client.post(f"/api/crm/pipelines/{old['id']}/archive").status_code == 200
    assert all(p["id"] != old["id"] for p in client.get("/api/crm/pipeline/meta").json()["pipelines"])          # el archivado no sale en los formularios
