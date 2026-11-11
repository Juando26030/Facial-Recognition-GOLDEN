"""Valida en el SERVIDOR un QR dinámico/estático de la credencial digital (app/dynamic_qr.py) y devuelve la persona para seguir el flujo normal de registro/áreas/inventario.
Solo personal con acceso al evento. Sin datos personales en logs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import dynamic_qr
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import EventAttendee, StaffUser, User

router = APIRouter()


@router.post("/qr/resolve")
def resolve_qr(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    try:
        event_id = int((data or {}).get("event_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Falta el evento")
    event = get_event_for_staff(event_id, db, staff)
    parsed = dynamic_qr.parse((data or {}).get("text"))
    att = db.get(EventAttendee, parsed["att_id"]) if parsed else None
    if not parsed or att is None or att.event_id != event.id:
        raise HTTPException(status_code=400, detail="Código no válido para este evento")
    if event.archived_at is not None or event.data_archived_at is not None:
        raise HTTPException(status_code=400, detail="Código no válido para este evento")
    purpose = str((data or {}).get("purpose") or "entry").strip().lower()
    if parsed["kind"] == "s" and purpose != "entry":          # F5-9 B: el código ESTÁTICO del pase de Wallet es solo de ENTRADA (no rota): áreas e inventario exigen el dinámico
        raise HTTPException(status_code=400, detail="El código del pase de Wallet solo sirve en la entrada. Aquí muestra la credencial digital (el QR que cambia cada 30 segundos).")
    verdict = dynamic_qr.verify(parsed, att.digital_token or "")
    if verdict == "expired":
        raise HTTPException(status_code=410, detail="Código vencido: que la persona lo muestre de nuevo (se renueva solo cada 30 segundos). Una captura de pantalla no sirve.")
    if verdict != "ok":
        raise HTTPException(status_code=400, detail="Código no válido para este evento")
    user = db.query(User).filter(User.id == att.user_id, User.tenant_id == att.tenant_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="La persona de este código ya no está en el evento")
    return {"kind": parsed["kind"], "cedula": user.id, "first_name": user.first_name or "", "last_name": user.last_name or ""}
