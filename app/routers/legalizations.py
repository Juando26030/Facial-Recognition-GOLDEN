"""Legalizaciones del evento en el formato oficial de Golden (reunión 14-nov-2026).

El coordinador registra sus gastos por rubro (hospedaje, pasajes, taxis a terminales, taxis y transporte público, digitadores(as),
alimentación, otros gastos), completa el encabezado (responsable, cédula, anticipo en pesos) y la ENVÍA. La aprobación la da el director
(rol admin o superior, sin rol nuevo): puede marcar cada gasto como aprobado o no, y aprobar o devolver la legalización completa.
El Excel sale con el formato de PLANTILLA-LEG.xlsx (`app/legalization_xlsx.py`). Archivar, restaurar y borrar un gasto siguen siendo las rutas
de siempre de `event_docs.py` (/expenses/{id}/archive …)."""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_actions, legalization_svc as svc, uploads
from app import legalization_xlsx as lx
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff, require_role
from app.database import get_db
from app.models import EventExpense, EventLegalization, LEGALIZATION_STATUSES, StaffUser
from app.routers import event_docs
from app.timeutil import utcnow

router = APIRouter()

COORD = require_role("coordinador")
DIRECTOR = require_role("admin")      # «director de coordinadores»: no hay rol nuevo (decisión de Juan David, 14-nov-2026); es admin o superior
MAX_MONEY = Decimal("999999999999.99")
MEALS = ("breakfast", "lunch", "dinner", "snack")
MONEY = ("amount", "iva", "unit_value") + MEALS
TEXT = ("tax_id", "vendor_name", "address", "phone", "email", "origin", "destination", "concept", "plate")
EDITABLE_STATES = ("borrador", "devuelta")

Money = Optional[Union[str, float, int]]


class LineIn(BaseModel):
    kind: str
    expense_date: Optional[str] = None
    tax_id: Optional[str] = Field(None, max_length=60)
    vendor_name: Optional[str] = Field(None, max_length=200)
    address: Optional[str] = Field(None, max_length=250)
    phone: Optional[str] = Field(None, max_length=60)
    email: Optional[str] = Field(None, max_length=200)
    origin: Optional[str] = Field(None, max_length=200)
    destination: Optional[str] = Field(None, max_length=200)
    concept: Optional[str] = Field(None, max_length=300)
    plate: Optional[str] = Field(None, max_length=20)
    vehicle: Optional[str] = None
    observation: Optional[str] = Field(None, max_length=1000)
    amount: Money = None
    iva: Money = None
    breakfast: Money = None
    lunch: Money = None
    dinner: Money = None
    snack: Money = None
    unit_value: Money = None
    has_support: Optional[bool] = None


class HeaderIn(BaseModel):
    responsible_name: Optional[str] = Field(None, max_length=200)
    responsible_cc: Optional[str] = Field(None, max_length=40)
    advance_amount: Money = None
    legalization_date: Optional[str] = None


class ReviewIn(BaseModel):
    approved: Optional[bool] = None


class NoteIn(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)


def _money(raw, label: str) -> Optional[Decimal]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        v = Decimal(str(raw).replace(",", ".").strip())
        if not v.is_finite() or v < 0 or v > MAX_MONEY:
            raise InvalidOperation
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"{label}: escribe un número mayor o igual a 0")
    return v


def _date(raw, label: str) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}: la fecha no es válida")


