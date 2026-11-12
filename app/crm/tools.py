"""Herramientas transversales del CRM (C3): búsqueda global, filtros guardados y exportación CSV. Sin commit propio.

* Búsqueda global: SOLO al enviar (sin escribir-y-buscar con temporizador), mínimo 2 caracteres, una consulta por tipo con LIMIT: cuentas, contactos, oportunidades, cotizaciones y leads (5 consultas como máximo).
  Los nombres se comparan sin tildes ni mayúsculas con las columnas `*_norm`; un número exacto busca por código.
* Filtros guardados: solo filtros estructurados (nunca el texto libre: podría ser el nombre de una persona). Cada quien ve los suyos y los compartidos.
* Exportación CSV: SOLO administradores (hay datos personales), tope de filas, protección contra inyección de fórmulas (=, +, -, @) y una fila de auditoría con el CONTEO, nunca los datos."""
import csv
import io
import json
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.crm import normalize
from app.crm import quote_rules as qr
from app.crm.errors import CrmError
from app.crm.sqlfold import fold
from app.models import CrmAccount, CrmContact, CrmLead, CrmOpportunity, CrmQuote, CrmSavedFilter, StaffUser

SEARCH_MIN = 2
SEARCH_LIMIT = 8
EXPORT_MAX_ROWS = 20000
BOM = "\ufeff"          # para que Excel respete las tildes
EXPORT_SCOPES = ("cuentas", "contactos", "oportunidades", "leads", "cotizaciones")


# ------------------------------------------------------------------ búsqueda global
def search(db: Session, q: str) -> dict:
    text = (q or "").strip()
    if len(text) < SEARCH_MIN:
        raise CrmError(f"Escribe al menos {SEARCH_MIN} caracteres para buscar.")
    if len(text) > 100:
        raise CrmError("El texto de búsqueda es demasiado largo (máximo 100 caracteres).")
    n = normalize(text)
    like = f"%{n}%"
    number = int(text) if text.isdigit() and len(text) <= 12 else None
    acc = db.query(CrmAccount.id, CrmAccount.code, CrmAccount.name, CrmAccount.status).filter(CrmAccount.archived_at.is_(None))
    acc = acc.filter(or_(CrmAccount.name_norm.like(like), CrmAccount.nit == text, *( [CrmAccount.code == number] if number is not None else [])))
    con = db.query(CrmContact.id, CrmContact.account_id, CrmContact.first_name, CrmContact.last_name, CrmContact.job_title).filter(CrmContact.archived_at.is_(None))
    con = con.filter(or_(CrmContact.full_name_norm.like(like), CrmContact.email_norm == text.lower()))
    opp = db.query(CrmOpportunity.id, CrmOpportunity.code, CrmOpportunity.name, CrmOpportunity.outcome).filter(CrmOpportunity.archived_at.is_(None))
    opp = opp.filter(or_(fold(CrmOpportunity.name).like(like), *( [CrmOpportunity.code == number] if number is not None else [])))
    quo = db.query(CrmQuote.id, CrmQuote.number, CrmQuote.version, CrmQuote.title, CrmQuote.stage).filter(CrmQuote.archived_at.is_(None))
    quo = quo.filter(or_(fold(CrmQuote.title).like(like), *( [CrmQuote.number == number] if number is not None else [])))
    led = db.query(CrmLead.id, CrmLead.first_name, CrmLead.last_name, CrmLead.company_name, CrmLead.status).filter(CrmLead.archived_at.is_(None))
    led = led.filter(or_(CrmLead.full_name_norm.like(like), CrmLead.email_norm == text.lower()))
    return {
        "accounts": [{"id": i, "code": c, "name": nm, "status": st} for i, c, nm, st in acc.order_by(CrmAccount.name_norm).limit(SEARCH_LIMIT).all()],
        "contacts": [{"id": i, "account_id": a, "name": " ".join(p for p in (f, ln) if p), "job_title": jt} for i, a, f, ln, jt in con.order_by(CrmContact.full_name_norm).limit(SEARCH_LIMIT).all()],
        "opportunities": [{"id": i, "code": c, "name": nm, "outcome": o} for i, c, nm, o in opp.order_by(CrmOpportunity.updated_at.desc()).limit(SEARCH_LIMIT).all()],
        "quotes": [{"id": i, "number": nu, "version": v, "title": t, "stage": s} for i, nu, v, t, s in quo.order_by(CrmQuote.updated_at.desc()).limit(SEARCH_LIMIT).all()],
        "leads": [{"id": i, "name": " ".join(p for p in (f, ln) if p) or co, "company_name": co, "status": s} for i, f, ln, co, s in led.order_by(CrmLead.updated_at.desc()).limit(SEARCH_LIMIT).all()],
    }


# ------------------------------------------------------------------ filtros guardados
def serialize_filter(f: CrmSavedFilter, staff_id: int) -> dict:
    return {"id": f.id, "scope": f.scope, "name": f.name, "filters": json.loads(f.filters_json), "shared": f.shared, "mine": f.owner_staff_id == staff_id}


