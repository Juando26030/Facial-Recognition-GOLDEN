"""Reembolsos de los pagos de Formularios Web (Sprint 5) — solo admin+ (es plata que sale).

Lo que Wompi permite hoy (documentación oficial, 2026-09): **anular** (`POST /transactions/<id>/void`, llave privada) una
transacción de **tarjeta** por el valor completo. Todo lo demás —reembolso parcial o de PSE, Nequi, Bancolombia…— no tiene
API de producción: se devuelve por fuera (panel de Wompi o transferencia) y aquí se **registra como manual**, con nota
obligatoria y auditoría. (Wompi tiene una API de reembolsos V2 con parciales, pero por ahora solo en sandbox.)

Cuando un reembolso se completa: la suma reembolsada sube; si cubre todo el pago, el pago pasa a `refunded`; y, si se pidió
(por defecto en un reembolso completo), la inscripción queda cancelada (`status='refunded'`: sale de listas, reportes y
analítica y libera el cupo; los datos se conservan). Un pago anulado desde el panel de Wompi llega por webhook (VOIDED) y se
registra igual, para que la plataforma nunca quede desfasada."""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import wompi
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import FormPayment, FormRefund, FormSubmission, StaffUser
from app.routers.forms import _get_form

router = APIRouter()
ADMIN = require_role("admin")


def complete(db: Session, pay: FormPayment, refund: FormRefund) -> Optional[str]:
    """Da por hecho un reembolso: actualiza el pago y, si corresponde, cancela la inscripción. Devuelve un aviso o None."""
    refund.status, refund.done_at = "done", datetime.utcnow()
    pay.refunded_cents = (pay.refunded_cents or 0) + refund.amount_cents
    if pay.refunded_cents >= pay.amount_cents:
        pay.status = "refunded"
    warning = None
    if refund.cancel_registration and pay.submission_id:
        sub = db.query(FormSubmission).filter(FormSubmission.id == pay.submission_id).first()
        if sub and sub.status == "confirmed":
            sub.status = "refunded"
            if sub.fed:
                warning = "La persona ya estaba cargada a la base del evento: revísala en Registro si hay que sacarla de allí."
    return warning


def complete_external_void(db: Session, pay: FormPayment) -> None:
    """Wompi avisó (webhook VOIDED) que se anuló una transacción aprobada: si nosotros la habíamos pedido, se confirma ese
    reembolso; si se anuló desde el panel de Wompi, se registra uno nuevo por el saldo. Hace commit."""
    refund = db.query(FormRefund).filter(FormRefund.payment_id == pay.id, FormRefund.kind == "void", FormRefund.status == "pending").first()
    if not refund:
        refund = FormRefund(payment_id=pay.id, amount_cents=pay.amount_cents - (pay.refunded_cents or 0), kind="void", status="pending",
                            reason="Anulada desde el panel de Wompi (registrada por el webhook)", cancel_registration=True)
        db.add(refund)
        db.flush()
    complete(db, pay, refund)
    db.commit()


def _row(r: FormRefund) -> dict:
    return {"id": r.id, "amount": r.amount_cents // 100, "kind": r.kind, "status": r.status, "reason": r.reason, "note": r.note or "", "cancel_registration": r.cancel_registration,
            "by": r.created_by_id, "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")}


@router.post("/events/{event_id}/forms/{form_id}/payments/{payment_id}/refund")
async def refund_payment(event_id: int, form_id: int, payment_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Body: `reason` (obligatorio), `amount` (COP; por defecto el saldo), `manual` (true = ya se devolvió por fuera; exige `note`),
    `cancel_registration` (por defecto: sí si el reembolso deja el pago en cero)."""
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    pay = db.query(FormPayment).filter(FormPayment.id == payment_id, FormPayment.form_id == form.id).with_for_update().first()
    if not pay:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if pay.status != "approved":
        raise HTTPException(status_code=400, detail="Solo se pueden reembolsar pagos aprobados y con saldo por devolver")
    reason = str(data.get("reason") or "").strip()[:500]
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="Escribe el motivo del reembolso")
    if db.query(FormRefund).filter(FormRefund.payment_id == pay.id, FormRefund.status == "pending").first():
        raise HTTPException(status_code=409, detail="Ya hay una anulación de este pago en proceso: espera a que Wompi la confirme")

    remaining = pay.amount_cents - (pay.refunded_cents or 0)
    try:
        amount_cents = int(round(float(data.get("amount") if data.get("amount") not in (None, "") else remaining / 100))) * 100
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El monto debe ser un número en pesos")
    if not 0 < amount_cents <= remaining:
        raise HTTPException(status_code=400, detail=f"El monto debe estar entre $1 y ${remaining // 100:,} COP (lo que queda por devolver)".replace(",", "."))
    manual = bool(data.get("manual"))
    cancel = bool(data["cancel_registration"]) if "cancel_registration" in data else amount_cents == remaining
    refund = FormRefund(payment_id=pay.id, amount_cents=amount_cents, kind="manual" if manual else "void", status="pending", reason=reason, cancel_registration=cancel, created_by_id=staff.id)

    if manual:
        note = str(data.get("note") or "").strip()[:500]
        if len(note) < 3:
            raise HTTPException(status_code=400, detail="Un reembolso manual necesita una nota: cómo y dónde se devolvió el dinero (comprobante, banco…)")
        refund.note = note
        db.add(refund)
        warning = complete(db, pay, refund)
        db.commit()
        return {"status": "done", "message": "Reembolso manual registrado", "warning": warning}

    # Anulación automática: solo tarjeta y por el valor completo (lo único que la API de Wompi permite hoy).
    if (pay.payment_method or "").upper() != "CARD":
        raise HTTPException(status_code=400, detail="La anulación automática solo aplica a pagos con tarjeta. Devuelve el dinero por el panel de Wompi o por transferencia y regístralo como reembolso manual")
    if amount_cents != pay.amount_cents or pay.refunded_cents:
        raise HTTPException(status_code=400, detail="La anulación automática devuelve el valor completo. Para un reembolso parcial hazlo por Wompi y regístralo como manual")
    cfg = wompi.config(pay.is_test)
    if not cfg or not pay.transaction_id:
        raise HTTPException(status_code=503, detail="Wompi no está configurado para anular este pago")
    ok, detail = wompi.void_transaction(cfg, pay.transaction_id)
    refund.wompi_response = json.dumps(detail, ensure_ascii=False)[:4000] if isinstance(detail, dict) else str(detail)[:4000]
    db.add(refund)
    if not ok:
        refund.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Wompi no pudo anular el pago. {detail}")
    txn = wompi.fetch_transaction(cfg, pay.transaction_id)
    body = detail.get("data") if isinstance(detail, dict) else {}
    statuses = {str((txn or {}).get("status", "")).upper(), str(((body or {}).get("transaction") or body or {}).get("status", "")).upper()}
    if "VOIDED" in statuses:
        warning = complete(db, pay, refund)
        db.commit()
        return {"status": "done", "message": "Pago anulado: Wompi devolverá el dinero a la tarjeta", "warning": warning}
    db.commit()
    return {"status": "pending", "message": "Wompi recibió la anulación y todavía la está procesando; el pago se marcará como reembolsado cuando la confirme", "warning": None}
