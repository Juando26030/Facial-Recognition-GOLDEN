# ruff: noqa: F811
"""Plan 5 (carga flexible de la base de un evento): el Excel se acepta como venga, columna por columna se informa qué se entendió, «No eliminar repetidos» (serial 123456-2) y el selector de mayúsculas.

Origen del plan: una base con las columnas «correo» y «ciudad» (típica: cédula, nombres, apellidos, empresa, cargo, correo, teléfono, ciudad) no cargaba sin que el dueño tuviera que rotular/ajustar columnas a mano.
Las pruebas de la capa de columnas no necesitan base de datos; las de la carga siguen el estilo de tests/test_roster_columns.py."""
import io
import json
import zipfile

import pytest
from PIL import Image

from app import roster_columns, roster_dups, roster_text
from app.models import EventAttendee, EventFieldConfig, User
from app.routers import parametros
from app.routers.api import _read_roster_rows
from tests.test_carga_por_pasos import _drive, _post, coord, small_steps  # noqa: F401  (fixtures)
from tests.test_roster_columns import _coord, _csv, _upload, _xlsx
from tests.test_solo_agregar import _drive as _drive_append, _post_append, live  # noqa: F401  (fixture)

TYPICAL = ["cédula", "nombres", "apellidos", "empresa", "cargo", "correo", "teléfono", "ciudad"]
TYPICAL_ROW = ["1001", "Ana", "Mora", "Acme", "Jefa", "ana@example.com", "3001112233", "Cali"]


