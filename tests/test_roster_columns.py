"""Carga de la base por TÍTULO de columna, fecha de nacimiento en los tres formatos, rastro del cambio de estado de registro y edición de la fecha de nacimiento."""
import io
import json
import zipfile
from datetime import date, datetime

import pytest
from openpyxl import Workbook
from PIL import Image

from app import roster_columns
from app.models import PersonChange, User
from tests.conftest import login


def _coord(client, factory, status="creado", **event_extra):
    event_extra.setdefault("facial_enabled", True)          # la fecha de nacimiento solo se usa con rostro (sin él la columna se ignora: ver test_no_biometrics.py)
    factory.staff("coordinador", "coord1")
    ev = factory.event(status, **event_extra)
    login(client, "coord1")
    return ev


def _csv(*lines):
    return ("\n".join(lines) + "\n").encode()


def _upload(client, ev, content, name="base.csv", **extra):
    data = {"event_id": str(ev.id), **extra.pop("data", {})}
    files = {"roster_file": (name, content, "text/csv" if name.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    files.update(extra.pop("files", {}))
    return client.post("/api/bulk_register", data=data, files=files)


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------------------------------------------- reconocimiento de títulos (sin base)
def test_known_titles_are_recognised_ignoring_case_accents_and_common_variants():
    header = {h: "ABCDEFGHIJKLMNOP"[i] for i, h in enumerate(["número de documento", "nombre", "apellido", "puesto", "empresa", "celular", "e-mail", "categoría", "tipo de asistente", "fecha de nacimiento"])}
    new_header, rows, report, new_labels = roster_columns.canonicalize(header, [dict.fromkeys(header, "x")], {})
    assert list(new_header) == ["id", "nombres", "apellidos", "cargo", "entidad", "telefono", "correo", "categoria", "tipo de asistente", "fecha de nacimiento"]
    assert new_labels == {} and report["created"] == [] and report["unused"] == [] and len(report["recognized"]) == 10 and "id" in rows[0]
    assert roster_columns.norm("  FECHA_de-Nacimiento ") == "fecha de nacimiento" and roster_columns.norm("Cédula") == "cedula"


def test_a_title_of_its_own_becomes_an_optional_field_and_the_same_title_reuses_it():
    header = {"id": "A", "nombres": "B", "apellidos": "C", "talla de camisa": "D", "observaciones": "E"}
    rows = [{"id": "1", "nombres": "A", "apellidos": "B", "talla de camisa": "M", "observaciones": ""}]
    new_header, new_rows, report, labels = roster_columns.canonicalize(header, rows, {})
    assert labels == {"opcional_1": "Talla de camisa"} and new_rows[0]["opcional_1"] == "M"
    assert report["created"] == [{"title": "talla de camisa", "field": "Talla de camisa"}]
    assert report["unused"] == [{"title": "observaciones", "reason": "columna vacía"}]                    # nada se ignora en silencio: aparece como «no usada» y con el motivo
    _, _, again, labels2 = roster_columns.canonicalize(header, rows, {"opcional_1": "Talla de camisa"})      # volver a cargar el mismo archivo
    assert labels2 == {} and again["created"] == [] and again["recognized"][-1]["field"] == "Talla de camisa"


def test_slots_do_not_collide_with_explicit_optional_columns_or_existing_labels_and_run_out_at_30():
    header = {"id": "A", "nombres": "B", "apellidos": "C", "opcional 1": "D", "ciudad": "E"}
    rows = [{"id": "1", "nombres": "A", "apellidos": "B", "opcional 1": "x", "ciudad": "Cali"}]
    _, new_rows, _, labels = roster_columns.canonicalize(header, rows, {"opcional_2": "Otra"})
    assert labels == {"opcional_3": "Ciudad"} and new_rows[0]["opcional_1"] == "x" and new_rows[0]["opcional_3"] == "Cali"
    full = {f"opcional_{n}": f"Campo {n}" for n in range(1, 31)}
    _, _, report, labels = roster_columns.canonicalize({"id": "A", "nuevo": "B"}, [{"id": "1", "nuevo": "v"}], full)
    assert labels == {} and "30 campos opcionales" in report["unused"][0]["reason"]


def test_a_second_column_for_the_same_field_is_reported_not_silently_dropped():
    _, _, report, _ = roster_columns.canonicalize({"cedula": "A", "id": "B", "nombres": "C"}, [{"cedula": "1", "id": "2", "nombres": "x"}], {})
    assert any(u["title"] == "id" and "repetida" in u["reason"] for u in report["unused"])


# ---------------------------------------------------------------------------------------------------------------------------------------- carga completa
def test_columns_with_their_own_title_are_mapped_or_created_without_asking(client, factory, db):
    ev = _coord(client, factory)
    csv = _csv("Cédula,Nombres,Apellidos,Fecha de Nacimiento,Talla de Camisa,Teléfono Celular,Observaciones",
               "1001,Ana,Mora,1990-04-02,M,3001112233,", "1002,Beto,Paz,15/08/1985,L,3002223344,")
    r = _upload(client, ev, csv)
    assert r.status_code == 200 and r.json().get("result") != "NEEDS_LABELS", r.text
    body = r.json()
    cols = body["columns"]
    assert {c["field"] for c in cols["recognized"]} >= {"Cédula", "Nombres", "Apellidos", "Fecha de nacimiento", "Teléfono"}
    assert cols["created"] == [{"title": "talla de camisa", "field": "Talla de camisa"}] and [u["title"] for u in cols["unused"]] == ["observaciones"]
    assert "Campos reconocidos" in body["message"] and "campos nuevos creados: 1" in body["message"] and "columnas no usadas: 1" in body["message"]
    db.expire_all()
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Talla de camisa"}
    u = db.query(User).filter_by(id="1001").one()
    assert u.get_extras() == {"opcional_1": "M"} and u.birth_date == date(1990, 4, 2) and u.phone == "3001112233"
    assert db.query(User).filter_by(id="1002").one().birth_date == date(1985, 8, 15)


def test_the_template_columns_marked_optional_still_ask_what_they_are_and_coexist_with_titled_ones(client, factory, db):
    ev = _coord(client, factory)
    csv = _csv("id,nombres,apellidos,opcional 1,Ciudad", "1001,Ana,Mora,Gold,Cali")
    first = _upload(client, ev, csv).json()
    assert first["result"] == "NEEDS_LABELS" and first["fields"] == ["opcional_1"] and first["examples"]["opcional_1"] == ["Gold"]        # solo pregunta por la columna «opcional», no por «Ciudad»
    assert db.query(User).filter_by(id="1001").first() is None                                                                        # nada se procesó todavía
    done = _upload(client, ev, csv, data={"field_labels": json.dumps({"opcional_1": "Nivel"})})
    assert done.status_code == 200 and done.json()["count"] == 1
    db.expire_all()
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Nivel", "opcional_2": "Ciudad"}
    assert db.query(User).filter_by(id="1001").one().get_extras() == {"opcional_1": "Gold", "opcional_2": "Cali"}


def test_birth_date_is_read_in_the_three_formats_and_an_unreadable_one_is_a_row_note_not_a_failure(client, factory, db):
    ev = _coord(client, factory)
    r = _upload(client, ev, _csv("id,nombres,apellidos,fecha de nacimiento", "1,A,Iso,2011-03-10", "2,B,Dmy,10/03/2011", "3,C,Excel,40612", "4,D,Mala,el diez de marzo", "5,E,Vacia,"))
    assert r.status_code == 200 and r.json()["count"] == 5
    db.expire_all()
    births = {u.id: u.birth_date for u in db.query(User).filter(User.id.in_(["1", "2", "3", "4", "5"]))}
    assert births == {"1": date(2011, 3, 10), "2": date(2011, 3, 10), "3": date(2011, 3, 10), "4": None, "5": None}
    notes = [e for e in r.json()["errors"] if "fecha de nacimiento" in e]
    assert len(notes) == 2 and "fila(s) 5" in notes[0] and "Fila 5" in notes[1] and "el diez de marzo" in notes[1]      # el resumen y la ilegible con su fila (la 4.ª persona está en la fila 5 del archivo)


def test_birth_date_from_a_real_excel_file_as_a_date_cell_or_as_a_serial_number(client, factory, db):
    ev = _coord(client, factory)
    content = _xlsx([["id", "nombres", "apellidos", "fecha de nacimiento"], ["11", "A", "Celda", datetime(2011, 3, 10)], ["12", "B", "Serie", 40612], ["13", "C", "Texto", "10/03/2011"]])
    r = _upload(client, ev, content, name="base.xlsx")
    assert r.status_code == 200 and r.json()["count"] == 3, r.text
    db.expire_all()
    assert {u.birth_date for u in db.query(User).filter(User.id.in_(["11", "12", "13"]))} == {date(2011, 3, 10)}
    assert not [e for e in r.json()["errors"] if "fecha de nacimiento" in e]


def test_uploading_the_same_base_again_updates_by_cedula_without_duplicating_and_without_vectors(client, factory, db, monkeypatch):
    from app.models import EventAttendee
    from app.storage import get_storage, photo_key
    monkeypatch.setattr("app.routers.api.BiometricEngine.process_image_stream", staticmethod(lambda raw: __import__("numpy").zeros((40, 40, 3), dtype="uint8")))
    ev = _coord(client, factory, facial_enabled=True, client_photos_before=True)

    def zip_with(*ids):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for uid in ids:
                img = io.BytesIO()
                Image.new("RGB", (40, 40), (10, 20, 30)).save(img, "JPEG")
                z.writestr(f"{uid}.jpg", img.getvalue())
        return buf.getvalue()

    first_csv = _csv("id,nombres,apellidos,fecha de nacimiento,Talla de camisa", "1001,Ana,Mora,1990-04-02,M", "1002,Beto,Paz,1985-08-15,L")
    files = {"zip_file": ("f.zip", zip_with("1001", "1002"), "application/zip")}
    r1 = _upload(client, ev, first_csv, data={"photos_authorized": "true"}, files=files)
    assert r1.status_code == 200 and r1.json()["count"] == 2, r1.text
    # cambia un dato y se vuelve a subir la MISMA base (mismas cédulas) con las mismas fotos
    second_csv = _csv("id,nombres,apellidos,fecha de nacimiento,Talla de camisa", "1001,Ana María,Mora,1990-04-02,XL", "1002,Beto,Paz,1985-08-15,L")
    r2 = _upload(client, ev, second_csv, data={"photos_authorized": "true"}, files={"zip_file": ("f.zip", zip_with("1001", "1002"), "application/zip")})
    assert r2.status_code == 200 and r2.json()["count"] == 2, r2.text
    db.expire_all()
    assert db.query(User).filter(User.tenant_id == ev.tenant_id, User.id.in_(["1001", "1002"])).count() == 2
    assert db.query(EventAttendee).filter_by(event_id=ev.id).count() == 2                                       # ni personas ni asistentes duplicados
    a = db.query(User).filter_by(id="1001").one()
    assert a.first_name == "Ana María" and a.get_extras() == {"opcional_1": "XL"}                             # actualizada por cédula
    assert json.loads(db.get(type(ev), ev.id).optional_field_labels) == {"opcional_1": "Talla de camisa"}      # el campo de título propio se reutilizó: no nació un «opcional_2»
    assert all(u.face_encoding is None for u in db.query(User).filter(User.id.in_(["1001", "1002"])))          # fotos sí, vectores no
    assert get_storage().exists(photo_key(ev.tenant_id, "1001")) and get_storage().exists(photo_key(ev.tenant_id, "1002"))
    assert r2.json()["columns"]["created"] == [] and r2.json()["columns"]["recognized"]                        # la segunda vez no crea nada nuevo


def test_an_event_in_process_that_already_had_a_roster_refuses_another_one(client, factory):
    ev = _coord(client, factory, "en_proceso", roster_uploaded=True)
    r = _upload(client, ev, _csv("id,nombres,apellidos", "1,A,B"))
    assert r.status_code == 400 and "ya tiene una base cargada" in r.json()["detail"]


# ---------------------------------------------------------------------------------------------------------------------------------------- rastro del estado de registro
def _status(client, ev, uid, status):
    return client.patch(f"/api/events/{ev.id}/users/{uid}/status", json={"status": status})


def test_every_change_of_registration_status_leaves_who_when_old_and_new(client, factory, db):
    staff = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "coord1")
    assert _status(client, ev, "1001", "registrado").status_code == 200
    assert _status(client, ev, "1001", "registrado").status_code == 200                                      # sin cambio real: no deja otra fila
    assert _status(client, ev, "1001", "no_registrado").status_code == 200
    db.expire_all()
    rows = db.query(PersonChange).filter_by(event_id=ev.id, user_id="1001", kind="registration_status").order_by(PersonChange.id).all()
    assert [(r.old_value, r.new_value) for r in rows] == [("No registrado", "Registrado"), ("Registrado", "No registrado")]
    assert all(r.staff_user_id == staff.id and r.at is not None and r.tenant_id == ev.tenant_id for r in rows)
    assert rows[1].detail == "accesos borrados: 1"                                                          # deshacer borra los accesos: queda cuántos


def test_suppressing_a_person_keeps_the_status_history_without_them_and_drops_birth_date_changes(client, factory, db):
    from app import privacy
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    factory.person(ev, "1001")
    login(client, "coord1")
    _status(client, ev, "1001", "registrado")
    client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": "1990-01-01"})
    assert db.query(PersonChange).filter_by(user_id="1001").count() == 2
    privacy.erase_person(db, ev, "1001", "all")
    db.expire_all()
    assert db.query(PersonChange).filter_by(user_id="1001").count() == 0
    left = db.query(PersonChange).filter_by(event_id=ev.id).all()
    assert len(left) == 1 and left[0].kind == "registration_status" and left[0].user_id is None


# ---------------------------------------------------------------------------------------------------------------------------------------- fecha de nacimiento en Editar persona y Parámetros
def test_the_edit_form_shows_and_saves_birth_date_and_a_minor_loses_the_face(client, factory, db):
    from app.storage import get_storage, photo_key
    staff = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    u = factory.person(ev, "1001")
    u.face_encoding, u.is_biometric_enabled = json.dumps([[0.1] * 128]), True
    db.commit()
    get_storage().put(photo_key(ev.tenant_id, "1001"), b"foto")
    login(client, "coord1")
    row = next(r for r in client.get(f"/api/users?event_id={ev.id}").json() if r["id"] == "1001")
    assert row["birth_date"] == ""
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": "31/02/2000"}).status_code == 400
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": "1990-04-02"}).status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().birth_date == date(1990, 4, 2) and db.query(User).filter_by(id="1001").one().face_encoding
    minor_birth = date(date.today().year - 12, 1, 1).isoformat()
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": minor_birth}).status_code == 200
    db.expire_all()
    u = db.query(User).filter_by(id="1001").one()
    assert u.birth_date.isoformat() == minor_birth and u.face_encoding is None and u.is_biometric_enabled is False and not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    changes = db.query(PersonChange).filter_by(user_id="1001", kind="birth_date").order_by(PersonChange.id).all()
    assert [(c.old_value, c.new_value, c.staff_user_id) for c in changes] == [("", "1990-04-02", staff.id), ("1990-04-02", minor_birth, staff.id)]
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": "1990-04-02"}).status_code == 200      # corrigieron un error: vuelve a poder aceptar el reconocimiento
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().is_biometric_enabled is True
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": ""}).status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().birth_date is None


def test_birth_date_is_a_field_of_the_event_parameters_and_of_the_registration_form(client, factory):
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "adm")
    cfgs = {c["key"]: c for c in client.get(f"/api/events/{ev.id}/field-configs").json()}
    assert cfgs["birth_date"]["label"] == "Fecha de nacimiento" and cfgs["birth_date"]["field_type"] == "date" and cfgs["birth_date"]["locked"] and not cfgs["birth_date"]["required"]
    assert client.put(f"/api/events/{ev.id}/field-configs/birth_date", json={"label": "Nacimiento", "sort_order": 3}).json()["label"] == "Nacimiento"
    page = client.get(f"/kiosk/{ev.id}/registro")
    assert page.status_code == 200 and 'type="date" name="birth_date"' in page.text and page.text.count('name="birth_date"') == 1


