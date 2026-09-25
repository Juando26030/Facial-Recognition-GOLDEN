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
    assert privacy.retention_days() is None                                                                      # sin plazo definido: nada se borra solo
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "180")
    assert privacy.retention_days() == 180
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
    monkeypatch.setenv("LEGAL_ADDRESS", "Calle 1 # 2-3")
    monkeypatch.setenv("BIOMETRIC_RETENTION_DAYS", "90")
    monkeypatch.setenv("REFUND_REQUEST_DAYS", "15")
    assert "Calle 1 # 2-3" in client.get("/terminos").text
    assert "90 días después de la fecha de finalización" in client.get("/privacidad").text
    assert "15 días calendario" in client.get("/reembolsos").text
    monkeypatch.delenv("BIOMETRIC_RETENTION_DAYS")
    assert "pendiente de definir por Golden" in client.get("/privacidad").text                          # sin plazo definido no se inventa uno


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
