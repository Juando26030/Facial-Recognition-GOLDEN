"""Supresión de datos del CRM (Ley 1581). Borrar un contacto quita sus datos de TODOS los sitios donde el CRM los guarda; sin commit propio. El flujo de la plataforma por cédula
(`privacy.erase_person`) NO cubre estos datos: ver docs/crm/README.md, «Solicitudes de supresión».

Un contacto deja rastro en cinco sitios:
  1. su fila y sus notas (`crm_contacts`, `crm_notes` por cascada);
  2. su propio historial (`crm_change_log`, entidad `contact`);
  3. el historial de la CUENTA, cuando alguien escribió sus datos en campos de la cuenta (correo, teléfono, contacto de facturación): se borran las filas que traen sus valores;
  4. los mismos campos de la cuenta, si hoy tienen sus valores: se dejan vacíos (sin escribir historial: el valor anterior es justo el dato a suprimir);
  5. la copia en `tenants.contact_name/phone/email` (regla del contacto principal): se vacía lo que coincida con sus valores.
Etapa C2 (docs/crm/ETAPA_C1C_C4_DISENO.md §6): además se borran las actividades del contacto (`contact_id`), se desvincula de las oportunidades donde era el contacto principal y se borran los LEADS que
tienen exactamente su correo (con sus actividades e historial: `app/crm/lead_erase.py`). Un lead que solo coincide por teléfono o por nombre NO se borra solo (podría ser un homónimo): se cuenta en `review`.
Lo que NO se puede encontrar con certeza es el texto libre (descripción de la cuenta, notas generales): se cuenta cuántas veces parece mencionarse y se devuelve en `review` para que una
persona lo revise. Todo se devuelve como conteos, nunca como valores.
"""
from typing import Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.crm import normalize
from app.crm.history import FREE_TEXT
from app.crm.matching import ACCOUNT_PERSONAL_FIELDS, digits, identifiers, mentions, value_matches
from app.models import CrmAccount, CrmActivity, CrmChangeLog, CrmContact, CrmLead, CrmNote, CrmOpportunity, CrmProforma, CrmQuote, EventContact, Tenant

def _history_hits(db: Session, account: CrmAccount, ids: dict) -> tuple:
    """Filas del historial de la cuenta que traen datos de esta persona: (ids a BORRAR, filas de texto libre a VACIAR).
    Campos con datos personales (correo, teléfonos, contacto de facturación): se borra la fila. Texto libre (descripción): la fila se conserva (queda constancia de que cambió) pero se le vacían
    los valores, porque nombran a la persona. Los cambios nuevos de texto libre ya se guardan sin valores (history.FREE_TEXT); esto limpia lo anterior."""
    free = FREE_TEXT["account"]
    rows = db.execute(select(CrmChangeLog).where(CrmChangeLog.entity == "account", CrmChangeLog.entity_id == account.id,
                                                CrmChangeLog.field_key.in_(ACCOUNT_PERSONAL_FIELDS + free))).scalars().all()
    drop = [r.id for r in rows if r.field_key in ACCOUNT_PERSONAL_FIELDS and (value_matches(r.field_key, r.old_value, ids) or value_matches(r.field_key, r.new_value, ids))]
    blank = [r for r in rows if r.field_key in free and (mentions(r.old_value, ids) or mentions(r.new_value, ids))]
    return drop, blank


def _scrub_account(db: Session, account: CrmAccount, ids: dict) -> dict:
    """Pasos 3 y 4: historial de la cuenta y valores actuales de la cuenta."""
    drop, blank = _history_hits(db, account, ids)
    removed = db.execute(delete(CrmChangeLog).where(CrmChangeLog.id.in_(drop))).rowcount if drop else 0
    for r in blank:
        r.old_value = r.new_value = None
    cleared = 0
    for f in ACCOUNT_PERSONAL_FIELDS:
        if value_matches(f, getattr(account, f), ids):
            setattr(account, f, None)
            cleared += 1
    return {"account_history": removed + len(blank), "account_fields": cleared}


