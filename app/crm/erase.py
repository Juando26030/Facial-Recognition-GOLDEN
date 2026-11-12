"""Supresión de datos del CRM (Ley 1581): borrar un contacto o una cuenta borra TAMBIÉN su historial de cambios (`crm_change_log`, sin llaves foráneas) y sus notas (`crm_notes`, por
cascada de la base). Sin commit propio. El flujo de la plataforma por cédula (`privacy.erase_person`) NO cubre estos datos: ver docs/crm/README.md, «Solicitudes de supresión»."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CrmAccount, CrmChangeLog, CrmContact, CrmNote


def erase_contact(db: Session, contact_id: int) -> dict:
    """Borra el contacto, su historial de cambios y las notas que lo señalan. Devuelve conteos (sin datos personales)."""
    contact = db.get(CrmContact, contact_id)
    if contact is None:
        return {"contacts": 0, "notes": 0, "changes": 0}
    notes = db.execute(delete(CrmNote).where(CrmNote.contact_id == contact_id)).rowcount
    changes = db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id == contact_id)).rowcount
    db.delete(contact)
    db.flush()
    return {"contacts": 1, "notes": notes, "changes": changes}


def erase_account(db: Session, account_id: int) -> dict:
    """Borra la cuenta con sus contactos, notas e historiales (de la cuenta y de cada contacto)."""
    account = db.get(CrmAccount, account_id)
    if account is None:
        return {"accounts": 0, "contacts": 0, "notes": 0, "changes": 0}
    contact_ids = [r[0] for r in db.execute(select(CrmContact.id).where(CrmContact.account_id == account_id)).all()]
    notes = db.execute(delete(CrmNote).where(CrmNote.account_id == account_id)).rowcount
    changes = 0
    if contact_ids:
        changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id.in_(contact_ids))).rowcount
    changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "account", CrmChangeLog.entity_id == account_id)).rowcount
    db.delete(account)          # sus contactos caen por cascada (la base; el ORM borra los ya cargados)
    db.flush()
    return {"accounts": 1, "contacts": len(contact_ids), "notes": notes, "changes": changes}
