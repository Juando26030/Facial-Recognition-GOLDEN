"""Base de datos final del evento (Fase 5, app/final_db.py): subir/reemplazar y descargar. Coordinador o más (comercial y administrador incluidos); respeta el alcance del evento
(cliente y pertenencia) y la base archivada (L7). Los archivos grandes pueden llegar ya subidos al almacenamiento (`upload_token`, propósito `final_database` de app/uploads.py)."""
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import event_archive, final_db, jobs, uploads
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser
from app.storage import get_storage

router = APIRouter()


@router.post("/events/{event_id}/final-database")
def upload_final_database(
    event_id: int, file: Optional[UploadFile] = File(None), upload_token: Optional[str] = Form(None), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo para subir la base de datos final")
    up = uploads.fetch(upload_token, "final_database", {"e": event_id})
    if up is not None:
        filename, content = up.filename, up.content
    elif file is not None:
        filename, content = file.filename or "", file.file.read(final_db.MAX_BYTES + 1)
    else:
        raise HTTPException(status_code=400, detail="Elige el archivo de la base de datos final (Excel o CSV)")
    result = final_db.save(db, event, staff, filename, content)
    db.commit()
    if result["notice_queued"]:
        jobs.kick()
    uploads.discard(up)
    commercial = event.commercial
    return {"message": "Base de datos final reemplazada" if result["replaced"] else "Base de datos final subida", "replaced": result["replaced"],
            "notice_queued": result["notice_queued"], "final_db_name": event.final_db_name, "final_db_uploaded_at": event.final_db_uploaded_at.isoformat(),
            "final_db_uploaded_by_name": staff.full_name or staff.username,
            "notice": ("Se le avisará por correo a la comercial del evento" if result["notice_queued"] else
                       ("El evento no tiene comercial asignada: no se envió aviso" if commercial is None else "La comercial no tiene un correo válido: no se envió aviso"))}


@router.get("/events/{event_id}/final-database")
def download_final_database(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    if not event.final_db_key or not get_storage().exists(event.final_db_key):
        raise HTTPException(status_code=404, detail="Este evento todavía no tiene base de datos final")
    ext = os.path.splitext(event.final_db_key)[1].lower()
    return get_storage().response(event.final_db_key, media_type=final_db.MEDIA_TYPES.get(ext, "application/octet-stream"), filename=f"Base_final_{event.event_code}{ext}")
