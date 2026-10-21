"""L4: supresión individual y revocación, de punta a punta (base, Storage, roster local, anonimización de ingresos, tombstone, consentimientos intactos)."""
import json

import pytest
from sqlalchemy import text

from app import consent, faces
from app.models import AccessLog, AuditConsentLog, EventAttendee, FormPayment, FormSubmission, PrintLog, SystemEvent, User, WebForm
from app.storage import form_file_key, get_storage, photo_key
from tests.conftest import accept, login


def _setup(client, factory, db, role="admin"):
    factory.staff(role, "adm")
    ev = factory.event("en_proceso", facial_enabled=True)
    other = factory.event("en_proceso", facial_enabled=True)
    db.add(User(id="1001", tenant_id=ev.tenant_id, first_name="Ana", last_name="Mora", email="ana@x.test", phone="3001112233", role="VIP", face_encoding=json.dumps([0.1] * 128)))
    db.add(User(id="2002", tenant_id=ev.tenant_id, first_name="Luis", last_name="Paz"))
    db.flush()
    for e in (ev, other):
        db.add(EventAttendee(event_id=e.id, user_id="1001", tenant_id=ev.tenant_id))
    db.add(EventAttendee(event_id=ev.id, user_id="2002", tenant_id=ev.tenant_id))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, record_type="Existente", registration_method="biometrico", client_id="c1"))
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="2002", event_id=ev.id, record_type="Existente", registration_method="qr", client_id="c2"))
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id))
    get_storage().put(photo_key(ev.tenant_id, "1001"), b"JPEG")
    db.commit()
    accept(db, ev, "1001")
    login(client, "adm")
    return ev, other


def _purge(client, ev, scope, uid="1001", confirm=True):
    return client.delete(f"/api/attendees/{uid}/purge-data", params={"event_id": ev.id, "scope": scope, **({"confirm": "true"} if confirm else {})})


def _form_with_submission_and_payment(db, ev):
    form = WebForm(event_id=ev.id, name="F", slug="f", design_json="{}", settings_json="{}", test_key="k1")
    db.add(form)
    db.flush()
    sub = FormSubmission(form_id=form.id, event_id=ev.id, person_id="1001", data_json=json.dumps({"f1": "Ana", "f2": {"filename": "cv.pdf", "stored": "abc123.pdf", "size": 10}}))
    db.add(sub)
    db.flush()
    db.add(FormPayment(form_id=form.id, event_id=ev.id, submission_id=sub.id, reference="REF-1", amount_cents=10000, status="approved", person_id="1001", payer_email="ana@x.test"))
    get_storage().put(form_file_key(ev.tenant_id, form.id, "abc123.pdf"), b"PDF")
    db.commit()
    return form, sub


def test_only_admin_and_up_can_purge_and_it_must_be_confirmed(client, factory, db):
    ev, _ = _setup(client, factory, db, role="coordinador")
    assert _purge(client, ev, "all").status_code == 403
    client.post("/api/auth/logout")
    factory.staff("admin", "adm2")
    login(client, "adm2")
    assert _purge(client, ev, "all", confirm=False).status_code == 400 and _purge(client, ev, "otro").status_code == 400
    assert _purge(client, ev, "all", uid="9999").status_code == 404
    assert db.query(User).filter_by(id="1001").first() is not None


def test_revocation_deletes_vector_and_photo_records_it_and_keeps_the_person(client, factory, db):
    ev, _ = _setup(client, factory, db)
    r = _purge(client, ev, "biometric")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["had_biometrics"] is True and body["scope"] == "biometric" and any("copias de seguridad" in x for x in body["not_immediate"])
    db.expire_all()
    u = db.query(User).filter_by(id="1001").one()
    assert u.face_encoding is None and u.is_biometric_enabled is False and u.first_name == "Ana"           # sigue siendo una persona: entra por cédula/QR
    assert not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    last = consent.latest(db, ev.tenant_id, "1001", ev.id)
    assert last.reason == "revocation" and not consent.has_acceptance(db, ev.tenant_id, "1001", ev.id)
    assert db.query(AuditConsentLog).filter_by(user_id="1001", reason="consent").count() == 1             # la prueba de que aceptó SE CONSERVA
    ev_row = db.query(SystemEvent).filter_by(kind="person_purge").one()
    assert "1001" not in (ev_row.ref or "") + (ev_row.detail or "") and "biometric" in ev_row.detail      # auditoría: quién, cuándo, alcance; nada personal
    # el roster local ya no la marca como aceptada
    people = {p["n"]: p for p in client.get(f"/api/events/{ev.id}/local-roster").json()["people"]}
    assert people["Ana Mora"]["a"] == 0


