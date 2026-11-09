"""Campo «Pago» de los Formularios Web (Sprint 5, Wompi) — endpoints PÚBLICOS: cotización del monto, confirmación desde
el navegador, estado del pago y el webhook de Wompi (autoritativo).

Regla central: la inscripción NO existe hasta que el pago se APRUEBA. Al enviar el formulario queda «esperando pago»
(`FormSubmission.status = awaiting_payment`, invisible en listas, reportes, analítica y carga a la base). Cuando Wompi
confirma —por webhook o, como respaldo, consultando la transacción— se confirma y sigue el flujo normal (analítica,
invitación usada, carga a la base). Si el pago se rechaza o se abandona, esa persona no queda inscrita. Aprobado es
terminal; un rechazo puede pasar a aprobado (Wompi deja reintentar con la misma referencia)."""
import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from app.timeutil import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import formlib, formsvc, fx, ops, security, timing, wompi, payment_accounts
from app.database import SessionLocal, get_db
from app.models import FormPayment, FormRefund, FormSubmission, WebForm
from app.routers import forms_public as fp

router = APIRouter()
log = logging.getLogger("golden.form_payments")
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
    if pay and pay.status == "approved" and new == "approved":
        # C5: webhook repetido o conciliación sobre un pago ya aprobado cuya inscripción quedó en espera: se completa (idempotente).
        sub = db.query(FormSubmission).filter(FormSubmission.id == pay.submission_id).with_for_update().first() if pay.submission_id else None
        if sub and sub.status == formsvc.PENDING:
            return _admit_or_flag(db, pay, sub)
    if pay and new == "voided" and pay.status == "refunded":
        # D16: el VOIDED de una anulación que nosotros mismos pedimos llega con el pago ya «refunded» (normal, sin alerta). Si en cambio el pago se devolvió A MANO y ninguna
        # anulación por la API quedó hecha (p. ej. se descartó un void pendiente y luego se registró un reembolso manual), Wompi devolvió el dinero también: doble devolución.
        done = {k for (k,) in db.query(FormRefund.kind).filter(FormRefund.payment_id == pay.id, FormRefund.status == "done").all()}
        if "manual" in done and not done & {"void", "api"}:
            ops.record_system_event("void_after_refund", str(pay.reference)[:80], "Wompi anuló una transacción que ya se devolvió a mano: doble devolución, revisar en la lista de pagos")
        db.rollback()
        return pay
    if not pay or not new or pay.status in ("approved", "refunded"):
        db.rollback()
        return pay
    pay.status = new
    if new in ("declined", "error", "voided") and pay.submission_id:
        # H1 (ronda de ataque 2): un resultado negativo libera el cupo; la inscripción pendiente deja de contar como «apartado vigente» para que una aprobación tardía de
        # la MISMA referencia pase por el conteo completo de `admit_on_approval` (si otra persona ya tomó el cupo, queda en reembolso). Mismo orden de candados: pago -> inscripción.
        held = db.query(FormSubmission).filter(FormSubmission.id == pay.submission_id, FormSubmission.status == formsvc.PENDING, FormSubmission.is_test == False).with_for_update().first()  # noqa: E712
        if held:
            held.created_at = utcnow() - formsvc.PENDING_HOLD - timedelta(minutes=1)
    formsvc.invalidate_held()          # un pago rechazado/expirado libera su cupo: la vía rápida del «lleno» no debe seguir rechazando
    pay.transaction_id = transaction_id or pay.transaction_id
    pay.payment_method = method or pay.payment_method
    pay.updated_at = utcnow()
    if new == "approved":
        pay.confirmed_at = utcnow()
        sub = db.query(FormSubmission).filter(FormSubmission.id == pay.submission_id).first() if pay.submission_id else None
        if sub and sub.status == formsvc.PENDING:
            return _admit_or_flag(db, pay, sub)          # confirma y hace commit (o la deja «reembolso pendiente»)
        # Aprobado pero sin inscripción pendiente (la persona reintentó y se descartó el intento, o se borró): nunca se pierde. Queda a la vista en la
        # lista de pagos como «sin inscripción» (con el motivo de la revisión) y se anota en «Estado del sistema» para conciliarlo a mano.
        log.warning("pago %s aprobado sin inscripción pendiente: queda marcado para revisión", pay.id)
        ops.record_system_event("payment_without_submission", str(pay.reference)[:80], "aprobado sin inscripción: revisar en la lista de pagos")
    db.commit()
    return pay


def _admit_or_flag(db: Session, pay: FormPayment, sub: FormSubmission) -> FormPayment:
    """R2: un pago aprobado confirma su inscripción solo si `formsvc.admit_on_approval` (bajo el candado del formulario) no encuentra un motivo; si lo hay, la inscripción pasa a
    `refund_due` (no cuenta como inscrita ni aparta cupo), el pago queda aprobado y a la vista para reembolsar, y se anota en «Estado del sistema». Nunca se pierde un cobro."""
    form = db.query(WebForm).filter(WebForm.id == pay.form_id).first()
    why = formsvc.admit_on_approval(db, form, sub)
    if why:
        sub.status = formsvc.REFUND_DUE
        formsvc.invalidate_held()
        log.warning("pago %s aprobado que no se puede admitir (%s): queda para reembolso", pay.id, why)
        db.commit()
        ops.record_system_event("payment_refund_due", str(pay.reference)[:80], f"aprobado sin poder admitir la inscripción ({why}): reembolsar")
        return pay
    formsvc.finalize_submission(db, form, sub)           # confirma y hace commit (suelta el candado del formulario)
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


