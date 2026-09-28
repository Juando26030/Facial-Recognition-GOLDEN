"""Subida directa al almacenamiento (app/uploads.py): el navegador sube el archivo y la app solo firma y después procesa."""
import json
from types import SimpleNamespace

import pytest

from app import uploads
from app.models import EventDocument, FormSubmission
from app.storage import get_storage
from tests.conftest import login
from tests.test_forms import _basic_fields, _create, _design, _event, _open, _url

CSV = b"id,nombres,apellidos,entidad\n1001,Ana,Uno,ACME\n1002,Beto,Dos,ACME\n"


def _sign(client, purpose, ev, filename="base.csv", size=None, content=CSV, ctype="text/csv"):
    return client.post("/api/uploads", json={"purpose": purpose, "event_id": ev.id, "filename": filename,
                                             "size": len(content) if size is None else size, "content_type": ctype})


def _upload(client, sig, content):
    assert sig["method"] == "PUT" and sig["url"].startswith("/api/uploads/local/")
    return client.put(sig["url"], content=content, headers=sig["headers"])


def _staged_key(token):
    return uploads.read_token(token)["k"]


def _admin(client, factory, status="creado"):
    factory.staff("admin", "root")
    ev = factory.event(status)
    login(client, "root")
    return ev


def test_bulk_register_reads_the_roster_from_the_direct_upload_and_cleans_up(client, factory):
    ev = _admin(client, factory)
    sig = _sign(client, "bulk_roster", ev).json()
    assert _upload(client, sig, CSV).status_code == 200
    assert get_storage().exists(_staged_key(sig["token"]))
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "roster_upload": sig["token"]})
    assert r.status_code == 200 and r.json()["count"] == 2
    assert not get_storage().exists(_staged_key(sig["token"]))            # el temporal se borra al procesar


def test_needs_labels_keeps_the_staged_file_for_the_resend(client, factory):
    ev = _admin(client, factory)
    csv = b"id,nombres,apellidos,opcional_1\n1001,Ana,Uno,M\n"
    sig = _sign(client, "bulk_roster", ev, content=csv).json()
    _upload(client, sig, csv)
    first = client.post("/api/bulk_register", data={"event_id": str(ev.id), "roster_upload": sig["token"]}).json()
    assert first["result"] == "NEEDS_LABELS" and get_storage().exists(_staged_key(sig["token"]))
    again = client.post("/api/bulk_register", data={"event_id": str(ev.id), "roster_upload": sig["token"],
                                                    "field_labels": json.dumps({"opcional_1": "Talla"})})
    assert again.status_code == 200 and again.json()["count"] == 1


def test_a_token_only_works_for_its_event_and_purpose(client, factory):
    ev = _admin(client, factory)
    other = factory.event("creado")
    sig = _sign(client, "bulk_roster", ev).json()
    _upload(client, sig, CSV)
    assert client.post("/api/bulk_register", data={"event_id": str(other.id), "roster_upload": sig["token"]}).status_code == 400
    assert client.post("/api/bulk_register", data={"event_id": str(ev.id), "zip_upload": sig["token"], "photos_authorized": "true"}).status_code == 400
    assert client.post("/api/bulk_register", data={"event_id": str(ev.id), "roster_upload": sig["token"] + "x"}).status_code == 400


def test_signing_validates_type_size_and_role(client, factory):
    ev = _admin(client, factory)
    assert _sign(client, "bulk_roster", ev, filename="base.exe").status_code == 400
    assert _sign(client, "bulk_roster", ev, size=0).status_code == 400
    assert _sign(client, "bulk_roster", ev, size=60 * 1024 * 1024).status_code == 400
    assert _sign(client, "bulk_zip", ev, filename="fotos.zip", size=900 * 1024 * 1024, ctype="application/zip").status_code == 200   # más de 32 MiB: justo para esto
    assert _sign(client, "otra_cosa", ev).status_code == 400
    client.post("/logout")
    factory.staff("comercial", "ventas")
    login(client, "ventas")
    assert _sign(client, "bulk_roster", ev).status_code == 403              # la comercial no carga bases (mismo criterio de bulk_register)


def test_local_receiver_enforces_the_signed_size(client, factory):
    ev = _admin(client, factory)
    sig = _sign(client, "bulk_roster", ev, size=10).json()                  # el límite firmado es el del propósito, no el tamaño declarado
    assert uploads.read_token(sig["token"])["m"] == uploads.PURPOSES["bulk_roster"][1]
    small = uploads.create("event_doc", {"e": ev.id}, ev.tenant_id, "a.pdf", 5, "application/pdf", max_bytes=5)
    assert client.put(small["url"], content=b"%PDF-mas-de-cinco", headers=small["headers"]).status_code == 413
    assert client.put("/api/uploads/local/no-es-un-token", content=b"x").status_code == 400


