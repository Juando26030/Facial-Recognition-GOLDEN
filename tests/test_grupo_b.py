"""Grupo B (26-oct-2026): borrar campos en Parámetros (B2), cédula nueva en los formularios (B3) y origen de carga (B1). Datos ficticios."""
import json
import pathlib

from app.models import BadgeTemplate, EventFieldConfig, PersonChange, User, WebForm
from app.routers import parametros
from tests.conftest import login


def _ev(factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    ev.set_optional_labels({"opcional_1": "Talla"})
    db.commit()
    for uid, ent, talla in (("1001", "Golden", "M"), ("1002", "", "L"), ("1003", "Otra", "")):
        factory.person(ev, uid, f"N{uid}", "Prueba")
        u = db.get(User, (uid, ev.tenant_id)); u.entity = ent or None; u.set_extras({"opcional_1": talla} if talla else {})
    db.commit()
    return ev


# ---------------------------------------------------------------------------------------------------- B2
def test_usage_and_strong_confirmation_before_deleting_a_field(client, factory, db):
    ev = _ev(factory, db)
    db.add(BadgeTemplate(tenant_id=ev.tenant_id, event_id=ev.id, name="General", elements_json=json.dumps([{"id": "t", "type": "text_variable", "variable": "opcional_1"}, {"id": "n", "type": "text_variable", "variable": "first_name"}])))
    db.add(WebForm(event_id=ev.id, name="Inscripción", slug="insc", test_key="k-test", design_json=json.dumps({"fields": {"f1": {"type": "text", "key": "opcional_1"}, "f2": {"type": "text", "key": "first_name"}}})))
    db.commit()
    login(client, "root")
    u = client.get(f"/api/events/{ev.id}/fields/opcional_1/usage").json()
    assert u["deletable"] and u["people"] == 2 and u["templates"] == ["General"] and u["forms"] == ["Inscripción"] and u["label"] == "Talla"
    assert client.request("DELETE", f"/api/events/{ev.id}/fields/opcional_1", json={"confirm": "talla mal"}).status_code == 400      # hay que escribir el nombre
    r = client.request("DELETE", f"/api/events/{ev.id}/fields/opcional_1", json={"confirm": " talla "})
    assert r.status_code == 200 and r.json()["cleared"] == 2
    db.expire_all()
    assert "opcional_1" not in db.get(type(ev), ev.id).get_optional_labels()
    assert all("opcional_1" not in db.get(User, (i, ev.tenant_id)).get_extras() for i in ("1001", "1002"))
    tpl = db.query(BadgeTemplate).filter_by(event_id=ev.id).one()
    assert [e["variable"] for e in tpl.get_elements()] == ["first_name"]                            # la variable de escarapela desaparece
    design = json.loads(db.query(WebForm).filter_by(event_id=ev.id).one().design_json)
    assert design["fields"]["f1"]["key"] is None and design["fields"]["f2"]["key"] == "first_name"
    audit = db.query(PersonChange).filter_by(event_id=ev.id, kind="field_deleted").one()
    assert audit.staff_user_id and "opcional_1" in audit.old_value and audit.user_id is None   # quién y cuándo
    assert all(c["key"] != "opcional_1" for c in client.get(f"/api/events/{ev.id}/field-configs").json())


def test_a_fixed_field_from_the_original_base_can_be_deleted_and_identity_cannot(client, factory, db):
    ev = _ev(factory, db)
    other = factory.event("en_proceso"); factory.person(other, "1003", "N1003", "Prueba")         # 1003 también está en otro evento: su dato se conserva
    login(client, "root")
    r = client.request("DELETE", f"/api/events/{ev.id}/fields/entity", json={"confirm": "Entidad"})
    assert r.status_code == 200 and r.json()["people_with_data"] == 2 and r.json()["cleared"] == 1 and r.json()["kept_other_events"] == 1
    db.expire_all()
    assert db.get(User, ("1001", ev.tenant_id)).entity is None and db.get(User, ("1003", ev.tenant_id)).entity == "Otra"
    keys = [c["key"] for c in parametros.field_configs_for_event(db, db.get(type(ev), ev.id))]
    assert "entity" not in keys and db.query(EventFieldConfig).filter_by(event_id=ev.id, field_key="entity").one().field_type == "deleted"
    assert client.put(f"/api/events/{ev.id}/field-configs/entity", json={"required": True, "field_type": "text_short"}).status_code == 400
    for key in ("id", "first_name", "last_name"):
        assert client.request("DELETE", f"/api/events/{ev.id}/fields/{key}", json={"confirm": "x"}).status_code == 400
        assert client.get(f"/api/events/{ev.id}/fields/{key}/usage").json()["deletable"] is False


def test_only_coordinator_or_more_can_delete_fields(client, factory, db):
    ev = _ev(factory, db)
    dig = factory.staff("digitador", "dig"); factory.authorize(ev, dig)
    login(client, "dig")
    assert client.request("DELETE", f"/api/events/{ev.id}/fields/opcional_1", json={"confirm": "Talla"}).status_code == 403


def test_parametros_page_has_the_delete_button():
    html = pathlib.Path("templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert "Borrar campo" in html and "cfg-delete" in html and "/usage" in html and "Escribe <b>" in html


# ---------------------------------------------------------------------------------------------------- B3
def test_new_cedula_is_a_checkbox_and_the_scan_goes_in_the_same_id_field():
    reg = pathlib.Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert 'id="regNewCedulaChk"' in reg and 'id="regNewCedulaBox" hidden' in reg and "Adjuntar imagen" in reg and "Usar cámara" in reg
    assert 'id="regScanCedulaInput"' not in reg                                                     # un solo campo de cédula
    assert "const regScanCedulaInput = document.getElementById('manualIdField');" in reg
    js = pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    assert 'id="editNewCedulaChk"' in js and "/cedula-mrz-scan" in js


# ---------------------------------------------------------------------------------------------------- B1
def test_origin_is_set_at_creation_and_never_changes_with_the_state(client, factory, db, tmp_path):
    from app.models import EventAttendee
    from app.routers import api, forms
    ev = _ev(factory, db)                                                                          # factory.person: inscripción sin origen (dato viejo) = «Desconocido»
    login(client, "root")
    r = client.post("/api/register", data={"event_id": ev.id, "id": "2001", "first_name": "Nuevo", "last_name": "Manual"})
    assert r.status_code == 200
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2001").one()
    assert att.origin == "manual"
    for status in ("no_registrado", "registrado", "no_registrado"):                                # el caso del pedido: alta a mano → No registrado → Registrado
        assert client.patch(f"/api/events/{ev.id}/users/2001/status", json={"status": status}).status_code == 200
    db.expire_all()
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="2001").one().origin == "manual"
    cache, created = {}, []
    db.add(User(id="3001", tenant_id=ev.tenant_id, first_name="De", last_name="Excel")); db.flush()
    api._upsert_attendee_cached(db, ev.id, "3001", ev.tenant_id, cache, created); db.commit()
    assert cache["3001"].origin == "base"                                                          # carga masiva = «Base (Excel)»
    db.add(User(id="4001", tenant_id=ev.tenant_id, first_name="Del", last_name="Formulario")); db.flush()
    forms._upsert()(db, ev.id, "4001", ev.tenant_id); db.commit()
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="4001").one().origin == "autoregistro"
    rows = {u["id"]: u for u in client.get(f"/api/users?event_id={ev.id}").json()}
    assert rows["2001"]["origin"] == "manual" and rows["3001"]["origin"] == "base" and rows["4001"]["origin"] == "autoregistro" and rows["1001"]["origin"] == "desconocido"
    assert client.patch(f"/api/events/{ev.id}/users/2001/status", json={"status": "registrado"}).status_code == 200
    rows = {u["id"]: u for u in client.get(f"/api/users?event_id={ev.id}").json()}
    assert rows["2001"]["origin"] == "manual"