def _erase_event_contacts(db: Session, contact_ids: list, emails=()) -> int:
    """Borra las copias de este contacto como contacto de eventos (event_contacts): las enlazadas por id y las que alguien escribió a mano con el mismo correo (Ley 1581)."""
    n = 0
    if contact_ids:
        n += db.execute(delete(EventContact).where(EventContact.crm_contact_id.in_(contact_ids))).rowcount
    mails = [e for e in emails if e]
    if mails:
        n += db.execute(delete(EventContact).where(func.lower(EventContact.email).in_([m.lower() for m in mails]))).rowcount
    return n


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


def review_hints(db: Session, account: CrmAccount, ids: dict, *, skip_contact_id: Optional[int] = None) -> dict:
    """Texto libre donde parece nombrarse a la persona: no se toca, se avisa. `opportunity_texts` = oportunidades de la cuenta cuya descripción o siguiente paso la mencionan;
    `activity_texts` = actividades de la cuenta (no las del contacto, que se borran) cuyo asunto o detalle la mencionan."""
    notes = db.execute(select(CrmNote.body).where(CrmNote.account_id == account.id, CrmNote.contact_id.is_(None)).limit(2000)).scalars().all()
    opps = db.execute(select(CrmOpportunity.description, CrmOpportunity.next_step).where(CrmOpportunity.account_id == account.id).limit(2000)).all()
    q = select(CrmActivity.subject, CrmActivity.description).where(CrmActivity.account_id == account.id)
    if skip_contact_id is not None:
        q = q.where((CrmActivity.contact_id.is_(None)) | (CrmActivity.contact_id != skip_contact_id))
    acts = db.execute(q.limit(2000)).all()
    return {"description": mentions(account.description, ids), "general_notes": sum(1 for b in notes if mentions(b, ids)),
            "opportunity_texts": sum(1 for d, n in opps if mentions(d, ids) or mentions(n, ids)),
            "activity_texts": sum(1 for sub, d in acts if mentions(sub, ids) or mentions(d, ids))}


def _empty_review() -> dict:
    return {"description": False, "general_notes": 0, "opportunity_texts": 0, "activity_texts": 0, "leads_to_check": 0, "quote_texts": 0}


def _delete_files(keys) -> None:
    """Borra del almacenamiento los PDF guardados (llevan el nombre de la persona o de la cuenta). Un fallo del almacenamiento no debe frenar la supresión de la base."""
    from app.storage import get_storage
    st = get_storage()
    for key in keys:
        if key:
            try:
                st.delete(key)
            except Exception:
                pass


def _quote_texts(db: Session, account_id: int, ids: dict) -> int:
    rows = db.execute(select(CrmQuote.meeting_notes, CrmQuote.terms_text, CrmQuote.title).where(CrmQuote.account_id == account_id)).all()
    return sum(1 for n, t, ti in rows if mentions(n, ids) or mentions(t, ids) or mentions(ti, ids))


def _leads_by_email(db: Session, ids: dict) -> list:
    """Leads con EXACTAMENTE el correo de esta persona (normalizado): los únicos que se borran solos."""
    if not ids["emails"]:
        return []
    return list(db.execute(select(CrmLead.id).where(CrmLead.email_norm.in_(ids["emails"]))).scalars().all())


