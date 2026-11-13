"""Supresión de un lead (Ley 1581), con el mismo criterio que los contactos (app/crm/erase.py): se borra todo lo que el CRM guarda de la persona y se devuelven SOLO conteos, nunca valores.

Un lead deja rastro en cuatro sitios:
  1. su fila (`crm_leads`);
  2. sus actividades (`crm_activities` con `lead_id`; la base también las borra en cascada);
  3. su historial (`crm_change_log`, entidad `lead`);
  4. si fue convertido, la copia de sus datos en el CONTACTO creado: no se borra aquí (puede ser un contacto que ya se usa) pero se avisa en `review.converted_contact` para que un administrador
     lo suprima con «Suprimir sus datos» del contacto.
Lo que no se puede encontrar con certeza es el texto libre de la cuenta y la oportunidad a las que pasó (notas, descripción, siguiente paso, actividades): se cuenta cuántas veces parece mencionarse
y se devuelve en `review` para que una persona lo revise. Sin commit propio.
"""
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.crm.matching import identifiers, mentions
from app.models import CrmActivity, CrmChangeLog, CrmContact, CrmLead, CrmNote, CrmOpportunity


def lead_identifiers(lead: CrmLead) -> dict:
    """Con qué se reconoce al lead en otros textos. `identifiers` espera un contacto (con `mobile`): se le arma uno equivalente."""
    return identifiers(SimpleNamespace(first_name=lead.first_name, last_name=lead.last_name, email=lead.email, phone=lead.phone, mobile=None))


def _review(db: Session, lead: CrmLead, ids: dict) -> dict:
    out = {"converted_contact": False, "account_notes": 0, "account_activities": 0, "opportunity_texts": 0}
    if lead.converted_contact_id is not None:
        out["converted_contact"] = db.get(CrmContact, lead.converted_contact_id) is not None
    account_id = lead.converted_account_id
    if account_id is None:
        return out
    notes = db.execute(select(CrmNote.body).where(CrmNote.account_id == account_id).limit(2000)).scalars().all()
    out["account_notes"] = sum(1 for body in notes if mentions(body, ids))
    acts = db.execute(select(CrmActivity.subject, CrmActivity.description).where(CrmActivity.account_id == account_id, CrmActivity.lead_id.is_(None)).limit(2000)).all()
    out["account_activities"] = sum(1 for subject, description in acts if mentions(subject, ids) or mentions(description, ids))
    opps = db.execute(select(CrmOpportunity.description, CrmOpportunity.next_step).where(CrmOpportunity.account_id == account_id).limit(2000)).all()
    out["opportunity_texts"] = sum(1 for description, next_step in opps if mentions(description, ids) or mentions(next_step, ids))
    return out


def preview_lead(db: Session, lead_id: int) -> Optional[dict]:
    """Adelanto de la supresión (no borra nada). None si el lead no existe."""
    lead = db.get(CrmLead, lead_id)
    if lead is None:
        return None
    return {"leads": 1,
            "activities": db.execute(select(func.count()).select_from(CrmActivity).where(CrmActivity.lead_id == lead_id)).scalar() or 0,
            "changes": db.execute(select(func.count()).select_from(CrmChangeLog).where(CrmChangeLog.entity == "lead", CrmChangeLog.entity_id == lead_id)).scalar() or 0,
            "review": _review(db, lead, lead_identifiers(lead))}


def erase_lead(db: Session, lead_id: int) -> dict:
    """Borra el lead, sus actividades y su historial. Devuelve conteos y `review` (sin datos personales)."""
    lead = db.get(CrmLead, lead_id)
    if lead is None:
        return {"leads": 0, "activities": 0, "changes": 0, "review": {"converted_contact": False, "account_notes": 0, "account_activities": 0, "opportunity_texts": 0}}
    review = _review(db, lead, lead_identifiers(lead))
    out = {"leads": 1}
    out["activities"] = db.execute(delete(CrmActivity).where(CrmActivity.lead_id == lead_id)).rowcount
    out["changes"] = db.execute(delete(CrmChangeLog).where(CrmChangeLog.entity == "lead", CrmChangeLog.entity_id == lead_id)).rowcount
    out["review"] = review
    db.delete(lead)
    db.flush()
    return out
