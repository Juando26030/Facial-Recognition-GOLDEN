"""CRM C2: límites de longitud de oportunidades, leads y actividades (con base de datos; SIN EJECUTAR). 400 en español, nunca 500."""
import pytest

from app.crm import pipeline_rules as rules
from tests.crm_helpers import crm_on, new_account, staff_client  # noqa: F401


def _valid(key, size):
    return "a" * (size - len("@e.co")) + "@e.co" if key == "email" else "x" * size


@pytest.mark.parametrize("key,limit", sorted(k for k in rules.OPPORTUNITY_LIMITS.items() if k[0] != "lost_reason"))
def test_opportunity_fields_over_the_limit_answer_400(client, factory, crm_on, key, limit):
    staff_client(client, factory)
    acc = new_account(client)
    body = {"account_id": acc["id"], "name": "Op límites", key: _valid(key, limit + 1)}
    r = client.post("/api/crm/opportunities", json=body)
    assert r.status_code == 400, r.text
    assert "demasiado largo" in r.json()["detail"]


@pytest.mark.parametrize("key,limit", sorted(k for k in rules.OPPORTUNITY_LIMITS.items() if k[0] != "lost_reason"))
def test_opportunity_fields_exactly_at_the_limit_are_saved(client, factory, crm_on, key, limit):
    staff_client(client, factory)
    acc = new_account(client)
    r = client.post("/api/crm/opportunities", json={"account_id": acc["id"], "name": "Op al límite", key: _valid(key, limit)})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("key,limit", sorted(rules.LEAD_LIMITS.items()))
def test_lead_fields_over_the_limit_answer_400(client, factory, crm_on, key, limit):
    staff_client(client, factory)
    body = {"first_name": "Ana", key: _valid(key, limit + 1)}
    r = client.post("/api/crm/leads", json=body)
    assert r.status_code == 400, r.text
    assert "demasiado largo" in r.json()["detail"]


@pytest.mark.parametrize("key,limit", sorted(rules.ACTIVITY_LIMITS.items()))
def test_activity_fields_over_the_limit_answer_400(client, factory, crm_on, key, limit):
    staff_client(client, factory)
    acc = new_account(client)
    body = {"kind": "task", "account_id": acc["id"], "subject": "Tarea", key: _valid(key, limit + 1)}
    r = client.post("/api/crm/activities", json=body)
    assert r.status_code == 400, r.text
    assert "demasiado largo" in r.json()["detail"]


def test_lost_reason_over_the_limit_answers_400_when_moving_to_a_lost_stage(client, factory, crm_on):
    staff_client(client, factory)
    meta = client.get("/api/crm/pipeline/meta").json()["pipelines"][0]
    lost = next(s for s in meta["stages"] if s["kind"] == "lost")
    o = client.post("/api/crm/opportunities", json={"account_id": new_account(client)["id"], "name": "Perdida larga"}).json()
    r = client.post(f"/api/crm/opportunities/{o['id']}/move", json={"stage_id": lost["id"], "lost_reason": "x" * (rules.OPPORTUNITY_LIMITS["lost_reason"] + 1)})
    assert r.status_code == 400 and "demasiado largo" in r.json()["detail"]
