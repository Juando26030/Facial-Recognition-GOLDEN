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
