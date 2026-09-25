"""Privacidad y cumplimiento (Ley 1581 de 2012): consentimiento para el dato biométrico, borrado, páginas legales y accesibilidad básica."""
import io
import zipfile

import pytest
from PIL import Image

from tests.conftest import login


def _photo():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def faces(monkeypatch):
    monkeypatch.setattr("app.routers.api.BiometricEngine.extract_encoding", staticmethod(lambda img, is_registration=False, **kw: [[0.1] * 128]))


def _kiosk(client, factory, role="digitador"):
    staff = factory.staff(role, "9990001" if role == "digitador" else "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    if role == "digitador":
        factory.authorize(ev, staff)
    login(client, staff.username)
    return ev


def _register(client, ev, uid="1001", consent=None, photo=True):
    data = {"event_id": ev.id, "id": uid, "first_name": "Ana", "last_name": "Mora"}
    if consent is not None:
        data["biometric_consent"] = consent
    files = {"file": ("f.jpg", _photo(), "image/jpeg")} if photo else None
    return client.post("/api/register", data=data, files=files)


def test_a_face_is_never_saved_without_the_persons_explicit_authorization(client, factory, faces, db):
    from app.models import User
    ev = _kiosk(client, factory)
    r = _register(client, ev)                                                                       # sin casilla de autorización
    assert r.status_code == 400 and "autorización" in r.json()["detail"]
    assert db.query(User).filter_by(id="1001").first() is None                                      # y no quedó nada guardado
    r = _register(client, ev, consent="false")
    assert r.status_code == 400
    ok = _register(client, ev, consent="true")
    assert ok.status_code == 200, ok.text
    u = db.query(User).filter_by(id="1001").first()
    assert u.face_encoding and u.biometric_consent_at and u.biometric_consent_source == "kiosko"     # queda constancia de cuándo y cómo


def test_registering_by_cedula_without_photo_needs_no_biometric_consent(client, factory, db):
    from app.models import User
    ev = _kiosk(client, factory)
    r = _register(client, ev, uid="2002", photo=False)                                              # la alternativa sin rostro siempre funciona
    assert r.status_code == 200
    u = db.query(User).filter_by(id="2002").first()
    assert u.face_encoding is None and u.biometric_consent_at is None


def test_photo_zip_needs_the_organizers_declaration_and_records_it(client, factory, faces, db):
    from app.models import User
    ev = _kiosk(client, factory, role="coordinador")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("3003.jpg", _photo())
    files = {"roster_file": ("b.csv", b"id,nombres,apellidos\n3003,Luis,Paz\n", "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")}
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files=files)
    assert r.status_code == 400 and "autorización" in r.json()["detail"]
    files = {"roster_file": ("b.csv", b"id,nombres,apellidos\n3003,Luis,Paz\n", "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")}
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"}, files=files)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(User).filter_by(id="3003").first().biometric_consent_source == "carga_masiva"


# ------------------------------- borrado / retención -------------------------------
def _with_face(db, ev, uid, other_event=None):
    import os
    from datetime import datetime
    from app.models import EventAttendee, User
    u = db.query(User).filter_by(id=uid, tenant_id=ev.tenant_id).first() or User(id=uid, tenant_id=ev.tenant_id, first_name="N", last_name="A")
    u.face_encoding = "[[0.1]]"
    u.biometric_consent_at, u.biometric_consent_source = datetime.utcnow(), "kiosko"
    db.add(u)
    db.flush()
    for e in (ev, other_event):
        if e is not None and not db.query(EventAttendee).filter_by(event_id=e.id, user_id=uid).first():
            db.add(EventAttendee(event_id=e.id, user_id=uid, tenant_id=ev.tenant_id))
    os.makedirs(os.path.join("data", ev.tenant_id, "known_people"), exist_ok=True)
    with open(os.path.join("data", ev.tenant_id, "known_people", f"{uid}.jpg"), "wb") as fh:
        fh.write(b"x")
    db.commit()


