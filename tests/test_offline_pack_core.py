"""Reglas puras del paquete sin red (app/offline_pack_core.py): mismas líneas que el servidor da persona por persona. Sin base de datos."""
from app import inv_assign_core as core
from app import offline_pack_core as pc

ROWS = [
    {"id": 1, "uid": "u1", "holder": "100", "name": "Hijo Uno", "doc": "", "person_key": "k1", "data": {"Producto": "Camiseta", "Cantidad": "2"}, "row_num": 2},
    {"id": 2, "uid": "u2", "holder": "100", "name": "", "doc": "300", "person_key": "k2", "data": {"Producto": "Gorra"}, "row_num": 3},
    {"id": 3, "uid": "u3", "holder": "200", "name": "Otro", "doc": "", "person_key": "k3", "data": {"Producto": ""}, "row_num": 4},
]
CFG = {"holder_product": "opt_1", "holder_qty": "", "dep_product": "Producto", "dep_qty": "Cantidad"}


def test_dependents_view_matches_the_per_holder_endpoint():
    people, own = pc.dependents_view(ROWS)
    pub = pc.public_dependents(people)
    assert [p["label"] for p in pub["100"]] == ["Hijo Uno", "Dependiente 2"]
    assert pub["100"][0]["rows"] == [{"Producto": "Camiseta", "Cantidad": "2"}]
    assert pub["100"][1]["doc"] == "300" and list(own) == ["300"]          # 300 es dependiente de 100 con su propio documento


def test_assigned_lines_holder_dependents_and_own_rows():
    people, own = pc.dependents_view(ROWS)
    items = {core.norm("Camiseta"): {"id": 7, "name": "Camiseta", "initial_qty": 10}, core.norm("Kit"): {"id": 8, "name": "Kit", "initial_qty": 5}}
    users = [{"id": "100", "product": "Kit", "qty": None}, {"id": "300", "product": "", "qty": None}, {"id": "999", "product": "", "qty": None}]
    out = pc.assigned_lines(CFG, users, people, own, items, {7: 4, 8: 5}, {"100": 1}, {core.dep_line_key("u1"): 1})
    assert set(out) == {"100", "300"}                                      # a 999 no le toca nada: no viaja
    by_key = {ln["key"]: ln for ln in out["100"]}
    holder = by_key[core.HOLDER_KEY]
    assert (holder["item_id"], holder["delivered"], holder["pending"], holder["done"], holder["available"]) == (8, 1, 0, True, 0)
    shirt = by_key[core.dep_line_key("u1")]
    assert (shirt["qty"], shirt["delivered"], shirt["pending"], shirt["available"], shirt["dependent"]) == (2, 1, 1, 6, True)
    cap = by_key[core.dep_line_key("u2")]
    assert cap["item_id"] is None and "no está en el inventario" in cap["problem"]
    mine = out["300"][0]                                                    # la misma fila, vista por el propio dependiente
    assert mine["key"] == core.dep_line_key("u2") and "dependiente de 100" in mine["who"]


def test_without_dependent_column_only_the_holder_line():
    out = pc.assigned_lines({"holder_product": "opt_1"}, [{"id": "100", "product": "Kit", "qty": None}], {}, {}, {}, {}, {}, {})
    assert [ln["key"] for ln in out["100"]] == [core.HOLDER_KEY]
