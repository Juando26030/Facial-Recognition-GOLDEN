"""0161 (21-nov-2026): inventario «lo define la base», base de dependientes, vista previa de las cargas y bloqueo de la configuración del digitador (docs/25_INVENTARIO_POR_BASE.md)."""
import json

import pytest

from tests.conftest import login

DEPS = "cedula_titular,nombre_dependiente,producto,cantidad,edad\n1001,Sofía,Kit escolar,,7\n1001,Tomás,Balón,2,10\n1002,,Kit escolar,,5\n9999,Nadie,Balón,,3\n"


@pytest.fixture()
def ev(factory, db, client):
    coord = factory.staff("coordinador", "coordinv")
    e = factory.event("en_proceso", coordinator=coord, inventory_enabled=True)
    factory.authorize(e, coord)
    factory.person(e, "1001", "Ana", "Uno", registered=True)
    factory.person(e, "1002", "Beto", "Dos", registered=False)
    login(client, "coordinv")
    return e


def _upload(client, ev, text=DEPS, mode="replace", what="preview"):
    return client.post(f"/api/events/{ev.id}/dependents/{what}", data={"mode": mode}, files={"roster_file": ("d.csv", text.encode(), "text/csv")})


def _assign(client, ev, **cfg):
    body = {"mode": "assigned", **cfg}
    return client.put(f"/api/events/{ev.id}/inventory-assign", json=body)


def test_dependents_preview_writes_nothing_and_explains_what_happens(client, ev, db):
    from app.models import EventDependent
    r = _upload(client, ev)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["columns"]["holder"] == "cedula_titular" and p["columns"]["name"] == "nombre_dependiente"
    assert p["loaded_rows"] == 3 and p["skipped_count"] == 1 and "no está en la base" in p["skipped"][0]["reason"]
    assert p["holders"] == 2 and p["holders_not_registered"] == 1 and p["dependents_after"] == 3 and p["dependents_before"] == 0
    assert len(p["samples"]) == 2 and {s["holder"] for s in p["samples"]} == {"1001", "1002"}
    assert "_plan" not in p
    assert db.query(EventDependent).filter_by(event_id=ev.id).count() == 0


def test_dependents_need_the_holder_column(client, ev):
    r = _upload(client, ev, "nombre,producto\nAna,Kit\n")
    assert r.status_code == 400 and "TITULAR" in r.json()["detail"]


def test_load_then_reload_replace_keeps_delivered_rows_and_append_adds(client, ev, db):
    from app.models import EventDependent
    assert _upload(client, ev, what="load").status_code == 200
    assert db.query(EventDependent).filter_by(event_id=ev.id).count() == 3
    s = client.get(f"/api/events/{ev.id}/dependents/summary").json()
    assert s == {"rows": 3, "dependents": 3, "holders": 2}
    people = client.get(f"/api/events/{ev.id}/dependents", params={"holder": "1001"}).json()
    assert people["count"] == 2 and [p["label"] for p in people["people"]] == ["Sofía", "Tomás"]
    # se entrega lo de Tomás y luego se recarga un archivo SIN Tomás: su fila se conserva (ya se entregó), la de Beto se borra
    assert _assign(client, ev, dep_product="producto", dep_qty="cantidad").status_code == 200
    lines = client.get(f"/api/events/{ev.id}/inventory/assigned", params={"cedula": "1001"}).json()["lines"]
    tomas = next(ln for ln in lines if ln["who"] == "Tomás")
    assert client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "keys": [tomas["key"]]}).status_code == 200
    r = _upload(client, ev, "cedula_titular,nombre_dependiente,producto\n1001,Sofía,Kit escolar\n", what="load")
    assert r.status_code == 200 and r.json()["kept_delivered"] == 1
    assert db.query(EventDependent).filter_by(event_id=ev.id).count() == 2
    r = _upload(client, ev, "cedula_titular,nombre_dependiente,producto\n1002,Luz,Kit escolar\n", mode="append", what="load")
    assert r.json()["inserted"] == 1 and db.query(EventDependent).filter_by(event_id=ev.id).count() == 3


