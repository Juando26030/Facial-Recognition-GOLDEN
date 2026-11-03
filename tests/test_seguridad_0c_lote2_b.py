"""Fase 0C, lote 2, grupo B: C5 (pago aprobado sin inscripción), E2/E3 (cédulas en la cola y errores sin enmascarar), E4 (directorio para `cliente`),
E8 (cuentas de servicio por servicio), A2/A6/A7 (asignación masiva y pertenencia al evento) y E-N1 (revocación por evento)."""
from datetime import timedelta

from app import formsvc, reconcile
from app.models import FormPayment, FormSubmission, WebForm
from app.timeutil import utcnow
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
