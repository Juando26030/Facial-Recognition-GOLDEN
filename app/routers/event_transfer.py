"""Exportar / importar un evento COMPLETO entre entornos (docs/18_EXPORTAR_EVENTOS.md). Solo super_admin. El motor vive en app/event_transfer.py (el mismo que usan los scripts
de línea de comandos). F1: sin biometría y sin archivos. Respuestas síncronas (los eventos grandes irán por un Job con progreso en F4)."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import event_transfer
from app.auth import require_role
from app.database import get_db
from app.models import Event, StaffUser

router = APIRouter()
SUPER = require_role("super_admin")


def _fail(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("/event-transfer/export/{event_id}")
def export_event(event_id: int, include_biometrics: bool = False, staff: StaffUser = Depends(SUPER), db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    try:
        data, _ = event_transfer.export_event(db, event, staff_username=staff.username, include_biometrics=include_biometrics)
    except event_transfer.TransferError as e:
        raise _fail(e)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", event.event_code or "evento")
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="evento_{name}.zip"', "Cache-Control": "no-store"})


def _run(file: UploadFile, new_event_code: Optional[str], new_name: Optional[str], keep_original_state: bool, dry_run: bool, staff: StaffUser, db: Session) -> dict:
    data = file.file.read()
    try:
        return event_transfer.import_package(db, data, staff_username=staff.username, new_event_code=(new_event_code or "").strip() or None,
                                             new_name=(new_name or "").strip() or None, keep_original_state=keep_original_state, dry_run=dry_run)
    except event_transfer.TransferError as e:
        raise _fail(e)


@router.post("/event-transfer/import/dry-run")
def import_dry_run(file: UploadFile = File(...), new_event_code: Optional[str] = Form(None), new_name: Optional[str] = Form(None), keep_original_state: bool = Form(False),
                   staff: StaffUser = Depends(SUPER), db: Session = Depends(get_db)):
    return _run(file, new_event_code, new_name, keep_original_state, True, staff, db)


@router.post("/event-transfer/import")
def import_event(file: UploadFile = File(...), new_event_code: Optional[str] = Form(None), new_name: Optional[str] = Form(None), keep_original_state: bool = Form(False),
                 staff: StaffUser = Depends(SUPER), db: Session = Depends(get_db)):
    report = _run(file, new_event_code, new_name, keep_original_state, False, staff, db)
    if not report.get("ok"):
        raise HTTPException(status_code=409, detail={"message": "No se importó nada: hay conflictos.", "conflicts": report["conflicts"]})
    return report


@router.post("/event-transfer/imports/{import_id}/confirm")
def confirm_import(import_id: int, staff: StaffUser = Depends(SUPER), db: Session = Depends(get_db)):
    try:
        return event_transfer.confirm_import(db, import_id, staff.username)
    except event_transfer.TransferError as e:
        raise _fail(e)
