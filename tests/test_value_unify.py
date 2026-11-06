"""Unificar valores de un campo con cupos (lógica pura)."""
from app import value_unify

RULES = [{"id": "a", "match": "all", "limit": 5, "conds": [{"field": "c", "op": "equals", "value": "Bogotá"}]},
         {"id": "b", "match": "all", "limit": 5, "conds": [{"field": "c", "op": "equals", "value": "Cúcuta"}]},
         {"id": "d", "match": "all", "limit": 5, "conds": [{"field": "otro", "op": "equals", "value": "X"}]}]


def test_canonical_values_only_come_from_the_given_field():
    assert value_unify.canonical_values(RULES, "c") == {"bogota": "Bogotá", "cucuta": "Cúcuta"}


def test_resolve_by_case_accent_spaces_and_explicit_alias():
    canon = value_unify.canonical_values(RULES, "c")
    al = value_unify.alias_map({"Bogotá, D.C.": "Bogotá", "San José de Cúcuta": "Cucuta"}, canon)
    for raw in ("BOGOTA", "bogotá", "  Bogota  ", "BOGOTÁ", "Bogotá, D.C.", "bogotá, d.c."):
        assert value_unify.resolve(raw, canon, al) == "Bogotá", raw
    assert value_unify.resolve("SAN JOSÉ DE CÚCUTA", canon, al) == "Cúcuta"
    assert value_unify.resolve("Manizales", canon, al) is None            # sin regla: no se adivina
    assert value_unify.resolve("", canon, al) is None and value_unify.resolve(None, canon, al) is None and value_unify.resolve(["Bogotá"], canon, al) is None


def test_an_alias_cannot_point_to_a_city_without_quota():
    canon = value_unify.canonical_values(RULES, "c")
    try:
        value_unify.alias_map({"Duitama": "Tunja"}, canon)
    except ValueError:
        return
    raise AssertionError("debía rechazar un destino que no es de los cupos")
