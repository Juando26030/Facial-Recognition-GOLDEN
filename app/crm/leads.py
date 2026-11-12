"""Leads del CRM (C2): clientes potenciales y su conversión en cuenta + contacto (+ oportunidad). Sin commit propio.

* DATOS PERSONALES (Ley 1581): nombre, correo y teléfono. Se suprimen con `app/crm/lead_erase.py`, que sigue el mismo criterio que los contactos.
* `full_name_norm` y `email_norm` se escriben SOLO desde aquí (una sola puerta, como en accounts.py); `full_name_norm` incluye también la empresa para que la búsqueda encuentre por ambos.
* La conversión es UNA transacción: cuenta (nueva o existente), contacto, oportunidad opcional y marca del lead. Un lead se convierte una sola vez.
"""
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.crm import accounts, history, normalize, opportunities
from app.crm.accounts import MAX_ID, MAX_PAGE, NORM_MAX, PAGE_SIZE, _check_owner, _check_version, _like
from app.crm.errors import CrmError
from app.crm.pipeline_rules import LEAD_STATUSES, check_convertible, clean_lead, lead_has_identity
from app.models import CrmAccount, CrmLead, StaffUser
from app.timeutil import utcnow


def get_lead(db: Session, lead_id: int) -> CrmLead:
    lead = db.get(CrmLead, lead_id) if 0 < lead_id <= MAX_ID else None
    if lead is None:
        raise CrmError("Lead no encontrado.", 404)
    return lead


def lead_name(lead: CrmLead) -> str:
    return " ".join(p for p in ((lead.first_name or "").strip(), (lead.last_name or "").strip()) if p)


def _norms(lead: CrmLead) -> None:
    lead.full_name_norm = normalize(" ".join(p for p in (lead_name(lead), lead.company_name or "") if p))[:NORM_MAX["full_name_norm"]]
    lead.email_norm = normalize(lead.email)[:NORM_MAX["email_norm"]] or None


def create_lead(db: Session, staff: StaffUser, data: dict, *, confirm_duplicate: bool = False) -> CrmLead:
    fields = clean_lead(data, creating=True)
    if not lead_has_identity(fields.get("first_name"), fields.get("last_name"), fields.get("company_name"), fields.get("email")):
        raise CrmError("El lead necesita al menos un nombre, una empresa o un correo.")
    _check_owner(db, fields.get("owner_staff_id"))
    if fields.get("owner_staff_id") is None:                      # el formulario manda null cuando se deja «Yo»: se guarda quien crea
        fields["owner_staff_id"] = staff.id
    fields.setdefault("status", "nuevo")
    lead = CrmLead(created_by_id=staff.id, **fields)
    _norms(lead)
    if lead.email_norm and not confirm_duplicate:
        twin = db.query(CrmLead.id).filter(CrmLead.email_norm == lead.email_norm, CrmLead.archived_at.is_(None), CrmLead.status != "descartado").first()
        if twin is not None:
            raise CrmError("Ya hay un lead con ese correo. Si de verdad es otro, confirma el duplicado.", 409)
    db.add(lead)
    db.flush()
    return lead


def update_lead(db: Session, staff: StaffUser, lead: CrmLead, data: dict, expected_updated_at: Optional[str]) -> CrmLead:
    _check_version(lead, expected_updated_at)
    if lead.status == "convertido":
        raise CrmError("Este lead ya fue convertido: sus datos viven ahora en la cuenta y el contacto.", 409)
    fields = clean_lead(data, creating=False)
    _check_owner(db, fields.get("owner_staff_id"))
    before = history.snapshot(lead, "lead")
    for key, value in fields.items():
        setattr(lead, key, value)
    if not lead_has_identity(lead.first_name, lead.last_name, lead.company_name, lead.email):
        raise CrmError("El lead necesita al menos un nombre, una empresa o un correo.")
    _norms(lead)
    if history.record(db, lead, "lead", before, staff_id=staff.id):
        lead.updated_at = utcnow()
    db.flush()
    return lead


def set_archived(db: Session, staff: StaffUser, lead: CrmLead, archived: bool) -> CrmLead:
    if archived == (lead.archived_at is not None):
        raise CrmError("El lead ya está archivado." if archived else "El lead no está archivado.")
    before = history.snapshot(lead, "lead")
    lead.archived_at = utcnow() if archived else None
    history.record(db, lead, "lead", before, staff_id=staff.id)
    lead.updated_at = utcnow()
    db.flush()
    return lead


def discard(db: Session, staff: StaffUser, lead: CrmLead) -> CrmLead:
    if lead.status == "convertido":
        raise CrmError("Este lead ya fue convertido.", 409)
    if lead.status == "descartado":
        raise CrmError("El lead ya estaba descartado.", 409)
    before = history.snapshot(lead, "lead")
    lead.status = "descartado"
    history.record(db, lead, "lead", before, staff_id=staff.id)
    lead.updated_at = utcnow()
    db.flush()
    return lead


