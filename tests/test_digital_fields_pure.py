"""Escarapela digital: lógica pura de los datos visibles (app/digital_fields.py); no necesita base."""
import pytest

from app import digital_fields

LABELS = {"opcional_2": "Talla", "opcional_1": "Alergias"}


# ---- lógica pura (corre sin base de datos) ----
def test_allowed_keys_include_event_extras_in_order_and_contact_last():
    keys = digital_fields.allowed_keys(LABELS)
    assert keys[:4] == ["role", "entity", "opt_1", "categories"] and keys[4:6] == ["opcional_1", "opcional_2"] and keys[-2:] == ["phone", "email"]
    assert "id" not in keys                                    # la cédula no es elegible


def test_validate_none_is_default_and_dedupes_and_rejects_unknown():
    assert digital_fields.validate(None, LABELS) is None
    assert digital_fields.validate(["role", "role", "opcional_1"], LABELS) == ["role", "opcional_1"]
    for bad in (["id"], ["password"], ["opcional_9"], "role", [1], ["role", "<x>"]):
        with pytest.raises(digital_fields.FieldsError):
            digital_fields.validate(bad, LABELS)


def test_visible_keys_default_uses_template_and_never_contact():
    assert digital_fields.visible_keys(None, {"role", "phone", "email", "first_name"}, LABELS) == {"role"}
    assert digital_fields.visible_keys(["phone"], {"role"}, LABELS) == {"phone"}
    assert digital_fields.visible_keys(["opcional_7"], set(), LABELS) == set()          # clave que el evento ya no tiene


def test_parse_stored_tolerates_garbage():
    assert digital_fields.parse_stored(None) is None and digital_fields.parse_stored("") is None
    assert digital_fields.parse_stored("{no") is None and digital_fields.parse_stored('{"a":1}') is None
    assert digital_fields.parse_stored('["role", 3]') == ["role"]
