"""Servicios de productos, condiciones, plantillas, cotizaciones y proformas del CRM (C3). Hablan con la base; las reglas puras viven en quote_rules.py. Sin commit propio (lo hace `_run` del router).

* Una cotización nueva toma su número de `next_code(db, "quote")`; una VERSIÓN nueva copia las líneas, repite el número y sube `version` (la anterior queda intacta).
* Los totales se recalculan SIEMPRE en el servidor con `quote_rules.totals` al guardar las líneas; nunca se confía en los que manda el navegador.
* Edición concurrente por `updated_at` (409). El texto libre `meeting_notes` no se guarda en el historial.
* El PDF se genera bajo demanda (app/crm/quote_pdf.py) y se guarda con `get_storage()` en `crm/quotes/<id>/`; se borra al suprimir al contacto de la cotización.
"""
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crm import history, normalize
from app.crm import quote_rules as qr
from app.crm.accounts import MAX_ID, _check_owner, _check_version, get_account
from app.crm.codes import next_code
from app.crm.errors import CrmError
from app.models import (CrmAccount, CrmContact, CrmDocTemplate, CrmOpportunity, CrmProduct, CrmProforma, CrmQuote, CrmQuoteLine, CrmTerm, StaffUser)
from app.timeutil import utcnow

PAGE_SIZE = 50
MAX_PAGE = 10_000


def _get(db: Session, model, obj_id, label: str):
    obj = db.get(model, obj_id) if isinstance(obj_id, int) and 0 < obj_id <= MAX_ID else None
    if obj is None:
        raise CrmError(f"{label} no encontrado.", 404)
    return obj


def _page(page, size):
    return max(1, min(int(page or 1), MAX_PAGE)), max(1, min(int(size or PAGE_SIZE), 200))


# ------------------------------------------------------------------ productos
def serialize_product(p: CrmProduct) -> dict:
    return {"id": p.id, "sku": p.sku, "name": p.name, "description": p.description, "category": p.category, "cost": str(p.cost), "price": str(p.price), "currency": p.currency,
            "tax_percent": str(p.tax_percent), "active": p.active, "updated_at": p.updated_at.isoformat()}


def _check_sku(db: Session, sku: Optional[str], own_id: Optional[int] = None) -> None:
    if sku:
        q = db.query(CrmProduct.id).filter(CrmProduct.sku == sku)
        if own_id:
            q = q.filter(CrmProduct.id != own_id)
        if q.first():
            raise CrmError("Ya existe un producto con ese código (SKU).", 409)


def create_product(db: Session, data: dict) -> CrmProduct:
    fields = qr.clean_product(data, creating=True)
    _check_sku(db, fields.get("sku"))
    p = CrmProduct(name_norm=normalize(fields["name"])[:200], **fields)
    db.add(p)
    db.flush()
    return p


def update_product(db: Session, product_id: int, data: dict, expected: Optional[str]) -> CrmProduct:
    p = _get(db, CrmProduct, product_id, "Producto")
    _check_version(p, expected)
    fields = qr.clean_product(data)
    _check_sku(db, fields.get("sku"), p.id)
    for k, v in fields.items():
        setattr(p, k, v)
    if "name" in fields:
        p.name_norm = normalize(p.name)[:200]
    p.updated_at = utcnow()
    db.flush()
    return p


def list_products(db: Session, *, q: str = "", category: str = "", active: Optional[bool] = None, page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmProduct)
    if q.strip():
        n = normalize(q)
        query = query.filter(CrmProduct.name_norm.like(f"%{n}%") | (func.lower(CrmProduct.sku) == q.strip().lower()))
    if category:
        query = query.filter(CrmProduct.category == category)
    if active is not None:
        query = query.filter(CrmProduct.active == active)
    total = query.count()
    page, size = _page(page, size)
    rows = query.order_by(CrmProduct.name_norm, CrmProduct.id).offset((page - 1) * size).limit(size).all()
    return {"items": [serialize_product(p) for p in rows], "total": total, "page": page, "size": size}


# ------------------------------------------------------------------ condiciones y plantillas
def serialize_term(t: CrmTerm) -> dict:
    return {"id": t.id, "name": t.name, "body": t.body, "position": t.position, "archived": t.archived_at is not None}


