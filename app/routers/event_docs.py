"""Documentos del Evento (ítem 8) y Legalizaciones / gastos (ítem 7) — reunión 2026-09-21.

Ambas son secciones a nivel de evento (coordinador+, `comercial` incluida: no son módulos operativos
de registro). Los archivos viven en `data/<tenant>/event_docs/<evento>/` y `.../event_expenses/<evento>/`
con un nombre interno aleatorio; el nombre original se conserva en la base para las descargas."""
import io
import os
import uuid
import zipfile
from datetime import datetime
from app import audit_actions, heavy, safe_limits
from app.timeutil import utcnow
from decimal import Decimal, InvalidOperation

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.timeutil import to_local
from app.models import EventDocument, EventExpense, EventLegalization, StaffUser
from app import uploads
from app.storage import get_storage, key_of

router = APIRouter()

ARCHIVE_ROLE = require_role("coordinador")      # Fase 3 (cambio 7-nov): archivar y restaurar documentos / gastos = coordinador+ (incluye comercial)
ARCHIVE_VIEW_ROLES = ("coordinador", "comercial", "admin", "super_admin")
HARD_DELETE_ROLE = require_role("super_admin")  # borrado definitivo: solo super_admin, de lo ya archivado


def _only_active(query, model, include_archived: bool, staff: StaffUser):
    """Por defecto SOLO los activos; `include_archived=true` es de coordinador+ (pantalla «Ver archivados»)."""
    if include_archived:
        return query          # el acceso (coordinador+) ya lo exige cada endpoint; digitador y cliente no llegan aquí
    return query.filter(model.archived_at.is_(None))

DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods",
           ".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_FILE_BYTES = 25_000_000
MAX_EXPENSE = Decimal("999999999999.99")      # cabe en Numeric(14, 2)


def _store(tenant_id: str, kind: str, event_id: int, upload_name: str, content: bytes) -> str:
    return get_storage().put(key_of(tenant_id, kind, event_id, f"{uuid.uuid4().hex}{os.path.splitext(upload_name)[1].lower()}"), content)


def _remove(path: str) -> None:
    if path:
        get_storage().delete(path)


def delete_event_files(db: Session, event_id: int) -> None:
    """Borra filas y archivos de documentos y gastos de un evento (lo usa delete_event)."""
    for doc in db.query(EventDocument).filter(EventDocument.event_id == event_id).all():
        _remove(doc.stored_path)
    for exp in db.query(EventExpense).filter(EventExpense.event_id == event_id).all():
        _remove(exp.evidence_path)
    db.query(EventDocument).filter(EventDocument.event_id == event_id).delete()
    db.query(EventExpense).filter(EventExpense.event_id == event_id).delete()
    db.query(EventLegalization).filter(EventLegalization.event_id == event_id).delete()


# ---------------------------------------------------------------- Documentos del Evento (ítem 8)

def _doc_json(d: EventDocument) -> dict:
    return {
        "id": d.id, "name": d.name, "description": d.description or "", "filename": d.original_filename,
        "size_bytes": d.size_bytes, "created_at": d.created_at.isoformat() if d.created_at else None,
        "archived": d.archived_at is not None,
    }


