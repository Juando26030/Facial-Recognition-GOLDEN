"""Lista de «Personas ya registradas» con datos del formulario: reconocimiento de columnas (lógica pura, sin base)."""
from app import registered_list

DESIGN = {"fields": {"cedula": {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id"}, "nombres": {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name"},
                     "ciudad": {"id": "ciudad", "type": "text_short", "label": "Ciudad", "key": "opcional_1"}, "ok": {"id": "ok", "type": "checkbox", "label": "Autorizo"},
                     "doc": {"id": "doc", "type": "paragraph", "label": "x"}},
          "rows": [{"items": ["cedula"]}, {"items": ["nombres", "ciudad"]}, {"items": ["ok"]}]}


def test_columns_are_matched_by_form_label_event_label_and_contained_words():
    header = ["número de documento", "nombre completo", "sociedad", "ciudad del evento"]
    canon = {"número de documento": "id", "nombre completo": "nombres"}
    got = registered_list.match_columns(DESIGN, header, canon, {"opcional_1": "Otra cosa"}, skip={"número de documento"})
    assert got == {"nombres": "nombre completo", "ciudad": "ciudad del evento"}            # «Ciudad del evento» contiene «Ciudad»; la casilla y el texto nunca se traen
    exact = registered_list.match_columns(DESIGN, ["ciudad", "ciudad del evento"], {}, {}, skip=set())
    assert exact["ciudad"] == "ciudad"                                                      # el título exacto gana
    by_event = registered_list.match_columns(DESIGN, ["sede"], {}, {"opcional_1": "Sede"}, skip=set())
    assert by_event == {"ciudad": "sede"}                                                   # por el nombre del campo del evento


def test_row_values_and_template_columns():
    assert registered_list.row_values({"c": "  Bogotá  ", "n": ""}, {"ciudad": "c", "nombres": "n"}) == {"ciudad": "Bogotá"}
    assert registered_list.template_columns(DESIGN, "cedula") == ["Cédula", "Nombres", "Ciudad"]