def test_assigned_mode_creates_products_with_stock_from_the_base_and_blocks_choosing(client, ev, db):
    from app.models import InventoryItem
    _upload(client, ev, what="load")
    r = _assign(client, ev, dep_product="producto", dep_qty="cantidad")
    assert r.status_code == 200, r.text
    items = {i.name: i for i in db.query(InventoryItem).filter_by(event_id=ev.id)}
    assert items["Kit escolar"].initial_qty == 2 and items["Balón"].initial_qty == 2          # 1001 Sofía + 1002 = 2 kits; Tomás = 2 balones (9999 no entra)
    summary = r.json()["summary"]
    assert summary["assigned_units"] == 4 and summary["short_products"] == 0
    r = client.post(f"/api/events/{ev.id}/inventory/deliver", json={"cedula": "1001", "items": [{"item_id": items["Balón"].id, "qty": 1}]})
    assert r.status_code == 400 and "lo define la base" in r.json()["detail"]


def test_deliver_one_then_all_never_twice_and_only_registered(client, ev, db):
    _upload(client, ev, what="load")
    _assign(client, ev, dep_product="producto", dep_qty="cantidad")
    data = client.get(f"/api/events/{ev.id}/inventory/assigned", params={"cedula": "1001"}).json()
    assert data["registered"] is True and len(data["lines"]) == 2 and data["pending"] == 2
    first = data["lines"][0]["key"]
    assert client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "keys": [first]}).status_code == 200
    again = client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "keys": [first]})
    assert again.status_code == 409 and "ya se entregó" in again.json()["detail"]
    out = client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "all": True})
    assert out.status_code == 200 and all(ln["done"] for ln in out.json()["lines"])
    assert out.json()["delivered"][0]["qty"] == 2                                                        # Tomás: 2 balones de una vez
    assert client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "all": True}).status_code == 409
    nope = client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1002", "all": True})
    assert nope.status_code == 409 and "registrada" in nope.json()["detail"]


def test_holder_field_defines_the_holders_own_product_and_stock_can_be_lower_than_assigned(client, ev, db):
    from app.models import InventoryItem, User
    ev.optional_field_labels = json.dumps({"opcional_1": "Producto"})
    db.commit()
    for uid, kit in (("1001", "Kit A"), ("1002", "kit a")):
        u = db.query(User).filter_by(id=uid, tenant_id=ev.tenant_id).first()
        u.set_extras({"opcional_1": kit})
    db.commit()
    r = _assign(client, ev, holder_product="opcional_1")
    assert r.status_code == 200, r.text
    item = db.query(InventoryItem).filter_by(event_id=ev.id).one()
    assert item.initial_qty == 2 and item.source_value == "kit a"                                       # «Kit A» y «kit a» son el mismo producto
    assert client.patch(f"/api/events/{ev.id}/inventory/{item.id}", json={"initial_qty": 0}).status_code == 200
    s = client.get(f"/api/events/{ev.id}/inventory-assign").json()["summary"]
    assert s["products"][0]["short"] == 2                                                             # alerta, sin bloquear la configuración
    r = client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "all": True})
    assert r.status_code == 400 and "No alcanza" in r.json()["detail"]
    assert client.post(f"/api/events/{ev.id}/inventory-assign/match-stock", json={}).json()["changed"] == 1
    assert client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "all": True}).status_code == 200


def test_config_validation(client, ev):
    assert _assign(client, ev).status_code == 400                                                       # sin ningún campo de producto
    assert _assign(client, ev, holder_product="no_existe").status_code == 400
    assert _assign(client, ev, dep_qty="cantidad").status_code == 400
    assert client.put(f"/api/events/{ev.id}/inventory-assign", json={"mode": "otro"}).status_code == 400


def test_dependent_search_finds_the_holder(client, ev):
    _upload(client, ev, what="load")
    res = client.get(f"/api/events/{ev.id}/dependents/search", params={"q": "sofi"}).json()["results"]
    assert res and res[0]["holder_id"] == "1001" and res[0]["dependent"] == "Sofía"
    assert client.get(f"/api/events/{ev.id}/dependents/search", params={"q": "so"}).json()["results"] == []