def test_full_purge_removes_personal_data_anonymizes_logs_and_keeps_proof_and_payments(client, factory, db):
    ev, other = _setup(client, factory, db)
    form, sub = _form_with_submission_and_payment(db, ev)
    version_before = client.get(f"/api/events/{ev.id}/local-roster").headers["etag"]
    assert _purge(client, ev, "all").status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").first() is None                                           # nombre, correo, teléfono, extras: fuera
    assert db.query(EventAttendee).filter_by(user_id="1001").count() == 0                                # de TODOS los eventos
    assert db.query(PrintLog).filter_by(user_id="1001").count() == 0
    assert not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    # ingresos: anonimizados de forma irreversible (se conservan hora, tipo y evento)
    logs = db.query(AccessLog).filter_by(client_id="c1").one()
    assert logs.user_id is None and logs.record_type == "Existente" and logs.event_id == ev.id and logs.timestamp is not None
    assert db.query(AccessLog).filter_by(user_id="2002").count() == 1                                    # los de otras personas, intactos
    # inscripción: se conserva pero vacía y desvinculada; el adjunto se borra; el pago se conserva sin el correo
    s = db.query(FormSubmission).filter_by(id=sub.id).one()
    assert s.data_json == "{}" and s.person_id is None
    assert not get_storage().exists(form_file_key(ev.tenant_id, form.id, "abc123.pdf"))
    pay = db.query(FormPayment).filter_by(reference="REF-1").one()
    assert pay.payer_email is None and pay.person_id == "1001" and pay.amount_cents == 10000 and pay.submission_id == sub.id
    # prueba de consentimiento intacta
    assert db.query(AuditConsentLog).filter_by(user_id="1001").count() == 2                              # el consentimiento y la revocación
    # roster: la persona ya no está y la versión cambió (el quiosco la baja de nuevo)
    r = client.get(f"/api/events/{ev.id}/local-roster")
    assert r.headers["etag"] != version_before and [p["n"] for p in r.json()["people"]] == ["Luis Paz"]
    # el reconocimiento ya no la ve
    db.refresh(ev)
    faces.clear_cache()
    assert faces.event_index(db, ev).ids == []


def test_a_suppressed_cedula_is_not_recreated_by_register_bulk_or_forms(client, factory, db):
    ev, _ = _setup(client, factory, db)
    _purge(client, ev, "all")
    r = client.post("/api/register", data={"event_id": ev.id, "id": "1001", "first_name": "Ana", "last_name": "Mora"})
    assert r.status_code == 409 and "supresión" in r.json()["detail"]
    csv = "\n".join(["id,nombres,apellidos", "1001,Ana,Mora", "3003,Eva,Ríos", ""]).encode()
    out = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", csv, "text/csv")})
    assert out.status_code == 200, out.text
    assert db.query(User).filter_by(id="1001").first() is None and db.query(User).filter_by(id="3003").first() is not None
    assert any("supresión" in str(e) for e in out.json().get("errors", []))
    row = db.execute(text("SELECT cedula_hash FROM suppressed_people")).scalar()
    assert row == consent.cedula_hash("1001") and "1001" not in row                                       # solo la huella


def test_purge_scope_all_for_a_person_with_no_biometrics_still_works(client, factory, db):
    ev, _ = _setup(client, factory, db)
    r = _purge(client, ev, "all", uid="2002")
    assert r.status_code == 200 and r.json()["had_biometrics"] is False
    assert db.query(User).filter_by(id="2002").first() is None


def test_gcs_delete_all_versions_lists_every_generation_and_reports_failures():
    from app.storage import GcsStorage

    class Blob:
        def __init__(self, name, gen, fail=False): self.name, self.generation, self.fail, self.deleted = name, gen, fail, False

        def delete(self, generation=None):
            if self.fail:
                raise RuntimeError("403")
            self.deleted = True

    blobs = [Blob("p/acme/known_people/1.jpg", 1), Blob("p/acme/known_people/1.jpg", 2, fail=True), Blob("p/acme/known_people/10.jpg", 3)]

    class Client:
        def list_blobs(self, bucket, prefix, versions):
            assert versions is True
            return [b for b in blobs if b.name.startswith(prefix)]

    g = GcsStorage.__new__(GcsStorage)
    g.client, g.bucket, g.prefix, g._missing = Client(), object(), "p", ()
    g._name = lambda key: f"p/{key}"
    assert g.delete_all_versions("acme/known_people/1.jpg") == 1                                       # una versión no se pudo borrar: se informa
    assert blobs[0].deleted and not blobs[2].deleted                                                   # otra cédula con el mismo prefijo ("10.jpg") no se toca