def _quote_form_context(event_id: int, slug: str, k: Optional[str]) -> dict:
    """Lo único que el cálculo del monto necesita del formulario, SIN objetos de la sesión (se guarda en la caché compartida unos segundos): su id y su diseño. 404 si no está
    disponible (misma regla de acceso que antes; no cuenta el cupo: el precio no depende de que el formulario esté lleno)."""
    db = SessionLocal()
    try:
        form = fp._load(db, event_id, slug)
        fp._access(db, form, k, check_full=False)
        return {"id": form.id, "design": formsvc.get_design(form)}
    finally:
        db.close()


def _build_quote(design: dict, values: dict, field: dict, ctx: dict, code_row, problem: Optional[str], code) -> dict:
    q = formlib.compute_amount(field["pay"], formlib.priced_values(design, values), formsvc.now_local().date(), 1 + formlib.companions_count(design, values), ctx)
    if code_row and not any(a.get("id") == code_row.discount_id for a in q["applied"]):
        problem = "not_applicable"
    out = {"has_payment": True, "amount": q["amount"], "subtotal": q["subtotal"], "tax": q["tax"], "unit": q["unit"], "people": q["people"], "base": q["base"], "applied": q["applied"], "description": field["pay"].get("description", "")}
    if formsvc.normalize_code(code):
        out["code"] = {"status": problem or "ok", "message": formsvc.CODE_MESSAGES.get(problem, "Código aplicado")}
    service = wompi.service_problem()          # solo si Wompi reporta una incidencia: el formulario avisa antes de que la persona intente pagar (no espera a la red: ver wompi.service_status)
    if service:
        out["service"] = service
    return out


def _quote_with_code(form_id: int, design: dict, values: dict, field: dict, link, code, ip: Optional[str] = None) -> dict:
    """Con un código de descuento el monto depende de la base (existe, no está agotado): único camino del `quote` que la consulta."""
    db = SessionLocal()
    try:
        ctx, code_row, problem = formsvc.price_context(db, SimpleNamespace(id=form_id), field["pay"], link, code)
        out = _build_quote(design, values, field, ctx, code_row, problem, code)
        if (out.get("code") or {}).get("status") != "ok":
            fp.code_attempt_failed(form_id, ip)          # R4: inválido, agotado o que no aplica: cuenta como intento fallido
        return out
    finally:
        db.close()


@router.post("/f/{event_id}/{slug}/quote")
async def quote(event_id: int, slug: str, data: dict, request: Request):
    """Monto a pagar según lo que la persona lleva escrito (para mostrar el total en vivo). Solo lee; no guarda nada.
    Se llama al dibujar el formulario y tras cada cambio (con 10.000 personas, decenas de miles de veces): el contexto del formulario (id y diseño) sale de la caché compartida
    (`FORM_PUBLIC_CACHE_SECONDS`, refresco en segundo plano: `fp._cached_async`) y el cálculo es puro, así que el caso común —sin código de descuento ni clave de pruebas— no toca la
    base ni usa un hilo. Con código se consulta la base (existencia y usos); con clave de pruebas (`k`) nunca se usa la caché. El precio que se COBRA siempre lo recalcula el envío."""
    k = data.get("k")
    if k:
        ctx = await timing.run(_quote_form_context, event_id, slug, k)
    else:
        ctx = await fp._cached_async(formsvc.public_cache, ("quote", event_id, slug), lambda: _quote_form_context(event_id, slug, None))
    fp._limit(None, request, "form_quote", SimpleNamespace(id=ctx["id"]), 600)
    design = ctx["design"]
    values = dict(data.get("values") or {})
    field = formlib.payment_field(design, values)
    if not field:
        return {"has_payment": False}
    if formsvc.normalize_code(data.get("code")):
        ip = security.limit_ip(request)
        fp.code_attempts_check(ctx["id"], ip)          # R4
        return await timing.run(_quote_with_code, ctx["id"], design, values, field, data.get("d"), data.get("code"), ip)
    price_ctx, _, _ = formsvc.price_context(None, None, field["pay"], data.get("d"), None)         # sin código no usa la base
    return _build_quote(design, values, field, price_ctx, None, None, None)


@router.get("/f/{event_id}/{slug}/rates")
def rates(event_id: int, slug: str, request: Request, k: Optional[str] = None, db: Session = Depends(get_db)):
    """Tasas de REFERENCIA COP→USD/EUR para que la persona vea el precio en su moneda. El cobro es siempre en COP."""
    form = fp._load(db, event_id, slug)
    fp._access(db, form, k)
    fp._limit(db, request, "form_rates", form, 300)
    return fx.get_rates()


