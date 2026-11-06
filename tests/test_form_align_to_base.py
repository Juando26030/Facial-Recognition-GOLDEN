"""POST /forms/{id}/align-to-base: lleva el campo con cupos de cada inscripción al valor que la base del evento tiene para esa persona."""
import json

from app.models import FormSubmission
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _put, _status


def _form(client, factory, db):
    ev = _event(client, factory)
    factory.staff("admin", "adm1")
    login(client, "adm1")
    ev.set_optional_labels({"opcional_1": "Ciudad"})
    db.commit()
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "ciudad", "type": "text_short", "label": "Ciudad", "key": "opcional_1"}]
    rules = [{"label": "Bogotá", "match": "all", "limit": 10, "conds": [{"field": "ciudad", "op": "equals", "value": "Bogotá"}]},
             {"label": "Cali", "match": "all", "limit": 10, "conds": [{"field": "ciudad", "op": "equals", "value": "Cali"}]}]
    assert _put(client, ev, f, design=_design(fields), settings={"quotas": {"rules": rules}, "prefill": {"mode": "cedula", "source": "event"}}).status_code == 200
    _status(client, ev, f, manual_status="activo")
    return ev, f


def _person(factory, db, ev, pid, city, attend=True):
    u = factory.person(ev, pid, "N" + pid, "A" + pid, attend=attend)
    u.set_extras({"opcional_1": city} if city else {})
    db.commit()


def _add(db, ev, f, pid, city, source="web"):
    db.add(FormSubmission(form_id=f["id"], event_id=ev.id, data_json=json.dumps({"cedula": pid, "ciudad": city}), is_test=False, person_id=pid, source=source, status="confirmed", fed=False))


def _used(client, ev, f):
    d = client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()
    names = {r["id"]: r["label"] for r in d["settings"]["quotas"]["rules"]}
    return {names[q["id"]]: q["used"] for q in d["quota_status"]}


def test_align_moves_each_registration_to_the_base_city_and_skips_what_it_cannot_decide(client, factory, db):
    ev, f = _form(client, factory, db)
    _person(factory, db, ev, "1", "Cali")             # escribió un pueblo → pasa a Cali
    _person(factory, db, ev, "2", "Bogotá")           # escribió Cali → pasa a Bogotá
    _person(factory, db, ev, "3", "Bogotá")           # ya coincide
    _person(factory, db, ev, "4", "Duitama")          # la base tiene una ciudad sin cupo: no se toca
    _person(factory, db, ev, "5", None)               # la base no tiene ciudad: no se toca
    _person(factory, db, ev, "6", "Cali", attend=False)   # tiene usuario pero no está en la base de este evento: no se toca
    _person(factory, db, ev, "7", "Cali")             # marca de «Personas ya registradas»: no se toca
    for pid, city, src in [("1", "Palmira", "web"), ("2", "Cali", "web"), ("3", "Bogotá", "web"), ("4", "Manizales", "web"), ("5", "Bogotá", "web"), ("6", "Bogotá", "web"), ("7", "Bogotá", "lista_cupo"),
                           ("8", "Bogotá", "web")]:     # 8: no existe en la base
        _add(db, ev, f, pid, city, src)
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    before = _used(client, ev, f)
    r = client.post(url, json={"field": "ciudad", "detail": True}).json()
    assert r["applied"] is False and r["changed"] == 2 and r["already_ok"] == 1
    assert r["skipped"] == {"not_in_base": 2, "base_empty": 1, "base_without_quota": 1}
    assert sorted((d["id"], d["from"], d["to"]) for d in r["detail"]) == [("1", "Palmira", "Cali"), ("2", "Cali", "Bogotá")]
    assert _used(client, ev, f) == before                                                      # informar no escribe
    r = client.post(url, json={"field": "ciudad", "apply": True}).json()
    assert r["applied"] is True and r["changed"] == 2
    db.expire_all()
    rows = {s.person_id: json.loads(s.data_json)["ciudad"] for s in db.query(FormSubmission).filter(FormSubmission.form_id == f["id"]).all()}
    assert rows == {"1": "Cali", "2": "Bogotá", "3": "Bogotá", "4": "Manizales", "5": "Bogotá", "6": "Bogotá", "7": "Bogotá", "8": "Bogotá"}
    assert _used(client, ev, f) == {"Bogotá": 6, "Cali": 1}
    assert client.post(url, json={"field": "ciudad", "apply": True}).json()["changed"] == 0     # repetir no cambia nada