def test_dependents_field_appears_in_parameters_and_stats_counts_registered_plus_dependents(client, ev):
    _upload(client, ev, what="load")
    keys = [c["key"] for c in client.get(f"/api/events/{ev.id}/field-configs").json()]
    assert "dependents" in keys
    r = client.put(f"/api/events/{ev.id}/field-configs/dependents", json={"label": "Hijos", "required": True, "default_stat_enabled": True, "default_chart_type": "bar"})
    assert r.status_code == 200 and r.json()["required"] is False and r.json()["default_stat_enabled"] is True and r.json()["label"] == "Hijos"
    variables = {v["key"]: v for v in client.get(f"/api/events/{ev.id}/stats/variables").json()}
    assert variables["dependents"]["default_stat_enabled"] is True
    data = client.get(f"/api/events/{ev.id}/stats/data", params={"variable": "dependents"}).json()
    assert data["totals"]["registered"] == 1 and data["totals"]["dependents_of_registered"] == 2 and data["totals"]["with_dependents"] == 3
    assert "contando a los dependientes" in data["summary"]


def test_normal_roster_preview_shows_sample_people_and_impact_without_writing(client, ev, db):
    from app.models import EventAttendee
    sheet = "id,nombres,apellidos,Talla\n1001,Ana,Nueva,M\n2001,Carla,Tres,S\n2001,Carla,Repetida,L\n"
    r = client.post("/api/bulk_roster/preview", data={"event_id": str(ev.id), "mode": "normal"}, files={"roster_file": ("b.csv", sheet.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["impact"]["new"] == 1 and p["impact"]["updated"] == 1 and p["impact"]["event_after"] == p["impact"]["event_before"] + 1
    assert len(p["samples"]) == 3
    upd = next(s for s in p["samples"] if s["kind"] == "update")
    last = next(f for f in upd["fields"] if f["label"] == "Apellidos")
    assert last["value"] == "Nueva" and last["old"] == "Uno"
    assert any(s["status"].startswith("Cédula repetida") for s in p["samples"])
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 2                                # nada se escribió
    db.refresh(ev)
    assert "Talla" not in (ev.optional_field_labels or "")


def test_append_preview_keeps_old_keys_and_adds_samples(client, ev):
    sheet = "id,nombres\n1001,Ana\n3001,Nuevo\n"
    p = client.post("/api/bulk_roster/preview", data={"event_id": str(ev.id)}, files={"roster_file": ("n.csv", sheet.encode(), "text/csv")}).json()
    assert p["new"] == 1 and p["existing"] == 1 and p["impact"]["untouched"] == 1 and len(p["samples"]) == 2


def test_config_lock_password_and_unlock(client, factory, ev, db):
    r = client.put(f"/api/events/{ev.id}/config-lock", json={"areas_locked": True, "inventory_locked": True, "password": "12"})
    assert r.status_code == 400
    r = client.put(f"/api/events/{ev.id}/config-lock", json={"areas_locked": True, "inventory_locked": True, "password": "clave1"})
    assert r.status_code == 200 and r.json() == {"registro_open": False, "areas_locked": True, "inventory_locked": True, "has_password": True}
    db.refresh(ev)
    assert ev.config_unlock_hash and "clave1" not in ev.config_unlock_hash
    dig = factory.staff("digitador", "diginv")
    factory.authorize(ev, dig)
    client.post("/logout")
    login(client, "diginv")
    page = client.get(f"/kiosk/{ev.id}/areas").text
    lock = json.loads(page.split('id="gwConfigLock">')[1].split("</script>")[0])
    assert lock["areas"] is True and lock["inventory"] is True and lock["registro"] is True and lock["has_password"] is True
    assert client.post(f"/api/events/{ev.id}/config-lock/unlock", json={"scope": "areas", "password": "mala"}).status_code == 403
    assert client.post(f"/api/events/{ev.id}/config-lock/unlock", json={"scope": "areas", "password": "clave1"}).json() == {"ok": True}
    assert client.put(f"/api/events/{ev.id}/config-lock", json={"areas_locked": False}).status_code in (401, 403)          # el digitador no cambia el candado


def test_coordinator_is_never_locked(client, ev, db):
    ev.areas_config_locked = True
    db.commit()
    page = client.get(f"/kiosk/{ev.id}/areas").text
    lock = json.loads(page.split('id="gwConfigLock">')[1].split("</script>")[0])
    assert lock["areas"] is False


def test_node_precheck_answer_counts_what_the_cloud_already_has(client, ev, db):
    from app import node_precheck
    _upload(client, ev, what="load")
    _assign(client, ev, dep_product="producto", dep_qty="cantidad")
    lines = client.get(f"/api/events/{ev.id}/inventory/assigned", params={"cedula": "1001"}).json()["lines"]
    client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "keys": [lines[0]["key"]]})
    ans = node_precheck.cloud_answer(db, ev, {"cedula": "1001", "keys": [ln["key"] for ln in lines], "items": ["kit escolar"]})
    assert ans["keys"][lines[0]["key"]] == 1 and lines[1]["key"] not in ans["keys"] and ans["items"]["kit escolar"] == 1
    assert node_precheck.ask(ev, "1001", keys=["h"])["skipped"] is True                                 # en la nube no se pregunta a nadie


def test_removing_a_person_removes_her_dependents(client, ev, db):
    from app.models import EventDependent
    _upload(client, ev, what="load")
    from app import dependents
    dependents.delete_for_holders(db, ev.id, ["1001"])
    db.commit()
    assert db.query(EventDependent).filter_by(event_id=ev.id).count() == 1


def test_screens_carry_the_new_pieces():
    inv = open("templates/kiosk_inventario.html", encoding="utf-8").read()
    assert "js/inventario-asignado.js" in inv and 'id="depSearchInput"' in inv and '_config_lock.html' in inv
    par = open("templates/kiosk_parametros.html", encoding="utf-8").read()
    assert 'name="invMode" value="assigned"' in par and 'id="cfgLockBox"' in par and 'id="invWizard"' in par and "js/inventory-assign-admin.js" in par
    ros = open("templates/kiosk_roster.html", encoding="utf-8").read()
    assert 'id="depForm"' in ros and "js/roster-preview.js" in ros and "RosterPreview.confirmLoad(pdata" in ros and "plantilla_carga_dependientes.xlsx" in ros


# ------------------------------------------------------------------------------------------------ 21-nov-2026: tipo «Número», «Mostrar en el registro» y «Texto al escribir» para todos
def test_number_field_type_only_accepts_numbers(client, ev, db):
    ev.optional_field_labels = json.dumps({"opcional_1": "Edad"})
    db.commit()
    r = client.put(f"/api/events/{ev.id}/field-configs/opcional_1", json={"label": "Edad", "field_type": "number", "required": False})
    assert r.status_code == 200 and r.json()["field_type"] == "number"
    bad = client.patch(f"/api/users/1001?event_id={ev.id}", json={"extra_fields": {"opcional_1": "doce"}})
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Número no válido")
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"extra_fields": {"opcional_1": "12,5"}}).status_code == 200
    assert "value: 'number'" in open("templates/kiosk_parametros.html", encoding="utf-8").read()
    assert "data-gw-number" in open("static/js/field-render.js", encoding="utf-8").read()


