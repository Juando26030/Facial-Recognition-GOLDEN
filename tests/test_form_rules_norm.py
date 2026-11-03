"""P6: las reglas de visibilidad comparan sin tildes, mayúsculas ni espacios de más (mismos casos que tests/js/form_rules_norm_check.js)."""
from app import formlib

R = lambda op, value, have: formlib.condition_met({"field": "c", "op": op, "value": value}, {"c": have})


def test_equals_ignores_accents_case_and_spaces():
    assert R("equals", "Bogotá", "Bogota")
    assert R("equals", "Bogota", " BOGOTÁ  ")
    assert R("equals", "Apartado", "apartadó")
    assert R("equals", "San  Andrés", "san andres")
    assert not R("equals", "Bogotá", "Medellín")


def test_exact_values_keep_working():
    assert R("equals", "Bogotá", "Bogotá")
    assert R("in", ["Bogotá", "Cali"], "Cali")
    assert not R("in", ["Bogotá"], "Cali")


def test_other_operators_normalize():
    assert R("not_equals", "Bogotá", "Cali") and not R("not_equals", "Bogotá", "bogota")
    assert R("contains", "necocli", "Necoclí - Antioquia")
    assert R("in", ["Bogotá", "Apartadó"], "apartado")
    assert R("in", ["Bogotá"], ["Cali", "bogota"])
    assert R("filled", "", "x") and not R("filled", "", "")


def test_same_cases_as_browser():
    assert formlib.norm_value("  ÑANDÚ   Ávila ") == "nandu avila"