def _leads_to_check(db: Session, ids: dict, exclude: list) -> int:
    """Leads que podrían ser la misma persona por nombre o por teléfono pero no por correo: se cuentan para revisión manual, no se tocan."""
    parts = []
    if ids["name"] and " " in ids["name"]:
        parts.append(CrmLead.full_name_norm == ids["name"])
        parts.append(CrmLead.full_name_norm.like(ids["name"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + " %", escape="\\"))
    if ids["phones"]:
        tails = {p[-7:] for p in ids["phones"]}
        digits_only = func.regexp_replace(CrmLead.phone, "[^0-9]", "", "g")
        for t in tails:
            parts.append(func.right(digits_only, 7) == t)
    if not parts:
        return 0
    q = select(func.count()).select_from(CrmLead).where(or_(*parts))
    if exclude:
        q = q.where(CrmLead.id.notin_(exclude))
    return db.execute(q).scalar() or 0


def erase_contact(db: Session, contact_id: int) -> dict:
    """Borra el contacto y todo su rastro (ver el encabezado). Devuelve conteos y `review` (sin datos personales)."""
    contact = db.get(CrmContact, contact_id)
    if contact is None:
        return {"contacts": 0, "notes": 0, "changes": 0, "account_history": 0, "account_fields": 0, "tenant_fields": 0, "activities": 0, "opportunities": 0, "leads": 0, "quotes": 0, "review": _empty_review()}
    from app.crm.lead_erase import erase_lead          # import tardío: lead_erase no depende de este módulo, pero así se evita un ciclo si algún día lo hace
    account = db.get(CrmAccount, contact.account_id)
    ids = identifiers(contact)
    out = {"contacts": 1}
    out["notes"] = db.execute(delete(CrmNote).where(CrmNote.contact_id == contact_id)).rowcount
    out["changes"] = db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id == contact_id)).rowcount
    out["activities"] = db.execute(delete(CrmActivity).where(CrmActivity.contact_id == contact_id)).rowcount
    out["opportunities"] = db.execute(update(CrmOpportunity).where(CrmOpportunity.primary_contact_id == contact_id).values(primary_contact_id=None)).rowcount
    quotes = db.execute(select(CrmQuote).where(CrmQuote.contact_id == contact_id)).scalars().all()          # cotizaciones dirigidas a él: sin contacto y sin PDF (el PDF trae su nombre)
    _delete_files(q.pdf_key for q in quotes)
    for q in quotes:
        q.contact_id, q.pdf_key, q.pdf_generated_at = None, None, None
    out["quotes"] = len(quotes)
    out.update(_scrub_account(db, account, ids) if account is not None else {"account_history": 0, "account_fields": 0})
    out["tenant_fields"] = _clear_tenant_mirror(db, account.tenant_id if account is not None else None, contact)
    _erase_event_contacts(db, [contact_id], ids["emails"])
    lead_ids = _leads_by_email(db, ids)
    out["leads"] = 0
    for lid in lead_ids:
        out["leads"] += erase_lead(db, lid)["leads"]
    review = review_hints(db, account, ids, skip_contact_id=contact_id) if account is not None else _empty_review()
    review["leads_to_check"] = _leads_to_check(db, ids, lead_ids)
    review["quote_texts"] = _quote_texts(db, account.id, ids) if account is not None else 0
    out["review"] = {**_empty_review(), **review}
    db.delete(contact)
    db.flush()
    return out