def list_terms(db: Session, include_archived: bool = False) -> list:
    q = db.query(CrmTerm)
    if not include_archived:
        q = q.filter(CrmTerm.archived_at.is_(None))
    return [serialize_term(t) for t in q.order_by(CrmTerm.position, CrmTerm.id).all()]


def create_term(db: Session, data: dict) -> CrmTerm:
    t = CrmTerm(position=(db.query(func.coalesce(func.max(CrmTerm.position), 0)).scalar() or 0) + 1, **qr.clean_term(data, creating=True))
    db.add(t)
    db.flush()
    return t


def update_term(db: Session, term_id: int, data: dict) -> CrmTerm:
    t = _get(db, CrmTerm, term_id, "Condición")
    for k, v in qr.clean_term(data).items():
        setattr(t, k, v)
    if "archived" in data:
        t.archived_at = utcnow() if data["archived"] else None
    db.flush()
    return t


def serialize_template(t: CrmDocTemplate) -> dict:
    return {"id": t.id, "kind": t.kind, "name": t.name, "header_text": t.header_text, "greeting_text": t.greeting_text, "footer_text": t.footer_text, "is_default": t.is_default, "archived": t.archived_at is not None}


def list_templates(db: Session, kind: str = "") -> list:
    q = db.query(CrmDocTemplate).filter(CrmDocTemplate.archived_at.is_(None))
    if kind:
        q = q.filter(CrmDocTemplate.kind == kind)
    return [serialize_template(t) for t in q.order_by(CrmDocTemplate.kind, CrmDocTemplate.id).all()]


def create_template(db: Session, data: dict) -> CrmDocTemplate:
    fields = qr.clean_template(data, creating=True)
    first = db.query(CrmDocTemplate.id).filter(CrmDocTemplate.kind == fields["kind"], CrmDocTemplate.archived_at.is_(None)).first() is None
    t = CrmDocTemplate(is_default=first, **fields)
    db.add(t)
    db.flush()
    return t


def update_template(db: Session, template_id: int, data: dict) -> CrmDocTemplate:
    t = _get(db, CrmDocTemplate, template_id, "Plantilla")
    for k, v in qr.clean_template(data).items():
        if k != "kind":
            setattr(t, k, v)
    if data.get("is_default") and not t.is_default:
        db.query(CrmDocTemplate).filter(CrmDocTemplate.kind == t.kind, CrmDocTemplate.is_default.is_(True)).update({"is_default": False})
        db.flush()
        t.is_default = True
    db.flush()
    return t


def default_template(db: Session, kind: str) -> Optional[CrmDocTemplate]:
    return db.query(CrmDocTemplate).filter(CrmDocTemplate.kind == kind, CrmDocTemplate.is_default.is_(True), CrmDocTemplate.archived_at.is_(None)).first()


# ------------------------------------------------------------------ cotizaciones
def get_quote(db: Session, quote_id: int) -> CrmQuote:
    return _get(db, CrmQuote, quote_id, "Cotización")


def lines_of(db: Session, quote_id: int) -> list:
    return db.query(CrmQuoteLine).filter(CrmQuoteLine.quote_id == quote_id).order_by(CrmQuoteLine.position, CrmQuoteLine.id).all()


def serialize_line(ln: CrmQuoteLine) -> dict:
    return {"id": ln.id, "position": ln.position, "product_id": ln.product_id, "name": ln.name, "description": ln.description, "qty": str(ln.qty), "unit_price": str(ln.unit_price),
            "discount_percent": str(ln.discount_percent), "tax_percent": str(ln.tax_percent), "line_total": str(ln.line_total)}


