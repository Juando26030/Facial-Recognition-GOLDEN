"""Conciliación de pagos con Wompi (docs/13 §8.10): además de los webhooks, se consulta a Wompi por REFERENCIA los pagos que llevan un rato «pendientes»,
por si un webhook se perdió durante una caída. Es idempotente: usa la misma `apply_result` que el webhook y la confirmación del navegador.

Se corre cada pocos minutos (cron: `scripts/reconcile_payments.py`, o el trabajo `payments_reconcile` de la cola). Solo mira pagos pendientes de entre
`MIN_AGE` y `MAX_AGE`: los más nuevos aún los está resolviendo el navegador/el webhook; los más viejos ya se dieron por abandonados."""
import logging
from datetime import datetime, timedelta
from app.timeutil import utcnow

from sqlalchemy.orm import Session

from app import jobs, ops, wompi
from app.database import SessionLocal
from app.models import FormPayment

log = logging.getLogger("golden.reconcile")
MIN_AGE = timedelta(minutes=3)
MAX_AGE = timedelta(days=3)


def reconcile_pending(db: Session, limit: int = 200) -> dict:
    from app.routers.form_payments import apply_result
    now = utcnow()
    pending = (db.query(FormPayment).filter(FormPayment.status == "pending", FormPayment.created_at < now - MIN_AGE, FormPayment.created_at > now - MAX_AGE)
               .order_by(FormPayment.created_at).limit(limit).all())
    summary = {"checked": len(pending), "updated": 0, "not_found": 0, "unavailable": 0, "mismatch": 0}
    for pay in pending:
        cfg = wompi.config(pay.is_test)
        if not cfg:
            summary["unavailable"] += 1
            continue
        txn = wompi.fetch_by_reference(cfg, pay.reference)
        if not txn:
            summary["not_found"] += 1               # la persona nunca llegó a pagar (o Wompi no respondió): se reintenta en la próxima corrida
            continue
        if int(txn.get("amount_in_cents") or -1) != pay.amount_cents or txn.get("currency") != pay.currency:
            summary["mismatch"] += 1
            log.warning("el pago %s no coincide con la transacción de Wompi (monto o moneda)", pay.id)
            continue
        before = pay.status
        updated = apply_result(db, pay.id, txn.get("status", ""), txn.get("id"), txn.get("payment_method_type"))
        if updated and updated.status != before:
            summary["updated"] += 1
    summary["healed"] = heal_approved_pending(db)
    if summary["updated"] or summary["mismatch"] or summary["healed"]:
        ops.record_system_event("payments_reconciled", None, str(summary))
    log.info("conciliación de pagos: %s", summary)
    return summary


def heal_approved_pending(db: Session, limit: int = 100) -> int:
    """C5: pagos APROBADOS cuya inscripción sigue «esperando pago» (p. ej. se cayó la confirmación a mitad): se completan con la misma `apply_result`. Idempotente."""
    from app.models import FormSubmission
    from app.routers.form_payments import apply_result
    rows = (db.query(FormPayment.id, FormPayment.transaction_id).join(FormSubmission, FormSubmission.id == FormPayment.submission_id)
            .filter(FormPayment.status == "approved", FormSubmission.status == "awaiting_payment").limit(limit).all())
    for pid, txn in rows:
        apply_result(db, pid, "APPROVED", txn)
    return len(rows)


@jobs.handler("payments_reconcile")
def _reconcile_job(payload: dict) -> None:
    db = SessionLocal()
    try:
        reconcile_pending(db)
    finally:
        db.close()
