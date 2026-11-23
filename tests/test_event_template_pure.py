"""Plantilla de evento (Fase 2): lógica pura de app/event_template.py (sin base de datos)."""
import copy
import json

from app import event_template as et


def _tpl():
    return et.default_template()


def _custom(key="c_tipo", type_="select", title="Tipo de evento", **kw):
    f = {"key": key, "type": type_, "title": title, "required": False, "options": ["Congreso", "Feria"] if type_ == "select" else [], "config": {}, "help": "", "retired": False}
    f.update(kw)
    return f


def _with(tpl, *fields, place=None):
    t = copy.deepcopy(tpl)
    t["fields"] += list(fields)
    if place:
        t["creation_layout"]["sections"][0]["keys"] += place
    return t


def _raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except et.TemplateError as exc:
        return str(exc)
    raise AssertionError("debía lanzar TemplateError")


def test_default_template_is_valid_and_round_trips():
    t = _tpl()
    clean = et.validate_template(t)
    assert clean["fields"] == t["fields"] and clean["creation_layout"] == t["creation_layout"] and clean["calendar_layout"] == t["calendar_layout"]


def test_default_reproduces_todays_new_event_form():
    t = _tpl()
    keys = [k for s in t["creation_layout"]["sections"] for k in s["keys"]]
    assert keys == ["client", "event_code", "name", "event_type_id", "country", "city", "location", "address", "start_date", "end_date", "event_time_start", "event_time_end", "setup_date", "setup_time_start", "setup_time_end",
                    "coordinator_staff_id", "commercial_staff_id", "super_event_id", "bandana", "notes", "sw_review_detail"]
    req = {f["key"] for f in t["fields"] if f["required"]}
    assert req == set(keys) - {"event_type_id", "super_event_id", "bandana", "notes", "sw_review_detail"}
    assert len(t["creation_layout"]["sections"]) == 4


def test_switch_fields_exist_and_map_to_parametros_columns():
    t = _tpl()
    sw = {f["config"]["switch"]: f["key"] for f in t["fields"] if f["type"] == "switch"}
    assert set(sw) == set(et.SWITCH_KEYS)
    assert sw["inventory_enabled"] == "sw_inventory_enabled" and et.BASE_COLUMNS["sw_inventory_enabled"] == ("inventory_enabled",)
    placed = {k for s in t["creation_layout"]["sections"] for k in s["keys"]}
    assert not placed & (set(sw.values()) - {"sw_review_detail"})            # de fábrica no se piden al crear: se definen después en Parámetros (salvo «Revisar el detalle», que nace en «Revisa y crea»)


def test_locked_fields_cannot_be_removed_or_made_optional():
    t = _tpl()
    t["creation_layout"]["sections"][0]["keys"].remove("event_code")
    assert "no se puede quitar" in _raises(et.validate_template, t)
    t = _tpl()
    for f in t["fields"]:
        if f["key"] in et.LOCKED_KEYS:
            f["required"] = False
    assert all(f["required"] for f in et.validate_template(t)["fields"] if f["key"] in et.LOCKED_KEYS)


def test_optional_base_fields_can_be_dropped_but_a_required_one_must_be_placed():
    t = _tpl()
    t["creation_layout"]["sections"][2]["keys"].remove("super_event_id")
    et.validate_template(t)
    t = _tpl()
    t["creation_layout"]["sections"][1]["keys"].remove("end_date")
    assert "es obligatorio" in _raises(et.validate_template, t)
    for f in t["fields"]:
        if f["key"] == "end_date":
            f["required"] = False
    et.validate_template(t)


def test_base_field_type_and_key_cannot_change():
    t = _tpl()
    for f in t["fields"]:
        if f["key"] == "start_date":
            f["type"] = "text_long"
    out = et.validate_template(t)
    assert [f["type"] for f in out["fields"] if f["key"] == "start_date"] == ["date"]
    t = _tpl()
    t["fields"] = [f for f in t["fields"] if f["key"] != "name"]
    assert "Falta el campo base" in _raises(et.validate_template, t)


def test_custom_field_rules():
    t = _with(_tpl(), _custom(), place=["c_tipo"])
    out = et.validate_template(t)
    assert [f for f in out["fields"] if f["key"] == "c_tipo"][0]["options"] == ["Congreso", "Feria"]
    bad = [_custom(key="tipo"), _custom(key="C_x"), _custom(type_="switch"), _custom(type_="client"), _custom(type_="nada"), _custom(title=""), _custom(title="<b>x</b>"), _custom(title="x" * 61),
           _custom(options=[]), _custom(options=["a", "A"]), _custom(options=["x" * 61]), _custom(options=[str(i) for i in range(51)])]
    for f in bad:
        _raises(et.validate_template, _with(_tpl(), f))
    dup = _with(_tpl(), _custom(), _custom())
    assert "repetido" in _raises(et.validate_template, dup)


