"""Reconocer a una persona en los campos de una cuenta (supresión, Ley 1581). Puro: no usa la base de datos ni SQLAlchemy (se prueba sin conexión). `contact` es cualquier objeto con
first_name, last_name, email, phone y mobile."""
import re
from typing import Optional

from app.crm import normalize

ACCOUNT_PERSONAL_FIELDS = ("billing_contact_name", "billing_contact_phone", "email", "phone")      # campos de la cuenta donde puede haber datos de una persona
MIN_PHONE_DIGITS = 7


def digits(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def full_name(c) -> str:
    return " ".join(p for p in ((c.first_name or "").strip(), (c.last_name or "").strip()) if p)


def identifiers(contact) -> dict:
    """Con qué se reconoce a esta persona en otros campos: nombre completo normalizado, correo normalizado y teléfonos (solo dígitos, mínimo 7)."""
    return {"name": normalize(full_name(contact)),
            "emails": {e for e in (normalize(contact.email),) if e},
            "phones": {d for d in (digits(contact.phone), digits(contact.mobile)) if len(d) >= MIN_PHONE_DIGITS}}


def name_in(name: str, text: str) -> bool:
    if not name or not text:
        return False
    if " " not in name:                        # un solo nombre: solo si el campo es exactamente ese nombre (evita «ana» dentro de «banana»)
        return text == name
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def value_matches(field: str, value: Optional[str], ids: dict) -> bool:
    """¿Este valor de un campo de la cuenta es de esta persona? Pura (sin base de datos)."""
    if not value:
        return False
    if field == "billing_contact_name":
        return name_in(ids["name"], normalize(value))
    if field == "email":
        return normalize(value) in ids["emails"]
    if field in ("phone", "billing_contact_phone"):
        d = digits(value)
        return len(d) >= MIN_PHONE_DIGITS and any(d == p or d.endswith(p) or p.endswith(d) for p in ids["phones"])
    return False


def mentions(text: Optional[str], ids: dict) -> bool:
    n = normalize(text)
    return bool(n) and (name_in(ids["name"], n) or any(e in n for e in ids["emails"]))