def serialize_quote(q: CrmQuote, *, account_name=None, contact_name=None, owner_name=None, today: Optional[date] = None) -> dict:
    today = today or utcnow().date()
    return {"id": q.id, "number": q.number, "version": q.version, "parent_quote_id": q.parent_quote_id, "account_id": q.account_id, "account_name": account_name, "contact_id": q.contact_id,
            "contact_name": contact_name, "opportunity_id": q.opportunity_id, "title": q.title, "stage": q.stage, "expired": qr.is_expired(q.stage, q.valid_until, today),
            "approval_status": q.approval_status, "invoice_status": q.invoice_status, "currency": q.currency, "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "event_start": q.event_start.isoformat() if q.event_start else None, "terms_id": q.terms_id, "template_id": q.template_id, "subtotal": str(q.subtotal), "discount_total": str(q.discount_total),
            "tax_total": str(q.tax_total), "total": str(q.total), "has_pdf": bool(q.pdf_key), "sent_at": q.sent_at.isoformat() if q.sent_at else None, "owner_staff_id": q.owner_staff_id,
            "owner_name": owner_name, "archived": q.archived_at is not None, "created_at": q.created_at.isoformat(), "updated_at": q.updated_at.isoformat()}


def quote_detail(db: Session, q: CrmQuote) -> dict:
    account = db.get(CrmAccount, q.account_id)
    contact = db.get(CrmContact, q.contact_id) if q.contact_id else None
    owner = db.get(StaffUser, q.owner_staff_id) if q.owner_staff_id else None
    out = serialize_quote(q, account_name=account.name if account else None, contact_name=" ".join(p for p in ((contact.first_name or ""), (contact.last_name or "")) if p).strip() if contact else None,
                          owner_name=owner.full_name if owner else None)
    out.update({"terms_text": q.terms_text, "meeting_notes": q.meeting_notes, "lines": [serialize_line(ln) for ln in lines_of(db, q.id)],
                "versions": [{"id": r.id, "version": r.version, "stage": r.stage} for r in db.query(CrmQuote.id, CrmQuote.version, CrmQuote.stage).filter(CrmQuote.number == q.number).order_by(CrmQuote.version).all()]})
    return out


def _check_links(db: Session, account: CrmAccount, fields: dict) -> None:
    if fields.get("contact_id"):
        c = db.get(CrmContact, fields["contact_id"])
        if c is None or c.account_id != account.id:
            raise CrmError("El contacto no pertenece a la cuenta de la cotización.")
    if fields.get("opportunity_id"):
        o = db.get(CrmOpportunity, fields["opportunity_id"])
        if o is None or o.account_id != account.id:
            raise CrmError("La oportunidad no pertenece a la cuenta de la cotización.")
    if fields.get("terms_id") and db.get(CrmTerm, fields["terms_id"]) is None:
        raise CrmError("La condición comercial elegida no existe.")
    if fields.get("template_id") and db.get(CrmDocTemplate, fields["template_id"]) is None:
        raise CrmError("La plantilla elegida no existe.")
    _check_owner(db, fields.get("owner_staff_id"))


def _apply_lines(db: Session, q: CrmQuote, raw_lines) -> None:
    cleaned = qr.clean_lines(raw_lines)
    for c in cleaned:
        if c["product_id"] is not None and db.get(CrmProduct, c["product_id"]) is None:
            c["product_id"] = None
    db.query(CrmQuoteLine).filter(CrmQuoteLine.quote_id == q.id).delete()
    for c in cleaned:
        a = qr.line_amounts(c["qty"], c["unit_price"], c["discount_percent"], c["tax_percent"])
        db.add(CrmQuoteLine(quote_id=q.id, line_total=a["net"], **c))
    t = qr.totals(cleaned)
    q.subtotal, q.discount_total, q.tax_total, q.total = t["subtotal"], t["discount_total"], t["tax_total"], t["total"]
    _drop_pdf(q)


def _drop_pdf(q: CrmQuote) -> None:
    """Al cambiar la cotización el PDF guardado deja de valer: se olvida y se borra del almacenamiento."""
    if q.pdf_key:
        from app.storage import get_storage
        try:
            get_storage().delete(q.pdf_key)
        except Exception:
            pass
    q.pdf_key, q.pdf_generated_at = None, None