def _event_leg(event_id: int, db: Session, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    return event, svc.get_legalization(db, event.id)


def _check_editable(leg: Optional[EventLegalization]) -> None:
    if leg is not None and leg.status not in EDITABLE_STATES:
        raise HTTPException(status_code=400, detail="La legalización ya fue enviada: para cambiarla, el director debe devolverla primero")


def _apply(e: EventExpense, body: LineIn) -> None:
    """Pasa lo que escribió el coordinador a la fila. Valida por rubro lo mínimo que el formato necesita."""
    kind = e.kind
    values = {f: _money(getattr(body, f), lbl) for f, lbl in (("amount", "Valor"), ("iva", "IVA"), ("unit_value", "Valor unitario"),
                                                              ("breakfast", "Desayuno"), ("lunch", "Almuerzo"), ("dinner", "Cena"), ("snack", "Refrigerio"))}
    if kind == lx.ALIMENTACION:
        meals = sum((values[m] or Decimal(0)) for m in MEALS)
        total = meals if meals else values["amount"]
        if total is None:
            raise HTTPException(status_code=400, detail="Alimentación: escribe el valor de al menos una comida")
    else:
        total = values["amount"]
        if total is None:
            raise HTTPException(status_code=400, detail="El valor del gasto es obligatorio")
        for m in MEALS + ("unit_value",):
            values[m] = None
    if total > MAX_MONEY:
        raise HTTPException(status_code=400, detail="El valor es demasiado grande")
    if kind in (lx.TAXI_CIUDAD,) and body.vehicle not in (None, "", "taxi", "otro"):
        raise HTTPException(status_code=400, detail="El vehículo debe ser «taxi» u «otro»")
    if kind == lx.OTRO and not (body.concept or "").strip():
        raise HTTPException(status_code=400, detail="Otros gastos: escribe el concepto (detalle)")
    if kind == lx.DIGITADOR and not (body.vendor_name or "").strip():
        raise HTTPException(status_code=400, detail="Digitadores(as): escribe el nombre")
    e.expense_date = _date(body.expense_date, "Fecha")
    for f in TEXT:
        setattr(e, f, (getattr(body, f) or "").strip() or None)
    e.vehicle = body.vehicle if kind == lx.TAXI_CIUDAD and body.vehicle else None
    e.observation = (body.observation or "").strip() or None
    e.amount = total
    e.iva = values["iva"]
    e.unit_value = values["unit_value"]
    for m in MEALS:
        setattr(e, m, values[m])
    e.has_support = body.has_support
    if kind == lx.DIGITADOR:
        e.has_support = None


def _view(db: Session, event, leg, staff: StaffUser, include_archived: bool = False) -> dict:
    rows = svc.active_lines(db, event.id, include_archived)
    return {
        "header": svc.header_json(event, leg, staff.full_name or ""),
        "lines": [svc.line_json(e) for e in rows],
        "summary": svc.summary(db, event.id, leg),
        "kinds": [{"kind": k, "label": svc.RUBRO[k]} for k in lx.KINDS],
        "file_name": lx.file_name(event.event_code, event.name),
        "can_review": max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) >= ROLE_HIERARCHY["admin"],      # aprobar o devolver: lo mismo que exige DIRECTOR
    }