def erase_account(db: Session, account_id: int) -> dict:
    """Borra la cuenta con sus contactos, notas, oportunidades, actividades e historiales (de la cuenta, de cada contacto y de cada oportunidad) y vacía la copia de cada contacto en `tenants`.
    Las cotizaciones y proformas de la cuenta las cubre la pieza C3 al fusionarse."""
    account = db.get(CrmAccount, account_id)
    if account is None:
        return {"accounts": 0, "contacts": 0, "notes": 0, "changes": 0, "tenant_fields": 0, "opportunities": 0, "activities": 0, "quotes": 0, "proformas": 0}
    contacts = db.execute(select(CrmContact).where(CrmContact.account_id == account_id)).scalars().all()
    contact_ids = [c.id for c in contacts]
    opp_ids = list(db.execute(select(CrmOpportunity.id).where(CrmOpportunity.account_id == account_id)).scalars().all())
    tenant_fields = sum(_clear_tenant_mirror(db, account.tenant_id, c) for c in contacts)
    _erase_event_contacts(db, contact_ids, [e for c in contacts for e in identifiers(c)["emails"]])
    notes = db.execute(delete(CrmNote).where(CrmNote.account_id == account_id)).rowcount
    activities = db.execute(delete(CrmActivity).where(CrmActivity.account_id == account_id)).rowcount
    changes = 0
    if contact_ids:
        changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id.in_(contact_ids))).rowcount
    if opp_ids:
        changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "opportunity", CrmChangeLog.entity_id.in_(opp_ids))).rowcount
    changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "account", CrmChangeLog.entity_id == account_id)).rowcount
    quote_rows = db.execute(select(CrmQuote.id, CrmQuote.pdf_key).where(CrmQuote.account_id == account_id)).all()
    proforma_keys = list(db.execute(select(CrmProforma.pdf_key).where(CrmProforma.account_id == account_id)).scalars().all())
    quote_ids = [r[0] for r in quote_rows]
    _delete_files([r[1] for r in quote_rows] + proforma_keys)
    if quote_ids:
        changes += db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "quote", CrmChangeLog.entity_id.in_(quote_ids))).rowcount
    db.delete(account)          # sus contactos y oportunidades caen por cascada (la base; el ORM borra los ya cargados)
    db.flush()
    return {"accounts": 1, "contacts": len(contact_ids), "notes": notes, "changes": changes, "tenant_fields": tenant_fields, "opportunities": len(opp_ids), "activities": activities,
            "quotes": len(quote_ids), "proformas": len(proforma_keys)}


def preview_contact(db: Session, contact_id: int) -> Optional[dict]:
    """Lo mismo que `erase_contact` pero SIN tocar nada: cuántas cosas se borrarían y qué texto libre habría que revisar. Es el «adelanto» de la ventana de confirmación (C1b-3).
    Devuelve None si el contacto no existe. Solo conteos, nunca valores."""
    contact = db.get(CrmContact, contact_id)
    if contact is None:
        return None
    account = db.get(CrmAccount, contact.account_id)
    ids = identifiers(contact)
    lead_ids = _leads_by_email(db, ids)
    out = {"contacts": 1,
           "notes": db.execute(select(func.count()).select_from(CrmNote).where(CrmNote.contact_id == contact_id)).scalar() or 0,
           "changes": db.execute(select(func.count()).select_from(CrmChangeLog).where(CrmChangeLog.entity == "contact", CrmChangeLog.entity_id == contact_id)).scalar() or 0,
           "activities": db.execute(select(func.count()).select_from(CrmActivity).where(CrmActivity.contact_id == contact_id)).scalar() or 0,
           "opportunities": db.execute(select(func.count()).select_from(CrmOpportunity).where(CrmOpportunity.primary_contact_id == contact_id)).scalar() or 0,
           "leads": len(lead_ids), "account_history": 0, "account_fields": 0, "tenant_fields": 0, "review": _empty_review(),
           "quotes": db.execute(select(func.count()).select_from(CrmQuote).where(CrmQuote.contact_id == contact_id)).scalar() or 0}
    out["review"]["leads_to_check"] = _leads_to_check(db, ids, lead_ids)
    if account is None:
        return out
    drop, blank = _history_hits(db, account, ids)
    out["account_history"] = len(drop) + len(blank)
    out["account_fields"] = sum(1 for f in ACCOUNT_PERSONAL_FIELDS if value_matches(f, getattr(account, f), ids))
    tenant = db.get(Tenant, account.tenant_id) if account.tenant_id else None
    if tenant is not None:
        out["tenant_fields"] = ((1 if tenant.contact_name and normalize(tenant.contact_name) == ids["name"] else 0)
                                + (1 if tenant.contact_email and normalize(tenant.contact_email) in ids["emails"] else 0)
                                + (1 if tenant.contact_phone and digits(tenant.contact_phone) in ids["phones"] else 0))
    review = review_hints(db, account, ids, skip_contact_id=contact_id)
    out["review"] = {**_empty_review(), **review, "leads_to_check": out["review"]["leads_to_check"], "quote_texts": _quote_texts(db, account.id, ids)}
    return out