def create_quote(db: Session, staff: StaffUser, data: dict) -> CrmQuote:
    account = get_account(db, int(data["account_id"])) if str(data.get("account_id") or "").isdigit() else None
    if account is None:
        raise CrmError("Elige la cuenta de la cotización.")
    fields = qr.clean_quote(data, creating=True)
    if fields.get("opportunity_id"):                       # hereda de la oportunidad lo que no se indicó
        opp = db.get(CrmOpportunity, fields["opportunity_id"])
        if opp is not None and opp.account_id == account.id:
            fields.setdefault("currency", opp.currency)
            fields.setdefault("contact_id", opp.primary_contact_id)
            fields.setdefault("event_start", opp.event_start)
    _check_links(db, account, fields)
    fields.setdefault("currency", "COP")
    fields.setdefault("owner_staff_id", staff.id)
    tpl = default_template(db, "quote")
    fields.setdefault("template_id", tpl.id if tpl else None)
    if fields.get("terms_id") and "terms_text" not in fields:
        fields["terms_text"] = db.get(CrmTerm, fields["terms_id"]).body
    q = CrmQuote(number=next_code(db, "quote"), version=1, account_id=account.id, created_by_id=staff.id, **fields)
    db.add(q)
    db.flush()
    _apply_lines(db, q, data.get("lines") or [])
    db.flush()
    return q


def update_quote(db: Session, staff: StaffUser, q: CrmQuote, data: dict, expected: Optional[str]) -> CrmQuote:
    _check_version(q, expected)
    if q.archived_at is not None:
        raise CrmError("La cotización está archivada.")
    fields = qr.clean_quote(data)
    account = db.get(CrmAccount, q.account_id)
    _check_links(db, account, fields)
    if fields.get("terms_id") and "terms_text" not in fields and fields["terms_id"] != q.terms_id:
        fields["terms_text"] = db.get(CrmTerm, fields["terms_id"]).body
    before = history.snapshot(q, "quote")
    for k, v in fields.items():
        setattr(q, k, v)
    if "lines" in data:
        _apply_lines(db, q, data["lines"])
    else:
        _drop_pdf(q)
    history.record(db, q, "quote", before, staff_id=staff.id)
    q.updated_at = utcnow()
    db.flush()
    return q


def set_stage(db: Session, staff: StaffUser, q: CrmQuote, new_stage: str, expected: Optional[str] = None) -> CrmQuote:
    if expected is not None:
        _check_version(q, expected)
    qr.check_stage(q.stage, new_stage)
    before = history.snapshot(q, "quote")
    q.stage = new_stage
    if new_stage == "enviada" and q.sent_at is None:
        q.sent_at = utcnow()
    if new_stage in ("aprobada", "rechazada"):
        q.approval_status = new_stage
    history.record(db, q, "quote", before, staff_id=staff.id)
    q.updated_at = utcnow()
    db.flush()
    return q


def new_version(db: Session, staff: StaffUser, q: CrmQuote) -> CrmQuote:
    """Copia la cotización como versión N+1 (mismo número) en borrador; la anterior no se toca."""
    last = db.query(func.max(CrmQuote.version)).filter(CrmQuote.number == q.number).scalar() or q.version
    fields = {c: getattr(q, c) for c in ("account_id", "contact_id", "opportunity_id", "title", "currency", "valid_until", "event_start", "terms_id", "terms_text", "meeting_notes", "template_id", "owner_staff_id")}
    nq = CrmQuote(number=q.number, version=last + 1, parent_quote_id=q.id, created_by_id=staff.id, stage="borrador", **fields)
    db.add(nq)
    db.flush()
    _apply_lines(db, nq, [{"product_id": ln.product_id, "name": ln.name, "description": ln.description, "qty": ln.qty, "unit_price": ln.unit_price, "discount_percent": ln.discount_percent,
                           "tax_percent": ln.tax_percent} for ln in lines_of(db, q.id)])
    db.flush()
    return nq


def set_archived(db: Session, staff: StaffUser, q: CrmQuote, archived: bool) -> CrmQuote:
    if archived == (q.archived_at is not None):
        raise CrmError("La cotización ya está archivada." if archived else "La cotización no está archivada.")
    before = history.snapshot(q, "quote")
    q.archived_at = utcnow() if archived else None
    history.record(db, q, "quote", before, staff_id=staff.id)
    q.updated_at = utcnow()
    db.flush()
    return q