def test_show_in_card_defaults_to_id_and_names_and_can_be_chosen(client, ev):
    cfgs = {c["key"]: c for c in client.get(f"/api/events/{ev.id}/field-configs").json()}
    assert cfgs["id"]["show_in_card"] and cfgs["first_name"]["show_in_card"] and cfgs["last_name"]["show_in_card"]
    assert cfgs["entity"]["show_in_card"] is False                                                     # la entidad ya no sale de fábrica
    assert client.put(f"/api/events/{ev.id}/field-configs/entity", json={"label": "", "field_type": "text_short", "show_in_card": True}).json()["show_in_card"] is True
    assert client.put(f"/api/events/{ev.id}/field-configs/last_name", json={"label": "", "show_in_card": False}).json()["show_in_card"] is True          # cédula, nombres y apellidos: siempre
    page = client.get(f"/kiosk/{ev.id}/registro").text
    card = json.loads(page.split("window.REG_CARD_FIELDS = ")[1].split(";")[0])
    assert {c["key"] for c in card} == {"id", "first_name", "last_name", "entity"}
    assert client.put(f"/api/events/{ev.id}/field-configs/entity", json={"show_in_card": "si"}).status_code == 400


def test_users_carry_their_dependents_count(client, ev):
    _upload(client, ev, what="load")
    rows = {u["id"]: u for u in client.get(f"/api/users?event_id={ev.id}").json()}
    assert rows["1001"]["dependents"] == 2 and rows["1002"]["dependents"] == 1


