"""Cuentas de cobro de Wompi de terceros (Fase 8, docs/23_COBROS_WOMPI_MULTICUENTA.md): alta, edición, prueba de conexión, asignación a formularios y QR/enlaces de pago.

Solo admin y super_admin. Las llaves secretas se aceptan una vez, se guardan cifradas y NUNCA salen por la API (ni en logs ni en la auditoría).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import audit_actions, payment_accounts as pa, public_slug, publicurl, wompi
from app.auth import require_role
from app.database import get_db
from app.models import Event, FormPayment, PaymentAccount, StaffUser, WebForm
from app.timeutil import utcnow

log = logging.getLogger("golden.payment_accounts")
router = APIRouter()
ADMIN = require_role("admin")


def _get(db: Session, account_id: int) -> PaymentAccount:
    acc = db.get(PaymentAccount, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Cuenta de cobro no encontrada")
    return acc


def _clean(data: dict, key: str, limit: int = 200) -> str:
    return str((data or {}).get(key) or "").strip()[:limit]


def _row(db: Session, acc: PaymentAccount, request: Request) -> dict:
    n = db.query(WebForm).filter(WebForm.payment_account_id == acc.id).count()
    return pa.serialize(acc, publicurl.base(str(request.base_url)), forms=n)


@router.get("/payment-accounts")
def list_accounts(request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    return {"accounts": [_row(db, a, request) for a in db.query(PaymentAccount).order_by(PaymentAccount.created_at.desc(), PaymentAccount.id.desc()).all()],
            "encryption_ready": pa.enabled()}


@router.post("/payment-accounts")
def create_account(data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    if not pa.enabled():
        raise HTTPException(status_code=503, detail="Falta configurar PAYMENT_KEYS_ENCRYPTION_KEY en el servidor: sin ella no se guardan llaves de otras personas")
    name = _clean(data, "name", 80)
    if not name:
        raise HTTPException(status_code=400, detail="Ponle un nombre a la cuenta (por ejemplo, el del titular)")
    public, private = _clean(data, "public_key"), _clean(data, "private_key") or None
    integrity, events = _clean(data, "integrity_secret"), _clean(data, "events_secret")
    problem = pa.validate_keys(public, private, integrity, events)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    acc = PaymentAccount(ref=pa.new_ref(), name=name, holder=_clean(data, "holder", 120) or None, note=_clean(data, "note", 500) or None, public_key=public,
                         private_enc=pa.encrypt(private) if private else None, integrity_enc=pa.encrypt(integrity), events_enc=pa.encrypt(events), active=True, created_by_id=staff.id)
    db.add(acc)
    db.flush()
    audit_actions.record(db, staff, "payment_account_create", "payment_account", acc.id, acc.name, f"Cuenta de cobro creada ({pa.mask(public)})")
    db.commit()
    return _row(db, acc, request)


@router.put("/payment-accounts/{account_id}")
def update_account(account_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Nombre, titular, nota y activa/desactivada. Las llaves se cambian TODAS juntas (pública + integridad + eventos, y la privada si se usa): se vuelven a validar."""
    acc = _get(db, account_id)
    changes = []
    if "name" in data:
        name = _clean(data, "name", 80)
        if not name:
            raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío")
        acc.name = name
        changes.append("nombre")
    for field in ("holder", "note"):
        if field in data:
            setattr(acc, field, _clean(data, field, 500 if field == "note" else 120) or None)
            changes.append(field)
    if "active" in data:
        acc.active = bool(data["active"])
        changes.append("activa" if acc.active else "desactivada")
    if any(k in data for k in ("public_key", "integrity_secret", "events_secret", "private_key")):
        if not pa.enabled():
            raise HTTPException(status_code=503, detail="Falta configurar PAYMENT_KEYS_ENCRYPTION_KEY en el servidor")
        public, private = _clean(data, "public_key"), _clean(data, "private_key") or None
        integrity, events = _clean(data, "integrity_secret"), _clean(data, "events_secret")
        problem = pa.validate_keys(public, private, integrity, events)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        if pa.is_test_key(public) != pa.is_test_key(acc.public_key) and db.query(FormPayment.id).filter(FormPayment.account_id == acc.id).first():
            raise HTTPException(status_code=409, detail="Esta cuenta ya cobró: no se puede pasar de pruebas a producción (o al revés). Crea otra cuenta")
        acc.public_key, acc.integrity_enc, acc.events_enc = public, pa.encrypt(integrity), pa.encrypt(events)
        acc.private_enc = pa.encrypt(private) if private else None
        changes.append("llaves")
    if not changes:
        raise HTTPException(status_code=400, detail="No hay nada que cambiar")
    audit_actions.record(db, staff, "payment_account_update", "payment_account", acc.id, acc.name, "Cambió: " + ", ".join(changes))
    db.commit()
    return _row(db, acc, request)


