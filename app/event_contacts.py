"""Contactos del cliente en un evento (16-nov-2026). Varios por evento, con una nota de quién es y para qué; UNO principal, que es a quien se envían el informe final y la encuesta.
Vienen de los contactos de la cuenta del CRM (por defecto, el principal de la cuenta) o se crean a mano con nombre y teléfono (el correo es opcional, pero sin correo no reciben nada).
Se guarda una COPIA de nombre, teléfono y correo en el evento (el evento no cambia si luego se edita el contacto del CRM). Sin commit propio: quien llama confirma."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import CrmAccount, CrmContact, EventContact
from app.staff_credentials import valid_email

MAX_CONTACTS = 10
NAME_MAX, PHONE_MAX, NOTE_MAX = 200, 60, 200


class ContactError(ValueError):
    """Dato inválido: el mensaje va al usuario (en español)."""


def _full_name(c: CrmContact) -> str:
    return " ".join(p for p in ((c.first_name or "").strip(), (c.last_name or "").strip()) if p)


def serialize(c: EventContact) -> dict:
    return {"id": c.id, "crm_contact_id": c.crm_contact_id, "name": c.name, "phone": c.phone or "", "email": c.email or "", "note": c.note or "", "is_primary": bool(c.is_primary)}


def list_for(db: Session, event_id: int) -> List[dict]:
    rows = db.query(EventContact).filter(EventContact.event_id == event_id).order_by(EventContact.position, EventContact.id).all()
    return [serialize(r) for r in rows]


def _is_inactive(c: CrmContact) -> bool:
    """SuiteCRM no trae una columna de estado: los contactos dados de baja llevan «INACTIVO» en el nombre. No se ofrecen para elegir."""
    return "inactiv" in _full_name(c).lower()


def _account_contacts(db: Session, tenant_id: str) -> List[CrmContact]:
    acc = db.query(CrmAccount).filter(CrmAccount.tenant_id == tenant_id, CrmAccount.archived_at.is_(None)).first() if tenant_id else None
    if acc is None:
        return []
    rows = db.query(CrmContact).filter(CrmContact.account_id == acc.id, CrmContact.archived_at.is_(None)).order_by(CrmContact.is_primary.desc(), CrmContact.id).all()
    return [c for c in rows if not _is_inactive(c)]


def crm_options(db: Session, tenant_id: str) -> List[dict]:
    """Contactos de la cuenta del CRM de este cliente, para elegirlos al crear o editar el evento (el principal de la cuenta, primero)."""
    return [{"crm_contact_id": c.id, "name": _full_name(c) or (c.email or ""), "phone": c.mobile or c.phone or "", "email": c.email or "", "job_title": c.job_title or "", "is_primary": bool(c.is_primary)}
            for c in _account_contacts(db, tenant_id)]


def default_from_crm(db: Session, tenant_id: str) -> List[dict]:
    """Por defecto: el contacto principal de la cuenta del CRM, como principal del evento. Vacío si el cliente no tiene cuenta o contactos en el CRM."""
    opts = crm_options(db, tenant_id)
    if not opts:
        return []
    o = opts[0]
    return [{"crm_contact_id": o["crm_contact_id"], "name": o["name"], "phone": o["phone"], "email": o["email"], "note": "", "is_primary": True}]


def clean(items, allowed_crm_ids: Optional[set] = None) -> List[dict]:
    """Valida la lista: hasta 10, nombre obligatorio, correo con forma de correo (si lo trae), exactamente un principal (si ninguno lo marca, el primero)."""
    if items is None:
        return []
    if not isinstance(items, list):
        raise ContactError("Los contactos del evento deben ser una lista.")
    if len(items) > MAX_CONTACTS:
        raise ContactError(f"Un evento admite hasta {MAX_CONTACTS} contactos.")
    out, seen_primary = [], 0
    for i, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            raise ContactError("Cada contacto debe tener nombre, teléfono y correo.")
        name = str(raw.get("name") or "").strip()[:NAME_MAX]
        if not name:
            raise ContactError(f"El contacto {i} necesita un nombre.")
        email_raw = str(raw.get("email") or "").strip()
        email = valid_email(email_raw)
        if email_raw and not email:
            raise ContactError(f"El correo del contacto «{name}» no parece un correo válido.")
        crm_id = raw.get("crm_contact_id")
        crm_id = int(crm_id) if isinstance(crm_id, int) and not isinstance(crm_id, bool) and (allowed_crm_ids is None or crm_id in allowed_crm_ids) else None
        phone_raw = str(raw.get("phone") or "").strip()
        if crm_id is None and (not phone_raw or not email):          # a mano (no está en el CRM): teléfono y correo obligatorios
            raise ContactError(f"El contacto «{name}» no está en el CRM: escribe su teléfono y su correo.")
        primary = bool(raw.get("is_primary"))
        seen_primary += 1 if primary else 0
        out.append({"crm_contact_id": crm_id, "name": name, "phone": str(raw.get("phone") or "").strip()[:PHONE_MAX] or None, "email": email or None,
                    "note": str(raw.get("note") or "").strip()[:NOTE_MAX] or None, "is_primary": primary})
    if seen_primary > 1:
        raise ContactError("Solo un contacto puede ser el principal.")
    if out and not seen_primary:
        out[0]["is_primary"] = True
    return out


def replace(db: Session, event, items) -> List[dict]:
    """Deja exactamente `items` como los contactos del evento (reemplaza lo anterior)."""
    allowed = {c.id for c in _account_contacts(db, event.tenant_id)}
    allowed |= {r[0] for r in db.query(EventContact.crm_contact_id).filter(EventContact.event_id == event.id, EventContact.crm_contact_id.isnot(None))}          # los que ya tenía siguen siendo del CRM aunque hoy estén dados de baja
    rows = clean(items, allowed)
    db.query(EventContact).filter(EventContact.event_id == event.id).delete(synchronize_session=False)
    db.flush()
    for pos, r in enumerate(rows):
        db.add(EventContact(event_id=event.id, position=pos, **r))
    db.flush()
    return list_for(db, event.id)


def copy_to(db: Session, src_event_id: int, dst_event_id: int) -> int:
    n = 0
    for r in db.query(EventContact).filter(EventContact.event_id == src_event_id).order_by(EventContact.position, EventContact.id):
        db.add(EventContact(event_id=dst_event_id, crm_contact_id=r.crm_contact_id, name=r.name, phone=r.phone, email=r.email, note=r.note, is_primary=r.is_primary, position=r.position))
        n += 1
    db.flush()
    return n


def primary(db: Session, event_id: int) -> Optional[dict]:
    """El contacto principal del evento con correo válido ({name, email, phone}); None si no hay principal o no tiene correo."""
    c = db.query(EventContact).filter(EventContact.event_id == event_id, EventContact.is_primary.is_(True)).first()
    mail = valid_email(c.email) if c is not None else ""
    return {"name": c.name, "email": mail, "phone": c.phone or ""} if c is not None and mail else None
