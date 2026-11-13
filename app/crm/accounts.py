"""Lógica de cuentas y contactos del CRM (C1b-1). Sin commit propio: quien llama (el router) confirma o revierte la transacción.

Reglas (docs/crm/README.md y plan C1b):
* El número de la cuenta sale de `next_code` (contador consecutivo), nunca de `max()+1`.
* `name_norm` / `full_name_norm` / `email_norm` se escriben SOLO desde aquí (una sola puerta): la búsqueda sin tildes depende de ellos (ver `search_clause`).
* Un solo contacto principal por cuenta (índice único parcial en la base). El primer contacto activo de una cuenta nace principal.
* Con el contacto principal manda el CRM: `tenants.contact_name/phone/email` se rellenan desde él, en un solo sentido (CRM → cliente) y solo si la cuenta ya es cliente de la plataforma.
* Cada cambio de campo queda en `crm_change_log` (app/crm/history.py). Los valores viven solo en la base, nunca en los logs.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session

from app.crm import history, normalize, validate_status
from app.crm.codes import next_code
from app.crm.errors import CrmError  # noqa: F401  (se re-exporta: el router y las pruebas lo usan como svc.CrmError)
from app.models import CrmAccount, CrmContact, CrmNote, StaffUser, Tenant
from app.timeutil import utcnow

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


ACCOUNT_LIMITS = {"name": 200, "nit": 40, "email": 200, "phone": 60, "billing_address": 300, "billing_city": 120, "billing_state": 120, "billing_country": 120,
                  "shipping_address": 300, "shipping_city": 120, "shipping_country": 120, "billing_contact_name": 200, "billing_contact_phone": 60,
                  "payment_term": 60, "billing_close": 60, "description": 20000, "category": 40, "account_type": 40, "industry": 60, "website": 300}
ACCOUNT_TEXT = tuple(ACCOUNT_LIMITS)
CONTACT_LIMITS = {"first_name": 120, "last_name": 120, "job_title": 120, "email": 200, "phone": 60, "mobile": 60, "notes": 20000}
NOTE_MAX = 5000
PAGE_SIZE = 50
MAX_ID = 2_147_483_647          # el entero más grande que admite la base (columnas `integer`): un id mayor no puede existir y no debe llegar al SQL
MAX_PAGE = 1_000_000
NORM_MAX = {"name_norm": 200, "full_name_norm": 240, "email_norm": 200}          # columnas de búsqueda: normalizar (NFKD) puede alargar el texto, y nombre + apellido suman 241 con el espacio


# ------------------------------------------------------------------ limpieza de datos
def _text(data: dict, key: str, limit: int, out: dict) -> None:
    if key not in data:
        return
    v = data[key]
    v = (str(v).strip() if v is not None else "") or None
    if v is not None and len(v) > limit:
        raise CrmError(f"El campo «{key}» es demasiado largo (máximo {limit} caracteres).")
    out[key] = v


def clean_account(data: dict) -> dict:
    """Valida y limpia los campos que llegan (solo los presentes). Lanza CrmError con un mensaje en español."""
    out: dict = {}
    for key, limit in ACCOUNT_LIMITS.items():
        _text(data, key, limit, out)
    if "name" in out and not out["name"]:
        raise CrmError("La cuenta necesita un nombre.")
    if out.get("email") and not _EMAIL.match(out["email"]):
        raise CrmError("El correo de la cuenta no es válido.")
    if "status" in data:
        try:
            out["status"] = validate_status(data["status"])
        except ValueError as exc:
            raise CrmError(str(exc)) from exc
    if "payment_days" in data:
        v = data["payment_days"]
        if v in (None, ""):
            out["payment_days"] = None
        else:
            try:
                n = int(v)
            except (TypeError, ValueError) as exc:
                raise CrmError("Los días de plazo de pago deben ser un número entero.") from exc
            if not 0 <= n <= 365:
                raise CrmError("Los días de plazo de pago deben estar entre 0 y 365.")
            out["payment_days"] = n
    if "agency_percent" in data:
        v = data["agency_percent"]
        if v in (None, ""):
            out["agency_percent"] = None
        else:
            try:
                d = Decimal(str(v).replace(",", "."))
            except InvalidOperation as exc:
                raise CrmError("El porcentaje de agencia debe ser un número.") from exc
            if not d.is_finite() or not Decimal(0) <= d <= Decimal(100):          # NaN no se puede comparar y rompería con 500
                raise CrmError("El porcentaje de agencia debe estar entre 0 y 100.")
            out["agency_percent"] = d.quantize(Decimal("0.01"))
    if "owner_staff_id" in data:
        v = data["owner_staff_id"]
        try:
            out["owner_staff_id"] = int(v) if v not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise CrmError("El responsable indicado no es válido.") from exc
    return out


def clean_contact(data: dict) -> dict:
    out: dict = {}
    for key, limit in CONTACT_LIMITS.items():
        _text(data, key, limit, out)
    if out.get("email") and not _EMAIL.match(out["email"]):
        raise CrmError("El correo del contacto no es válido.")
    return out


def full_name(c: CrmContact) -> str:
    return " ".join(p for p in ((c.first_name or "").strip(), (c.last_name or "").strip()) if p)


def _norms(c: CrmContact) -> None:
    c.full_name_norm = normalize(full_name(c))[:NORM_MAX["full_name_norm"]]
    c.email_norm = normalize(c.email)[:NORM_MAX["email_norm"]] or None


def _check_owner(db: Session, owner_id) -> None:
    if owner_id is not None and (not 0 < owner_id <= MAX_ID or db.get(StaffUser, owner_id) is None):
        raise CrmError("El responsable indicado no existe.")


def _check_version(obj, expected: Optional[str]) -> None:
    """Edición concurrente: quien edita manda el `updated_at` que vio; si cambió, otra persona guardó antes."""
    if expected is None:
        raise CrmError("Falta la versión del registro (updated_at): recarga la pantalla.", 400)
    if obj.updated_at.isoformat() != expected:
        raise CrmError("Alguien más modificó este registro mientras lo editabas. Recarga la pantalla para ver los cambios.", 409)


# ------------------------------------------------------------------ cuentas
def get_account(db: Session, account_id: int) -> CrmAccount:
    account = db.get(CrmAccount, account_id)
    if account is None:
        raise CrmError("Cuenta no encontrada.", 404)
    return account


def create_account(db: Session, staff: StaffUser, data: dict, *, confirm_duplicate: bool = False) -> CrmAccount:
    fields = clean_account(data)
    if not fields.get("name"):
        raise CrmError("La cuenta necesita un nombre.")
    fields.setdefault("status", "activo")
    _check_owner(db, fields.get("owner_staff_id"))
    norm = normalize(fields["name"])[:NORM_MAX["name_norm"]]
    if not confirm_duplicate:
        twin = db.query(CrmAccount.code).filter(CrmAccount.name_norm == norm).first()
        if twin is not None:
            raise CrmError(f"Ya existe una cuenta con ese nombre (código {twin[0]}). Si de verdad es otra, confirma el duplicado.", 409)
    account = CrmAccount(code=next_code(db, "account"), name_norm=norm, created_by_id=staff.id, **fields)
    db.add(account)
    db.flush()
    return account


def update_account(db: Session, staff: StaffUser, account: CrmAccount, data: dict, expected_updated_at: Optional[str]) -> CrmAccount:
    _check_version(account, expected_updated_at)
    fields = clean_account(data)
    _check_owner(db, fields.get("owner_staff_id"))
    before = history.snapshot(account, "account")
    for key, value in fields.items():
        setattr(account, key, value)
    if "name" in fields:
        account.name_norm = normalize(account.name)[:NORM_MAX["name_norm"]]
    if history.record(db, account, "account", before, staff_id=staff.id):
        account.updated_at = utcnow()
    db.flush()
    return account


def set_archived(db: Session, staff: StaffUser, account: CrmAccount, archived: bool) -> CrmAccount:
    if archived == (account.archived_at is not None):
        raise CrmError("La cuenta ya está archivada." if archived else "La cuenta no está archivada.")
    before = history.snapshot(account, "account")
    account.archived_at = utcnow() if archived else None
    history.record(db, account, "account", before, staff_id=staff.id)
    account.updated_at = utcnow()
    db.flush()
    return account


def _like(text_: str) -> str:
    return "%" + text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search_clause(q: str):
    """Búsqueda «contiene» y SIN TILDES, sin extensiones ni migración: el texto buscado se normaliza aquí (minúsculas, sin tildes) y se compara contra `name_norm` /
    `full_name_norm` / `email_norm`, que se guardan YA normalizados al escribir. Además: código exacto y NIT sin puntos ni guiones. Sin índice trigrama: es un barrido, suficiente hasta ~20.000 cuentas."""
    q = (q or "").strip()
    norm = normalize(q)
    parts = []
    if norm:
        parts.append(CrmAccount.name_norm.like(_like(norm), escape="\\"))
        parts.append(exists().where(and_(CrmContact.account_id == CrmAccount.id,
                                         or_(CrmContact.full_name_norm.like(_like(norm), escape="\\"), CrmContact.email_norm.like(_like(norm), escape="\\")))))
    if q.isdigit() and len(q) <= 12:
        parts.append(CrmAccount.code == int(q))
    clean = re.sub(r"[^0-9A-Za-z]", "", q)
    if len(clean) >= 4:
        parts.append(func.regexp_replace(CrmAccount.nit, "[^0-9A-Za-z]", "", "g") == clean)
    return or_(*parts) if parts else None


def list_accounts(db: Session, *, q: str = "", status: str = "", owner_id: Optional[int] = None, city: str = "", archived: bool = False, page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmAccount)
    query = query.filter(CrmAccount.archived_at.isnot(None) if archived else CrmAccount.archived_at.is_(None))
    if status:
        query = query.filter(CrmAccount.status == status)
    if owner_id:
        if not 0 < owner_id <= MAX_ID:
            return {"items": [], "total": 0, "page": 1, "size": size}
        query = query.filter(CrmAccount.owner_staff_id == owner_id)
    if city:
        query = query.filter(CrmAccount.billing_city == city)
    q = (q or "")[:200]          # una búsqueda más larga que el campo más largo no encuentra nada distinto
    clause = search_clause(q) if q else None
    if q and clause is None:
        return {"items": [], "total": 0, "page": 1, "size": size}
    if clause is not None:
        query = query.filter(clause)
    total = query.count()
    size = max(1, min(int(size or PAGE_SIZE), 200))
    page = max(1, min(int(page or 1), MAX_PAGE))
    rows = query.order_by(CrmAccount.name_norm, CrmAccount.id).offset((page - 1) * size).limit(size).all()
    primaries = {}
    if rows:
        for c in db.query(CrmContact).filter(CrmContact.account_id.in_([r.id for r in rows]), CrmContact.is_primary.is_(True)).all():
            primaries[c.account_id] = c
    return {"items": [serialize_account(a, primaries.get(a.id)) for a in rows], "total": total, "page": page, "size": size}


def serialize_account(a: CrmAccount, primary: Optional[CrmContact] = None, *, detail: bool = False) -> dict:
    out = {"id": a.id, "code": a.code, "name": a.name, "status": a.status, "city": a.billing_city, "owner_staff_id": a.owner_staff_id,
           "is_client": a.tenant_id is not None, "tenant_id": a.tenant_id, "archived": a.archived_at is not None,
           "primary_contact": full_name(primary) if primary is not None else None, "updated_at": a.updated_at.isoformat()}
    if detail:
        for key in ACCOUNT_TEXT:
            out[key] = getattr(a, key)
        out["payment_days"] = a.payment_days
        out["agency_percent"] = str(a.agency_percent) if a.agency_percent is not None else None
        out["created_at"] = a.created_at.isoformat()
        try:
            out["legacy"] = json.loads(a.legacy_json) if a.legacy_json else None          # datos originales de SuiteCRM (solo lectura)
        except ValueError:
            out["legacy"] = None
    return out


# ------------------------------------------------------------------ contactos
def get_contact(db: Session, contact_id: int) -> CrmContact:
    contact = db.get(CrmContact, contact_id)
    if contact is None:
        raise CrmError("Contacto no encontrado.", 404)
    return contact


def primary_of(db: Session, account_id: int) -> Optional[CrmContact]:
    return db.query(CrmContact).filter(CrmContact.account_id == account_id, CrmContact.is_primary.is_(True)).first()


def serialize_contact(c: CrmContact) -> dict:
    return {"id": c.id, "account_id": c.account_id, "first_name": c.first_name, "last_name": c.last_name, "full_name": full_name(c), "job_title": c.job_title, "email": c.email,
            "phone": c.phone, "mobile": c.mobile, "is_primary": bool(c.is_primary), "notes": c.notes, "archived": c.archived_at is not None, "updated_at": c.updated_at.isoformat()}


def mirror_primary_to_tenant(db: Session, account: CrmAccount) -> bool:
    """Regla del contacto principal (decidida): CRM → cliente, un solo sentido. Copia nombre, teléfono (celular primero, luego fijo) y correo del principal a `tenants.contact_*`.
    Si la cuenta no es cliente o no tiene principal activo, no toca nada (los valores ya copiados se conservan). Devuelve si cambió algo."""
    if account.tenant_id is None:
        return False
    contact = primary_of(db, account.id)
    tenant = db.get(Tenant, account.tenant_id)
    if contact is None or contact.archived_at is not None or tenant is None:
        return False
    new = {"contact_name": full_name(contact) or None, "contact_phone": contact.mobile or contact.phone, "contact_email": contact.email}
    changed = False
    for key, value in new.items():
        if getattr(tenant, key) != value:
            setattr(tenant, key, value)
            changed = True
    return changed


def tenant_contact_locked(db: Session, tenant_id: str) -> bool:
    """¿Los datos de contacto de este cliente se editan en el CRM? Sí cuando el CRM está encendido (quien llama lo comprueba) y su cuenta tiene un contacto principal activo."""
    return db.query(CrmContact.id).join(CrmAccount, CrmAccount.id == CrmContact.account_id).filter(
        CrmAccount.tenant_id == tenant_id, CrmContact.is_primary.is_(True), CrmContact.archived_at.is_(None)).first() is not None


def create_contact(db: Session, staff: StaffUser, account: CrmAccount, data: dict, *, make_primary: bool = False) -> CrmContact:
    fields = clean_contact(data)
    if not (fields.get("first_name") or fields.get("last_name")):
        raise CrmError("El contacto necesita al menos un nombre o un apellido.")
    current = primary_of(db, account.id)
    want_primary = make_primary or current is None          # el primer contacto de una cuenta nace principal
    if want_primary and current is not None:
        _demote(db, staff, current)
    contact = CrmContact(account_id=account.id, created_by_id=staff.id, is_primary=want_primary, **fields)
    _norms(contact)
    db.add(contact)
    db.flush()
    if want_primary:
        mirror_primary_to_tenant(db, account)
    db.flush()
    return contact


def update_contact(db: Session, staff: StaffUser, contact: CrmContact, data: dict, expected_updated_at: Optional[str]) -> CrmContact:
    _check_version(contact, expected_updated_at)
    fields = clean_contact(data)
    merged = {**{k: getattr(contact, k) for k in ("first_name", "last_name")}, **{k: v for k, v in fields.items() if k in ("first_name", "last_name")}}
    if not (merged["first_name"] or merged["last_name"]):
        raise CrmError("El contacto necesita al menos un nombre o un apellido.")
    before = history.snapshot(contact, "contact")
    for key, value in fields.items():
        setattr(contact, key, value)
    _norms(contact)
    if history.record(db, contact, "contact", before, staff_id=staff.id):
        contact.updated_at = utcnow()
    db.flush()
    if contact.is_primary:
        mirror_primary_to_tenant(db, contact.account)
    return contact


def _demote(db: Session, staff: StaffUser, current: CrmContact) -> None:
    """Baja al principal actual y hace flush: el índice único parcial no admite dos principales a la vez, ni siquiera dentro de una transacción."""
    before = history.snapshot(current, "contact")
    current.is_primary = False
    history.record(db, current, "contact", before, staff_id=staff.id)
    current.updated_at = utcnow()
    db.flush()


def _promote(db: Session, staff: StaffUser, account: CrmAccount, contact: CrmContact) -> None:
    current = primary_of(db, account.id)
    if current is not None and current.id == contact.id:
        return
    if current is not None:
        _demote(db, staff, current)
    before = history.snapshot(contact, "contact")
    contact.is_primary = True
    history.record(db, contact, "contact", before, staff_id=staff.id)
    contact.updated_at = utcnow()
    db.flush()


def make_primary(db: Session, staff: StaffUser, contact: CrmContact) -> CrmContact:
    if contact.archived_at is not None:
        raise CrmError("Un contacto archivado no puede ser el principal. Restáuralo primero.")
    _promote(db, staff, contact.account, contact)
    mirror_primary_to_tenant(db, contact.account)
    db.flush()
    return contact


def set_contact_archived(db: Session, staff: StaffUser, contact: CrmContact, archived: bool) -> CrmContact:
    if archived == (contact.archived_at is not None):
        raise CrmError("El contacto ya está archivado." if archived else "El contacto no está archivado.")
    before = history.snapshot(contact, "contact")
    contact.archived_at = utcnow() if archived else None
    if archived:
        contact.is_primary = False          # un archivado no es principal; los valores ya copiados al cliente se conservan
    history.record(db, contact, "contact", before, staff_id=staff.id)
    contact.updated_at = utcnow()
    db.flush()
    return contact


# ------------------------------------------------------------------ notas
def add_note(db: Session, staff: StaffUser, account: CrmAccount, body: str, contact_id: Optional[int] = None) -> CrmNote:
    body = (body or "").strip()
    if not body:
        raise CrmError("La nota está vacía.")
    if contact_id is not None and not 0 < contact_id <= MAX_ID:
        raise CrmError("El contacto de la nota no pertenece a esta cuenta.")
    if len(body) > NOTE_MAX:
        raise CrmError(f"La nota es demasiado larga (máximo {NOTE_MAX} caracteres).")
    if contact_id is not None:
        c = db.get(CrmContact, contact_id)
        if c is None or c.account_id != account.id:
            raise CrmError("El contacto de la nota no pertenece a esta cuenta.")
    note = CrmNote(account_id=account.id, contact_id=contact_id, body=body, created_by_id=staff.id)
    db.add(note)
    db.flush()
    return note