def test_event_document_from_a_direct_upload(client, factory, db):
    ev = _admin(client, factory)
    pdf = b"%PDF-1.4 documento grande"
    sig = _sign(client, "event_doc", ev, filename="contrato.pdf", content=pdf, ctype="application/pdf").json()
    _upload(client, sig, pdf)
    r = client.post(f"/api/events/{ev.id}/documents", data={"name": "Contrato", "upload": sig["token"]})
    assert r.status_code == 200, r.text
    doc = db.query(EventDocument).one()
    assert doc.original_filename == "contrato.pdf" and doc.size_bytes == len(pdf) and get_storage().get(doc.stored_path) == pdf
    assert client.post(f"/api/events/{ev.id}/documents", data={"name": "Sin archivo"}).status_code == 400


def test_public_form_files_go_direct_and_the_submit_only_carries_tokens(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "cv", "type": "file", "label": "Hoja de vida", "required": True, "accept": ["pdf"], "max_mb": 1}]
    _open(client, ev, f, design=_design(fields))
    base = {"cedula": "1001", "nombres": "A", "apellidos": "B"}
    sign = lambda **b: client.post(f"{_url(ev, f)}/upload", json={"fid": "cv", "filename": "cv.pdf", "size": 100, "content_type": "application/pdf", **b})
    assert sign(size=2 * 1024 * 1024).status_code == 400                   # tope del campo (1 MB)
    assert sign(filename="cv.docx").status_code == 400                     # formato del campo
    assert sign(fid="nombres").status_code == 400                          # ese campo no es de archivo
    content = b"%PDF-1.4 hoja de vida"
    sig = sign(size=len(content)).json()
    assert _upload(client, sig, content).status_code == 200
    bad = client.post(f"{_url(ev, f)}/submit", json={"values": base, "sid": "s1", "uploads": {"cv": "falso"}})
    assert bad.status_code == 422 and "cv" in bad.json()["errors"]
    ok = client.post(f"{_url(ev, f)}/submit", json={"values": base, "sid": "s2", "uploads": {"cv": sig["token"]}})
    assert ok.status_code == 200, ok.text
    sub = db.query(FormSubmission).one()
    assert json.loads(sub.data_json)["cv"]["filename"] == "cv.pdf" and not get_storage().exists(_staged_key(sig["token"]))
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/forms/{f['id']}/files/{sub.id}/cv").content == content


def test_public_signing_requires_the_same_stage_as_the_submit(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "cv", "type": "file", "label": "CV", "accept": ["pdf"]}]
    _open(client, ev, f, design=_design(fields), settings={"security": {"enabled": True, "type": "code", "code": "1234"}})
    r = client.post(f"{_url(ev, f)}/upload", json={"fid": "cv", "filename": "cv.pdf", "size": 10, "content_type": "application/pdf"})
    assert r.status_code == 403


# ------------------------------------------------------------------ URL firmada de Cloud Storage
class _FakeBlob:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def generate_signed_url(self, **kw):
        self.calls.append((self.name, kw))
        return "https://storage.googleapis.com/firmada"


def _gcs(creds):
    from app.storage import GcsStorage
    calls = []
    store = GcsStorage.__new__(GcsStorage)
    store.client = SimpleNamespace(_credentials=creds)
    store.bucket = SimpleNamespace(blob=lambda name: _FakeBlob(name, calls))
    store.prefix = "golden"
    return store, calls


def test_gcs_signed_put_url_signs_type_and_size_and_uses_iam_without_a_private_key():
    from google.auth.credentials import Signing

    class KeyCreds(Signing):
        signer = signer_email = None
        def sign_bytes(self, message):  # noqa: E301
            return b""

    store, calls = _gcs(KeyCreds())
    url, headers = store.signed_put_url("uploads/acme/bulk_zip/x/fotos.zip", "application/zip", 1000, 900)
    name, kw = calls[0]
    assert url.startswith("https://") and name == "golden/uploads/acme/bulk_zip/x/fotos.zip"
    assert headers == {"Content-Type": "application/zip", "x-goog-content-length-range": "0,1000"} and kw["headers"] == headers
    assert kw["method"] == "PUT" and kw["version"] == "v4" and "access_token" not in kw

    metadata_creds = SimpleNamespace(valid=True, service_account_email="app@p.iam.gserviceaccount.com", token="tok")   # Cloud Run: sin llave privada
    store, calls = _gcs(metadata_creds)
    store.signed_put_url("uploads/a/b", "text/csv", 10, 900)
    assert calls[0][1]["service_account_email"] == "app@p.iam.gserviceaccount.com" and calls[0][1]["access_token"] == "tok"


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))