def test_registration_card_and_text_case_for_all_are_in_the_screens():
    d = open("static/js/directory.js", encoding="utf-8").read()
    assert "window.REG_CARD_FIELDS" in d and "dataset.cardHidden" in d and "data-field" in d
    css = open("static/css/p-registro-puerta.css", encoding="utf-8").read()
    assert "td[data-card-hidden]" in css and "td[data-field=cardx]" in css
    pf = open("static/js/person-form-designer.js", encoding="utf-8").read()
    assert "Aplicar a todos los campos de texto" in pf


def test_directory_etag_changes_when_the_dependents_base_changes(client, ev):
    """Staging 21-nov-2026: cargar dependientes no cambiaba la huella del directorio y el navegador seguía mostrando «Dependientes» viejo (304)."""
    before = client.get(f"/api/users?event_id={ev.id}")
    _upload(client, ev, what="load")
    after = client.get(f"/api/users?event_id={ev.id}", headers={"If-None-Match": before.headers["etag"]})
    assert after.status_code == 200 and after.headers["etag"] != before.headers["etag"]
    assert {u["id"]: u["dependents"] for u in after.json()}["1001"] == 2


def test_reload_never_duplicates_a_delivered_row_when_other_columns_change_or_rows_move(client, ev, db):
    """Staging 21-nov-2026: la fila se comparaba con TODAS sus columnas y con su número de fila: corregir la edad, subir menos columnas o reordenar duplicaba lo ya entregado."""
    from app.models import EventDependent
    assert _assign(client, ev, dep_product="producto", dep_qty="cantidad").status_code == 200
    base = "cedula_titular,nombre_dependiente,producto,edad\n1001,Sofía,Kit escolar,7\n1001,,Balón,3\n"
    assert _upload(client, ev, base, what="load").status_code == 200
    lines = client.get(f"/api/events/{ev.id}/inventory/assigned", params={"cedula": "1001"}).json()["lines"]
    assert client.post(f"/api/events/{ev.id}/inventory/deliver-assigned", json={"cedula": "1001", "all": True}).status_code == 200
    count = lambda: db.query(EventDependent).filter_by(event_id=ev.id).count()          # noqa: E731
    assert count() == 2
    # (1) se corrige la edad y (3) se reordena: el dependiente anónimo pasa de la fila 3 a la 2
    fixed = "cedula_titular,nombre_dependiente,producto,edad\n1001,,Balón,3\n1001,Sofía,Kit escolar,8\n"
    pv = _upload(client, ev, fixed, what="preview").json()
    assert pv["insert_rows"] == 0 and pv["updated_rows"] == 1 and pv["kept_rows"] == 2
    r = _upload(client, ev, fixed, what="load").json()
    assert r["inserted"] == 0 and r["updated"] == 1 and count() == 2
    after = client.get(f"/api/events/{ev.id}/inventory/assigned", params={"cedula": "1001"}).json()["lines"]
    assert sorted(ln["key"] for ln in after) == sorted(ln["key"] for ln in lines) and all(ln["pending"] == 0 for ln in after)          # mismas filas (uid), nada pendiente
    assert any(p["rows"][0].get("edad") == "8" for p in client.get(f"/api/events/{ev.id}/dependents", params={"holder": "1001"}).json()["people"])
    # (2) «Agregar» con menos columnas: no duplica
    r = _upload(client, ev, "cedula_titular,nombre_dependiente,producto\n1001,Sofía,Kit escolar\n", mode="append", what="load").json()
    assert r["inserted"] == 0 and count() == 2
    # dos filas iguales siguen siendo dos unidades (la regla de siempre)
    two = "cedula_titular,nombre_dependiente,producto\n1002,Luz,Kit escolar\n1002,Luz,Kit escolar\n"
    _upload(client, ev, two, mode="append", what="load")
    assert count() == 4
