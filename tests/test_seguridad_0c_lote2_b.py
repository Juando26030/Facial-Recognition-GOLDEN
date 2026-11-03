"""Fase 0C, lote 2, grupo B: C5 (pago aprobado sin inscripción), E2/E3 (cédulas en la cola y errores sin enmascarar), E4 (directorio para `cliente`),
E8 (cuentas de servicio por servicio), A2/A6/A7 (asignación masiva y pertenencia al evento) y E-N1 (revocación por evento)."""
from datetime import timedelta

from app import formsvc, reconcile
from app.models import FormPayment, FormSubmission, WebForm
from app.timeutil import utcnow
from tests.conftest import login
from tests.test_form_payments import _event, _event_for, _staff, _submit, _values, _with_payment, keys, _no_dns  # noqa: F401,F811


# ------------------------------------------------------------------ C5: pago aprobado sin inscripción
def _pending(client, factory, db, keys):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    ref = _submit(client, ev, form, _values(), sid="s1").json()["payment"]["reference"]
    return ev, form, ref


def _age(db, hours):
    """Envejece la inscripción en espera y su pago (como si la persona hubiera tardado `hours` horas)."""
    past = utcnow() - timedelta(hours=hours)
    db.query(FormSubmission).update({"created_at": past})
    db.query(FormPayment).update({"created_at": past})
    db.commit()