# ---------------------------------------------------------------------------------------------------------------------------------------- la plantilla descargable
TEMPLATE = "static/templates/plantilla_carga_base_asistentes.xlsx"


def test_the_template_has_the_birth_date_column_right_after_the_email_and_explains_it():
    from openpyxl import load_workbook
    wb = load_workbook(TEMPLATE)
    header = [c.value for c in wb["Base de Asistentes"][1]]
    assert header[:9] == ["id", "nombres", "apellidos", "cargo", "entidad", "telefono", "correo", "fecha de nacimiento", "tipo de asistente"] and header[-1] == "opcional_30" and len(header) == 40
    unused = roster_columns.canonicalize({h: "A" for h in header}, [], {})[2]["unused"]
    assert all(u["title"].startswith("opcional_") for u in unused)                                         # la única "no usada" son las opcionales vacías: la fecha y las demás se reconocen
    rows = {r[0].value: r[1].value for r in wb["Instrucciones"].iter_rows(min_row=2) if r[0].value and r[1].value}
    order = [r[0].value for r in wb["Instrucciones"].iter_rows(min_row=2, max_row=10)]
    assert order.index("fecha de nacimiento") == order.index("correo") + 1
    text = rows["fecha de nacimiento"]
    assert "DD/MM/AAAA" in text and "AAAA-MM-DD" in text and "menores" in text and "opcional" in text.lower()
    assert any("título propio" in str(c.value) for c in wb["Instrucciones"]["A"])                          # y se explica que un título libre se toma como etiqueta