def list_filters(db: Session, staff: StaffUser, scope: str = "") -> list:
    q = db.query(CrmSavedFilter).filter(or_(CrmSavedFilter.owner_staff_id == staff.id, CrmSavedFilter.shared.is_(True)))
    if scope:
        q = q.filter(CrmSavedFilter.scope == scope)
    return [serialize_filter(f, staff.id) for f in q.order_by(CrmSavedFilter.name, CrmSavedFilter.id).limit(100).all()]


def create_filter(db: Session, staff: StaffUser, data: dict) -> CrmSavedFilter:
    clean = qr.clean_filter(data)
    if db.query(func.count(CrmSavedFilter.id)).filter(CrmSavedFilter.owner_staff_id == staff.id).scalar() >= 100:
        raise CrmError("Ya tienes 100 filtros guardados: borra alguno.")
    f = CrmSavedFilter(owner_staff_id=staff.id, scope=clean["scope"], name=clean["name"], filters_json=json.dumps(clean["filters"], ensure_ascii=False), shared=clean["shared"])
    db.add(f)
    db.flush()
    return f


def delete_filter(db: Session, staff: StaffUser, filter_id: int) -> None:
    f = db.get(CrmSavedFilter, filter_id) if isinstance(filter_id, int) and 0 < filter_id <= 2_147_483_647 else None
    if f is None:
        raise CrmError("Filtro no encontrado.", 404)
    if f.owner_staff_id != staff.id and staff.role not in ("admin", "super_admin"):
        raise CrmError("Solo quien lo creó (o un administrador) puede borrar este filtro.", 403)
    db.delete(f)
    db.flush()


# ------------------------------------------------------------------ exportación CSV
def safe_cell(value) -> str:
    """Un valor que empieza con = + - @ (o tabulador/retorno) lo interpretaría Excel como fórmula: se le antepone una comilla."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _rows(db: Session, scope: str):
    if scope == "cuentas":
        yield ["codigo", "nombre", "estado", "nit", "correo", "telefono", "ciudad", "direccion"]
        for a in db.query(CrmAccount).filter(CrmAccount.archived_at.is_(None)).order_by(CrmAccount.code).limit(EXPORT_MAX_ROWS):
            yield [a.code, a.name, a.status, a.nit, a.email, a.phone, a.billing_city, a.billing_address]
    elif scope == "contactos":
        yield ["cuenta_codigo", "nombre", "apellidos", "cargo", "correo", "telefono", "movil"]
        for c, code in db.query(CrmContact, CrmAccount.code).join(CrmAccount, CrmAccount.id == CrmContact.account_id).filter(CrmContact.archived_at.is_(None)).order_by(CrmAccount.code, CrmContact.id).limit(EXPORT_MAX_ROWS):
            yield [code, c.first_name, c.last_name, c.job_title, c.email, c.phone, c.mobile]
    elif scope == "oportunidades":
        yield ["codigo", "nombre", "cuenta_codigo", "monto", "moneda", "resultado", "cierre_esperado", "ciudad"]
        for o, code in db.query(CrmOpportunity, CrmAccount.code).join(CrmAccount, CrmAccount.id == CrmOpportunity.account_id).filter(CrmOpportunity.archived_at.is_(None)).order_by(CrmOpportunity.code).limit(EXPORT_MAX_ROWS):
            yield [o.code, o.name, code, o.amount, o.currency, o.outcome, o.expected_close, o.city]
    elif scope == "leads":
        yield ["nombre", "apellidos", "empresa", "correo", "telefono", "origen", "estado"]
        for ld in db.query(CrmLead).filter(CrmLead.archived_at.is_(None)).order_by(CrmLead.id).limit(EXPORT_MAX_ROWS):
            yield [ld.first_name, ld.last_name, ld.company_name, ld.email, ld.phone, ld.source, ld.status]
    elif scope == "cotizaciones":
        yield ["numero", "version", "titulo", "cuenta_codigo", "etapa", "moneda", "subtotal", "impuestos", "total", "valida_hasta"]
        for q, code in db.query(CrmQuote, CrmAccount.code).join(CrmAccount, CrmAccount.id == CrmQuote.account_id).filter(CrmQuote.archived_at.is_(None)).order_by(CrmQuote.number, CrmQuote.version).limit(EXPORT_MAX_ROWS):
            yield [q.number, q.version, q.title, code, q.stage, q.currency, q.subtotal, q.tax_total, q.total, q.valid_until]
    else:
        raise CrmError("Elige qué exportar: " + ", ".join(EXPORT_SCOPES) + ".")


def export_csv(db: Session, scope: str) -> tuple:
    """(bytes UTF-8 con BOM para que Excel respete las tildes, número de filas de datos). Separador «;» (Excel en español)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    n = -1
    for row in _rows(db, scope):
        w.writerow([safe_cell(c) for c in row])
        n += 1
    return (BOM + buf.getvalue()).encode("utf-8"), max(n, 0)


def clean_scope(scope: Optional[str]) -> str:
    if scope not in EXPORT_SCOPES:
        raise CrmError("Elige qué exportar: " + ", ".join(EXPORT_SCOPES) + ".")
    return scope