@router.get("/events/{event_id}/documents")
def list_documents(event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    query = _only_active(db.query(EventDocument).filter(EventDocument.event_id == event.id), EventDocument, include_archived, staff)
    docs = query.order_by(EventDocument.created_at.desc()).all()
    return [_doc_json(d) for d in docs]


@router.post("/events/{event_id}/documents")
def add_document(
    event_id: int, name: str = Form(...), description: str = Form(""), file: UploadFile = File(None), upload: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """El archivo llega en la petición o ya subido directo al almacenamiento (`upload`, ver app/uploads.py)."""
    event = get_event_for_staff(event_id, db, staff)
    if not name.strip():
        raise HTTPException(status_code=400, detail="El documento necesita un nombre o referencia")
    up = uploads.fetch(upload, "event_doc", {"e": event.id})
    if up is None and (file is None or not file.filename):
        raise HTTPException(status_code=400, detail="Adjunta el archivo")
    filename = up.filename if up else file.filename
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in DOC_EXT:
        raise HTTPException(status_code=400, detail=f"Formato no permitido — usa uno de: {', '.join(sorted(DOC_EXT))}")
    content = up.content if up else file.file.read()
    if not content or len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="El archivo está vacío o pesa más de 25 MB")
    doc = EventDocument(
        event_id=event.id, name=name.strip(), description=description.strip() or None,
        original_filename=os.path.basename(filename), mime_type=up.content_type if up else file.content_type, size_bytes=len(content),
        stored_path=_store(event.tenant_id, "event_docs", event.id, filename, content),
        uploaded_by_id=staff.id, created_at=utcnow(),
    )
    db.add(doc)
    db.commit()
    uploads.discard(up)
    return _doc_json(doc)


def _find_doc(db: Session, event_id: int, doc_id: int, staff: StaffUser) -> EventDocument:
    event = get_event_for_staff(event_id, db, staff)
    doc = db.query(EventDocument).filter(EventDocument.id == doc_id, EventDocument.event_id == event.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


def _get_doc(db: Session, event_id: int, doc_id: int, staff: StaffUser) -> EventDocument:
    """Documento con su archivo presente. Uno archivado lo descarga coordinador+ (cualquiera que llegue aquí); para digitador y cliente es como si no existiera."""
    doc = _find_doc(db, event_id, doc_id, staff)
    if doc.archived_at is not None and staff.role not in ARCHIVE_VIEW_ROLES:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if not get_storage().exists(doc.stored_path):
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.get("/events/{event_id}/documents/zip")
def download_all_documents(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Todos los documentos del evento en un ZIP (al finalizar el evento). Cada archivo se nombra
    "<referencia> - <archivo original>" y los nombres repetidos se numeran."""
    event = get_event_for_staff(event_id, db, staff)
    docs = db.query(EventDocument).filter(EventDocument.event_id == event.id, EventDocument.archived_at.is_(None)).order_by(EventDocument.created_at).all()
    if not docs:
        raise HTTPException(status_code=404, detail="Este evento no tiene documentos")
    buffer, used = io.BytesIO(), set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            if not get_storage().exists(d.stored_path):
                continue
            entry = f"{d.name} - {d.original_filename}".replace("/", "_").replace("\\", "_")
            base, n = entry, 1
            while entry in used:
                n += 1
                stem, ext = os.path.splitext(base)
                entry = f"{stem} ({n}){ext}"
            used.add(entry)
            zf.writestr(entry, get_storage().get(d.stored_path))
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="Documentos_{event.event_code}.zip"'},
    )


@router.get("/events/{event_id}/documents/{doc_id}/download")
def download_document(event_id: int, doc_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    doc = _get_doc(db, event_id, doc_id, staff)
    return get_storage().response(doc.stored_path, filename=doc.original_filename, media_type=doc.mime_type or "application/octet-stream")


@router.post("/events/{event_id}/documents/{doc_id}/archive")
def archive_document(event_id: int, doc_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    """Oculta el documento de la lista y del ZIP; el archivo se conserva y se puede restaurar."""
    doc = _find_doc(db, event_id, doc_id, staff)
    if doc.archived_at is not None:
        raise HTTPException(status_code=400, detail="El documento ya está archivado")
    doc.archived_at, doc.archived_by_id = utcnow(), staff.id
    audit_actions.record(db, staff, "archive", "event_document", doc.id, doc.name, f"evento {doc.event_id}")
    db.commit()
    return {"message": "Documento archivado"}


@router.post("/events/{event_id}/documents/{doc_id}/restore")
def restore_document(event_id: int, doc_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    doc = _find_doc(db, event_id, doc_id, staff)
    if doc.archived_at is None:
        raise HTTPException(status_code=400, detail="El documento no está archivado")
    doc.archived_at, doc.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "event_document", doc.id, doc.name, f"evento {doc.event_id}")
    db.commit()
    return {"message": "Documento restaurado"}


@router.delete("/events/{event_id}/documents/{doc_id}")
def delete_document(event_id: int, doc_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(HARD_DELETE_ROLE)):
    """Borrado DEFINITIVO: solo super_admin y solo de un documento ya archivado; borra también el archivo del almacenamiento."""
    doc = _find_doc(db, event_id, doc_id, staff)
    if doc.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el documento; el borrado definitivo solo aplica a documentos archivados")
    audit_actions.record(db, staff, "delete", "event_document", doc.id, doc.name, f"evento {doc.event_id}")
    stored = doc.stored_path
    db.delete(doc)
    db.commit()
    _remove(stored)   # después del commit: si falla la base no se pierde el archivo
    return {"message": "Documento eliminado definitivamente"}


# ---------------------------------------------------------------- Legalizaciones (ítem 7)

def _expense_json(e: EventExpense) -> dict:
    return {
        "id": e.id, "category": e.category, "responsible": e.responsible, "description": e.description or "",
        "applies_to": e.applies_to or "", "amount": float(e.amount or 0), "has_evidence": bool(e.evidence_path),
        "created_at": e.created_at.isoformat() if e.created_at else None, "archived": e.archived_at is not None,
    }


@router.get("/events/{event_id}/expenses")
def list_expenses(event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """El total suma SOLO los gastos activos (un gasto archivado no cuenta aunque se muestre con `include_archived`)."""
    event = get_event_for_staff(event_id, db, staff)
    query = _only_active(db.query(EventExpense).filter(EventExpense.event_id == event.id), EventExpense, include_archived, staff)
    rows = query.order_by(EventExpense.created_at).all()
    return {"expenses": [_expense_json(e) for e in rows], "total": float(sum((e.amount or 0) for e in rows if e.archived_at is None))}


@router.post("/events/{event_id}/expenses")
def add_expense(
    event_id: int, category: str = Form(...), responsible: str = Form(...), description: str = Form(""),
    applies_to: str = Form(""), amount: str = Form(...), evidence: UploadFile = File(None), evidence_upload: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    if not category.strip() or not responsible.strip():
        raise HTTPException(status_code=400, detail="La categoría y la persona responsable son obligatorias")
    try:
        value = Decimal(amount.replace(",", ".").strip())
        if not value.is_finite() or value < 0 or value > MAX_EXPENSE:      # C11: Infinity / 1E+999 pasaban «< 0» y la columna Numeric(14, 2) daba 500
            raise InvalidOperation
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="El valor del gasto debe ser un número mayor o igual a 0")

    evidence_path = evidence_name = None
    up = uploads.fetch(evidence_upload, "expense_evidence", {"e": event.id})
    if up is not None or (evidence is not None and evidence.filename):
        evidence_filename = up.filename if up else evidence.filename
        ext = os.path.splitext(evidence_filename)[1].lower()
        if ext not in IMAGE_EXT:
            raise HTTPException(status_code=400, detail="La evidencia debe ser una imagen (PNG, JPG, WebP o GIF)")
        content = up.content if up else evidence.file.read()
        if not content or len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="La imagen está vacía o pesa más de 25 MB")
        try:
            safe_limits.check_image_dimensions(content)
            Image.open(io.BytesIO(content)).verify()
        except safe_limits.LimitError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message)
        except Exception:
            raise HTTPException(status_code=400, detail="La evidencia no es una imagen válida")
        evidence_path = _store(event.tenant_id, "event_expenses", event.id, evidence_filename, content)
        evidence_name = os.path.basename(evidence_filename)

    expense = EventExpense(
        event_id=event.id, category=category.strip(), responsible=responsible.strip(),
        description=description.strip() or None, applies_to=applies_to.strip() or None, amount=value,
        evidence_path=evidence_path, evidence_name=evidence_name, created_by_id=staff.id, created_at=utcnow(),
    )
    db.add(expense)
    db.commit()
    uploads.discard(up)
    return _expense_json(expense)


def store_evidence(event, evidence: UploadFile | None, evidence_upload: str | None):
    """Valida y guarda la foto de un soporte (misma regla que `add_expense`). Devuelve (ruta, nombre, subida_directa); (None, None, None) si no vino archivo.
    Lo usa también la pantalla de legalizaciones por rubro (app/routers/legalizations.py)."""
    up = uploads.fetch(evidence_upload, "expense_evidence", {"e": event.id})
    if up is None and not (evidence is not None and evidence.filename):
        return None, None, None
    filename = up.filename if up else evidence.filename
    if os.path.splitext(filename)[1].lower() not in IMAGE_EXT:
        raise HTTPException(status_code=400, detail="La evidencia debe ser una imagen (PNG, JPG, WebP o GIF)")
    content = up.content if up else evidence.file.read()
    if not content or len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="La imagen está vacía o pesa más de 25 MB")
    try:
        safe_limits.check_image_dimensions(content)
        Image.open(io.BytesIO(content)).verify()
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except Exception:
        raise HTTPException(status_code=400, detail="La evidencia no es una imagen válida")
    return _store(event.tenant_id, "event_expenses", event.id, filename, content), os.path.basename(filename), up


def _get_expense(db: Session, event_id: int, expense_id: int, staff: StaffUser) -> EventExpense:
    event = get_event_for_staff(event_id, db, staff)
    exp = db.query(EventExpense).filter(EventExpense.id == expense_id, EventExpense.event_id == event.id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return exp


@router.get("/events/{event_id}/expenses/report")
def expenses_report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Reporte Excel de legalizaciones en el formato oficial de Golden (PLANTILLA-LEG.xlsx, ver app/legalization_svc.py). Se conserva esta ruta
    de siempre; la pantalla usa /legalization/report, que entrega lo mismo."""
    from app import legalization_svc
    event = get_event_for_staff(event_id, db, staff)
    return legalization_svc.report_response(db, event)


@router.get("/events/{event_id}/expenses/{expense_id}/evidence")
def expense_evidence(event_id: int, expense_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    exp = _get_expense(db, event_id, expense_id, staff)
    if exp.archived_at is not None and staff.role not in ARCHIVE_VIEW_ROLES:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if not exp.evidence_path or not get_storage().exists(exp.evidence_path):
        raise HTTPException(status_code=404, detail="Este gasto no tiene evidencia")
    return get_storage().response(exp.evidence_path, filename=exp.evidence_name)


@router.post("/events/{event_id}/expenses/{expense_id}/archive")
def archive_expense(event_id: int, expense_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    """Saca el gasto de la lista, del total y del reporte; la evidencia se conserva y se puede restaurar."""
    exp = _get_expense(db, event_id, expense_id, staff)
    if exp.archived_at is not None:
        raise HTTPException(status_code=400, detail="El gasto ya está archivado")
    exp.archived_at, exp.archived_by_id = utcnow(), staff.id
    audit_actions.record(db, staff, "archive", "event_expense", exp.id, exp.category, f"evento {exp.event_id}")
    db.commit()
    return {"message": "Gasto archivado"}


@router.post("/events/{event_id}/expenses/{expense_id}/restore")
def restore_expense(event_id: int, expense_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ARCHIVE_ROLE)):
    exp = _get_expense(db, event_id, expense_id, staff)
    if exp.archived_at is None:
        raise HTTPException(status_code=400, detail="El gasto no está archivado")
    exp.archived_at, exp.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "event_expense", exp.id, exp.category, f"evento {exp.event_id}")
    db.commit()
    return {"message": "Gasto restaurado"}


@router.delete("/events/{event_id}/expenses/{expense_id}")
def delete_expense(event_id: int, expense_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(HARD_DELETE_ROLE)):
    """Borrado DEFINITIVO: solo super_admin y solo de un gasto ya archivado; borra también su evidencia del almacenamiento."""
    exp = _get_expense(db, event_id, expense_id, staff)
    if exp.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el gasto; el borrado definitivo solo aplica a gastos archivados")
    audit_actions.record(db, staff, "delete", "event_expense", exp.id, exp.category, f"evento {exp.event_id}")
    evidence = exp.evidence_path
    db.delete(exp)
    db.commit()
    _remove(evidence)
    return {"message": "Gasto eliminado definitivamente"}