# ------------------------------------------------------------------ conversión
def convert(db: Session, staff: StaffUser, lead: CrmLead, data: dict) -> dict:
    """Convierte el lead. `data`: `account_id` (usar una cuenta existente) o `account_name` (crear; por omisión la empresa del lead), `confirm_duplicate`, y si se quiere oportunidad:
    `create_opportunity` + sus campos (`name`, `amount`, `currency`, `expected_close`, `event_start`, `city`, `opp_type`). Todo en una transacción; si algo falla no queda nada."""
    check_convertible(lead.status)
    if data.get("account_id") not in (None, ""):
        account = accounts.get_account(db, int(data["account_id"])) if str(data["account_id"]).isdigit() else None
        if account is None:
            raise CrmError("La cuenta elegida no existe.")
        if account.archived_at is not None:
            raise CrmError("La cuenta elegida está archivada.")
        account_created = False
    else:
        name = (data.get("account_name") or lead.company_name or lead_name(lead) or "").strip()
        if not name:
            raise CrmError("Escribe el nombre de la cuenta: el lead no tiene empresa.")
        account = accounts.create_account(db, staff, {"name": name, "owner_staff_id": lead.owner_staff_id or staff.id}, confirm_duplicate=bool(data.get("confirm_duplicate")))
        account_created = True
    contact = None
    if lead.first_name or lead.last_name:
        contact = accounts.create_contact(db, staff, account, {"first_name": lead.first_name, "last_name": lead.last_name, "job_title": lead.job_title, "email": lead.email, "phone": lead.phone})
    opportunity = None
    if data.get("create_opportunity"):
        opp_data = {k: data[k] for k in ("name", "amount", "currency", "expected_close", "event_start", "city", "opp_type") if k in data}
        opp_data.setdefault("name", account.name)
        opp_data.update({"account_id": account.id, "owner_staff_id": lead.owner_staff_id or staff.id, "source": lead.source})
        if contact is not None:
            opp_data["primary_contact_id"] = contact.id
        opportunity = opportunities.create_opportunity(db, staff, opp_data)
    before = history.snapshot(lead, "lead")
    lead.status = "convertido"
    lead.converted_at = utcnow()
    lead.converted_account_id = account.id
    lead.converted_contact_id = contact.id if contact is not None else None
    lead.converted_opportunity_id = opportunity.id if opportunity is not None else None
    history.record(db, lead, "lead", before, staff_id=staff.id)
    lead.updated_at = utcnow()
    db.flush()
    return {"account_id": account.id, "account_code": account.code, "account_created": account_created, "contact_id": contact.id if contact is not None else None,
            "opportunity_id": opportunity.id if opportunity is not None else None, "opportunity_code": opportunity.code if opportunity is not None else None}


# ------------------------------------------------------------------ lectura
def serialize(lead: CrmLead, owner_name: Optional[str] = None, *, detail: bool = False) -> dict:
    out = {"id": lead.id, "full_name": lead_name(lead), "company_name": lead.company_name, "email": lead.email, "phone": lead.phone, "source": lead.source, "status": lead.status,
           "owner_staff_id": lead.owner_staff_id, "owner_name": owner_name, "archived": lead.archived_at is not None, "converted_account_id": lead.converted_account_id,
           "converted_contact_id": lead.converted_contact_id, "converted_opportunity_id": lead.converted_opportunity_id, "created_at": lead.created_at.isoformat(), "updated_at": lead.updated_at.isoformat()}
    if detail:
        out.update({"first_name": lead.first_name, "last_name": lead.last_name, "job_title": lead.job_title, "description": lead.description,
                    "converted_at": lead.converted_at.isoformat() if lead.converted_at else None})
    return out


def list_leads(db: Session, *, q: str = "", status: str = "", owner_id: Optional[int] = None, archived: bool = False, page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmLead, StaffUser.full_name).join(StaffUser, StaffUser.id == CrmLead.owner_staff_id, isouter=True)
    query = query.filter(CrmLead.archived_at.isnot(None) if archived else CrmLead.archived_at.is_(None))
    if status:
        if status not in LEAD_STATUSES:
            return {"items": [], "total": 0, "page": 1, "size": size}
        query = query.filter(CrmLead.status == status)
    if owner_id:
        if not 0 < owner_id <= MAX_ID:
            return {"items": [], "total": 0, "page": 1, "size": size}
        query = query.filter(CrmLead.owner_staff_id == owner_id)
    norm = normalize((q or "")[:200])
    if norm:
        query = query.filter(or_(CrmLead.full_name_norm.like(_like(norm), escape="\\"), CrmLead.email_norm.like(_like(norm), escape="\\")))
    total = query.count()
    size = max(1, min(int(size or PAGE_SIZE), 200))
    page = max(1, min(int(page or 1), MAX_PAGE))
    rows = query.order_by(CrmLead.created_at.desc(), CrmLead.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"items": [serialize(lead, name) for lead, name in rows], "total": total, "page": page, "size": size}


def detail(db: Session, lead: CrmLead) -> dict:
    owner = db.query(StaffUser.full_name).filter(StaffUser.id == lead.owner_staff_id).first() if lead.owner_staff_id else None
    out = serialize(lead, owner[0] if owner else None, detail=True)
    if lead.converted_account_id:
        acc = db.get(CrmAccount, lead.converted_account_id)
        out["converted_account_name"] = acc.name if acc is not None else None
    return out
