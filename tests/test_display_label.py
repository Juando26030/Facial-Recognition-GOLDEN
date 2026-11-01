"""P8: nombre de presentación con formato en todos los tipos de campo; `label` sigue siendo texto plano (reportes, Excel, estadísticas…)."""
import pytest

from app import formlib as fl

TYPES = ["text_short", "text_long", "email", "phone", "number", "date", "checkbox", "select", "radio", "multiselect", "file"]


def _field(kind, **extra):
    f = {"id": "c1", "type": kind, "label": "Ciudad", **extra}
    if kind in ("select", "radio", "multiselect"):
        f["options"] = ["Bogotá", "Cali"]
    return f


def _design(field):
    return fl.sanitize_design({"fields": {field["id"]: field}, "rows": []}, set())["fields"][field["id"]]


@pytest.mark.parametrize("kind", TYPES)
def test_every_input_type_keeps_a_clean_display_label(kind):
    got = _design(_field(kind, display_label="<b>Tu ciudad</b><script>alert(1)</script>"))
    assert got["display_label"] == "<b>Tu ciudad</b>" and got["label"] == "Ciudad"


def test_payment_and_companions_too():
    pay = _design({"id": "p", "type": "payment", "label": "Pago", "display_label": "<u>Tu pago</u><img src=x>", "pay": {"mode": "fixed", "amount": 2000}})
    assert pay["display_label"] == "<u>Tu pago</u>"
    comp = _design({"id": "k", "type": "companions", "label": "Acompañantes", "display_label": "<i>Con quién vienes</i>", "max": 2, "min": 0,
                    "person_fields": [{"id": "nombre", "label": "Nombre", "type": "text_short", "required": True}]})
    assert comp["display_label"] == "<i>Con quién vienes</i>"


def test_existing_fields_gain_no_keys_and_plain_text_stays_identical():
    assert "display_label" not in _design(_field("text_short"))
    assert "display_label" not in _design(_field("text_short", display_label="   "))
    assert _design(_field("text_short", display_label="Edad <18"))["display_label"] == "Edad <18"


def test_label_stays_plain_text_everywhere():
    got = _design(_field("text_short", label="<b>Ciudad</b>", display_label="<b>Ciudad</b>"))
    assert got["label"] == "<b>Ciudad</b>"             # el nombre plano no se interpreta ni se limpia: es el dato (columna de reportes)


def test_static_elements_have_no_display_label():
    assert "display_label" not in _design({"id": "t", "type": "paragraph", "content": "x", "display_label": "<b>y</b>"})


def test_help_accepts_full_format_for_every_type_and_is_clean():
    for kind in TYPES:
        assert _design(_field(kind, help="<ul><li>a</li></ul><p style=\"text-align:justify\">b</p><script>1</script>"))["help"] == '<ul><li>a</li></ul><p style="text-align:justify">b</p>'


def test_display_label_roundtrips_for_export_import_duplicate():
    d = fl.sanitize_design({"fields": {"c1": _field("select", display_label="<b>Ciudad</b>")}, "rows": []}, set())
    assert fl.sanitize_design(d, set())["fields"]["c1"]["display_label"] == "<b>Ciudad</b>"
