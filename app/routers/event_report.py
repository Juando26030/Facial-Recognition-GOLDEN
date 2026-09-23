"""Informe final del evento (reunión 2026-09-21, ítem 6): el coordinador sube el informe ya corregido y
autorizado (PDF o Excel, desde 2026-09-23); queda guardado (bombillo verde en Calendario/Eventos/Clientes)
y se le manda por correo a la comercial del evento. Descargable desde ese mismo bombillo y desde el
botón "Descargar informe" del menú del evento."""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.mailer import send_mail
from app.models import StaffUser

router = APIRouter()

MAX_REPORT_BYTES = 15_000_000

# extensión -> (tipo MIME, firma de los primeros bytes) — se valida el contenido real, no solo el nombre.
REPORT_TYPES = {
    ".pdf": ("application/pdf", (b"%PDF",)),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (bytes.fromhex("504b0304"),)),  # ZIP
    ".xls": ("application/vnd.ms-excel", (bytes.fromhex("d0cf11e0"),)),  # OLE2
}


@router.post("/events/{event_id}/final-report")
async def upload_final_report(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    content = await file.read()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in REPORT_TYPES or not content.startswith(REPORT_TYPES[ext][1]):
        raise HTTPException(status_code=400, detail="El informe debe ser un archivo PDF o Excel (.xlsx / .xls)")
    if len(content) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=400, detail="El archivo pesa más de 15 MB")
    mime = REPORT_TYPES[ext][0]

    folder = os.path.join("data", event.tenant_id, "event_reports")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{event.id}{ext}")
    with open(path, "wb") as f:
        f.write(content)
    if event.report_pdf_path and event.report_pdf_path != path and os.path.isfile(event.report_pdf_path):
        os.remove(event.report_pdf_path)  # el informe nuevo reemplaza al anterior aunque cambie de formato
    event.report_pdf_path, event.report_uploaded_at = path, datetime.utcnow()
    db.commit()

    commercial = event.commercial
    if not commercial:
        email = {"sent": False, "detail": "El evento no tiene comercial asignada — no se envió correo"}
    elif not commercial.email:
        email = {"sent": False, "detail": f"{commercial.full_name or commercial.username} no tiene correo registrado (complétalo en Configuración > Staff) — no se envió correo"}
    else:
        coordinator = event.coordinator
        name = commercial.full_name or commercial.username
        body = (
            f"Hola {name}, este fue el evento {event.event_code} llamado {event.name} del cliente "
            f"{event.tenant.name if event.tenant else event.tenant_id}, coordinado por "
            f"{(coordinator.full_name or coordinator.username) if coordinator else 'sin coordinador asignado'}. "
            f"Adjunto el reporte."
        )
        email = send_mail(
            commercial.email, f"Informe final — {event.event_code} {event.name}", body,
            attachments=[(f"Informe_{event.event_code}{ext}", content, mime)],
        )
    return {"message": "Informe subido", "report_uploaded": True, "email": email}


@router.get("/events/{event_id}/final-report")
async def download_final_report(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    if not event.report_pdf_path or not os.path.isfile(event.report_pdf_path):
        raise HTTPException(status_code=404, detail="Este evento todavía no tiene informe final")
    ext = os.path.splitext(event.report_pdf_path)[1].lower()
    return FileResponse(event.report_pdf_path, media_type=REPORT_TYPES.get(ext, ("application/octet-stream",))[0], filename=f"Informe_{event.event_code}{ext}")
