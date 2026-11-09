"""Cuentas de cobro de Wompi de terceros (Fase 8, docs/23_COBROS_WOMPI_MULTICUENTA.md).

La cuenta de Golden vive en variables de entorno (app/wompi.py). Aquí están las de OTROS comercios que nos prestan su cuenta: cada una con sus llaves.
Seguridad: la llave pública (pub_…) no es secreta; la PRIVADA (prv_…), el secreto de INTEGRIDAD y el de EVENTOS sí. Se guardan CIFRADOS con `PAYMENT_KEYS_ENCRYPTION_KEY` (Fernet; varias llaves
separadas por coma: la primera cifra, todas descifran). Sin esa llave NO se puede guardar ninguna cuenta (falla cerrado) y lo ya guardado no se puede leer: perderla = pedir las llaves de nuevo.
Nunca se escriben en logs ni salen por la API (solo «configurada» y los últimos 4 caracteres de la pública). `cfg_*` devuelve el mismo diccionario que `wompi.config()`.
"""
import logging
import os
import re
import secrets
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.orm import Session, object_session

from app import wompi
from app.models import FormPayment, PaymentAccount, WebForm

log = logging.getLogger("golden.payment_accounts")
PREFIX = "pk1:"
PUBLIC_RE = re.compile(r"^pub_(test|prod)_[A-Za-z0-9]{8,80}$")
PRIVATE_RE = re.compile(r"^prv_(test|prod)_[A-Za-z0-9]{8,80}$")
SECRET_RE = re.compile(r"^(test|prod)_(integrity|events)_[A-Za-z0-9]{8,80}$")


class KeyMissing(RuntimeError):
    """Sin PAYMENT_KEYS_ENCRYPTION_KEY no se guarda ninguna llave de terceros."""


def _fernet() -> Optional[MultiFernet]:
    raw = os.getenv("PAYMENT_KEYS_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    return MultiFernet([Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()])


def enabled() -> bool:
    try:
        return _fernet() is not None
    except ValueError:
        return False


def encrypt(value: str) -> str:
    f = _fernet()
    if f is None:
        raise KeyMissing("Falta PAYMENT_KEYS_ENCRYPTION_KEY: no se pueden guardar llaves de cobro")
    return PREFIX + f.encrypt(value.encode()).decode()


def decrypt(token: Optional[str]) -> str:
    """'' si no hay dato o no se puede descifrar (llave perdida): nunca rompe una pantalla ni escribe el dato en el log."""
    if not token:
        return ""
    if not token.startswith(PREFIX):
        return ""
    f = _fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(token[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        log.error("no se pudo descifrar una llave de cobro (¿cambió PAYMENT_KEYS_ENCRYPTION_KEY?)")
        return ""


def new_ref() -> str:
    return secrets.token_urlsafe(18)


def is_test_key(public_key: str) -> bool:
    return str(public_key).startswith("pub_test_")


def validate_keys(public: str, private: Optional[str], integrity: str, events: str) -> Optional[str]:
    """Mensaje de error en español si las llaves no tienen la forma de Wompi; None si están bien. No se repite el valor en el mensaje."""
    if not PUBLIC_RE.match(public or ""):
        return "La llave pública debe empezar por pub_test_ o pub_prod_"
    env = "test" if is_test_key(public) else "prod"
    if private and not PRIVATE_RE.match(private):
        return "La llave privada debe empezar por prv_test_ o prv_prod_"
    if private and private.split("_")[1] != env:
        return "La llave privada es de otro ambiente (pruebas/producción) que la pública"
    for label, val, kind in (("secreto de integridad", integrity, "integrity"), ("secreto de eventos", events, "events")):
        m = SECRET_RE.match(val or "")
        if not m or m.group(2) != kind:
            return f"El {label} debe empezar por {env}_{kind}_ (cópialo tal cual del panel de Wompi)"
        if m.group(1) != env:
            return f"El {label} es de otro ambiente (pruebas/producción) que la llave pública"
    return None


def cfg_of(acc: PaymentAccount) -> Optional[dict]:
    """Llaves de la cuenta, listas para el widget y la API (mismo formato que `wompi.config`). None si está inactiva o no se pueden leer."""
    if acc is None or not acc.active:
        return None
    integrity, events, private = decrypt(acc.integrity_enc), decrypt(acc.events_enc), decrypt(acc.private_enc)
    if not integrity or not events:
        return None
    test = is_test_key(acc.public_key)
    return {"public_key": acc.public_key, "integrity_secret": integrity, "events_secret": events, "private_key": private, "api": wompi.API[test], "test": test}


def cfg_for(db: Session, account_id: Optional[int], test: bool) -> Optional[dict]:
    """Llaves con las que cobra un formulario: la cuenta asignada, o la de Golden (`wompi.config`) si no hay. Regla de seguridad igual a la de Golden: un formulario en `pruebas`
    NUNCA usa llaves de producción de nadie."""
    if not account_id:
        return wompi.config(test)
    acc = db.get(PaymentAccount, account_id)
    cfg = cfg_of(acc)
    if cfg and test and not cfg["test"]:
        return None
    return cfg


def cfg_for_form(db: Session, form: WebForm, test: bool) -> Optional[dict]:
    return cfg_for(db, getattr(form, "payment_account_id", None), test)


def cfg_for_payment(db: Session, pay: FormPayment) -> Optional[dict]:
    """Llaves de la cuenta con la que SE COBRÓ ese pago (para reembolsar, conciliar, consultar): nunca la de otra."""
    if getattr(pay, "account_id", None):
        db = db or object_session(pay)
        return cfg_of(db.get(PaymentAccount, pay.account_id))
    return wompi.config(pay.is_test)


def by_ref(db: Session, ref: str) -> Optional[PaymentAccount]:
    return db.query(PaymentAccount).filter(PaymentAccount.ref == ref).first() if ref else None


def mask(public_key: str) -> str:
    return "…" + str(public_key)[-4:]


def serialize(acc: PaymentAccount, base_url: str, forms: int = 0) -> dict:
    """Lo único que sale por la API: nada secreto."""
    return {"id": acc.id, "name": acc.name, "holder": acc.holder, "active": bool(acc.active), "note": acc.note,
            "public_key_masked": mask(acc.public_key), "env": "test" if is_test_key(acc.public_key) else "prod",
            "has_private": bool(acc.private_enc), "keys_readable": bool(cfg_of(PaymentAccount(active=True, public_key=acc.public_key, integrity_enc=acc.integrity_enc, events_enc=acc.events_enc, private_enc=acc.private_enc))),
            "webhook_url": f"{base_url}/webhooks/wompi/{acc.ref}" if base_url else f"/webhooks/wompi/{acc.ref}", "forms": forms,
            "created_at": acc.created_at.isoformat() if acc.created_at else None}