def test_purge_event_erases_faces_but_keeps_people_who_are_in_another_active_event(client, factory, db):
    import os
    from app.models import User
    factory.staff("admin", "adm1")
    ev = factory.event("finalizado")
    other = factory.event("en_proceso")
    _with_face(db, ev, "1001")
    _with_face(db, ev, "1002", other_event=other)
    login(client, "adm1")
    assert client.post(f"/api/events/{ev.id}/biometrics/purge", json={}).status_code == 400                                 # sin confirmación no borra
    st = client.get(f"/api/events/{ev.id}/privacy").json()
    assert (st["with_biometrics"], st["with_consent"]) == (2, 2)
    r = client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm": True}).json()
    assert r == {"deleted": 1, "kept_in_other_events": 1}
    db.expire_all()
    u1, u2 = db.query(User).filter_by(id="1001").first(), db.query(User).filter_by(id="1002").first()
    assert u1.face_encoding is None and u1.biometric_consent_at is None and not os.path.isfile(f"data/{ev.tenant_id}/known_people/1001.jpg")
    assert u2.face_encoding and os.path.isfile(f"data/{ev.tenant_id}/known_people/1002.jpg")


def test_a_coordinator_can_erase_one_persons_face_but_only_admins_purge_the_event(client, factory, db):
    from app.models import User
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    _with_face(db, ev, "1001")
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm": True}).status_code == 403
    assert client.delete(f"/api/events/{ev.id}/users/9999/biometrics").status_code == 404
    assert client.delete(f"/api/events/{ev.id}/users/1001/biometrics").json()["deleted"] is True
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().face_encoding is None
    assert client.delete(f"/api/events/{ev.id}/users/1001/biometrics").json()["deleted"] is False                         # ya no había nada


def test_automatic_retention_only_runs_when_configured_and_only_on_old_finalized_events(client, factory, db, monkeypatch):
    from datetime import date, timedelta
    from app import privacy
    ev_old = factory.event("finalizado", end_date=date.today() - timedelta(days=200))
    ev_recent = factory.event("finalizado", end_date=date.today() - timedelta(days=10))
    ev_live = factory.event("en_proceso", end_date=date.today() - timedelta(days=300))
    _with_face(db, ev_old, "1001")
    _with_face(db, ev_recent, "2002")
    _with_face(db, ev_live, "3003")
    monkeypatch.delenv("BIOMETRIC_RETENTION_DAYS", raising=False)
    assert privacy.retention_days() == 180                                                                       # decisión de Golden: 6 meses por defecto
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "0")
    assert privacy.retention_days() is None                                                                      # 0 apaga el borrado automático
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "180")
    r = privacy.purge_expired(db, 180)
    assert r == {"events": 1, "deleted": 1, "kept_in_other_events": 0}                                           # solo el evento finalizado hace más de 180 días
    assert privacy.purge_expired(db, 180)["events"] == 0                                                          # ya purgado: no se repite


# ------------------------------- páginas legales públicas -------------------------------
def test_legal_pages_are_public_marked_as_drafts_and_show_the_business_data(client):
    for path, title in (("/privacidad", "Política de Privacidad"), ("/terminos", "Términos y Condiciones"), ("/reembolsos", "Política de Reembolsos")):
        r = client.get(path)                                                                          # sin sesión
        assert r.status_code == 200 and title in r.text
        assert "PENDIENTE DE REVISIÓN LEGAL" in r.text                                                # borrador hasta que un abogado lo revise
        assert "901542833" in r.text and "GOLDEN EVENTOS Y LOGISTICA SAS" in r.text                   # identificación del vendedor/responsable
    p = client.get("/privacidad").text
    for needle in ("Wompi", "Microsoft", "Google Cloud", "biométric", "cédula", "10 días hábiles"):
        assert needle in p


def test_business_data_and_retention_come_from_the_environment(client, monkeypatch):
    monkeypatch.delenv("BIOMETRIC_RETENTION_DAYS", raising=False)
    home = client.get("/terminos").text
    assert "Carrera 14a # 71a - 59, Bogotá" in home and "+57 317 427 6073" in home and "info@goldenlogisticas.com" in home      # los datos reales de Golden
    assert "6 meses (180 días) después de la fecha de finalización" in client.get("/privacidad").text                         # retención por defecto: 6 meses
    monkeypatch.setenv("LEGAL_ADDRESS", "Calle 1 # 2-3")
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "90")
    monkeypatch.setenv("REFUND_REQUEST_DAYS", "15")
    assert "Calle 1 # 2-3" in client.get("/terminos").text
    assert "3 meses (90 días)" in client.get("/privacidad").text
    assert "15 días calendario" in client.get("/reembolsos").text
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "0")
    assert "hasta que solicites su supresión" in client.get("/privacidad").text                                                 # apagada explícitamente