@router.post("/f/{event_id}/{slug}/pay/confirm")
def confirm(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """El navegador avisa que el widget se cerró (con el id de la transacción, si la hay). No se le cree: el estado real
    se consulta a Wompi por ese id y solo cuenta si la referencia y el monto coinciden con los de este pago."""
    form = fp._load(db, event_id, slug, allow_archived=True)
    fp._access(db, form, data.get("k"))
    fp._limit(db, request, "form_pay", form, 120)
    pay = _pay_from_token(db, form, data.get("pt"))
    txn_id = str(data.get("transaction_id") or "").strip()
    if pay.status not in ("approved", "refunded") and txn_id:
        cfg = payment_accounts.cfg_for_payment(db, pay)
        txn = wompi.fetch_own_transaction(cfg, txn_id, pay.reference) if cfg else None          # F5-9 C1: solo una transacción del comercio con el que se cobró
        if txn and txn.get("reference") == pay.reference and int(txn.get("amount_in_cents") or -1) == pay.amount_cents and txn.get("currency") == pay.currency:
            pay = apply_result(db, pay.id, txn.get("status", ""), txn.get("id"), txn.get("payment_method_type"))
    return _result(db, form, pay)


@router.get("/f/{event_id}/{slug}/pay/status")
def pay_status(event_id: int, slug: str, request: Request, pt: Optional[str] = None, k: Optional[str] = None, db: Session = Depends(get_db)):
    """Para esperar la confirmación (p. ej. PSE tarda): el navegador consulta hasta que sea aprobado o rechazado."""
    form = fp._load(db, event_id, slug, allow_archived=True)
    fp._access(db, form, k)
    fp._limit(db, request, "form_pay_status", form, 600)
    return _result(db, form, _pay_from_token(db, form, pt))


@router.post("/webhooks/wompi/{ref}")
async def webhook_account(ref: str, request: Request, db: Session = Depends(get_db)):
    """Eventos de Wompi de una CUENTA DE COBRO de un tercero (Fase 8): cada cuenta tiene su propia URL y se verifica con SU secreto de eventos."""
    try:
        event = json.loads((await request.body()) or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Cuerpo inválido")
    return await run_in_threadpool(_process_webhook, db, event, request.headers.get("X-Event-Checksum"), ref)


@router.post("/webhooks/wompi")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Eventos de Wompi (`transaction.updated`). Lee el cuerpo (lo único asíncrono) y procesa en un hilo: el bucle de eventos nunca espera a la base."""
    try:
        event = json.loads((await request.body()) or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Cuerpo inválido")
    return await run_in_threadpool(_process_webhook, db, event, request.headers.get("X-Event-Checksum"))


def _process_webhook(db: Session, event: dict, checksum: Optional[str], ref: Optional[str] = None) -> dict:
    """Se acepta solo con checksum válido (SHA-256 con el secreto de eventos); sin secreto configurado se rechaza. Responde 200 aun si la referencia no
    es nuestra, para que Wompi no reintente. Cada evento válido queda anotado para «Estado del sistema» (último webhook recibido)."""
    account = None
    if ref:
        account = payment_accounts.by_ref(db, ref)
        cfg = payment_accounts.cfg_of(account, for_new_charges=False)          # F5-9 C2: una cuenta DESACTIVADA sigue recibiendo los eventos de lo que ya cobró
        if cfg is None:
            raise HTTPException(status_code=404, detail="Cuenta de cobro desconocida")
        env = wompi.verify_event_cfg(event, checksum, cfg)
    else:
        env = wompi.verify_event_env(event, checksum)          # D8: el secreto que firmó decide el ambiente
    if env is None:
        raise HTTPException(status_code=503, detail="Los eventos de Wompi no están configurados")
    if env is False:
        raise HTTPException(status_code=401, detail="Firma inválida")
    if event.get("event") != "transaction.updated":
        return {"ok": True, "ignored": "evento no manejado"}
    txn = (event.get("data") or {}).get("transaction") or {}
    ops.record_system_event("wompi_webhook", str(txn.get("reference") or "")[:80], f"estado {txn.get('status')}")
    pay = db.query(FormPayment).filter(FormPayment.reference == str(txn.get("reference") or "")).first()
    if not pay:
        return {"ok": True, "ignored": "referencia desconocida"}
    if (pay.account_id or None) != (account.id if account else None):
        return {"ok": True, "ignored": "cuenta distinta a la del pago"}        # el evento de una cuenta no puede aprobar el pago de otra
    if (env == "test") != bool(pay.is_test):
        return {"ok": True, "ignored": "ambiente distinto al del pago"}       # un evento de pruebas no puede aprobar un pago real
    if int(txn.get("amount_in_cents") or -1) != pay.amount_cents or txn.get("currency") != pay.currency:
        return {"ok": True, "ignored": "monto distinto al esperado"}
    apply_result(db, pay.id, txn.get("status", ""), txn.get("id"), txn.get("payment_method_type"))
    return {"ok": True}