def test_align_needs_a_field_with_quotas_linked_to_the_base(client, factory, db):
    ev, f = _form(client, factory, db)
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    assert client.post(url, json={"field": "nombres"}).status_code == 400
    assert client.post(url, json={"field": "nope"}).status_code == 400


def test_align_relabels_people_outside_the_base_and_frees_their_quota(client, factory, db):
    ev, f = _form(client, factory, db)
    _person(factory, db, ev, "1", "Cali")
    _person(factory, db, ev, "6", "Cali", attend=False)
    _add(db, ev, f, "1", "Bogotá")
    _add(db, ev, f, "6", "Bogotá")          # no está en la base de este evento
    _add(db, ev, f, "8", "Manizales")       # tampoco, y su ciudad no tenía cupo
    _add(db, ev, f, "7", "Bogotá", "lista_cupo")   # marca: no se toca
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    label = "Se registró sin estar en base"
    r = client.post(url, json={"field": "ciudad", "not_in_base_label": label}).json()
    assert r["changed"] == 3 and r["moved_to_base"] == 1 and r["marked_not_in_base"] == 2 and r["applied"] is False
    assert {q["quota"]: q["change"] for q in r["quota_change"]} == {"Bogotá": -1, "Cali": 1}
    assert client.post(url, json={"field": "ciudad", "not_in_base_label": label, "apply": True}).json()["changed"] == 3
    db.expire_all()
    rows = {s.person_id: json.loads(s.data_json)["ciudad"] for s in db.query(FormSubmission).filter(FormSubmission.form_id == f["id"]).all()}
    assert rows == {"1": "Cali", "6": label, "8": label, "7": "Bogotá"}
    assert _used(client, ev, f) == {"Bogotá": 1, "Cali": 1}
    assert client.post(url, json={"field": "ciudad", "not_in_base_label": label, "apply": True}).json()["changed"] == 0


def test_align_never_pushes_a_quota_over_its_limit(client, factory, db):
    ev, f = _form(client, factory, db)          # Bogotá y Cali con límite 10
    for i in range(1, 13):
        pid = str(100 + i)
        _person(factory, db, ev, pid, "Cali")
        _add(db, ev, f, pid, "Bogotá")          # 12 personas de Cali inscritas como Bogotá: Cali recibiría 12 > 10
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    r = client.post(url, json={"field": "ciudad"}).json()
    assert r["would_exceed"] == [{"quota": "Cali", "limit": 10, "used": 0, "after": 12}]
    resp = client.post(url, json={"field": "ciudad", "apply": True})
    assert resp.status_code == 409 and "Cali" in resp.json()["detail"]
    db.expire_all()
    assert {json.loads(s.data_json)["ciudad"] for s in db.query(FormSubmission).filter(FormSubmission.form_id == f["id"]).all()} == {"Bogotá"}


def test_align_keeps_listed_people_outside_the_base_in_their_quota(client, factory, db):
    ev, f = _form(client, factory, db)
    _add(db, ev, f, "6", "Bogota")          # fuera de la base, decisión explícita: cuenta en Bogotá
    _add(db, ev, f, "8", "Manizales")       # fuera de la base: queda con la etiqueta
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    body = {"field": "ciudad", "not_in_base_label": "Se registró sin estar en base", "keep_not_in_base": {"6": "Bogotá", "8": "Ciudad que no es cupo"}, "apply": True}
    assert client.post(url, json=body).json()["changed"] == 2
    db.expire_all()
    rows = {s.person_id: json.loads(s.data_json)["ciudad"] for s in db.query(FormSubmission).filter(FormSubmission.form_id == f["id"]).all()}
    assert rows == {"6": "Bogotá", "8": "Se registró sin estar en base"}
    assert _used(client, ev, f) == {"Bogotá": 1, "Cali": 0}


def test_align_can_exceed_a_quota_only_when_explicitly_allowed(client, factory, db):
    ev, f = _form(client, factory, db)          # Bogotá con límite 10
    for i in range(1, 11):
        _add(db, ev, f, str(200 + i), "Bogotá")  # Bogotá llena
    _add(db, ev, f, "6", "Se registró sin estar en base")
    db.commit()
    url = f"/api/events/{ev.id}/forms/{f['id']}/align-to-base"
    body = {"field": "ciudad", "keep_not_in_base": {"6": "Bogotá"}, "apply": True}
    assert client.post(url, json=body).status_code == 409
    r = client.post(url, json={**body, "allow_over": True}).json()
    assert r["changed"] == 1 and r["would_exceed"] == [{"quota": "Bogotá", "limit": 10, "used": 10, "after": 11}]
    assert _used(client, ev, f)["Bogotá"] == 11
