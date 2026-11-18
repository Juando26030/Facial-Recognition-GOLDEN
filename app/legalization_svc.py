"""Legalizaciones del evento en el formato oficial de Golden: lo que toca la base.

La lógica del Excel está en `app/legalization_xlsx.py` (pura, sin base). Aquí se lee el encabezado (`EventLegalization`) y los gastos
(`EventExpense`) y se arma lo que ese módulo entiende. Los gastos viejos (anteriores al formato, `kind='otro'`) salen en «Otros gastos»."""
import io
from datetime import date

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import legalization_xlsx as lx
from app.models import Event, EventExpense, EventLegalization
from app.storage import get_storage
from app.timeutil import to_local

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Nombre del rubro: se guarda en `EventExpense.category` (columna heredada y obligatoria) para que las pantallas y reportes viejos lo sigan mostrando.
RUBRO = {
    lx.HOSPEDAJE: "Hospedaje", lx.PASAJE: "Pasajes", lx.TAXI_TERMINAL: "Taxis a terminales", lx.TAXI_CIUDAD: "Taxis y transporte público",
    lx.ALIMENTACION: "Alimentación", lx.DIGITADOR: "Digitadores(as)", lx.OTRO: "Otros gastos",
}


def active_lines(db: Session, event_id: int, include_archived: bool = False) -> list[EventExpense]:
    q = db.query(EventExpense).filter(EventExpense.event_id == event_id)
    if not include_archived:
        q = q.filter(EventExpense.archived_at.is_(None))
    # 0148: lo que ya tiene lugar manual va por `position`; los gastos anteriores al orden manual (NULL) salen primero, por fecha
    return q.order_by(EventExpense.position.isnot(None), EventExpense.position, EventExpense.expense_date.is_(None), EventExpense.expense_date, EventExpense.id).all()


def get_legalization(db: Session, event_id: int) -> EventLegalization | None:
    return db.query(EventLegalization).filter(EventLegalization.event_id == event_id).first()


def ensure_legalization(db: Session, event: Event) -> EventLegalization:
    """La legalización del evento (una por evento); la crea en borrador la primera vez que se escribe algo."""
    leg = get_legalization(db, event.id)
    if leg is None:
        leg = EventLegalization(event_id=event.id, status="borrador")
        db.add(leg)
        db.flush()
    return leg


def line_date(e: EventExpense):
    """Fecha del gasto; en los gastos viejos (sin fecha) la del día en que se registraron, en hora local."""
    return e.expense_date or (to_local(e.created_at).date() if e.created_at else None)


def _f(v):
    return None if v is None else float(v)


def line_json(e: EventExpense) -> dict:
    d = line_date(e)
    return {
        "id": e.id, "kind": e.kind or lx.OTRO, "date": d.isoformat() if d else None,
        "tax_id": e.tax_id or "", "vendor_name": e.vendor_name or "", "address": e.address or "", "phone": e.phone or "", "email": e.email or "",
        "origin": e.origin or "", "destination": e.destination or "", "concept": e.concept or (e.category if (e.kind or lx.OTRO) == lx.OTRO and not e.vendor_name else "") or "",
        "plate": e.plate or "", "vehicle": e.vehicle or "", "amount": float(e.amount or 0), "iva": _f(e.iva), "has_support": e.has_support,
        "breakfast": _f(e.breakfast), "lunch": _f(e.lunch), "dinner": _f(e.dinner), "snack": _f(e.snack), "unit_value": _f(e.unit_value),
        "observation": e.observation or "", "approved": e.approved, "has_evidence": bool(e.evidence_path), "archived": e.archived_at is not None,
        "category": e.category, "description": e.description or "", "applies_to": e.applies_to or "",
    }