@router.delete("/payment-accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Borra la cuenta y sus llaves. Si ya cobró algo no se borra (los reembolsos y la conciliación la necesitan): se desactiva."""
    acc = _get(db, account_id)
    if db.query(FormPayment.id).filter(FormPayment.account_id == acc.id).first():
        raise HTTPException(status_code=409, detail="Esta cuenta ya tiene pagos: no se puede borrar. Desactívala")
    db.query(WebForm).filter(WebForm.payment_account_id == acc.id).update({WebForm.payment_account_id: None})
    audit_actions.record(db, staff, "payment_account_delete", "payment_account", acc.id, acc.name, "Cuenta de cobro borrada")
    db.delete(acc)
    db.commit()
    return {"ok": True}


@router.post("/payment-accounts/{account_id}/check")
def check_account(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Prueba la llave pública contra Wompi (`GET /merchants/<llave pública>`): confirma que existe y a quién pertenece el comercio. No toca dinero."""
    import json
    import urllib.error
    import urllib.request
    acc = _get(db, account_id)
    cfg = pa.cfg_of(acc)
    if cfg is None:
        raise HTTPException(status_code=409, detail="Las llaves de esta cuenta no se pueden leer (¿cambió PAYMENT_KEYS_ENCRYPTION_KEY o está desactivada?)")
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{cfg['api']}/merchants/{acc.public_key}", headers={"Accept": "application/json"}), timeout=8) as res:  # nosec B310 - URL https fija, llave ya validada
            merchant = (json.loads(res.read().decode()) or {}).get("data") or {}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        raise HTTPException(status_code=502, detail="Wompi no reconoció la llave pública o no respondió. Revísala")
    return {"ok": True, "merchant": str(merchant.get("name") or merchant.get("legal_name") or "")[:120], "env": "test" if cfg["test"] else "prod", "has_private": bool(cfg["private_key"])}


@router.post("/payment-accounts/{account_id}/payment-link")
def payment_link(account_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Crea un enlace de pago de Wompi con la cuenta (monto fijo o libre). El QR del enlace se dibuja en el navegador; el dinero entra a la cuenta del titular."""
    acc = _get(db, account_id)
    cfg = pa.cfg_of(acc)
    if cfg is None or not cfg["private_key"]:
        raise HTTPException(status_code=409, detail="Para crear enlaces de pago la cuenta necesita su llave privada")
    name = _clean(data, "name", 60)
    if not name:
        raise HTTPException(status_code=400, detail="Ponle un nombre al cobro")
    try:
        amount = int(data.get("amount_cop") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="El monto debe ser un número entero en pesos")
    if amount and not (1500 <= amount <= 100_000_000):
        raise HTTPException(status_code=400, detail="El monto debe estar entre $1.500 y $100.000.000 COP (o vacío para que la persona lo escriba)")
    ok, res = wompi.create_payment_link(cfg, name, _clean(data, "description", 200), amount or None, bool(data.get("single_use")))
    if not ok:
        raise HTTPException(status_code=502, detail=str(res))
    audit_actions.record(db, staff, "payment_link_create", "payment_account", acc.id, acc.name, f"Enlace de pago «{name}» ({'monto fijo' if amount else 'monto libre'})")
    db.commit()
    return res


@router.get("/payment-accounts-forms")
def forms_overview(request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Formularios con cobro (no archivados) y su cuenta, para asignarla y sacar su QR."""
    out = []
    rows = db.query(WebForm, Event).join(Event, Event.id == WebForm.event_id).filter(WebForm.archived_at.is_(None)).order_by(Event.id.desc(), WebForm.id).limit(500).all()
    for form, ev in rows:
        out.append({"id": form.id, "event_id": ev.id, "event": ev.name, "name": form.name, "payment_account_id": form.payment_account_id,
                    "url": public_slug.form_link(str(request.base_url), ev, form)})
    return {"forms": out, "generated_at": utcnow().isoformat()}