def test_jurisdiction_is_bogota_and_international_events_are_covered(client):
    t = client.get("/terminos").text
    assert "Bogotá D.C." in t and "Eventos fuera de Colombia" in t
    assert "fuera de Colombia" in client.get("/privacidad").text


def test_public_pages_carry_the_legal_footer_and_the_cookie_notice(client, factory):
    from tests.test_form_extras import _disc_form
    ev, form, _ = _disc_form(client, factory, [])
    html = client.get(f"/f/{ev.id}/{form['slug']}").text
    assert "/privacidad" in html and "NIT 901542833" in html and "js/cookie-notice.js" in html
    login_html = client.get("/login").text
    assert "/terminos" in login_html and "NIT 901542833" in login_html
    js = client.get("/static/js/form-render.js").text
    assert "/reembolsos" in js                                                                            # el cuadro de pago enlaza los términos y los reembolsos


def test_consent_text_configured_in_parameters_reaches_the_form_editor(client, factory, db):
    from app.models import EventFieldConfig
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    db.add(EventFieldConfig(event_id=ev.id, field_key="opcional_1", field_type="consent", help_text="Autorizo el tratamiento de mi rostro...", required=True))
    ev.set_optional_labels({"opcional_1": "Autorización biométrica"})
    db.commit()
    login(client, "coord1")
    fields = client.get(f"/api/events/{ev.id}/form-event-fields").json()
    bio = next(f for f in fields if f["key"] == "opcional_1")
    assert bio["type"] == "checkbox" and bio["required"] and bio["help"].startswith("Autorizo el tratamiento de mi rostro")


# ------------------------------- cifrado en reposo del dato biométrico -------------------------------
@pytest.fixture()
def face_key(monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", key)
    return key


def test_face_encoding_is_stored_encrypted_but_the_app_reads_it_in_the_clear(factory, db, face_key):
    from sqlalchemy import text
    from app.models import User
    ev = factory.event("en_proceso")
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="A", last_name="B", face_encoding="[[0.1, 0.2]]"))
    db.commit()
    raw = db.execute(text("SELECT face_encoding FROM users WHERE id='1001'")).scalar()
    assert raw.startswith("enc1:") and "0.1" not in raw                                                    # en la base NO se ve el dato
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().face_encoding == "[[0.1, 0.2]]"                     # el código lo lee normal
    assert db.query(User).filter(User.face_encoding != None).count() == 1                                  # noqa: E711 — y los filtros por «tiene rostro» siguen sirviendo


def test_without_a_key_data_stays_readable_and_old_plaintext_coexists_with_encrypted(factory, db, monkeypatch):
    from cryptography.fernet import Fernet
    from sqlalchemy import text
    from app.models import User
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    ev = factory.event("en_proceso")
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="A", last_name="B", face_encoding="[[1]]"))
    db.commit()
    assert db.execute(text("SELECT face_encoding FROM users WHERE id='1001'")).scalar() == "[[1]]"        # sin llave: en claro (como hasta ahora)
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db.add(User(id="1002", tenant_id=ev.tenant_id, first_name="C", last_name="D", face_encoding="[[2]]"))
    db.commit()
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first().face_encoding == "[[1]]"                             # lo viejo en claro se sigue leyendo
    assert db.query(User).filter_by(id="1002").first().face_encoding == "[[2]]"
    monkeypatch.delenv("FACE_ENCRYPTION_KEY")
    db.expire_all()
    assert db.query(User).filter_by(id="1002").first().face_encoding is None                                # sin la llave lo cifrado NO se lee (y no rompe nada)


