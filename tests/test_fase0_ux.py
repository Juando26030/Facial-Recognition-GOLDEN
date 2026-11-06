"""Fase 0 (UX del piloto): una sola fuente de verdad para la biometría del evento (Parámetros), Adjuntar Base de Datos de solo lectura, etiqueta accesible,
confirmación al finalizar y sin jerga técnica visible."""
import io
import re
import zipfile

from PIL import Image

from tests.conftest import login


def _coord(client, factory, **kw):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", **kw)
    login(client, "coord1")
    return ev


def _zip(uid):
    img, buf = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (40, 40), (1, 2, 3)).save(img, "JPEG")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{uid}.jpg", img.getvalue())
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------------------------------------------ 1) Paso 0: una sola opción
def test_step_0_is_one_choice_not_two_checkboxes(client, factory, db):
    ev = _coord(client, factory)
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    radios = re.findall(r'<input type="radio" name="bsUse" id="(bsFacial|bsLocked)" value="(on|off)"', page)
    assert radios == [("bsFacial", "on"), ("bsLocked", "off")] and 'type="checkbox" id="bsFacial"' not in page and 'type="checkbox" id="bsLocked"' not in page
    assert "Usa rostro." in page and "No usa rostro (bloqueado)." in page


def test_the_two_options_save_as_one_state(client, factory, db):
    ev = _coord(client, factory)
    url = f"/api/events/{ev.id}/biometric-setup"
    on = client.put(url, json={"facial_enabled": True, "biometrics_locked": False}).json()["config"]
    assert (on["facial_enabled"], on["biometrics_locked"]) == (True, False)
    off = client.put(url, json={"facial_enabled": False, "biometrics_locked": True}).json()["config"]
    assert (off["facial_enabled"], off["biometrics_locked"]) == (False, True)


# ------------------------------------------------------------------------------------------------------------------------------------ 2) Adjuntar Base de Datos: solo lectura
def test_the_roster_page_has_no_face_checkbox_and_shows_the_events_state(client, factory, db):
    ev = _coord(client, factory, facial_enabled=True, client_photos_before=False)
    page = client.get(f"/kiosk/{ev.id}/roster").text
    assert 'id="enableFacial"' not in page and 'id="facialState"' in page and "Este evento usa reconocimiento facial" in page
    assert "origen B" in page and 'id="facialZipGroup"' not in page and 'name="zip_file"' not in page              # selfie: ni zip ni declaración
    assert f'href="/kiosk/{ev.id}/parametros"' in page
    ev.client_photos_before = True
    db.commit()
    page = client.get(f"/kiosk/{ev.id}/roster").text
    assert 'id="facialZipGroup"' in page and 'name="photos_authorized"' in page and "origen A" in page                # fotos del cliente: zip + declaración


def test_without_the_face_the_warning_that_the_date_wont_be_saved_is_on_top(client, factory, db):
    ev = _coord(client, factory)
    page = client.get(f"/kiosk/{ev.id}/roster").text
    assert "Este evento NO usa reconocimiento facial" in page and "no se guardará" in page
    assert page.index('id="facialState"') < page.index('name="roster_file"')                                        # arriba, antes de elegir el archivo


def test_with_the_face_and_selfies_the_birth_date_is_always_saved_and_a_zip_is_refused(client, factory, db):
    from app.models import User
    ev = _coord(client, factory, facial_enabled=True, client_photos_before=False)
    csv = b"id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,26/03/2005\n"
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", csv, "text/csv")})
    assert r.status_code == 200
    db.expire_all()
    from datetime import date
    assert db.query(User).filter_by(id="1001").one().birth_date == date(2005, 3, 26)
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"},
                    files={"roster_file": ("b.csv", csv, "text/csv"), "zip_file": ("f.zip", _zip("1001"), "application/zip")})
    assert r.status_code == 400 and "origen A" in r.json()["detail"]
    db.refresh(ev)
    assert ev.facial_enabled is True and ev.client_photos_before is False                                            # la carga no cambió nada del evento


def test_a_load_never_turns_the_face_on(client, factory, db):
    ev = _coord(client, factory)
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"},
                    files={"roster_file": ("b.csv", b"id,nombres,apellidos\n1001,Ana,Mora\n", "text/csv"), "zip_file": ("f.zip", _zip("1001"), "application/zip")})
    assert r.status_code == 400
    db.refresh(ev)
    assert ev.facial_enabled is False


# ------------------------------------------------------------------------------------------------------------------------------------ 3) 4) 5)
def test_the_replace_dates_checkbox_has_an_accessible_name(client, factory, db):
    ev = _coord(client, factory, facial_enabled=True)
    page = client.get(f"/kiosk/{ev.id}/roster").text
    assert '<label for="overwriteBirth"' in page and 'id="overwriteBirth" value="true" aria-labelledby="overwriteBirthText"' in page and 'id="overwriteBirthText">Reemplazar las fechas' in page


def test_finalizing_an_event_asks_with_its_consequences_everywhere(client, factory):
    toast = open("static/js/toast.js", encoding="utf-8").read()
    assert "window.FINALIZE_CONFIRM" in toast and "nadie podrá registrar" in toast and "7 días" in toast
    for tpl in ("templates/eventos.html", "static/js/gw-clientes.js"):          # clientes: la lógica salió de la plantilla (Fase 1.5)
        assert "confirmStatusChange(newStatus" in open(tpl, encoding="utf-8").read()
    modal = open("templates/_event_edit_modal.html", encoding="utf-8").read()
    assert "payload.status === 'finalizado'" in modal and "window.FINALIZE_CONFIRM" in modal and "dataset.initial" in modal


def test_no_technical_jargon_is_visible_in_parameters_or_the_roster_card(client, factory, db):
    ev = _coord(client, factory, facial_enabled=True, face_door_enabled=True, aceptar_enabled=True)
    page = client.get(f"/kiosk/{ev.id}/parametros").text
    visible = re.sub(r"<script.*?</script>|<!--.*?-->|<[^>]+>", " ", page, flags=re.S)
    for word in (".env.example", "data/outbox", "SMTP", "Twilio", "encoding", "página /aceptar", f"/kiosk/{ev.id}/rostro"):
        assert word not in visible, word
    menu = client.get(f"/kiosk/{ev.id}").text
    assert "marca la casilla de reconocimiento facial" not in menu and "Carga masiva desde Excel/CSV</div>" in menu
    assert "Paso 0" not in visible