def test_limits_on_field_count():
    many = [_custom(key=f"c_{i}", type_="text_short", title=f"Campo {i}") for i in range(et.MAX_ACTIVE_FIELDS)]
    assert "campos activos" in _raises(et.validate_template, _with(_tpl(), *many))


def test_removing_a_custom_field_retires_it_and_keeps_its_definition():
    prev = et.validate_template(_with(_tpl(), _custom(), place=["c_tipo"]))
    nxt = _tpl()                                         # el administrador ya no lo manda
    out = et.validate_template(nxt, previous=prev)
    f = [x for x in out["fields"] if x["key"] == "c_tipo"][0]
    assert f["retired"] is True and f["title"] == "Tipo de evento"
    placed = {k for s in out["creation_layout"]["sections"] for k in s["keys"]}
    assert "c_tipo" not in placed
    # un retirado no se puede poner en las vistas
    t = _tpl()
    t["fields"].append(f)
    t["creation_layout"]["sections"][0]["keys"].append("c_tipo")
    assert "retirado" in _raises(et.validate_template, t)


def test_layout_validation():
    t = _tpl()
    t["creation_layout"]["sections"][0]["keys"].append("name")
    assert "dos veces" in _raises(et.validate_template, t)
    t = _tpl()
    t["creation_layout"]["sections"][0]["keys"].append("no_existe")
    _raises(et.validate_template, t)
    t = _tpl()
    t["creation_layout"]["sections"].append({"id": "extra", "title": "Vacío", "keys": []})
    assert "vacío" in _raises(et.validate_template, t)
    t = _tpl()
    t["creation_layout"]["sections"] = [{"id": f"p{i}", "title": "x", "keys": []} for i in range(7)]
    _raises(et.validate_template, t)
    t = _tpl()
    t["calendar_layout"]["zones"]["left"].append({"key": "name", "label": True})
    assert "dos veces" in _raises(et.validate_template, t)
    t = _tpl()
    t["calendar_layout"]["zones"]["centro"] = []
    _raises(et.validate_template, t)
    t = _tpl()
    t["calendar_layout"]["zones"]["bottom"] = [{"key": "sw_facial_enabled", "label": True}]
    et.validate_template(t)          # un interruptor sí puede salir en el calendario (solo visual)


def test_city_country_key_must_point_to_a_country_field():
    t = _with(_tpl(), _custom(key="c_ciudad", type_="city", title="Ciudad 2", config={"country_key": "name"}), place=["c_ciudad"])
    out = et.validate_template(t)
    assert [f for f in out["fields"] if f["key"] == "c_ciudad"][0]["config"]["country_key"] is None


def test_config_by_type_is_sanitised():
    f = _custom(key="c_n", type_="number", title="Aforo", config={"min": 5, "max": 1})
    assert "mínimo" in _raises(et.validate_template, _with(_tpl(), f))
    f = _custom(key="c_m", type_="money", title="Valor", config={"currency": "XXX"})
    _raises(et.validate_template, _with(_tpl(), f))
    inv = {"inventory_types": [{"key": "panoletas", "label": "Pañoletas", "refs": ["Roja", "Azul"]}]}
    f = _custom(key="c_i", type_="inventory", title="Inv", config=inv)
    assert "catálogo" in _raises(et.validate_template, _with(_tpl(), f))          # Fase 5: el campo viejo ya no se crea ni se deja activo (el inventario es el catálogo)
    out = et.validate_template(_with(_tpl(), {**f, "retired": True}))          # …pero uno retirado (migración 0109) sigue pasando sin romper la plantilla
    assert [x for x in out["fields"] if x["key"] == "c_i"][0]["retired"] is True
    assert not et.TYPES["inventory"]["creatable"]