def line_for_xlsx(e: EventExpense) -> dict:
    kind = e.kind or lx.OTRO
    legacy = kind == lx.OTRO and e.expense_date is None and not e.concept      # gasto anterior al formato nuevo: quien lo registró hace de «nombre»
    detail = e.concept or e.category
    if legacy and e.description:      # gasto viejo: «categoría — descripción»
        detail = f"{e.category} — {e.description}"
    return {
        "kind": kind, "date": line_date(e), "tax_id": e.tax_id, "name": e.vendor_name or (e.responsible if legacy else None),
        "address": e.address, "phone": e.phone, "email": e.email, "origin": e.origin, "destination": e.destination,
        "concept": e.concept, "amount": e.amount, "iva": e.iva, "support": e.has_support, "approved": e.approved, "plate": e.plate,
        "vehicle": e.vehicle, "breakfast": e.breakfast, "lunch": e.lunch, "dinner": e.dinner, "snack": e.snack, "unit_value": e.unit_value,
        "observation": e.observation, "detail": detail, "observations": e.observation if kind == lx.OTRO else None,
    }


def header_json(event: Event, leg: EventLegalization | None, default_responsible: str = "") -> dict:
    return {
        "responsible_name": (leg.responsible_name if leg and leg.responsible_name else default_responsible) or "",
        "responsible_cc": (leg.responsible_cc if leg else "") or "",
        "advance_amount": _f(leg.advance_amount) if leg else None,
        "legalization_date": leg.legalization_date.isoformat() if leg and leg.legalization_date else None,
        "status": leg.status if leg else "borrador",
        "review_note": (leg.review_note if leg else "") or "",
        "submitted_at": leg.submitted_at.isoformat() if leg and leg.submitted_at else None,
        "reviewed_at": leg.reviewed_at.isoformat() if leg and leg.reviewed_at else None,
        "event_code": event.event_code, "event_name": event.name, "city": event.city or "",
        "event_date": event.start_date.isoformat() if event.start_date else None,
    }


def header_for_xlsx(event: Event, leg: EventLegalization | None) -> dict:
    """Encabezado de la hoja «Legalización». El consecutivo, el CE final y las observaciones contables los escribe el área administrativa: salen en blanco."""
    return {
        "consecutivo": None, "fecha_legalizacion": leg.legalization_date if leg and leg.legalization_date else None,
        "responsable": leg.responsible_name if leg else None, "cc": leg.responsible_cc if leg else None,
        "cod_evento": event.event_code, "evento": event.name, "ciudad": event.city, "fecha_evento": event.start_date,
        "anticipo": leg.advance_amount if leg else None, "ce_final": None, "observaciones_contables": None,
    }


MAX_PHOTOS = 150      # tope de fotos en la hoja «Soportes» (el Excel se arma en memoria)


def photo_caption(e: EventExpense) -> str:
    d = line_date(e)
    who = e.vendor_name or e.concept or e.category
    return " · ".join(p for p in (RUBRO.get(e.kind or lx.OTRO, "Otros gastos"), who, d.strftime("%d/%m/%Y") if d else "", f"$ {float(e.amount or 0):,.0f}".replace(",", ".")) if p)


def photos_for_xlsx(rows: list[EventExpense]) -> list[dict]:
    """Las fotos de soporte de los gastos activos, agrupadas por rubro (en el orden del formato) para la hoja «Soportes». Una foto que falte en el almacenamiento se omite."""
    store = get_storage()
    order = {k: i for i, k in enumerate(lx.KINDS)}
    out = []
    for e in sorted((r for r in rows if r.evidence_path), key=lambda r: (order.get(r.kind or lx.OTRO, 99), line_date(r) or date.max, r.id)):
        if len(out) >= MAX_PHOTOS:
            break
        try:
            out.append({"caption": photo_caption(e), "data": store.get(e.evidence_path)})
        except Exception:      # noqa: BLE001 — archivo ausente o ilegible: el resto del reporte sale igual
            continue
    return out


def build_report(db: Session, event: Event) -> tuple[bytes, str]:
    rows = active_lines(db, event.id)
    data = lx.build_workbook(header_for_xlsx(event, get_legalization(db, event.id)), [line_for_xlsx(e) for e in rows], photos_for_xlsx(rows))
    return data, lx.file_name(event.event_code, event.name)


def report_response(db: Session, event: Event) -> StreamingResponse:
    data, name = build_report(db, event)
    return StreamingResponse(io.BytesIO(data), media_type=XLSX_MIME, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def summary(db: Session, event_id: int, leg: EventLegalization | None) -> dict:
    lines = [line_for_xlsx(e) for e in active_lines(db, event_id)]
    return lx.summarize(lines, leg.advance_amount if leg else 0)