@router.get("/events/{event_id}/legalization")
def get_legalization(event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    event, leg = _event_leg(event_id, db, staff)
    return _view(db, event, leg, staff, include_archived)


@router.put("/events/{event_id}/legalization")
def put_header(event_id: int, body: HeaderIn, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Encabezado: responsable, cédula, anticipo en pesos y fecha. Solo mientras está en borrador o devuelta."""
    event, leg = _event_leg(event_id, db, staff)
    _check_editable(leg)
    leg = leg or svc.ensure_legalization(db, event)
    leg.responsible_name = (body.responsible_name or "").strip() or None
    leg.responsible_cc = (body.responsible_cc or "").strip() or None
    leg.advance_amount = _money(body.advance_amount, "Anticipo")
    leg.legalization_date = _date(body.legalization_date, "Fecha de la legalización")
    leg.updated_at = utcnow()
    db.commit()
    return _view(db, event, leg, staff)


def _new_line(event_id: int, kind: str, staff: StaffUser, leg: EventLegalization, body: LineIn) -> EventExpense:
    if kind not in lx.KINDS:
        raise HTTPException(status_code=400, detail="Rubro de gasto no válido")
    e = EventExpense(event_id=event_id, kind=kind, category=svc.RUBRO[kind], responsible=(leg.responsible_name or staff.full_name or staff.username),
                     created_by_id=staff.id, created_at=utcnow())
    _apply(e, body)
    return e


@router.post("/events/{event_id}/legalization/lines")
def add_line(event_id: int, body: LineIn, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    event, leg = _event_leg(event_id, db, staff)
    _check_editable(leg)
    leg = leg or svc.ensure_legalization(db, event)
    e = _new_line(event.id, body.kind, staff, leg, body)
    db.add(e)
    db.commit()
    return svc.line_json(e)


def _find_line(db: Session, event_id: int, line_id: int) -> EventExpense:
    e = db.query(EventExpense).filter(EventExpense.id == line_id, EventExpense.event_id == event_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return e


@router.put("/events/{event_id}/legalization/lines/{line_id}")
def edit_line(event_id: int, line_id: int, body: LineIn, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Corrige un gasto. El rubro no se cambia (se archiva y se registra de nuevo); un gasto archivado no se edita."""
    event, leg = _event_leg(event_id, db, staff)
    _check_editable(leg)
    e = _find_line(db, event.id, line_id)
    if e.archived_at is not None:
        raise HTTPException(status_code=400, detail="El gasto está archivado: restáuralo para editarlo")
    if body.kind != (e.kind or lx.OTRO):
        raise HTTPException(status_code=400, detail="No se puede cambiar el rubro de un gasto: archívalo y regístralo en el rubro correcto")
    e.kind = e.kind or lx.OTRO
    _apply(e, body)
    e.approved, e.approved_by_id, e.approved_at = None, None, None      # lo corregido vuelve a revisarse
    db.commit()
    return svc.line_json(e)


@router.post("/events/{event_id}/legalization/lines/{line_id}/evidence")
def set_evidence(event_id: int, line_id: int, evidence: UploadFile = File(None), evidence_upload: str = Form(None),
                 db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Adjunta (o reemplaza) la foto del soporte de un gasto; la descarga es la de siempre (/expenses/{id}/evidence)."""
    event, leg = _event_leg(event_id, db, staff)
    _check_editable(leg)
    e = _find_line(db, event.id, line_id)
    if e.archived_at is not None:
        raise HTTPException(status_code=400, detail="El gasto está archivado: restáuralo para cambiar su soporte")
    path, name, up = event_docs.store_evidence(event, evidence, evidence_upload)
    if path is None:
        raise HTTPException(status_code=400, detail="Adjunta una imagen")
    old = e.evidence_path
    e.evidence_path, e.evidence_name = path, name
    db.commit()
    uploads.discard(up)
    event_docs._remove(old)
    return svc.line_json(e)


@router.get("/events/{event_id}/legalization/report")
def report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """El Excel en el formato oficial: LEG-COD_<código>-<EVENTO>.xlsx. Se puede bajar en cualquier etapa."""
    event, _leg = _event_leg(event_id, db, staff)
    return svc.report_response(db, event)


# ---------------------------------------------------------------- Envío y aprobación

@router.post("/events/{event_id}/legalization/submit")
def submit(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """El coordinador envía la legalización al director: queda bloqueada para cambios hasta que la apruebe o la devuelva."""
    event, leg = _event_leg(event_id, db, staff)
    _check_editable(leg)
    if not svc.active_lines(db, event.id):
        raise HTTPException(status_code=400, detail="Registra al menos un gasto antes de enviar la legalización")
    leg = leg or svc.ensure_legalization(db, event)
    if not (leg.responsible_name or "").strip() or not (leg.responsible_cc or "").strip():
        raise HTTPException(status_code=400, detail="Completa el responsable y su cédula antes de enviar la legalización")
    leg.status, leg.submitted_at, leg.submitted_by_id, leg.updated_at = "enviada", utcnow(), staff.id, utcnow()
    leg.reviewed_at, leg.reviewed_by_id, leg.review_note = None, None, None
    audit_actions.record(db, staff, "submit", "event_legalization", leg.id, event.event_code, f"evento {event.id}")
    db.commit()
    return _view(db, event, leg, staff)


def _require_sent(leg: Optional[EventLegalization]) -> EventLegalization:
    if leg is None or leg.status != "enviada":
        raise HTTPException(status_code=400, detail="La legalización no está pendiente de revisión")
    return leg


@router.post("/events/{event_id}/legalization/lines/{line_id}/review")
def review_line(event_id: int, line_id: int, body: ReviewIn, db: Session = Depends(get_db), staff: StaffUser = Depends(DIRECTOR)):
    """El director marca un gasto como aprobado (true), no aprobado (false) o pendiente (null) mientras la legalización está enviada."""
    event, leg = _event_leg(event_id, db, staff)
    _require_sent(leg)
    e = _find_line(db, event.id, line_id)
    if e.archived_at is not None:
        raise HTTPException(status_code=400, detail="El gasto está archivado")
    e.approved = body.approved
    e.approved_by_id, e.approved_at = (staff.id, utcnow()) if body.approved is not None else (None, None)
    db.commit()
    return svc.line_json(e)


@router.post("/events/{event_id}/legalization/approve")
def approve(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIRECTOR)):
    """Aprueba la legalización completa: los gastos que el director no marcó quedan aprobados; los marcados «no» se conservan como tal."""
    event, leg = _event_leg(event_id, db, staff)
    _require_sent(leg)
    now = utcnow()
    for e in svc.active_lines(db, event.id):
        if e.approved is None:
            e.approved, e.approved_by_id, e.approved_at = True, staff.id, now
    leg.status, leg.reviewed_at, leg.reviewed_by_id, leg.updated_at = "aprobada", now, staff.id, now
    audit_actions.record(db, staff, "approve", "event_legalization", leg.id, event.event_code, f"evento {event.id}")
    db.commit()
    return _view(db, event, leg, staff)


@router.post("/events/{event_id}/legalization/return")
def return_to_coordinator(event_id: int, body: NoteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(DIRECTOR)):
    """Devuelve la legalización al coordinador con una nota de qué corregir; vuelve a ser editable."""
    event, leg = _event_leg(event_id, db, staff)
    _require_sent(leg)
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Escribe qué debe corregir el coordinador")
    now = utcnow()
    leg.status, leg.review_note, leg.reviewed_at, leg.reviewed_by_id, leg.updated_at = "devuelta", note, now, staff.id, now
    audit_actions.record(db, staff, "return", "event_legalization", leg.id, event.event_code, f"evento {event.id}")
    db.commit()
    return _view(db, event, leg, staff)


assert set(EDITABLE_STATES) <= set(LEGALIZATION_STATUSES)