def test_clean_value_by_type():
    cv = lambda t, raw, **cfg: et.clean_value({"key": "c_x", "type": t, "title": "T", "options": cfg.pop("options", []), "config": cfg}, raw)      # noqa: E731
    assert cv("text_short", "  hola ") == "hola"
    assert cv("text_short", "") is None
    _raises(cv, "text_short", "<script>")
    _raises(cv, "text_short", "x" * 201)
    assert cv("text_long", "a\nb") == "a\nb"
    assert cv("select", "Feria", options=["Feria"]) == "Feria"
    _raises(cv, "select", "Otra", options=["Feria"])
    assert cv("money", "1500000") == 1500000 and cv("money", 99.5) == 99.5
    _raises(cv, "money", -1)
    _raises(cv, "money", "abc")
    _raises(cv, "money", 1.234)
    assert cv("number", "12", min=0, max=20, decimals=0) == 12
    _raises(cv, "number", 25, min=0, max=20, decimals=0)
    _raises(cv, "number", 1.5, decimals=0)
    assert cv("number", "1,5", decimals=1) == 1.5
    assert cv("commercial", "7") == 7
    _raises(cv, "commercial", "x")
    assert cv("date", "2026-11-07") == "2026-11-07"
    _raises(cv, "date", "2026-13-01")
    assert cv("time", "8:05") == "08:05"
    _raises(cv, "time", "25:00")
    assert cv("datetime", "2026-11-07T8:30") == "2026-11-07T08:30"
    _raises(cv, "datetime", "2026-11-07")
    assert cv("address_map", {"text": "Cl 1", "lat": 4.7, "lng": -74.0}) == {"text": "Cl 1", "lat": 4.7, "lng": -74.0}
    assert cv("address_map", {"text": "", "lat": None, "lng": None}) is None
    _raises(cv, "address_map", {"text": "x", "lat": 4.7})
    _raises(cv, "address_map", {"text": "x", "lat": 100, "lng": 0})
    assert cv("contact", {"name": "Ana", "phone": "+57 300 123 4567"}) == {"name": "Ana", "phone": "+573001234567"}
    _raises(cv, "contact", {"name": "Ana", "phone": "123"})
    assert cv("bandana_colors", [{"name": "Rojo", "hex": "#C0392B"}], max=2) == [{"name": "Rojo", "hex": "#c0392b"}]
    _raises(cv, "bandana_colors", [{"name": "x", "hex": "rojo"}], max=2)
    _raises(cv, "bandana_colors", [{"hex": "#000000"}, {"hex": "#111111"}], max=1)
    inv = {"inventory_types": [{"key": "pa", "label": "Pañoletas", "refs": ["Roja"]}, {"key": "cu", "label": "Cuerdas", "refs": []}]}
    assert cv("inventory", [{"type": "pa", "qty": "5", "ref": "Roja"}, {"type": "cu", "qty": 2, "ref": " Dell "}], **inv) == [{"type": "pa", "qty": 5, "ref": "Roja"}, {"type": "cu", "qty": 2, "ref": "Dell"}]          # sin lista de referencias = texto libre
    _raises(cv, "inventory", [{"type": "zz", "qty": 1}], **inv)
    _raises(cv, "inventory", [{"type": "pa", "qty": 1, "ref": "Verde"}], **inv)
    _raises(cv, "inventory", [{"type": "pa", "qty": -1, "ref": "Roja"}], **inv)
    assert cv("switch", False) is False and cv("switch", True) is True
    _raises(cv, "switch", "si")


def test_evaluate_creation_required_missing_and_waive():
    t = _tpl()
    raw = {"client": "acme", "event_code": "E-1", "name": "N"}
    res = et.evaluate_creation(t, raw)
    assert res["errors"][0].startswith("Falta completar:") and "Lugar" in res["errors"][0] and "Observaciones" not in res["errors"][0]
    full = {**raw, "country": "CO", "city": "B", "location": "L", "address": "D", "start_date": "2026-11-01", "end_date": "2026-11-02", "event_time_start": "08:00", "event_time_end": "18:00",
            "setup_date": "2026-10-31", "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": 3}
    res = et.evaluate_creation(t, full, waive={"commercial_staff_id"})
    assert res["errors"] == []
    assert "Comercial asignada" in et.evaluate_creation(t, full)["errors"][0]


