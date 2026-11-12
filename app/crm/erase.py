"""Supresión de datos del CRM (Ley 1581). Borrar un contacto quita sus datos de TODOS los sitios donde el CRM los guarda; sin commit propio. El flujo de la plataforma por cédula
(`privacy.erase_person`) NO cubre estos datos: ver docs/crm/README.md, «Solicitudes de supresión».

Un contacto deja rastro en cinco sitios:
  1. su fila y sus notas (`crm_contacts`, `crm_notes` por cascada);
  2. su propio historial (`crm_change_log`, entidad `contact`);
  3. el historial de la CUENTA, cuando alguien escribió sus datos en campos de la cuenta (correo, teléfono, contacto de facturación): se borran las filas que traen sus valores;
  4. los mismos campos de la cuenta, si hoy tienen sus valores: se dejan vacíos (sin escribir historial: el valor anterior es justo el dato a suprimir);
  5. la copia en `tenants.contact_name/phone/email` (regla del contacto principal): se vacía lo que coincida con sus valores.
Lo que NO se puede encontrar con certeza es el texto libre (descripción de la cuenta, notas generales): se cuenta cuántas veces parece mencionarse y se devuelve en `review` para que una
persona lo revise. Todo se devuelve como conteos, nunca como valores.
"""
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.crm import normalize
from app.crm.matching import ACCOUNT_PERSONAL_FIELDS, digits, identifiers, mentions, value_matches
from app.models import CrmAccount, CrmChangeLog, CrmContact, CrmNote, Tenant

def _scrub_account(db: Session, account: CrmAccount, ids: dict) -> dict:
    """Pasos 3 y 4: historial de la cuenta y valores actuales de la cuenta."""
    rows = db.execute(select(CrmChangeLog).where(CrmChangeLog.entity == "account", CrmChangeLog.entity_id == account.id,
                                                CrmChangeLog.field_key.in_(ACCOUNT_PERSONAL_FIELDS))).scalars().all()
    drop = [r.id for r in rows if value_matches(r.field_key, r.old_value, ids) or value_matches(r.field_key, r.new_value, ids)]
    removed = db.execute(delete(CrmChangeLog).where(CrmChangeLog.id.in_(drop))).rowcount if drop else 0
    cleared = 0
    for f in ACCOUNT_PERSONAL_FIELDS:
        if value_matches(f, getattr(account, f), ids):
            setattr(account, f, None)
            cleared += 1
    return {"account_history": removed, "account_fields": cleared}


def _clear_tenant_mirror(db: Session, tenant_id: Optional[str], contact: CrmContact) -> int:
    """Paso 5: vacía en `tenants` lo que coincide con los valores de este contacto (nombre, teléfono y correo, cada uno por separado)."""
    tenant = db.get(Tenant, tenant_id) if tenant_id else None
    if tenant is None:
        return 0
    ids = identifiers(contact)
    n = 0
    if tenant.contact_name and normalize(tenant.contact_name) == ids["name"]:
        tenant.contact_name, n = None, n + 1
    if tenant.contact_email and normalize(tenant.contact_email) in ids["emails"]:
        tenant.contact_email, n = None, n + 1
    if tenant.contact_phone and digits(tenant.contact_phone) in ids["phones"]:
        tenant.contact_phone, n = None, n + 1
    return n


def review_hints(db: Session, account: CrmAccount, ids: dict) -> dict:
    """Texto libre donde parece nombrarse a la persona: no se toca, se avisa."""
    notes = db.execute(select(CrmNote.body).where(CrmNote.account_id == account.id, CrmNote.contact_id.is_(None)).limit(2000)).scalars().all()
    return {"description": mentions(account.description, ids), "general_notes": sum(1 for b in notes if mentions(b, ids))}


def erase_contact(db: Session, contact_id: int) -> dict:
    """Borra el contacto y todo su rastro (ver el encabezado). Devuelve conteos y `review` (sin datos personales)."""
    contact = db.get(CrmContact, contact_id)
    if contact is None:
        return {"contacts": 0, "notes": 0, "changes": 0, "account_history": 0, "account_fields": 0, "tenant_fields": 0, "review": {"description": False, "general_notes": 0}}
    account = db.get(CrmAccount, contact.account_id)
    ids = identifiers(contact)
    out = {"contacts": 1}
    out["notes"] = db.execute(delete(CrmNote).where(CrmNote.contact_id == contact_id)).rowcount
    out["changes"] = db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id == contact_id)).rowcount
    out.update(_scrub_account(db, account, ids) if account is not None else {"account_history": 0, "account_fields": 0})
    out["tenant_fields"] = _clear_tenant_mirror(db, account.tenant_id if account is not None else None, contact)
    out["review"] = review_hints(db, account, ids) if account is not None else {"description": False, "general_notes": 0}
    db.delete(contact)
    db.flush()
    return out


def erase_account(db: Session, account_id: int) -> dict:
    """Borra la cuenta con sus contactos, notas e historiales (de la cuenta y de cada contacto) y vacía la copia de cada contacto en `tenants`."""
    account = db.get(CrmAccount, account_id)
    if account is None:
        return {"accounts": 0, "contacts": 0, "notes": 0, "changes": 0, "tenant_fields": 0}
    contacts = db.execute(select(CrmContact).where(CrmContact.account_id == account_id)).scalars().all()
    contact_ids = [c.id for c in contacts]
    tenant_fields = sum(_clear_tenant_mirror(db, account.tenant_id, c) for c in contacts)
    notes = db.execute(delete(CrmNote).where(CrmNote.account_id == account_id)).rowcount
    changes = 0
    if contact_ids:
        changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id.in_(contact_ids))).rowcount
    changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "account", CrmChangeLog.entity_id == account_id)).rowcount
    db.delete(account)          # sus contactos caen por cascada (la base; el ORM borra los ya cargados)
    db.flush()
    return {"accounts": 1, "contacts": len(contact_ids), "notes": notes, "changes": changes, "tenant_fields": tenant_fields}
