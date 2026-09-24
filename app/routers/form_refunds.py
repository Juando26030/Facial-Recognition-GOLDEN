"""Reembolsos de los pagos de Formularios Web (Sprint 5) — solo admin+ (es plata que sale).

Lo que Wompi permite hoy (documentación oficial, 2026-09): **anular** (`POST /transactions/<id>/void`, llave privada) una
transacción de **tarjeta**, total o por un monto (`amount_in_cents`). Para los demás medios (PSE, Nequi, Bancolombia…) existe
la API de reembolsos V2 (`POST /refunds`), que según la documentación es SOLO de sandbox por ahora: aquí se usa siempre en
sandbox y en producción solo con WOMPI_REFUNDS_V2=1. Lo que no tenga camino automático se devuelve por fuera (panel de Wompi o
transferencia) y se **registra como manual**, con nota obligatoria y auditoría.

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

    # Reembolso automático por la API de Wompi: anulación (`void`, solo TARJETA, total o parcial) o reembolso V2 (`api`, otros medios,
    # hoy solo sandbox salvo WOMPI_REFUNDS_V2=1). Lo demás se registra como manual.
    cfg = wompi.config(pay.is_test)
    method = (pay.payment_method or "").upper()
    via = "void" if method == "CARD" else ("v2" if cfg and wompi.refunds_v2_enabled(cfg) else None)
    if via is None:
        raise HTTPException(status_code=400, detail=f"Wompi no tiene reembolso automático en producción para pagos con {method or 'este medio'}. Devuelve el dinero por el panel de Wompi o por transferencia y regístralo como reembolso manual")
    if not cfg or not pay.transaction_id:
        raise HTTPException(status_code=503, detail="Wompi no está configurado para reembolsar este pago")
    if via == "void":
        full = amount_cents == pay.amount_cents and not pay.refunded_cents
        if not full:
            raise HTTPException(status_code=400, detail="Wompi solo anula una tarjeta por el valor original completo (probado en su sandbox). Para devolver solo una parte, hazlo por el panel de Wompi y regístralo como reembolso manual")
        ok, detail = wompi.void_transaction(cfg, pay.transaction_id)
        refund.kind = "void"
    else:
        ok, detail = wompi.create_refund_v2(cfg, pay.transaction_id, amount_cents, reason, pay.reference)
        refund.kind = "api"
    refund.wompi_response = json.dumps(detail, ensure_ascii=False)[:4000] if isinstance(detail, dict) else str(detail)[:4000]
    db.add(refund)
    if not ok:
        refund.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Wompi no pudo hacer el reembolso. {detail}")
    verdict = _verdict(cfg, pay, detail, via, full=(via == "void" and amount_cents == pay.amount_cents and not pay.refunded_cents))
    if verdict == "done":
        warning = complete(db, pay, refund)
        db.commit()
        return {"status": "done", "message": "Reembolso hecho por la API de Wompi", "warning": warning}
    db.commit()
    return {"status": "pending", "message": "Wompi recibió el reembolso y todavía lo está procesando; se marcará como hecho cuando lo confirme (botón «Verificar»)", "warning": None}


def _statuses(detail) -> set:
    """Todos los `status` que aparecen en la respuesta de Wompi (a cualquier profundidad razonable)."""
    out = set()

    def walk(x, depth=0):
        if depth > 4:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "status" and isinstance(v, str):
                    out.add(v.upper())
                else:
                    walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)

    walk(detail)
    return out


def _verdict(cfg: dict, pay: FormPayment, detail, via: str, full: bool) -> str:
    """`done` si Wompi confirmó el reembolso; `pending` si lo aceptó pero no ha terminado (se resuelve con el webhook o «Verificar»)."""
    st = _statuses(detail)
    if via == "void" and full:
        txn = wompi.fetch_transaction(cfg, pay.transaction_id)
        return "done" if "VOIDED" in (st | {str((txn or {}).get("status", "")).upper()}) else "pending"
    if st & {"DECLINED", "ERROR", "FAILED", "CANCELLED"}:
        return "pending"        # no se da por hecho algo que Wompi no aprobó; queda visible en la respuesta para revisar
    return "done" if st & {"APPROVED", "VOIDED", "COMPLETED", "SUCCESS", "SUCCEEDED"} else "pending"


@router.post("/events/{event_id}/forms/{form_id}/payments/{payment_id}/refunds/{refund_id}/{action}")
async def resolve_pending_refund(event_id: int, form_id: int, payment_id: int, refund_id: int, action: str, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Un reembolso `pending` (Wompi lo aceptó pero no confirma): `check` lo vuelve a consultar y lo completa si Wompi ya lo anuló; `discard`
    lo descarta (queda `failed`) para poder intentar de nuevo o registrarlo como manual."""
    if action not in ("check", "discard"):
        raise HTTPException(status_code=404, detail="Acción no válida")
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    pay = db.query(FormPayment).filter(FormPayment.id == payment_id, FormPayment.form_id == form.id).with_for_update().first()
    refund = db.query(FormRefund).filter(FormRefund.id == refund_id, FormRefund.payment_id == payment_id).first() if pay else None
    if not refund or refund.status != "pending":
        raise HTTPException(status_code=404, detail="No hay un reembolso pendiente con ese identificador")
    if action == "discard":
        refund.status = "failed"
        db.commit()
        return {"status": "failed", "message": "Reembolso pendiente descartado", "warning": None}
    cfg = wompi.config(pay.is_test)
    if refund.kind == "api" and cfg:
        wid = ((json.loads(refund.wompi_response or "{}").get("data") or {}).get("id")) if (refund.wompi_response or "").startswith("{") else None
        data = wompi.get_refund_v2(cfg, wid)
        st = str((data or {}).get("status", "")).upper()
        if st in ("APPROVED", "COMPLETED"):
            warning = complete(db, pay, refund)
            refund.wompi_response = json.dumps({"data": data}, ensure_ascii=False)[:4000]
            db.commit()
            return {"status": "done", "message": "Wompi confirmó el reembolso", "warning": warning}
        if st in ("DECLINED", "ERROR", "CANCELLED", "FAILED"):
            refund.status = "failed"
            refund.wompi_response = json.dumps({"data": data}, ensure_ascii=False)[:4000]
            db.commit()
            return {"status": "failed", "message": f"Wompi no aprobó el reembolso ({st}). Puedes intentarlo de nuevo o registrarlo como manual.", "warning": None}
        return {"status": "pending", "message": f"Wompi todavía lo procesa (estado: {st or 'desconocido'}). Verifica de nuevo en unos minutos.", "warning": None}
    txn = wompi.fetch_transaction(cfg, pay.transaction_id) if cfg and pay.transaction_id else None
    if refund.kind == "void" and txn and str(txn.get("status", "")).upper() == "VOIDED":
        warning = complete(db, pay, refund)
        db.commit()
        return {"status": "done", "message": "Wompi confirmó la anulación", "warning": warning}
    return {"status": "pending", "message": f"Wompi todavía no lo confirma (estado de la transacción: {(txn or {}).get('status', 'desconocido')}). Puedes verificar de nuevo en unos minutos o descartarlo.", "warning": None}
