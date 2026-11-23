"""Plantilla de evento (Fase 2, entrega 2): API, permisos por rol, versionado optimista, creación de eventos con campos extra e interruptores (misma fuente que Parámetros), campos retirados."""
import copy

import pytest

from app import event_template as et
from tests.conftest import login

ALL_ROLES = ["super_admin", "admin", "comercial", "coordinador", "digitador", "cliente"]


def _custom(key="c_tipo", type_="select", title="Tipo de evento", **kw):
    f = {"key": key, "type": type_, "title": title, "required": False, "options": ["Congreso", "Feria"] if type_ == "select" else [], "config": {}, "help": "", "retired": False}
    f.update(kw)
    return f


def _body(tpl, *fields, place=(), version=None):
    b = {"version": tpl["version"] if version is None else version, "fields": copy.deepcopy(tpl["fields"]) + list(fields),
         "creation_layout": copy.deepcopy(tpl["creation_layout"]), "calendar_layout": copy.deepcopy(tpl["calendar_layout"])}
    b["creation_layout"]["sections"][0]["keys"] += list(place)
    return b


def _payload(coord_id, code="PL-1", **extra):
    base = {"tenant_id": "acme", "event_code": code, "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá",
            "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord_id}
    base.update(extra)
    return base


@pytest.fixture()
def admin(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    login(client, "adm")
    return client


# ------------------------------------------------------------------ permisos
@pytest.mark.parametrize("role,can_read,can_write", [("super_admin", True, True), ("admin", True, True), ("comercial", True, False), ("coordinador", True, False), ("digitador", False, False), ("cliente", False, False)])
def test_permissions_by_role(client, factory, role, can_read, can_write):
    factory.tenant("acme")
    factory.staff(role, "actor1")
    login(client, "actor1")
    assert (client.get("/api/event-template").status_code == 200) is can_read
    tpl = et.default_template()
    tpl["version"] = 0
    r = client.put("/api/event-template", json=_body(tpl))
    assert (r.status_code == 200) is can_write, r.text
    if not can_write:
        assert r.status_code == 403
    assert (client.get("/api/event-template/revisions").status_code == 200) is can_write


def test_dual_role_coordinator_commercial_cannot_edit(client, factory):
    factory.tenant("acme")
    factory.staff("coordinador", "dual", secondary_role="comercial")
    login(client, "dual")
    tpl = et.default_template()
    assert client.get("/api/event-template").status_code == 200
    assert client.put("/api/event-template", json=_body({**tpl, "version": 0})).status_code == 403


def test_design_page_only_for_admin(client, factory):
    factory.tenant("acme")
    factory.staff("coordinador", "coord")
    factory.staff("admin", "adm")
    assert client.get("/configuracion/plantilla-evento").status_code == 302          # sin sesión
    login(client, "coord")
    r = client.get("/configuracion/plantilla-evento")
    assert r.status_code == 302 and r.headers["location"] == "/"
    client.post("/logout")
    login(client, "adm")
    page = client.get("/configuracion/plantilla-evento")
    assert page.status_code == 200 and "Diseñar plantilla para eventos" in page.text


# ------------------------------------------------------------------ leer / guardar
def test_get_returns_factory_template_when_nobody_edited(admin):
    d = admin.get("/api/event-template").json()
    assert d["version"] == 0 and d["is_default"] is True and d["scope"] == "global"
    assert d["fields"] == et.default_template()["fields"]
    assert d["catalog"]["locked"] == ["client", "event_code", "name"] and len(d["catalog"]["switches"]) == len(et.SWITCH_KEYS)


def test_put_roundtrip_versions_and_revisions(admin):
    tpl = admin.get("/api/event-template").json()
    r = admin.put("/api/event-template", json=_body(tpl, _custom(), place=["c_tipo"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["version"] == 1 and d["is_default"] is False and d["updated_by"]
    assert any(f["key"] == "c_tipo" for f in d["fields"])
    d2 = admin.put("/api/event-template", json=_body(d)).json()
    assert d2["version"] == 2
    revs = admin.get("/api/event-template/revisions").json()["revisions"]
    assert [x["version"] for x in revs] == [2, 1] and all(x["saved_by"] for x in revs)
    assert admin.get("/api/event-template").json()["version"] == 2


def test_optimistic_conflict_returns_409_and_keeps_the_first_save(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm1")
    factory.staff("admin", "adm2")
    login(client, "adm1")
    tpl = client.get("/api/event-template").json()
    assert client.put("/api/event-template", json=_body(tpl, _custom(), place=["c_tipo"])).status_code == 200
    r = client.put("/api/event-template", json=_body(tpl, _custom(key="c_otro", title="Otro"), place=["c_otro"]))          # mismo punto de partida (versión 0)
    assert r.status_code == 409 and "Recarga" in r.json()["detail"]
    keys = {f["key"] for f in client.get("/api/event-template").json()["fields"]}
    assert "c_tipo" in keys and "c_otro" not in keys


@pytest.mark.parametrize("mutate,fragment", [
    (lambda b: b["fields"].append(_custom(key="x_malo")), "Clave"),
    (lambda b: b["fields"].append(_custom(title="<script>alert(1)</script>")), "«<»"),
    (lambda b: b["fields"].append(_custom(type_="switch", key="c_sw")), "Tipo de campo no permitido"),
    (lambda b: b["creation_layout"]["sections"][0]["keys"].remove("name"), "no se puede quitar"),
    (lambda b: b.pop("fields"), "lista de campos"),
    (lambda b: b.update(version="abc"), "versión"),
])
def test_validation_errors_are_400_with_a_clear_message(admin, mutate, fragment):
    b = _body(admin.get("/api/event-template").json())
    mutate(b)
    r = admin.put("/api/event-template", json=b)
    assert r.status_code == 400 and fragment in r.json()["detail"], r.text


def test_oversized_payload_is_rejected(admin):
    b = _body(admin.get("/api/event-template").json())
    b["junk"] = "x" * (et.MAX_PAYLOAD_BYTES + 10)
    assert admin.put("/api/event-template", json=b).status_code == 413


# ------------------------------------------------------------------ crear eventos
def test_default_template_keeps_creating_events_exactly_as_before(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    r = client.post("/api/events", json=_payload(coord.id))
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["extra"] == {} and ev["switches"]["facial_enabled"] is False and ev["bandana_colors"] == []
    miss = client.post("/api/events", json={"tenant_id": "acme", "event_code": "SOLO", "name": "x"})
    assert miss.status_code == 400 and miss.json()["detail"].startswith("Falta completar:") and "Lugar" in miss.json()["detail"]


def test_old_events_without_extra_values_still_list_and_serialize(client, factory):
    factory.tenant("acme")
    factory.staff("admin", "adm")
    ev = factory.event()
    login(client, "adm")
    row = [e for e in client.get("/api/events").json() if e["id"] == ev.id][0]
    assert row["extra"] == {} and row["switches"]["inventory_enabled"] is False
    assert client.get("/api/events/calendar?start=2020-01-01&end=2030-01-01").status_code == 200


def _make_template(client, *fields, place=(), mutate=None):
    tpl = client.get("/api/event-template").json()
    b = _body(tpl, *fields, place=place)
    if mutate:
        mutate(b)
    r = client.put("/api/event-template", json=b)
    assert r.status_code == 200, r.text
    return r.json()


def test_custom_fields_are_validated_and_stored_in_extra_json(admin, factory, db):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    _make_template(admin, _custom(required=True), _custom(key="c_valor", type_="money", title="Valor"), _custom(key="c_com2", type_="commercial", title="Comercial 2"),
                   _custom(key="c_dir", type_="address_map", title="Dirección con mapa"), _custom(key="c_cto", type_="contact", title="Contacto"),
                   place=["c_tipo", "c_valor", "c_com2", "c_dir", "c_cto"])
    p = _payload(coord.id, commercial_staff_id=com.id)
    assert admin.post("/api/events", json=p).status_code == 400          # falta el tipo (obligatorio)
    good = {"c_tipo": "Feria", "c_valor": "1500000", "c_com2": com.id, "c_dir": {"text": "Cl 1 # 2-3", "lat": 4.7, "lng": -74.07}, "c_cto": {"name": "Ana", "phone": "3001234567"}}
    r = admin.post("/api/events", json={**p, "extra": good})
    assert r.status_code == 200, r.text
    assert r.json()["extra"]["c_valor"] == 1500000 and r.json()["extra"]["c_tipo"] == "Feria"
    from app.models import Event
    db.expire_all()
    stored = db.get(Event, r.json()["id"]).get_extra()
    assert stored["c_dir"] == {"text": "Cl 1 # 2-3", "lat": 4.7, "lng": -74.07}
    for bad in ({"c_tipo": "Otra"}, {"c_tipo": "Feria", "c_valor": -5}, {"c_tipo": "Feria", "c_com2": coord.id}, {"c_tipo": "Feria", "c_inv": [{"type": "zz", "qty": 1}]},
                {"c_tipo": "Feria", "c_nuevo": "x"}, {"c_tipo": "Feria", "start_date": "2026-01-01"}):
        r = admin.post("/api/events", json={**p, "event_code": "PL-BAD", "extra": bad})
        assert r.status_code == 400, (bad, r.text)


def test_base_field_can_be_made_optional_and_dropped_from_creation(admin, factory):
    coord = factory.staff("coordinador", "coord")
    def drop(b):
        for f in b["fields"]:
            if f["key"] in ("address", "setup_date", "setup_time_start", "setup_time_end", "commercial_staff_id"):
                f["required"] = False
        b["creation_layout"]["sections"][0]["keys"].remove("address")
    _make_template(admin, mutate=drop)
    p = _payload(coord.id)
    p.pop("address")
    r = admin.post("/api/events", json=p)
    assert r.status_code == 200, r.text
    assert r.json()["address"] is None and r.json()["commercial_staff_id"] is None          # el administrador no tuvo que elegir comercial porque la plantilla ya no la exige


def test_required_commercial_still_required_for_admin_and_self_assigned_for_commercial(client, factory):
    factory.tenant("acme")
    coord = factory.staff("coordinador", "coord")
    factory.staff("admin", "adm")
    me = factory.staff("comercial", "com")
    login(client, "adm")
    assert client.post("/api/events", json=_payload(coord.id)).status_code == 400
    client.post("/logout")
    login(client, "com")
    r = client.post("/api/events", json=_payload(coord.id))
    assert r.status_code == 200 and r.json()["commercial_staff_id"] == me.id


def test_switches_share_the_parametros_columns(admin, factory, db):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    tpl = admin.get("/api/event-template").json()
    placed = {k for sec in tpl["creation_layout"]["sections"] for k in sec["keys"]}          # la plantilla de fábrica ya trae algunos interruptores en la vista de creación
    place = [f["key"] for f in tpl["fields"] if f["type"] == "switch" and f["key"] not in placed]
    _make_template(admin, place=place)
    p = _payload(coord.id, commercial_staff_id=com.id)
    r = admin.post("/api/events", json={**p, "facial_enabled": True, "inventory_enabled": True, "areas_enabled": True, "digital_badge_enabled": True})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["switches"]["facial_enabled"] and ev["switches"]["inventory_enabled"] and ev["switches"]["areas_enabled"] and not ev["switches"]["certificates_enabled"]
    from app.models import Event, EventFieldConfig
    db.expire_all()
    row = db.get(Event, ev["id"])
    assert row.facial_enabled and row.inventory_enabled and row.areas_enabled and row.digital_badge_enabled          # las columnas que lee Parámetros
    assert db.query(EventFieldConfig).filter_by(event_id=ev["id"], field_key="digital_contact", required=True).count() == 1          # mismo efecto que prenderla en Parámetros
    # Parámetros ve y cambia lo mismo
    assert admin.put(f"/api/events/{ev['id']}/modules", json={"inventory_enabled": False}).status_code == 200
    db.expire_all()
    assert db.get(Event, ev["id"]).inventory_enabled is False and db.get(Event, ev["id"]).areas_enabled is True
    r = admin.post("/api/events", json={**p, "event_code": "PL-2", "aceptar_enabled": True})          # necesita el rostro
    assert r.status_code == 400 and "necesita" in r.json()["detail"]
    r = admin.post("/api/events", json={**p, "event_code": "PL-3", "aceptar_enabled": True, "facial_enabled": True})
    assert r.status_code == 200 and r.json()["switches"]["aceptar_enabled"] is True


def test_bandana_color_still_saved_in_its_columns(admin, factory):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    r = admin.post("/api/events", json=_payload(coord.id, commercial_staff_id=com.id, bandana_color="#C0392B", bandana_color_name="Rojo Golden"))
    assert r.status_code == 200 and r.json()["bandana_color"] == "#c0392b" and r.json()["bandana_colors"] == [{"name": "Rojo Golden", "hex": "#c0392b"}]
    assert admin.post("/api/events", json=_payload(coord.id, code="PL-9", commercial_staff_id=com.id, bandana_color="rojo")).status_code == 400


def test_retiring_a_field_never_deletes_values_saved_in_events(admin, factory, db):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    _make_template(admin, _custom(), place=["c_tipo"])
    r = admin.post("/api/events", json={**_payload(coord.id, commercial_staff_id=com.id), "extra": {"c_tipo": "Feria"}})
    assert r.status_code == 200
    ev_id = r.json()["id"]
    tpl = admin.get("/api/event-template").json()
    body = _body(tpl)
    body["fields"] = [f for f in body["fields"] if f["key"] != "c_tipo"]
    body["creation_layout"]["sections"][0]["keys"].remove("c_tipo")
    out = admin.put("/api/event-template", json=body).json()
    retired = [f for f in out["fields"] if f["key"] == "c_tipo"][0]
    assert retired["retired"] is True and retired["title"] == "Tipo de evento"
    ev = [e for e in admin.get("/api/events").json() if e["id"] == ev_id][0]
    assert ev["extra"] == {"c_tipo": "Feria"}                                           # el valor sigue ahí
    assert admin.post("/api/events", json={**_payload(coord.id, code="PL-R", commercial_staff_id=com.id), "extra": {"c_tipo": "Feria"}}).status_code == 400
    assert admin.patch(f"/api/events/{ev_id}", json={"extra": {"c_tipo": "Congreso"}}).status_code == 400          # un campo retirado no se edita
    # volver a poner el campo (mismo key) lo reactiva con su valor
    body2 = _body(out)
    for f in body2["fields"]:
        if f["key"] == "c_tipo":
            f["retired"] = False
    body2["creation_layout"]["sections"][0]["keys"].append("c_tipo")
    assert admin.put("/api/event-template", json=body2).status_code == 200


def test_edit_extra_values_with_patch(admin, factory):
    coord = factory.staff("coordinador", "coord")
    com = factory.staff("comercial", "com")
    _make_template(admin, _custom(), _custom(key="c_nota", type_="text_short", title="Nota"), place=["c_tipo", "c_nota"])
    ev = admin.post("/api/events", json={**_payload(coord.id, commercial_staff_id=com.id), "extra": {"c_tipo": "Feria", "c_nota": "hola"}}).json()
    r = admin.patch(f"/api/events/{ev['id']}", json={"extra": {"c_tipo": "Congreso", "c_nota": None}})
    assert r.status_code == 200 and r.json()["extra"] == {"c_tipo": "Congreso"}
    assert admin.patch(f"/api/events/{ev['id']}", json={"extra": {"c_tipo": "Mala"}}).status_code == 400
    assert admin.patch(f"/api/events/{ev['id']}", json={"name": "Nuevo nombre"}).json()["extra"] == {"c_tipo": "Congreso"}          # editar otra cosa no toca los extra
    assert admin.patch(f"/api/events/{ev['id']}", json={"extra": {"start_date": "2026-01-01"}}).status_code == 400


def test_title_and_option_text_is_stored_verbatim_for_the_client_to_escape(admin):
    b = _body(admin.get("/api/event-template").json(), _custom(title="Tipo & «clase»", options=["A&B", "Ñandú"]), place=["c_tipo"])
    out = admin.put("/api/event-template", json=b).json()
    f = [x for x in out["fields"] if x["key"] == "c_tipo"][0]
    assert f["title"] == "Tipo & «clase»" and f["options"] == ["A&B", "Ñandú"]