def _header(cols):
    return {c.lower(): "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i] for i, c in enumerate(cols)}


def _canon(cols, values=None, labels=None, **kw):
    header = _header(cols)
    row = {c.lower(): (values[i] if values else "x") for i, c in enumerate(cols)}
    return roster_columns.canonicalize(header, [row], labels or {}, **kw)


def _users(db, ev):
    db.expire_all()
    return {u.id: u for u in db.query(User).filter_by(tenant_id=ev.tenant_id)}


# ------------------------------------------------------------------------------------------------------------------------------ columnas (sin base)
def test_the_typical_template_with_email_and_city_maps_everything_and_makes_city_an_optional_field():
    header, rows, report, new_labels = _canon(TYPICAL, TYPICAL_ROW)
    assert list(header) == ["id", "nombres", "apellidos", "entidad", "cargo", "correo", "telefono", "opcional_1"]
    assert new_labels == {"opcional_1": "Ciudad"} and rows[0]["opcional_1"] == "Cali" and rows[0]["correo"] == "ana@example.com"
    assert report["created"] == [{"title": "ciudad", "field": "Ciudad"}] and report["unused"] == []
    kinds = {c["title"]: c["kind"] for c in report["columns"]}
    assert kinds == {"cédula": "entendida", "nombres": "entendida", "apellidos": "entendida", "empresa": "entendida", "cargo": "entendida", "correo": "entendida", "teléfono": "entendida", "ciudad": "opcional"}


def test_a_column_name_is_an_optional_field_directly_not_only_opcional_n_and_case_and_accents_do_not_matter():
    header, rows, report, new_labels = _canon(["CÉDULA", "NOMBRE", "APELLIDO", "Correo Electrónico", "CIUDAD de Residencia", "Talla"], ["1", "A", "B", "a@b.co", "Cali", "M"])
    assert list(header) == ["id", "nombres", "apellidos", "correo", "opcional_1", "opcional_2"]
    assert new_labels == {"opcional_1": "Ciudad de residencia", "opcional_2": "Talla"}


def test_unknown_columns_are_optional_empty_ones_are_ignored_with_reason_and_a_repeated_known_one_is_reported():
    cols = ["id", "nombres", "apellidos", "correo", "e-mail", "Observaciones", "Grupo"]
    header, rows, report, new_labels = _canon(cols, ["1", "A", "B", "a@b.co", "z@b.co", "", "Rojo"])
    assert new_labels == {"opcional_1": "Grupo"}
    reasons = {u["title"]: u["reason"] for u in report["unused"]}
    assert reasons["observaciones"] == "columna vacía" and "repetida" in reasons["e-mail"]
    assert {c["title"]: c["kind"] for c in report["columns"]}["observaciones"] == "ignorada"


def test_missing_default_fields_are_not_an_error_for_the_column_layer():
    header, rows, report, new_labels = _canon(["cédula", "ciudad"], ["1", "Cali"])
    assert list(header) == ["id", "opcional_1"] and report["unused"] == [] and new_labels == {"opcional_1": "Ciudad"}


def test_a_title_equal_to_an_existing_label_reuses_the_field_and_the_cap_of_30_has_a_clear_message():
    _, _, report, new_labels = _canon(["id", "ciudad"], ["1", "Cali"], labels={"opcional_4": "Ciudad"})
    assert new_labels == {} and report["columns"][1] == {"title": "ciudad", "kind": "opcional", "field": "Ciudad"}
    full = {f"opcional_{n}": f"Campo {n}" for n in range(1, 31)}
    _, _, report, new_labels = _canon(["id", "ciudad"], ["1", "Cali"], labels=full)
    assert new_labels == {} and "30 campos opcionales" in report["unused"][0]["reason"] and "ciudad" in report["unused"][0]["reason"].lower()


def test_a_header_repeated_in_the_file_keeps_the_first_column_and_reports_the_other():
    header, rows = _read_roster_rows("a.csv", _csv("id,nombres,apellidos,Ciudad,ciudad", "1,Ana,Mora,Cali,Bogotá"))
    assert rows[0]["ciudad"] == "Cali"                                                                    # no se pisa en silencio con la última
    _, _, report, new_labels = roster_columns.canonicalize(header, rows, {})
    assert new_labels == {"opcional_1": "Ciudad"} and [u["reason"] for u in report["unused"]] == ["columna repetida: se usó la primera con ese título"]
    xheader, xrows = _read_roster_rows("a.xlsx", _xlsx([["id", "ciudad", "ciudad"], ["1", "Cali", "Bogotá"]]))
    assert xrows[0]["ciudad"] == "Cali" and len(xheader) == 3


# ------------------------------------------------------------------------------------------------------------------------------ repetidos y texto (sin base)
def test_serials_follow_the_file_order_and_the_original_is_kept_in_its_field():
    rows = [{"id": "1001"}, {"id": "1002"}, {"id": "1001"}, {"id": "1001.0"}, {"id": ""}, {"id": "1002"}]
    out = roster_dups.assign(rows, original_key="opcional_1")
    assert [r["id"] for r in rows] == ["1001", "1002", "1001-2", "1001-3", "", "1002-2"]
    assert [r.get("opcional_1") for r in rows] == [None, None, "1001", "1001", None, "1002"] and out["serials"] == 3 and out["ids"] == 2


def test_offsets_from_previous_batches_make_the_numbering_consistent_across_batches():
    batch = [{"id": "1001"}, {"id": "1003"}]
    roster_dups.assign(batch, roster_dups.parse_offsets('{"1001": 2}'))
    assert [r["id"] for r in batch] == ["1001-3", "1003"]
    assert roster_dups.parse_offsets("no es json") == {} and roster_dups.has_repeats([{"id": "5"}, {"id": "5"}]) and not roster_dups.has_repeats([{"id": "5"}, {"id": "6"}])


def test_a_generated_serial_that_already_exists_in_the_file_is_reported():
    rows = [{"id": "1001"}, {"id": "1001-2"}, {"id": "1001"}]
    assert roster_dups.assign(rows)["collisions"] == ["1001-2"]


def test_text_case_never_touches_id_phone_or_birth_and_the_email_is_always_lowercase():
    def row():
        return {"id": "AB123", "nombres": "ana maría", "apellidos": "De la Torre", "cargo": "jefe", "correo": " ANA@Example.COM ", "telefono": "300 abc", "opcional_1": "Bogotá", "fecha de nacimiento": "1990-04-02", "categoria": "VIP"}
    up, low, asis = roster_text.apply([row()], roster_text.UPPER)[0], roster_text.apply([row()], roster_text.LOWER)[0], roster_text.apply([row()], "")[0]
    assert (up["nombres"], up["apellidos"], up["cargo"], up["opcional_1"]) == ("ANA MARÍA", "DE LA TORRE", "JEFE", "BOGOTÁ")
    assert (low["nombres"], low["apellidos"], low["opcional_1"]) == ("ana maría", "de la torre", "bogotá")
    assert (asis["nombres"], asis["apellidos"]) == ("ana maría", "De la Torre")
    for out in (up, low, asis):
        assert out["id"] == "AB123" and out["telefono"] == "300 abc" and out["fecha de nacimiento"] == "1990-04-02" and out["categoria"] == "VIP" and out["correo"] == "ana@example.com"
    assert roster_text.parse_mode("MAYUSCULAS") == roster_text.UPPER and roster_text.parse_mode("raro") is None and roster_text.parse_mode(None) == roster_text.AS_IS


# ------------------------------------------------------------------------------------------------------------------------------ la carga
def test_the_typical_base_with_email_and_city_loads_with_no_questions_and_a_column_report(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, _csv(",".join(TYPICAL), ",".join(TYPICAL_ROW), "1002,Beto,Paz,Acme,Jefe,beto@example.com,3002223344,Bogotá"))
    assert r.status_code == 200 and r.json().get("result") != "NEEDS_LABELS", r.text
    body = r.json()
    assert body["count"] == 2 and not [e for e in body["errors"] if e.startswith("❌")]
    assert [c["kind"] for c in body["columns"]["columns"]] == ["entendida"] * 7 + ["opcional"]
    users = _users(db, ev)
    assert users["1001"].email == "ana@example.com" and users["1001"].get_extras() == {"opcional_1": "Cali"} and users["1002"].entity == "Acme"
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Ciudad"}


def test_a_required_email_in_parameters_does_not_stop_the_load_nor_the_city(client, factory, db):
    ev = _coord(client, factory)
    db.add(EventFieldConfig(event_id=ev.id, field_key="email", required=True, field_type="email"))
    db.commit()
    r = _upload(client, ev, _csv(",".join(TYPICAL), ",".join(TYPICAL_ROW), "1002,Beto,Paz,Acme,Jefe,,3002223344,Bogotá"))      # a Beto le falta el correo obligatorio: la carga no valida obligatorios
    assert r.status_code == 200 and r.json()["count"] == 2, r.text
    assert set(_users(db, ev)) == {"1001", "1002"}
    db.expire_all()
    assert "email" in [c["key"] for c in parametros.field_configs_for_event(db, db.get(type(ev), ev.id))]       # el correo viene en el archivo: sigue visible y obligatorio


def test_a_file_with_only_the_cedula_and_a_city_loads_and_unused_fixed_fields_are_hidden_in_parameters(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, _csv("cédula,ciudad", "1001,Cali", "1002,Bogotá"))
    assert r.status_code == 200 and r.json()["count"] == 2, r.text
    assert not [e for e in r.json()["errors"] if e.startswith("❌")]
    db.expire_all()
    keys = [c["key"] for c in parametros.field_configs_for_event(db, db.get(type(ev), ev.id))]
    assert "opcional_1" in keys and not {"role", "entity", "phone", "email", "opt_1"} & set(keys)              # solo lo que trae el Excel (más la identidad)
    assert {"first_name", "last_name", "id"} <= set(keys)
    labels = [c["label"] for c in parametros.field_configs_for_event(db, db.get(type(ev), ev.id))]
    assert "Género" not in labels                                                                              # nada fijo vacío «de adorno»


def test_each_event_hides_exactly_the_fixed_fields_whose_column_the_file_does_not_bring(client, factory, db):
    ev = _coord(client, factory)
    assert _upload(client, ev, _csv("id,telefono", "2001,3001112233")).status_code == 200
    assert _upload_hidden(db, ev) == {"role", "entity", "email", "opt_1"}


def _upload_hidden(db, ev):
    db.expire_all()
    return {r.field_key for r in db.query(EventFieldConfig).filter_by(event_id=ev.id, field_type=parametros.DELETED_TYPE)}


def test_old_optional_labels_are_cleaned_only_in_an_event_without_people(client, factory, db):
    ev = _coord(client, factory)
    ev.set_optional_labels({"opcional_1": "Vieja", "opcional_2": "Otra vieja"})
    db.commit()
    assert _upload(client, ev, _csv("id,nombres,apellidos,Ciudad", "1001,Ana,Mora,Cali")).status_code == 200
    db.expire_all()
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Ciudad"}              # sin personas: solo lo del Excel
    # con personas ya cargadas, las etiquetas se conservan y se suman
    ev2 = factory.event("creado")
    ev2.set_optional_labels({"opcional_1": "Vieja"})
    db.commit()
    factory.person(ev2, "9001")
    assert _upload(client, ev2, _csv("id,nombres,apellidos,Ciudad", "1001,Ana,Mora,Cali")).status_code == 200
    db.expire_all()
    assert json.loads(db.get(type(ev2), ev2.id).optional_field_labels) == {"opcional_1": "Vieja", "opcional_2": "Ciudad"}


def test_a_label_with_its_own_parameters_configuration_survives_the_cleanup(client, factory, db):
    ev = _coord(client, factory)
    ev.set_optional_labels({"opcional_1": "Firma"})
    db.add(EventFieldConfig(event_id=ev.id, field_key="opcional_1", label="Firma", field_type="signature"))
    db.commit()
    assert _upload(client, ev, _csv("id,nombres,apellidos,Ciudad", "1001,Ana,Mora,Cali")).status_code == 200
    db.expire_all()
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Firma", "opcional_2": "Ciudad"}


def test_thirty_own_titled_columns_fit_and_the_31st_is_reported_with_a_clear_message(client, factory, db):
    ev = _coord(client, factory)
    titles = [f"Campo {n}" for n in range(1, 32)]
    r = _upload(client, ev, _csv("id,nombres,apellidos," + ",".join(titles), "1001,Ana,Mora," + ",".join(str(n) for n in range(1, 32))))
    assert r.status_code == 200, r.text
    cols = r.json()["columns"]
    assert len(cols["created"]) == 30 and len(cols["unused"]) == 1 and "30 campos opcionales" in cols["unused"][0]["reason"]


def test_a_file_without_a_cedula_column_is_the_only_format_error(client, factory):
    ev = _coord(client, factory)
    r = _upload(client, ev, _csv("nombres,apellidos,ciudad", "Ana,Mora,Cali"))
    assert r.status_code == 400 and "formato" in r.json()["detail"] and "cédula" in r.json()["detail"]


def test_a_base_without_names_loads_and_each_row_says_the_name_is_missing(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, _csv("id,correo", "1001,ana@example.com"))
    assert r.status_code == 200 and r.json()["count"] == 1
    assert any("falta el nombre" in e for e in r.json()["errors"])
    assert _users(db, ev)["1001"].email == "ana@example.com"


def test_the_flexible_columns_work_with_and_without_the_photos_zip(client, factory, db, monkeypatch):
    from app.storage import get_storage, photo_key
    monkeypatch.setattr("app.routers.api.BiometricEngine.process_image_stream", staticmethod(lambda raw: __import__("numpy").zeros((40, 40, 3), dtype="uint8")))
    ev = _coord(client, factory, facial_enabled=True, client_photos_before=True)
    img = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 20, 30)).save(img, "JPEG")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1001.jpg", img.getvalue())
    csv = _csv("cédula,ciudad,correo", "1001,Cali,ana@example.com", "1002,Bogotá,beto@example.com")
    r = _upload(client, ev, csv, data={"photos_authorized": "true"}, files={"zip_file": ("f.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200 and r.json()["count"] == 2, r.text
    assert get_storage().exists(photo_key(ev.tenant_id, "1001")) and not get_storage().exists(photo_key(ev.tenant_id, "1002"))
    assert _users(db, ev)["1002"].get_extras() == {"opcional_1": "Bogotá"}


# ------------------------------------------------------------------------------------------------------------------------------ No eliminar repetidos
REPEATED = _csv("id,nombres,apellidos,correo", "1001,Ana,Uno,a@example.com", "1002,Beto,Dos,b@example.com", "1001,Ana,Tres,c@example.com", "1001,Ana,Cuatro,d@example.com")


def test_with_the_box_off_the_last_row_wins_and_it_warns_as_always(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, REPEATED)
    assert r.status_code == 200 and r.json()["count"] == 4
    users = _users(db, ev)
    assert set(users) == {"1001", "1002"} and users["1001"].last_name == "Cuatro"
    assert any("aparece repetida" in e and "última fila" in e for e in r.json()["errors"])
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels or "{}") == {}                    # sin la casilla no nace «Cédula original»


def test_with_the_box_on_the_first_keeps_its_cedula_and_the_rest_get_a_serial_with_the_original_in_an_optional_field(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, REPEATED, data={"keep_duplicates": "true"})
    assert r.status_code == 200 and r.json()["count"] == 4, r.text
    users = _users(db, ev)
    assert set(users) == {"1001", "1002", "1001-2", "1001-3"}
    assert (users["1001"].last_name, users["1001-2"].last_name, users["1001-3"].last_name) == ("Uno", "Tres", "Cuatro")
    assert users["1001"].get_extras() == {} and users["1001-2"].get_extras() == {"opcional_1": "1001"} and users["1001-3"].get_extras() == {"opcional_1": "1001"}
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Cédula original"}
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 4
    errors = r.json()["errors"]
    assert not any("aparece repetida" in e for e in errors) and any("No eliminar repetidos" in e and "orden de las filas" in e for e in errors)      # avisa que recargar depende del orden


def test_reloading_the_same_file_in_the_same_order_does_not_duplicate_people(client, factory, db):
    ev = _coord(client, factory)
    assert _upload(client, ev, REPEATED, data={"keep_duplicates": "true"}).status_code == 200
    again = _upload(client, ev, REPEATED, data={"keep_duplicates": "true"})
    assert again.status_code == 200
    assert set(_users(db, ev)) == {"1001", "1002", "1001-2", "1001-3"} and db.query(EventAttendee).filter_by(event_id=ev.id).count() == 4
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Cédula original"}      # el campo se reutiliza, no nace otro


def test_the_same_id_in_different_batches_gets_consecutive_serials_using_the_offsets_the_browser_sends(client, factory, db):
    ev = _coord(client, factory)
    first = _upload(client, ev, _csv("id,nombres,apellidos", "1001,Ana,Uno", "1002,Beto,Dos", "1001,Ana,Tres"), data={"keep_duplicates": "true"})
    assert first.status_code == 200
    second = _upload(client, ev, _csv("id,nombres,apellidos", "1001,Ana,Cuatro", "1003,Caro,Seis"), data={"keep_duplicates": "true", "dup_offsets": json.dumps({"1001": 2})})
    assert second.status_code == 200, second.text
    users = _users(db, ev)
    assert set(users) == {"1001", "1002", "1001-2", "1001-3", "1003"} and users["1001-3"].last_name == "Cuatro"
    assert users["1001-3"].get_extras() == {"opcional_1": "1001"}                                              # el lote 2 reutilizó el campo «Cédula original» que creó el lote 1


def test_repeated_ids_get_their_serial_before_the_steps_so_a_repeat_in_a_later_step_is_numbered_by_the_whole_file(client, coord, db, small_steps):
    ids = ["2001", "2002", "2001", "2003", "2001", "2002"]
    book = _xlsx([["id", "nombres", "apellidos"]] + [[i, f"N{n}", "X"] for n, i in enumerate(ids)])
    first = _post(client, coord, book, keep_duplicates="true").json()
    final, _calls = _drive(client, first)
    assert final["status"] == "done" and final["result"]["count"] == 6, final
    assert set(_users(db, coord)) == {"2001", "2002", "2003", "2001-2", "2001-3", "2002-2"}
    assert _users(db, coord)["2001-3"].first_name == "N4"                                                    # la 5.ª fila (2.º paso) es la 3.ª aparición de 2001


def test_with_append_only_the_box_adds_the_repeated_rows_with_serial_and_without_it_only_the_first_is_kept(client, live, db):
    assert _drive_append(client, _post_append(client, live, data="id,nombres,apellidos\n5001,Ana,Uno\n5001,Ana,Dos\n", keep_duplicates="true").json())["status"] == "done"
    assert _drive_append(client, _post_append(client, live, data="id,nombres,apellidos\n6001,Ana,Uno\n6001,Ana,Dos\n").json())["status"] == "done"
    db.expire_all()
    ids = {u.id for u in db.query(User).filter_by(tenant_id=live.tenant_id)}
    assert {"5001", "5001-2", "6001"} <= ids and "6001-2" not in ids                                      # «solo agregar» no crea el campo «Cédula original», pero sí a la persona con serial


def test_the_downloadable_template_explains_the_flexible_load():
    from openpyxl import load_workbook
    text = " ".join(str(c.value) for c in load_workbook("static/templates/plantilla_carga_base_asistentes.xlsx")["Instrucciones"]["A"] if c.value)
    assert "No eliminar repetidos" in text and "Cédula original" in text and "MAYÚSCULAS" in text and "Lo único indispensable es la cédula" in text and "30 campos opcionales" in text


# ------------------------------------------------------------------------------------------------------------------------------ mayúsculas al subir
BASE = _csv("id,nombres,apellidos,cargo,correo,telefono,Ciudad", "1001,ana maría,De la Torre,jefe,ANA@Example.COM,300 111,Bogotá")


@pytest.mark.parametrize("mode, names, role, city", [("upper", ("ANA MARÍA", "DE LA TORRE"), "JEFE", "BOGOTÁ"), ("lower", ("ana maría", "de la torre"), "jefe", "bogotá"),
                                                      ("", ("ana maría", "De la Torre"), "jefe", "Bogotá")])
def test_the_text_selector_changes_names_and_text_fields_but_never_cedula_phone_and_always_lowercases_the_email(client, factory, db, mode, names, role, city):
    ev = _coord(client, factory)
    r = _upload(client, ev, BASE, data={"text_case": mode})
    assert r.status_code == 200, r.text
    u = _users(db, ev)["1001"]
    assert (u.first_name, u.last_name, u.role) == (names[0], names[1], role) and u.get_extras() == {"opcional_1": city}
    assert u.email == "ana@example.com" and u.phone == "300 111" and u.id == "1001"
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Ciudad"}              # la etiqueta del campo no cambia de caja


def test_an_invalid_text_selector_is_a_400(client, factory):
    ev = _coord(client, factory)
    assert _upload(client, ev, BASE, data={"text_case": "raro"}).status_code == 400


def test_the_text_selector_applies_in_the_steps_flow_too(client, coord, db, small_steps):
    book = _xlsx([["id", "nombres", "apellidos"]] + [[str(3000 + n), f"nombre {n}", "apellido"] for n in range(5)])
    final, _ = _drive(client, _post(client, coord, book, text_case="upper").json())
    assert final["status"] == "done"
    assert {u.first_name for u in _users(db, coord).values()} == {f"NOMBRE {n}" for n in range(5)}