def list_quotes(db: Session, *, q: str = "", stage: str = "", account_id: Optional[int] = None, opportunity_id: Optional[int] = None, owner_id: Optional[int] = None,
                archived: bool = False, page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmQuote).join(CrmAccount, CrmAccount.id == CrmQuote.account_id)
    query = query.filter(CrmQuote.archived_at.isnot(None) if archived else CrmQuote.archived_at.is_(None))
    if q.strip():
        n = normalize(q)
        query = query.filter(CrmAccount.name_norm.like(f"%{n}%") | func.lower(CrmQuote.title).like(f"%{q.strip().lower()}%") | (CrmQuote.number == int(q) if q.strip().isdigit() else False))
    if stage in qr.QUOTE_STAGES:
        query = query.filter(CrmQuote.stage == stage)
    if account_id:
        query = query.filter(CrmQuote.account_id == account_id)
    if opportunity_id:
        query = query.filter(CrmQuote.opportunity_id == opportunity_id)
    if owner_id:
        query = query.filter(CrmQuote.owner_staff_id == owner_id)
    total = query.count()
    page, size = _page(page, size)
    rows = (query.with_entities(CrmQuote, CrmAccount.name, StaffUser.full_name).join(StaffUser, StaffUser.id == CrmQuote.owner_staff_id, isouter=True)
            .order_by(CrmQuote.updated_at.desc(), CrmQuote.id.desc()).offset((page - 1) * size).limit(size).all())
    today = utcnow().date()
    return {"items": [serialize_quote(x, account_name=an, owner_name=on, today=today) for x, an, on in rows], "total": total, "page": page, "size": size}


# ------------------------------------------------------------------ proformas
def serialize_proforma(p: CrmProforma, account_name=None) -> dict:
    return {"id": p.id, "number": p.number, "quote_id": p.quote_id, "account_id": p.account_id, "account_name": account_name, "issued_at": p.issued_at.isoformat(), "due_at": p.due_at.isoformat() if p.due_at else None,
            "status": p.status, "event_name": p.event_name, "city": p.city, "currency": p.currency, "total": str(p.total), "has_pdf": bool(p.pdf_key), "updated_at": p.updated_at.isoformat()}


def create_proforma(db: Session, staff: StaffUser, q: CrmQuote, data: dict) -> CrmProforma:
    if q.stage not in ("aprobada", "enviada", "negociada"):
        raise CrmError("Solo se emite proforma de una cotización enviada, negociada o aprobada.")
    fields = qr.clean_proforma(data)
    opp = db.get(CrmOpportunity, q.opportunity_id) if q.opportunity_id else None
    fields.setdefault("event_name", (opp.name if opp else q.title)[:200])
    fields.setdefault("city", opp.city if opp else None)
    fields.setdefault("issued_at", utcnow().date())
    p = CrmProforma(number=next_code(db, "proforma"), quote_id=q.id, account_id=q.account_id, currency=q.currency, total=q.total, created_by_id=staff.id, **fields)
    db.add(p)
    db.flush()
    return p


def update_proforma(db: Session, staff: StaffUser, p: CrmProforma, data: dict, expected: Optional[str]) -> CrmProforma:
    _check_version(p, expected)
    for k, v in qr.clean_proforma(data).items():
        setattr(p, k, v)
    if p.pdf_key:
        from app.storage import get_storage
        try:
            get_storage().delete(p.pdf_key)
        except Exception:
            pass
        p.pdf_key = None
    p.updated_at = utcnow()
    db.flush()
    return p


def list_proformas(db: Session, *, account_id: Optional[int] = None, status: str = "", page: int = 1, size: int = PAGE_SIZE) -> dict:
    query = db.query(CrmProforma, CrmAccount.name).join(CrmAccount, CrmAccount.id == CrmProforma.account_id)
    if account_id:
        query = query.filter(CrmProforma.account_id == account_id)
    if status in qr.PROFORMA_STATUSES:
        query = query.filter(CrmProforma.status == status)
    total = query.count()
    page, size = _page(page, size)
    rows = query.order_by(CrmProforma.number.desc()).offset((page - 1) * size).limit(size).all()
    return {"items": [serialize_proforma(p, n) for p, n in rows], "total": total, "page": page, "size": size}