def test_key_rotation_reads_data_written_with_the_old_key(monkeypatch):
    from cryptography.fernet import Fernet
    from app import crypto
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", old)
    token = crypto.encrypt_text("secreto")
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", f"{new},{old}")                                               # la primera cifra, todas descifran
    assert crypto.decrypt_text(token) == "secreto" and crypto.encrypt_text("otro") != token
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", new)
    assert crypto.decrypt_text(token) is None                                                               # si se quita la llave vieja, lo viejo ya no se lee


def test_photos_are_encrypted_on_disk_and_served_decrypted(client, factory, faces, face_key, db):
    import os
    ev = _kiosk(client, factory, role="coordinador")
    assert _register(client, ev, consent="true").status_code == 200
    path = f"data/{ev.tenant_id}/known_people/1001.jpg"
    with open(path, "rb") as fh:
        head = fh.read(20)
    assert head.startswith(b"GWENC1:") and b"JFIF" not in head and not head.startswith(b"\xff\xd8")         # en disco no es un JPEG legible
    from app import crypto
    raw = crypto.read_bytes(path)
    assert raw[:2] == b"\xff\xd8"                                                                           # al leerla con la llave vuelve a ser JPEG
    r = client.get(f"/api/users/1001/photo?event_id={ev.id}")
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8" and r.headers["content-type"] == "image/jpeg"


def test_encrypt_faces_script_encrypts_what_was_left_in_the_clear(factory, db, monkeypatch, tmp_path):
    import os
    import subprocess
    import sys
    from cryptography.fernet import Fernet
    from sqlalchemy import text
    from app.models import User
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    ev = factory.event("en_proceso")
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="A", last_name="B", face_encoding="[[1]]"))
    db.commit()
    os.makedirs(f"data/{ev.tenant_id}/known_people", exist_ok=True)
    with open(f"data/{ev.tenant_id}/known_people/1001.jpg", "wb") as fh:
        fh.write(b"\xff\xd8plano")
    env = {**os.environ, "FACE_ENCRYPTION_KEY": Fernet.generate_key().decode()}
    out = subprocess.run([sys.executable, "scripts/encrypt_faces.py"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "quedó cifrado" in out.stdout, out.stdout + out.stderr
    db.expire_all()
    assert db.execute(text("SELECT face_encoding FROM users WHERE id='1001'")).scalar().startswith("enc1:")
    with open(f"data/{ev.tenant_id}/known_people/1001.jpg", "rb") as fh:
        assert fh.read(7) == b"GWENC1:"
    again = subprocess.run([sys.executable, "scripts/encrypt_faces.py", "--dry-run"], capture_output=True, text=True, env=env)
    assert "En claro: 0 encoding(s) y 0 foto(s)" in again.stdout                                            # idempotente


# ------------------------------- reembolsos editables por formulario -------------------------------
def test_refund_terms_are_configured_per_form_and_shown_on_the_refund_page(client, factory):
    from tests.test_form_extras import _disc_form
    from tests.test_forms import _put
    ev, form, _ = _disc_form(client, factory, [])
    login(client, "coord1")
    r = _put(client, ev, form, settings={"refunds": {"days": "10", "note": "La comisión de Wompi no se devuelve."}})
    assert r.status_code == 200 and r.json()["settings"]["refunds"] == {"days": 10, "note": "La comisión de Wompi no se devuelve."}
    assert _put(client, ev, form, settings={"refunds": {"days": 9999, "note": ""}}).json()["settings"]["refunds"]["days"] is None      # fuera de rango: se ignora
    _put(client, ev, form, settings={"refunds": {"days": 10, "note": "La comisión de Wompi no se devuelve."}})
    client.post("/logout")
    page = client.get(f"/reembolsos?e={ev.id}&f={form['slug']}").text
    assert "Condiciones de este formulario" in page and "hasta <b>10 días</b>" in page and "La comisión de Wompi no se devuelve." in page
    assert "Condiciones de este formulario" not in client.get("/reembolsos").text                                          # la página general no las muestra
    assert client.get(f"{'/f/%d/%s' % (ev.id, form['slug'])}/state").json()["refund"]["days"] == 10                       # y el formulario público las recibe