def test_evaluate_creation_extra_and_switch_rules():
    t = _with(_tpl(), _custom(required=True), place=["c_tipo"])
    base = {"client": "a", "event_code": "E", "name": "N"}
    t["fields"] = [dict(f, required=False) if f["key"] not in et.LOCKED_KEYS and f["key"] != "c_tipo" else f for f in t["fields"]]
    assert et.evaluate_creation(t, base)["errors"] == ["Falta completar: Tipo de evento"]
    ok = et.evaluate_creation(t, {**base, "c_tipo": "Feria"}, extra_keys=["c_tipo"])
    assert ok["errors"] == [] and ok["clean"]["c_tipo"] == "Feria"
    assert et.evaluate_creation(t, {**base, "c_tipo": "Otra"}, extra_keys=["c_tipo"])["errors"]
    assert any("no existe" in e for e in et.evaluate_creation(t, {**base, "c_tipo": "Feria", "c_zzz": "x"}, extra_keys=["c_tipo", "c_zzz"])["errors"])
    assert any("no existe" in e for e in et.evaluate_creation(t, base, extra_keys=["start_date"])["errors"])          # un campo base no entra por `extra`
    sw = et.evaluate_creation(t, {**base, "c_tipo": "Feria", "sw_aceptar_enabled": True}, extra_keys=["c_tipo"])
    assert "necesita" in sw["errors"][0]
    ok = et.evaluate_creation(t, {**base, "c_tipo": "Feria", "sw_aceptar_enabled": True, "sw_facial_enabled": True}, extra_keys=["c_tipo"])
    assert ok["errors"] == []


def test_retired_field_value_is_rejected_on_create_but_kept_in_template():
    prev = et.validate_template(_with(_tpl(), _custom(), place=["c_tipo"]))
    out = et.validate_template(_tpl(), previous=prev)
    out["version"] = 3
    res = et.evaluate_creation(out, {"client": "a", "event_code": "E", "name": "N", "c_tipo": "Feria"}, extra_keys=["c_tipo"], waive={"commercial_staff_id"})
    assert any("retirado" in e for e in res["errors"])


def test_split_clean_maps_to_columns_and_extra():
    cols, extra = et.split_clean({"client": "acme", "name": "N", "bandana": [{"name": "Rojo", "hex": "#c0392b"}], "sw_inventory_enabled": True, "sw_facial_enabled": False, "c_tipo": "Feria"})
    assert cols == {"name": "N", "bandana_color": "#c0392b", "bandana_color_name": "Rojo", "inventory_enabled": True, "facial_enabled": False}
    assert extra == {"c_tipo": "Feria"}


def test_raw_values_from_payload_collects_columns_switches_and_extra():
    raw = et.raw_values_from_payload({"tenant_id": "acme", "name": "N", "country": None, "bandana_color": "#aaaaaa", "bandana_color_name": "Gris", "areas_enabled": True, "facial_enabled": None}, {"c_x": 1})
    assert raw == {"client": "acme", "name": "N", "bandana": [{"name": "Gris", "hex": "#aaaaaa"}], "sw_areas_enabled": True, "c_x": 1}


def test_catalog_is_json_serialisable_and_lists_only_creatable_types_for_creation():
    c = et.catalog()
    json.dumps(c)
    assert {t["type"] for t in c["types"] if t["creatable"]} == set(et.CREATABLE_TYPES)
    assert "switch" not in et.CREATABLE_TYPES and "client" not in et.CREATABLE_TYPES
    assert set(c["locked"]) == {"client", "event_code", "name"}


def test_js_fixture_matches_the_factory_template():
    """tests/js/event_template_default.json es la plantilla de fábrica + catálogo tal como los entrega el servidor: las pruebas de Node (diseñador) parten de ella. Si cambia el código, se regenera."""
    import os
    path = os.path.join(os.path.dirname(__file__), "js", "event_template_default.json")
    fx = json.load(open(path, encoding="utf-8"))
    d = et.default_template()
    assert fx["fields"] == d["fields"] and fx["creation_layout"] == d["creation_layout"] and fx["calendar_layout"] == d["calendar_layout"]
    assert fx["catalog"] == json.loads(json.dumps(et.catalog()))


def test_renamed_factory_title_reaches_saved_templates():
    """«Impresión compartida y por USB» ya no existe: una plantilla guardada con ese título muestra el nuevo; un título propio del administrador se respeta."""
    t = _tpl()
    sw = next(f for f in t["fields"] if f["key"] == "sw_shared_print_enabled")
    assert sw["title"] == "Impresión compartida"
    old = copy.deepcopy(t)
    next(f for f in old["fields"] if f["key"] == "sw_shared_print_enabled")["title"] = "Impresión compartida y por USB"
    assert next(f for f in et.merge_missing_base(old)["fields"] if f["key"] == "sw_shared_print_enabled")["title"] == "Impresión compartida"
    own = copy.deepcopy(t)
    next(f for f in own["fields"] if f["key"] == "sw_shared_print_enabled")["title"] = "Imprimir entre varios"
    assert next(f for f in et.merge_missing_base(own)["fields"] if f["key"] == "sw_shared_print_enabled")["title"] == "Imprimir entre varios"
