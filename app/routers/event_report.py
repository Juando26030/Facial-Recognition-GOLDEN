"""Informe final del evento (reunión 2026-09-21, ítem 6): el coordinador sube el PDF ya corregido y
autorizado; queda guardado (bombillo verde en Calendario/Eventos/Clientes) y se le manda por correo a
la comercial del evento. Descargable desde ese mismo bombillo."""
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


@router.post("/events/{event_id}/final-report")
async def upload_final_report(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="El informe debe ser un archivo PDF")
    if len(content) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=400, detail="El PDF pesa más de 15 MB")

    folder = os.path.join("data", event.tenant_id, "event_reports")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{event.id}.pdf")
    with open(path, "wb") as f:
        f.write(content)
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
            attachments=[(f"Informe_{event.event_code}.pdf", content, "application/pdf")],
        )
    return {"message": "Informe subido", "report_uploaded": True, "email": email}


@router.get("/events/{event_id}/final-report")
async def download_final_report(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    event = get_event_for_staff(event_id, db, staff)
    if not event.report_pdf_path or not os.path.isfile(event.report_pdf_path):
        raise HTTPException(status_code=404, detail="Este evento todavía no tiene informe final")
    return FileResponse(event.report_pdf_path, media_type="application/pdf", filename=f"Informe_{event.event_code}.pdf")
