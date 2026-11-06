"""POST /forms/{id}/unify-values: unifica el valor de un campo con cupos en las inscripciones ya guardadas (informa sin escribir, o corrige y recalcula los cupos)."""
import json

from app.models import FormSubmission
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _put, _status


def _form(client, factory):
    ev = _event(client, factory)
    factory.staff("admin", "adm1")
    login(client, "adm1")
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "ciudad", "type": "text_short", "label": "Ciudad"}]
    rules = [{"label": "Bogotá", "match": "all", "limit": 10, "conds": [{"field": "ciudad", "op": "equals", "value": "Bogotá"}]},
             {"label": "Cúcuta", "match": "all", "limit": 10, "conds": [{"field": "ciudad", "op": "equals", "value": "Cúcuta"}]}]
    assert _put(client, ev, f, design=_design(fields), settings={"quotas": {"rules": rules}}).status_code == 200
    _status(client, ev, f, manual_status="activo")
    return ev, f


def _add(db, ev, f, pid, city, **kw):
    db.add(FormSubmission(form_id=f["id"], event_id=ev.id, data_json=json.dumps({"cedula": pid, "ciudad": city}), is_test=kw.get("is_test", False), person_id=pid, source="web", status="confirmed", fed=False))


def _used(client, ev, f):
    d = client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()
    names = {r["id"]: r["label"] for r in d["settings"]["quotas"]["rules"]}
    return {names[q["id"]]: q["used"] for q in d["quota_status"]}


def test_unify_reports_without_writing_then_applies_and_fixes_the_quota_counts(client, factory, db):
    ev, f = _form(client, factory)
    for i, city in enumerate(["Bogotá", "Bogota", "BOGOTÁ", "Bogotá, D.C.", "bogotá d.c.", "San José de Cúcuta", "Cucuta", "Manizales"]):
        _add(db, ev, f, f"10{i}", city)
    _add(db, ev, f, "999", "Bogota", is_test=True)                      # las pruebas no se tocan
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/unify-values"
    body = {"field": "ciudad", "aliases": {"Bogotá, D.C.": "Bogotá", "Bogotá D.C.": "Bogotá", "San José de Cúcuta": "Cúcuta"}}
    before = _used(client, ev, f)
    r = client.post(url, json=body).json()
    assert r["applied"] is False and r["changed"] == 6 and r["already_ok"] == 1                 # solo informa
    assert [u["value"] for u in r["unresolved"]] == ["Manizales"]
    assert _used(client, ev, f) == before                                                       # nada cambió
    r = client.post(url, json={**body, "apply": True}).json()
    assert r["applied"] is True and r["changed"] == 6
    db.expire_all()
    rows = {s.person_id: json.loads(s.data_json)["ciudad"] for s in db.query(FormSubmission).filter(FormSubmission.form_id == f["id"]).all()}
    assert [rows[f"10{i}"] for i in range(7)] == ["Bogotá"] * 5 + ["Cúcuta"] * 2 and rows["107"] == "Manizales" and rows["999"] == "Bogota"
    assert _used(client, ev, f) == {"Bogotá": 5, "Cúcuta": 2}
    again = client.post(url, json={**body, "apply": True}).json()
    assert again["changed"] == 0 and again["applied"] is False                                  # repetir no cambia nada


def test_unify_rejects_a_field_without_quota_and_an_alias_to_an_unknown_city(client, factory):
    ev, f = _form(client, factory)
    url = f"/api/events/{ev.id}/forms/{f['id']}/unify-values"
    assert client.post(url, json={"field": "nombres"}).status_code == 400
    assert client.post(url, json={"field": "ciudad", "aliases": {"Duitama": "Tunja"}}).status_code == 400
