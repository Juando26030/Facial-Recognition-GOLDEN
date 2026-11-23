"""0161 (21-nov-2026): reglas PURAS del inventario «lo define la base» y de la base de dependientes (app/inv_assign_core.py). Sin base de datos ni servidor."""
from app import inv_assign_core as core


def test_norm_treats_case_accents_and_spaces_as_the_same_product():
    assert core.norm("Astronauta  PROYECTOR") == core.norm("astronauta proyector") == "astronauta proyector"
    assert core.norm("Cámara digital") == core.norm("camara-digital")


def test_columns_of_the_dependents_file_are_recognized_and_a_bare_name_is_not_the_dependent():
    assert core.detect_columns(["cedula_titular", "nombre_dependiente", "cedula_dependiente", "producto"]) == {"holder": "cedula_titular", "name": "nombre_dependiente", "doc": "cedula_dependiente"}
    # la base real del cliente: «cc» del papá, «nombre» del papá -> el nombre NO se toma como el del hijo (agruparía a todos los hijos en uno)
    assert core.detect_columns(["cc", "nombre", "sucursal", "nombre del producto"]) == {"holder": "cc", "name": "", "doc": ""}
    assert core.detect_columns(["cedula", "cedula dependiente"])["doc"] == "cedula dependiente"
    assert core.detect_columns(["producto"])["holder"] == ""


def test_each_row_without_name_or_document_is_a_different_dependent_and_the_same_name_is_the_same_one():
    rows = [{"cedula_titular": "123.0", "nombre_dependiente": "Ana", "producto": "Kit"}, {"cedula_titular": "123", "nombre_dependiente": "ana", "producto": "Balón"},
            {"cedula_titular": "123", "producto": "Kit"}, {"cedula_titular": "123", "producto": "Kit"}, {"cedula_titular": ""}]
    parsed = core.parse_dependent_rows(rows, core.detect_columns(list(rows[0])))
    assert [p["holder"] for p in parsed] == ["123", "123", "123", "123"]          # la fila vacía se salta; «123.0» de Excel queda «123»
    people = core.group_people(parsed)
    assert [p["label"] for p in people] == ["Ana", "Dependiente 2", "Dependiente 3"]
    assert len(people[0]["rows"]) == 2                                              # Ana con dos productos


def test_sample_is_spread_from_first_to_last_row():
    assert core.sample_indices(0) == [] and core.sample_indices(3) == [0, 1, 2]
    s = core.sample_indices(100)
    assert len(s) == 10 and s[0] == 0 and s[-1] == 99


def test_quantities_one_row_is_one_unit_and_invalid_quantities_are_flagged():
    assert core.parse_qty("") is None and core.parse_qty("3") == 3 and core.parse_qty("2.0") == 2
    assert core.parse_qty("tres") is False and core.parse_qty("-1") is False and core.parse_qty("1.5") is False
    cfg = {"holder_product": "opcional_1", "dep_product": "producto", "dep_qty": "cantidad"}
    deps = [{"uid": "a", "label": "Ana", "data": {"Producto": "Kit", "cantidad": "2"}}, {"uid": "b", "label": "Dependiente 2", "data": {"producto": "Balón"}},
            {"uid": "c", "label": "Dependiente 3", "data": {"producto": ""}}]
    lines = core.lines_for("Kit A", None, deps, cfg)
    assert [(ln["key"], ln["product"], ln["qty"]) for ln in lines] == [("h", "Kit A", 1), ("da", "Kit", 2), ("db", "Balón", 1)]      # sin producto: no hay línea
    bad = core.lines_for("Kit A", "x", [], {"holder_product": "opcional_1", "holder_qty": "opcional_2"})
    assert bad[0]["qty"] == 0 and bad[0]["problem"]
    assert core.lines_for(None, None, deps, {"dep_product": "producto"})[0]["qty"] == 1          # sin columna de cantidad: 1 por fila
    assert core.lines_for("", None, [], {"holder_product": "opcional_1"}) == []                  # el titular sin valor no recibe


def test_assign_config_only_keeps_the_four_known_keys():
    assert core.clean_assign_config({"holder_product": " opcional_2 ", "x": 1, "dep_qty": ""}) == {"holder_product": "opcional_2", "holder_qty": None, "dep_product": None, "dep_qty": None}