def test_the_downloadable_template_loads_as_is_without_asking_anything_and_reads_its_example_birth_date(client, factory, db):
    ev = _coord(client, factory)
    with open(TEMPLATE, "rb") as f:
        r = _upload(client, ev, f.read(), name="plantilla.xlsx")
    assert r.status_code == 200 and r.json()["count"] == 1, r.text                                          # las celdas de ejemplo de opcional_1/2 están vacías: no pregunta etiquetas
    db.expire_all()
    assert db.query(User).filter_by(id="1020304050").one().birth_date == date(1990, 4, 2)
    assert not [e for e in r.json()["errors"] if "fecha de nacimiento" in e]



# ---------------------------------------------------------------------------------------------------------------------------------------- fecha de nacimiento: causa del enlace que la pedía (2026-10-16)
def _one(birth, cedula="9990000028"):
    return _xlsx([["cédula", "nombres", "apellidos", "correo", "fecha de nacimiento"], [cedula, "Ana", "Prueba", "a@example.com", birth]])


def test_text_ddmmyyyy_and_an_excel_date_cell_are_both_read_and_the_personal_link_does_not_ask_for_it(client, factory, db):
    from datetime import datetime as dt
    from app import acceptlink
    from app.models import EventAttendee
    ev = _coord(client, factory, aceptar_enabled=True)
    for cedula, birth in (("9990000028", "26/03/2005"), ("9990000029", dt(2005, 3, 26))):
        r = _upload(client, ev, _one(birth, cedula), name="p.xlsx")
        assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["birth"]["completed"] == 1
        db.expire_all()
        assert db.query(User).filter_by(id=cedula).one().birth_date == date(2005, 3, 26)
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="9990000028").one()
    token = acceptlink.issue(db, att, True)
    db.commit()
    chk = client.post(f"/api/aceptar/{ev.event_code}/check", data={"token": token, "cedula": "9990000028"}).json()
    assert chk == {"status": "ok", "selfie": True}                                                          # toma la fecha de la base: no la pregunta


