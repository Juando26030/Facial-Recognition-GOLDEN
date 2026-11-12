"""API de productos, condiciones, plantillas, cotizaciones y proformas del CRM (C3). Con CRM_ENABLED apagado responde 404.
Comerciales y administradores usan cotizaciones y proformas; productos, condiciones y plantillas solo los edita un administrador (todos los leen). Cuerpos como dicts: cada campo lo valida `quote_rules`."""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import audit_actions
from app.crm import quote_pdf, quotes as svc
from app.database import get_db
from app.models import CrmAccount, CrmProforma, StaffUser
from app.routers import crm as crm_router
from app.routers.crm import _run, admin_staff, view_staff
from app.storage import get_storage
from app.timeutil import utcnow

router = APIRouter(prefix="/crm", tags=["crm-quotes"], dependencies=[Depends(crm_router._require_crm_enabled)])
router.dependencies.append(Depends(crm_router._check_path_ids))


def _expected(data: dict):
    return data.get("updated_at")


# ------------------------------------------------------------------ metadatos
@router.get("/quotes/meta")
def quotes_meta(db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    from app.crm import quote_rules as qr
    return {"stages": list(qr.QUOTE_STAGES), "approvals": list(qr.APPROVALS), "invoice_statuses": list(qr.INVOICE_STATUSES), "proforma_statuses": list(qr.PROFORMA_STATUSES), "currencies": list(qr.CURRENCIES),
            "terms": svc.list_terms(db), "templates": svc.list_templates(db), "is_admin": staff.role in ("admin", "super_admin")}


# ------------------------------------------------------------------ productos
@router.get("/products")
def list_products(q: str = "", category: str = "", active: Optional[bool] = None, page: int = 1, size: int = svc.PAGE_SIZE, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return svc.list_products(db, q=q, category=category, active=active, page=page, size=size)


@router.post("/products")
def create_product(data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = svc.create_product(db, data)
        audit_actions.record(db, staff, "create", "crm_product", p.id, p.name)
        return svc.serialize_product(p)
    return _run(db, work)


@router.put("/products/{product_id}")
def update_product(product_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.serialize_product(svc.update_product(db, product_id, data, _expected(data))))


# ------------------------------------------------------------------ condiciones y plantillas
@router.get("/terms")
def list_terms(archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return {"items": svc.list_terms(db, include_archived=archived)}


@router.post("/terms")
def create_term(data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.serialize_term(svc.create_term(db, data)))


@router.put("/terms/{term_id}")
def update_term(term_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.serialize_term(svc.update_term(db, term_id, data)))


@router.get("/doc-templates")
def list_templates(kind: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return {"items": svc.list_templates(db, kind)}


@router.post("/doc-templates")
def create_template(data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.serialize_template(svc.create_template(db, data)))


@router.put("/doc-templates/{template_id}")
def update_template(template_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.serialize_template(svc.update_template(db, template_id, data)))


# ------------------------------------------------------------------ cotizaciones
@router.get("/quotes")
def list_quotes(q: str = "", stage: str = "", account_id: Optional[int] = None, opportunity_id: Optional[int] = None, owner_id: Optional[int] = None, archived: bool = False, page: int = 1,
                size: int = svc.PAGE_SIZE, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    if archived and staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo un administrador ve las archivadas.")
    return svc.list_quotes(db, q=q, stage=stage, account_id=account_id, opportunity_id=opportunity_id, owner_id=owner_id, archived=archived, page=page, size=size)


@router.post("/quotes")
def create_quote(data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        q = svc.create_quote(db, staff, data)
        audit_actions.record(db, staff, "create", "crm_quote", q.id, f"Cotización {q.number}")
        return svc.quote_detail(db, q)
    return _run(db, work)


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.get_quote(db, quote_id)))


@router.put("/quotes/{quote_id}")
def update_quote(quote_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.update_quote(db, staff, svc.get_quote(db, quote_id), data, _expected(data))))


@router.post("/quotes/{quote_id}/stage")
def quote_stage(quote_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.set_stage(db, staff, svc.get_quote(db, quote_id), str(data.get("stage") or ""), _expected(data))))


@router.post("/quotes/{quote_id}/new-version")
def quote_new_version(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.new_version(db, staff, svc.get_quote(db, quote_id))))


@router.post("/quotes/{quote_id}/archive")
def archive_quote(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.set_archived(db, staff, svc.get_quote(db, quote_id), True)))


@router.post("/quotes/{quote_id}/restore")
def restore_quote(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: svc.quote_detail(db, svc.set_archived(db, staff, svc.get_quote(db, quote_id), False)))


@router.get("/quotes/{quote_id}/history")
def quote_history(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    from app.models import CrmChangeLog
    svc.get_quote(db, quote_id)
    rows = db.query(CrmChangeLog).filter(CrmChangeLog.entity == "quote", CrmChangeLog.entity_id == quote_id).order_by(CrmChangeLog.changed_at.desc(), CrmChangeLog.id.desc()).limit(200).all()
    return [{"field": r.field_key, "old": r.old_value, "new": r.new_value, "source": r.source, "at": r.changed_at.isoformat()} for r in rows]


@router.get("/quotes/{quote_id}/pdf")
def quote_pdf_download(quote_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Sirve el PDF guardado o lo genera ahora. Una consulta por la cotización, sin trabajo en segundo plano (un PDF pequeño se arma en milisegundos)."""
    q = svc.get_quote(db, quote_id)
    key = q.pdf_key
    st = get_storage()
    if not key or not st.exists(key):
        detail = svc.quote_detail(db, q)
        tpl = next((t for t in svc.list_templates(db, "quote") if t["id"] == q.template_id), None) or next(iter(svc.list_templates(db, "quote")), None)
        key = quote_pdf.quote_key(q)
        st.put(key, quote_pdf.render_quote(detail, tpl))
        q.pdf_key, q.pdf_generated_at = key, utcnow()
        db.commit()
    return st.response(key, filename=f"cotizacion-{q.number}-v{q.version}.pdf", media_type="application/pdf")


# ------------------------------------------------------------------ proformas
@router.get("/proformas")
def list_proformas(account_id: Optional[int] = None, status: str = "", page: int = 1, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return svc.list_proformas(db, account_id=account_id, status=status, page=page)


@router.post("/quotes/{quote_id}/proforma")
def create_proforma(quote_id: int, data: dict = Body(default={}), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        p = svc.create_proforma(db, staff, svc.get_quote(db, quote_id), data)
        audit_actions.record(db, staff, "create", "crm_proforma", p.id, f"Proforma {p.number}")
        acc = db.get(CrmAccount, p.account_id)
        return svc.serialize_proforma(p, acc.name if acc else None)
    return _run(db, work)


@router.put("/proformas/{proforma_id}")
def update_proforma(proforma_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        p = svc._get(db, CrmProforma, proforma_id, "Proforma")
        svc.update_proforma(db, staff, p, data, _expected(data))
        acc = db.get(CrmAccount, p.account_id)
        return svc.serialize_proforma(p, acc.name if acc else None)
    return _run(db, work)


@router.get("/proformas/{proforma_id}/pdf")
def proforma_pdf_download(proforma_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    p = db.get(CrmProforma, proforma_id) if 0 < proforma_id <= svc.MAX_ID else None
    if p is None:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")
    st = get_storage()
    if not p.pdf_key or not st.exists(p.pdf_key):
        acc = db.get(CrmAccount, p.account_id)
        quote = svc.quote_detail(db, svc.get_quote(db, p.quote_id)) if p.quote_id else None
        tpl = next(iter(svc.list_templates(db, "proforma")), None)
        p.pdf_key = quote_pdf.proforma_key(p)
        st.put(p.pdf_key, quote_pdf.render_proforma(svc.serialize_proforma(p, acc.name if acc else None), quote, tpl))
        db.commit()
    return st.response(p.pdf_key, filename=f"proforma-{p.number}.pdf", media_type="application/pdf")
