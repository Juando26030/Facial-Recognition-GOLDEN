"""Campo «Pago» de los Formularios Web (Sprint 5, Wompi) — endpoints PÚBLICOS: cotización del monto, confirmación desde
el navegador, estado del pago y el webhook de Wompi (autoritativo).

Regla central: la inscripción NO existe hasta que el pago se APRUEBA. Al enviar el formulario queda «esperando pago»
(`FormSubmission.status = awaiting_payment`, invisible en listas, reportes, analítica y carga a la base). Cuando Wompi
confirma —por webhook o, como respaldo, consultando la transacción— se confirma y sigue el flujo normal (analítica,
invitación usada, carga a la base). Si el pago se rechaza o se abandona, esa persona no queda inscrita. Aprobado es
terminal; un rechazo puede pasar a aprobado (Wompi deja reintentar con la misma referencia)."""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import formlib, formsvc, fx, wompi
from app.database import get_db
from app.models import FormPayment, FormSubmission, WebForm
from app.routers import forms_public as fp

router = APIRouter()
_STATUS = {"APPROVED": "approved", "DECLINED": "declined", "ERROR": "error", "VOIDED": "voided", "PENDING": "pending"}


def apply_result(db: Session, pay_id: int, wompi_status: str, transaction_id: Optional[str] = None, method: Optional[str] = None) -> FormPayment:
    """Aplica el resultado de Wompi a un pago, de forma idempotente y a prueba de carreras (webhook y confirmación del
    navegador pueden llegar a la vez: se bloquea la fila del pago)."""
    pay = db.query(FormPayment).filter(FormPayment.id == pay_id).with_for_update().first()
    new = _STATUS.get(str(wompi_status).upper())
    if pay and new == "voided" and pay.status == "approved":      # anulado (p. ej. desde el panel de Wompi): reembolso completo
        from app.routers.form_refunds import complete_external_void
        complete_external_void(db, pay)
        return pay
    if not pay or not new or pay.status in ("approved", "refunded"):
        db.rollback()
        return pay
    pay.status = new
    pay.transaction_id = transaction_id or pay.transaction_id
    pay.payment_method = method or pay.payment_method
    pay.updated_at = datetime.utcnow()
    if new == "approved":
        pay.confirmed_at = datetime.utcnow()
        sub = db.query(FormSubmission).filter(FormSubmission.id == pay.submission_id).first() if pay.submission_id else None
        if sub and sub.status == formsvc.PENDING:
            formsvc.finalize_submission(db, db.query(WebForm).filter(WebForm.id == pay.form_id).first(), sub)   # confirma y hace commit
            return pay
        # Aprobado pero sin inscripción pendiente (se purgó por abandono antes de que llegara): queda a la vista en la
        # lista de pagos como «sin inscripción» para conciliarlo a mano.
    db.commit()
    return pay


def _pay_from_token(db: Session, form: WebForm, token: Optional[str]) -> FormPayment:
    claims = fp._read(token, form)
    pay = db.query(FormPayment).filter(FormPayment.id == claims.get("pay"), FormPayment.form_id == form.id).first() if claims.get("pay") else None
    if not pay:
        raise HTTPException(status_code=403, detail="No se pudo identificar el pago (el enlace venció). Vuelve a enviar el formulario.")
    return pay


def _result(db: Session, form: WebForm, pay: FormPayment) -> dict:
    out = {"status": pay.status}
    if pay.status == "approved":
        out["thanks"] = formsvc.get_settings(form)["thanks"]
    return out