def test_a_load_without_facial_on_keeps_the_date_and_a_reload_after_enabling_does_not_duplicate_it(client, factory, db):
    ev = _coord(client, factory, facial_enabled=False)
    first = _upload(client, ev, _one("26/03/2005"), name="p.xlsx").json()
    db.expire_all()
    assert db.query(User).filter_by(id="9990000028").one().birth_date == date(2005, 3, 26)                  # orden 22-oct-2026: sin rostro también se guarda
    assert first["birth"]["ignored_rows"] == 0 and first["birth"]["completed"] == 1 and not any("NO se guardaron" in e for e in first["errors"])
    ev.facial_enabled = True
    db.commit()
    second = _upload(client, ev, _one("26/03/2005"), name="p.xlsx").json()
    db.expire_all()
    assert db.query(User).filter_by(id="9990000028").one().birth_date == date(2005, 3, 26) and second["birth"]["completed"] == 0     # ya la tenía: nada que completar


def test_a_reload_does_not_overwrite_a_valid_date_unless_asked(client, factory, db):
    ev = _coord(client, factory)
    _upload(client, ev, _one("26/03/2005"), name="p.xlsx")
    r = _upload(client, ev, _one("01/01/1980"), name="p.xlsx").json()
    db.expire_all()
    assert db.query(User).filter_by(id="9990000028").one().birth_date == date(2005, 3, 26)                  # manda la guardada
    assert r["birth"]["kept_rows"] == [2] and any("no se cambió" in e for e in r["errors"])
    r = _upload(client, ev, _one("01/01/1980"), name="p.xlsx", data={"overwrite_birth": "true"}).json()
    db.expire_all()
    assert db.query(User).filter_by(id="9990000028").one().birth_date == date(1980, 1, 1) and r["birth"]["replaced"] == 1
    ch = db.query(PersonChange).filter_by(user_id="9990000028", kind="birth_date").one()
    assert (ch.old_value, ch.new_value) == ("2005-03-26", "1980-01-01") and "recarga" in ch.detail        # queda el rastro del cambio


def test_the_summary_counts_the_unreadable_dates_with_their_rows(client, factory, db):
    ev = _coord(client, factory)
    content = _csv("id,nombres,apellidos,fecha de nacimiento", "1,A,Uno,26/03/2005", "2,B,Dos,ayer", "3,C,Tres,", "4,D,Cuatro,31/02/2000")
    r = _upload(client, ev, content).json()
    assert r["birth"]["unreadable_rows"] == [3, 5] and r["birth"]["completed"] == 1                         # filas del archivo (la 1 es el encabezado)
    assert r["errors"][0].startswith("⚠️ 2 fila(s) con fecha de nacimiento que no se pudo entender: fila(s) 3, 5")
