"""Lista de «Personas ya registradas» con datos del formulario: restar de los cupos por variables (p. ej. por ciudad) sin duplicar a nadie."""
import io

from openpyxl import load_workbook

from app import formsvc
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _open, _put, _status

# ------------------------------- con base de datos
def _quota_form(client, factory, limit_bog=2, limit_baq=1):
    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "ciudad", "type": "text_short", "label": "Ciudad", "required": True}]
    rules = [{"label": "Bogotá", "match": "all", "limit": limit_bog, "conds": [{"field": "ciudad", "op": "equals", "value": "Bogotá"}]},
             {"label": "Barranquilla", "match": "all", "limit": limit_baq, "conds": [{"field": "ciudad", "op": "equals", "value": "Barranquilla"}]}]
    assert _put(client, ev, f, design=_design(fields), settings={"quotas": {"rules": rules}}).status_code == 200
    _status(client, ev, f, manual_status="activo")
    return ev, f


def _up(client, ev, f, lines, path="registered", **data):
    csv = ("\n".join(lines) + "\n").encode()
    return client.post(f"/api/events/{ev.id}/forms/{f['id']}/{path}", data=data, files={"file": ("lista.csv", csv, "text/csv")})


def _used(client, ev, f):
    return {q["id"]: q["used"] for q in client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["quota_status"]}


def test_preview_detects_the_quota_column_and_what_each_quota_would_lose(client, factory):
    ev, f = _quota_form(client, factory)
    r = _up(client, ev, f, ["Cédula;Nombres;Ciudad del evento;Sociedad", "1001;Ana;Bogotá;X", "1002;Luis;Barranquilla;X", "1003;Eva;Bogotá;X"], path="registered/preview")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rows"] == 3 and d["new"] == 3 and d["quota_fields"] == ["Ciudad"] and d["quota_missing"] == []
    by = {i["label"]: i for i in d["impact"]}
    assert by["Bogotá"]["adding"] == 2 and by["Bogotá"]["left_after"] == 0 and by["Barranquilla"]["adding"] == 1
    assert _up(client, ev, f, ["Cédula", "1001"], path="registered/preview").json()["quota_fields"] == []          # sin la columna de ciudad no hay nada que preguntar


def test_list_with_data_takes_quota_and_blocks_and_never_duplicates(client, factory, db):
    ev, f = _quota_form(client, factory)
    _open(client, ev, f)
    # 1001 ya estaba inscrita de verdad y 1002 ya tenía una marca que solo bloqueaba
    from app.models import FormSubmission
    db.add(FormSubmission(form_id=f["id"], event_id=ev.id, data_json='{"cedula": "1001", "ciudad": "Bogotá"}', is_test=False, person_id="1001", source="web", status="confirmed", fed=False))
    db.commit()
    assert _up(client, ev, f, ["Cédula", "1002"], effect="block").json()["added"] == 1
    assert _used(client, ev, f) == {r["id"]: (1 if r["label"] == "Bogotá" else 0) for r in client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["settings"]["quotas"]["rules"]}
    r = _up(client, ev, f, ["Cédula,Nombres,Ciudad", "1001,Ana,Bogotá", "1002,Luis,Bogotá", "1003,Eva,Barranquilla", "1003,Eva,Barranquilla"], effect="block", with_data="1")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["added"] == 1 and j["converted"] == 1 and j["existing"] == 2           # 1001 (real) y 1003 repetida en el archivo no se duplican
    rows = db.query(FormSubmission).filter(FormSubmission.form_id == f["id"], FormSubmission.is_test == False).all()    # noqa: E712
    assert sorted(x.person_id for x in rows) == ["1001", "1002", "1003"]              # UNA fila por persona
    assert next(x for x in rows if x.person_id == "1001").source == "web"            # la inscripción real no se toca
    used = _used(client, ev, f)
    names = {r["label"]: r["id"] for r in client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["settings"]["quotas"]["rules"]}
    assert used[names["Bogotá"]] == 2 and used[names["Barranquilla"]] == 1           # 1001 (real) + 1002 (marca convertida con su ciudad); 1003 en Barranquilla
    assert formsvc.held_count(db, db.get(__import__("app.models", fromlist=["WebForm"]).WebForm, f["id"])) == 3
    login(client, "coord1")
    assert client.delete(f"/api/events/{ev.id}/forms/{f['id']}/registered").json()["removed"] == 2           # quitar marcas libera lo de la lista, no la real
    assert _used(client, ev, f)[names["Bogotá"]] == 1


def test_list_over_a_full_quota_warns_and_the_template_has_the_form_columns(client, factory):
    ev, f = _quota_form(client, factory, limit_bog=1)
    r = _up(client, ev, f, ["Cédula,Ciudad", "1001,Bogotá", "1002,Bogotá"], with_data="1").json()
    assert r["over"] and "Bogotá" in r["over"][0] and "ATENCIÓN" in r["message"]
    t = client.get(f"/api/events/{ev.id}/forms/{f['id']}/registered/template")
    assert t.status_code == 200
    wb = load_workbook(io.BytesIO(t.content))
    assert [c.value for c in wb["Lista"][1]] == ["Cédula", "Nombres", "Apellidos", "Ciudad"]