def test_c5_stale_submission_with_pending_payment_is_not_purged_and_late_approval_confirms(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    _age(db, 30)                                           # pasó la purga de 24 h, pero el pago sigue pendiente dentro de la ventana de conciliación
    other = _values(cedula="2002", correo="luis@example.com", nombres="Luis")
    assert _submit(client, ev, form, other, sid="s2").status_code == 200      # la purga perezosa corre y NO debe llevarse la inscripción que aún puede pagarse
    db.expire_all()
    assert db.query(FormSubmission).filter_by(person_id="1001").count() == 1
    client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED", txn="TX-LATE"))
    db.expire_all()
    pay = db.query(FormPayment).filter_by(reference=ref).one()
    assert pay.status == "approved" and pay.submission_id
    assert db.get(FormSubmission, pay.submission_id).status == "confirmed"


def test_c5_old_pending_payment_outside_the_window_still_lets_the_purge_run(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    _age(db, 24 * 4)                                       # más de 3 días: ya se dio por abandonado
    assert _submit(client, ev, form, _values(cedula="2002", correo="luis@example.com", nombres="Luis"), sid="s2").status_code == 200
    db.expire_all()
    assert db.query(FormSubmission).filter_by(person_id="1001").count() == 0


def test_c5_discard_never_deletes_a_submission_with_an_approved_payment(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    sub = db.query(FormSubmission).one()
    db.query(FormPayment).update({"status": "approved"})        # estado inconsistente: aprobado pero la inscripción quedó en espera
    db.commit()
    assert formsvc.discard_submission(db, db.get(WebForm, sub.form_id), sub, force=True) is False
    assert db.query(FormSubmission).count() == 1


def test_c5_heal_completes_an_approved_payment_whose_submission_is_still_waiting(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    db.query(FormPayment).update({"status": "approved", "transaction_id": "TX-1"})
    db.commit()
    assert reconcile.heal_approved_pending(db) == 1
    db.expire_all()
    assert db.query(FormSubmission).one().status == "confirmed"
    assert reconcile.heal_approved_pending(db) == 0         # idempotente


def test_c5_repeated_webhook_does_not_duplicate(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    event = _event_for("prod", ref, 15000000, "APPROVED", txn="TX-9")
    assert client.post("/webhooks/wompi", json=event).status_code == 200
    assert client.post("/webhooks/wompi", json=event).status_code == 200
    db.expire_all()
    assert db.query(FormSubmission).filter_by(status="confirmed").count() == 1


def test_c5_approved_without_submission_is_flagged_for_review_never_lost(client, factory, db, keys):
    ev, form, ref = _pending(client, factory, db, keys)
    sub = db.query(FormSubmission).one()
    db.query(FormPayment).update({"submission_id": None})      # la inscripción se descartó antes de la aprobación
    db.delete(sub)
    db.commit()
    assert client.post("/webhooks/wompi", json=_event_for("prod", ref, 15000000, "APPROVED", txn="TX-11")).status_code == 200
    db.expire_all()
    assert db.query(FormPayment).one().status == "approved"      # el cobro queda registrado
    _staff(client)
    row = client.get(f"/api/events/{ev.id}/forms/{form['id']}/payments").json()["rows"][0]
    assert row["orphan"] and "sin inscripción" in row["review"]


# ------------------------------------------------------------------ E2/E3: la cola no guarda cédulas ni errores sin enmascarar
def test_e2_person_ref_is_opaque_and_reversible_and_legacy_payload_still_works():
    from app import jobs
    ref = jobs.person_ref("1016100329")
    assert "1016100329" not in ref and ref.startswith("jr1:")
    assert jobs.payload_user_id({"uref": ref}) == "1016100329"
    assert jobs.payload_user_id({"user_id": "555"}) == "555"          # trabajos encolados antes del cambio
    assert "user_id" not in jobs.scrub_payload('{"tenant_id": "acme", "user_id": "1", "uref": "x", "event_id": 3}')


def test_e2_enqueued_payloads_carry_no_cedula(db):
    from app import consent_receipt, jobs
    from app.models import Job
    consent_receipt.enqueue(db, "entry-1", "acme", 1, "1016100329", "door")
    jobs.enqueue(db, "face_enroll", {"tenant_id": "acme", "uref": jobs.person_ref("1016100329"), "event_id": 1})
    db.commit()
    for j in db.query(Job).all():
        assert "1016100329" not in j.payload_json


def test_e3_failed_job_error_is_masked_and_done_job_loses_the_person(db):
    from app import jobs
    from app.models import Job
    ok = Job(kind="x", payload_json='{"tenant_id": "acme", "user_id": "1016100329", "event_id": 1}', status="running", attempts=1, max_attempts=3, run_at=utcnow(), created_at=utcnow())
    bad = Job(kind="x", payload_json='{"tenant_id": "acme", "uref": "jr1:zzz"}', status="running", attempts=3, max_attempts=3, run_at=utcnow(), created_at=utcnow())
    db.add_all([ok, bad])
    db.commit()
    ok_id, bad_id = ok.id, bad.id
    jobs._finish(ok_id, None, 1, 3)
    jobs._finish(bad_id, "ValueError: la cédula 1016100329 de ana@example.com no existe", 3, 3)
    db.expire_all()
    assert db.get(Job, ok_id).status == "done" and "user_id" not in db.get(Job, ok_id).payload_json
    failed = db.get(Job, bad_id)
    assert failed.status == "failed" and "1016100329" not in failed.last_error and "ana@example.com" not in failed.last_error
    assert "uref" in failed.payload_json                                   # el fallido conserva su referencia sellada para poder reintentarse


def test_e2_total_suppression_removes_queue_rows_and_web_acceptances(db, factory):
    import json

    from app import jobs, privacy
    from app.models import Job, WebAcceptance
    ev = factory.event()
    factory.person(ev, "1016100329")
    other = factory.person(ev, "2002", first_name="Luis")
    db.add(WebAcceptance(tenant_id=ev.tenant_id, user_id="1016100329", event_id=ev.id))
    db.add(WebAcceptance(tenant_id=ev.tenant_id, user_id=other.id, event_id=ev.id))
    jobs.enqueue(db, "face_enroll", {"tenant_id": ev.tenant_id, "uref": jobs.person_ref("1016100329"), "event_id": ev.id})
    jobs.enqueue(db, "face_enroll", {"tenant_id": ev.tenant_id, "user_id": "1016100329", "event_id": ev.id})          # trabajo viejo, en claro
    jobs.enqueue(db, "face_enroll", {"tenant_id": ev.tenant_id, "uref": jobs.person_ref("2002"), "event_id": ev.id})
    db.commit()
    res = privacy.erase_person(db, ev, "1016100329", "all")
    assert res["jobs_deleted"] == 2
    db.expire_all()
    assert [w.user_id for w in db.query(WebAcceptance).all()] == ["2002"]
    left = db.query(Job).all()
    assert len(left) == 1 and jobs.payload_user_id(json.loads(left[0].payload_json)) == "2002"


# ------------------------------------------------------------------ E4: el directorio para el rol «cliente» no entrega datos personales
def _people_with_contact(db, factory, ev):
    from datetime import date
    for uid, name in (("1016100329", "Ana"), ("1016100429", "Luis")):       # mismas últimas cifras salvo una: la huella debe distinguirlas
        u = factory.person(ev, uid, first_name=name)
        u.phone, u.email, u.birth_date, u.entity = "3001234567", f"{name.lower()}@example.com", date(1990, 1, 2), "ACME SAS"
        u.set_extras({"opcional_1": "dato"})
    db.commit()


def test_e4_cliente_gets_masked_directory_and_staff_gets_full(client, factory, db):
    ev = factory.event(facial_enabled=True)
    _people_with_contact(db, factory, ev)
    cli = factory.staff("cliente", "cli1")
    factory.staff("coordinador", "coord9")
    factory.authorize(ev, cli)
    assert login(client, "cli1").status_code == 302
    rows = client.get(f"/api/users?event_id={ev.id}").json()
    blob = str(rows)
    assert len(rows) == 2 and len({r["id"] for r in rows}) == 2
    for secret in ("1016100329", "1016100429", "3001234567", "example.com", "1990-01-02"):
        assert secret not in blob
    assert all(r["phone"] == "" and r["email"] == "" and r["birth_date"] == "" and r["extra_fields"] == {} for r in rows)
    assert {r["first_name"] for r in rows} == {"Ana", "Luis"} and all(r["entity"] == "ACME SAS" for r in rows)
    changes = client.get(f"/api/users/changes?event_id={ev.id}").json()
    assert "1016100329" not in str(changes) and "example.com" not in str(changes)
    client.post("/logout")
    login(client, "coord9")
    full = client.get(f"/api/users?event_id={ev.id}").json()
    assert {r["id"] for r in full} == {"1016100329", "1016100429"} and all(r["phone"] == "3001234567" and r["email"] for r in full)


def test_e4_masked_and_full_directory_do_not_share_an_etag(client, factory, db):
    ev = factory.event()
    _people_with_contact(db, factory, ev)
    cli = factory.staff("cliente", "cli1")
    factory.staff("coordinador", "coord9")
    factory.authorize(ev, cli)
    login(client, "coord9")
    full_tag = client.get(f"/api/users?event_id={ev.id}").headers["etag"]
    client.post("/logout")
    login(client, "cli1")
    r = client.get(f"/api/users?event_id={ev.id}", headers={"If-None-Match": full_tag})
    assert r.status_code == 200 and r.headers["etag"] != full_tag