@router.post("/f/{event_id}/{slug}/quote")
async def quote(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """Monto a pagar según lo que la persona lleva escrito (para mostrar el total en vivo). Solo lee; no guarda nada."""
    form = fp._load(db, event_id, slug)
    fp._access(db, form, data.get("k"))
    fp._limit(db, request, "form_quote", form, 600)
    design = formsvc.get_design(form)
    values = dict(data.get("values") or {})
    field = formlib.payment_field(design, values)
    if not field:
        return {"has_payment": False}
    q = formlib.compute_amount(field["pay"], formlib.priced_values(design, values), formsvc.now_local().date())
    out = {"has_payment": True, "amount": q["amount"], "base": q["base"], "applied": q["applied"], "description": field["pay"].get("description", "")}
    problem = wompi.service_problem()          # solo si Wompi reporta una incidencia: el formulario avisa antes de que la persona intente pagar
    if problem:
        out["service"] = problem
    return out


@router.get("/f/{event_id}/{slug}/rates")
async def rates(event_id: int, slug: str, request: Request, k: Optional[str] = None, db: Session = Depends(get_db)):
    """Tasas de REFERENCIA COP→USD/EUR para que la persona vea el precio en su moneda. El cobro es siempre en COP."""
    form = fp._load(db, event_id, slug)
    fp._access(db, form, k)
    fp._limit(db, request, "form_rates", form, 300)
    return fx.get_rates()


@router.post("/f/{event_id}/{slug}/pay/confirm")
async def confirm(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """El navegador avisa que el widget se cerró (con el id de la transacción, si la hay). No se le cree: el estado real
    se consulta a Wompi por ese id y solo cuenta si la referencia y el monto coinciden con los de este pago."""
    form = fp._load(db, event_id, slug)
    fp._access(db, form, data.get("k"))
    fp._limit(db, request, "form_pay", form, 120)
    pay = _pay_from_token(db, form, data.get("pt"))
    txn_id = str(data.get("transaction_id") or "").strip()
    if pay.status not in ("approved", "refunded") and txn_id:
        cfg = wompi.config(pay.is_test)
        txn = wompi.fetch_transaction(cfg, txn_id) if cfg else None
        if txn and txn.get("reference") == pay.reference and int(txn.get("amount_in_cents") or -1) == pay.amount_cents and txn.get("currency") == pay.currency:
            pay = apply_result(db, pay.id, txn.get("status", ""), txn.get("id"), txn.get("payment_method_type"))
    return _result(db, form, pay)


@router.get("/f/{event_id}/{slug}/pay/status")
async def pay_status(event_id: int, slug: str, request: Request, pt: Optional[str] = None, k: Optional[str] = None, db: Session = Depends(get_db)):
    """Para esperar la confirmación (p. ej. PSE tarda): el navegador consulta hasta que sea aprobado o rechazado."""
    form = fp._load(db, event_id, slug)
    fp._access(db, form, k)
    fp._limit(db, request, "form_pay_status", form, 600)
    return _result(db, form, _pay_from_token(db, form, pt))


@router.post("/webhooks/wompi")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Eventos de Wompi (`transaction.updated`). Se acepta solo con checksum válido (SHA-256 con el secreto de eventos);
    sin secreto configurado se rechaza. Responde 200 aun si la referencia no es nuestra, para que Wompi no reintente."""
    try:
        event = json.loads((await request.body()) or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Cuerpo inválido")
    ok = wompi.verify_event(event, request.headers.get("X-Event-Checksum"))
    if ok is None:
        raise HTTPException(status_code=503, detail="Los eventos de Wompi no están configurados")
    if not ok:
        raise HTTPException(status_code=401, detail="Firma inválida")
    if event.get("event") != "transaction.updated":
        return {"ok": True, "ignored": "evento no manejado"}
    txn = (event.get("data") or {}).get("transaction") or {}
    pay = db.query(FormPayment).filter(FormPayment.reference == str(txn.get("reference") or "")).first()
    if not pay:
        return {"ok": True, "ignored": "referencia desconocida"}
    env_is_test = str(event.get("environment") or "").lower() == "test"
    if event.get("environment") and env_is_test != pay.is_test:
        return {"ok": True, "ignored": "ambiente distinto al del pago"}       # un evento de pruebas no puede aprobar un pago real
    if int(txn.get("amount_in_cents") or -1) != pay.amount_cents or txn.get("currency") != pay.currency:
        return {"ok": True, "ignored": "monto distinto al esperado"}
    apply_result(db, pay.id, txn.get("status", ""), txn.get("id"), txn.get("payment_method_type"))
    return {"ok": True}