def test_report_and_stats_show_origin_and_state(client, factory, db, tmp_path):
    import openpyxl
    from app.reports import ReportManager
    ev = _ev(factory, db)
    login(client, "root")
    client.post("/api/register", data={"event_id": ev.id, "id": "2001", "first_name": "Nuevo", "last_name": "Manual"})
    path = str(tmp_path / "r.xlsx")
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, path)
    ws = openpyxl.load_workbook(path).active
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    header = next(r for r in rows if r and "Origen de carga" in r)
    for col in ("Origen de carga", "Estado", "Fecha de Registro", "Hora de Registro", "Registrado por"):
        assert col in header
    body = [dict(zip(header, r)) for r in rows[rows.index(header) + 1:] if any(r)]
    manual = next(b for b in body if b["Origen de carga"] == "Alta manual")
    assert manual["Estado"] == "Registrado" and manual["Registrado por"] and manual["Hora de Registro"]
    assert any(b["Origen de carga"] == "Desconocido" and b["Estado"] == "No registrado" for b in body)
    stats = client.get(f"/api/events/{ev.id}/stats/data", params={"variable": "origin"}).json()
    labels = {b["label"]: b["count"] for b in stats["buckets"]}
    assert labels.get("Alta manual") == 1 and labels.get("Desconocido") == 3
    st = {b["label"] for b in client.get(f"/api/events/{ev.id}/stats/data", params={"variable": "status"}).json()["buckets"]}
    assert st <= {"Registrado", "No registrado"}
