"""Panel de solicitudes de privacidad (consultas y reclamos): radicar, listar, cambiar el estado y activar o quitar la bandera «reclamo en trámite». Solo admin y super_admin. El registro queda con quién
hizo cada cambio y cuándo. Nada de esto va a los logs de la aplicación."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import privacy_requests as pr
from app.auth import require_role
from app.database import get_db
from app.models import Event, PrivacyRequest, StaffUser

router = APIRouter()
ADMIN = require_role("admin")


def _get(db: Session, request_id: int) -> PrivacyRequest:
    row = db.get(PrivacyRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return row


@router.post("/privacy-requests")
def create_request(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    channel, rtype = str(data.get("channel") or ""), str(data.get("request_type") or "")
    name, cedula = str(data.get("holder_name") or "").strip(), str(data.get("cedula") or "").strip()
    if channel not in pr.CHANNELS or rtype not in pr.TYPES or not name or not cedula:
        raise HTTPException(status_code=400, detail="Indica el canal, el tipo de solicitud, el nombre del titular y su cédula")
    event_id: Optional[int] = data.get("event_id") if isinstance(data.get("event_id"), int) else None
    event = db.get(Event, event_id) if event_id else None
    req = pr.create(db, channel=channel, holder_name=name, cedula=cedula, request_type=rtype, tenant_id=event.tenant_id if event else None, event_id=event.id if event else None, staff_id=staff.id)
    db.commit()
    return pr.as_dict(req)


@router.get("/privacy-requests")
def list_requests(status: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    q = db.query(PrivacyRequest)
    if status:
        q = q.filter(PrivacyRequest.status == status)
    return [pr.as_dict(r) for r in q.order_by(PrivacyRequest.id.desc()).limit(200)]


@router.put("/privacy-requests/{request_id}/status")
def set_status(request_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    status = str(data.get("status") or "")
    if status not in pr.STATUSES:
        raise HTTPException(status_code=400, detail="Estado no válido")
    row = _get(db, request_id)
    pr.set_status(row, status, staff.id)
    db.commit()
    return pr.as_dict(row)


@router.put("/privacy-requests/{request_id}/claim-flag")
def set_claim_flag(request_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Activa o quita la bandera «reclamo en trámite» sobre el dato de la persona (máximo 2 días hábiles desde la radicación para activarla)."""
    row = _get(db, request_id)
    if row.status in ("resuelta", "rechazada") and data.get("active"):
        raise HTTPException(status_code=400, detail="La solicitud ya está cerrada")
    pr.set_claim_flag(row, bool(data.get("active")), staff.id)
    if data.get("active") and row.status == "recibida":
        pr.set_status(row, "en_tramite", staff.id)
    db.commit()
    return pr.as_dict(row)


@router.get("/privacy-requests/claim/{cedula}")
def claim_for(cedula: str, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """¿Hay un reclamo en trámite sobre esta persona? (para mostrar la leyenda junto a su dato)."""
    row = pr.open_claim(db, cedula)
    return {"claim_in_progress": bool(row), "radicado": row.radicado if row else None}
