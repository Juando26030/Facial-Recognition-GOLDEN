"""P4: ancho configurable de la tarjeta del formulario (theme.width): solo «full» o 480–1100 px; sin valor, el ancho de siempre."""
import pytest

from app import formlib as fl


def _theme(**theme_in):
    return fl.sanitize_design({"theme": theme_in, "fields": {}, "rows": []}, set())["theme"]


def test_existing_designs_have_no_width_key():
    assert "width" not in fl.sanitize_design(fl.default_design("Feria"), set())["theme"]
    assert "width" not in _theme(title="x")


@pytest.mark.parametrize("given,expected", [(600, 600), ("960", 960), (1100, 1100), (480, 480), (760, 760), (777.0, 777), ("full", "full")])
def test_valid_widths_are_kept(given, expected):
    assert _theme(width=given)["width"] == expected


@pytest.mark.parametrize("given", [479, 1101, 99999, 0, -600, "abc", "", None, True, [], {}, "full ", "FULL", "1e9"])
def test_invalid_widths_are_dropped(given):
    assert "width" not in _theme(width=given)


def test_width_survives_roundtrip():
    d = fl.sanitize_design({"theme": {"width": 960}, "fields": {}, "rows": []}, set())
    assert fl.sanitize_design(d, set())["theme"]["width"] == 960
