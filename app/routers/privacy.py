"""Privacidad de datos biométricos por evento (Parámetros del Evento): estado, borrado del evento y derecho de supresión de una persona."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import audit_actions, ops, privacy
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import EventAttendee, StaffUser

router = APIRouter()
VIEW = require_role_excluding("coordinador", ("comercial",))
ADMIN = require_role("admin")


@router.get("/events/{event_id}/privacy")
def get_privacy(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEW)):
    event = get_event_for_staff(event_id, db, staff)
    return {**privacy.stats(db, event), "after_event_days": privacy.days_after_event(), "max_days": privacy.max_days(), "event_name": event.name, "purged_at": event.biometrics_purged_at.isoformat() if event.biometrics_purged_at else None}


@router.post("/events/{event_id}/biometrics/purge")
def purge_event_biometrics(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Borra los datos biométricos del evento (irreversible; solo admin+). Exige `confirm_name` = nombre exacto del evento. Deja constancia
    de auditoría (quién, cuándo, evento, cuántas personas: nada personal)."""
    event = get_event_for_staff(event_id, db, staff)
    if str(data.get("confirm_name", "")).strip().casefold() != event.name.strip().casefold():
        raise HTTPException(status_code=400, detail="Escribe el nombre exacto del evento para confirmar: este borrado no se puede deshacer")
    result = privacy.purge_event(db, event)
    ops.record_system_event("biometrics_purge", f"event:{event.id}", f"por {staff.username} (id {staff.id}); {result['deleted']} borradas, {result['kept_in_other_events']} omitidas")
    return result


@router.delete("/events/{event_id}/users/{user_id}/biometrics")
def purge_person_biometrics(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Derecho de supresión de una persona (revocación): borra su rostro (vector, foto y todas las versiones) y deja la constancia de revocación. Conserva su identidad y su asistencia.
    B9 (decisión del dueño, 8-nov-2026): solo admin y superior (antes lo hacía un coordinador) y queda en el registro de acciones SIN datos personales (quién, evento, alcance)."""
    event = get_event_for_staff(event_id, db, staff)
    if not db.query(EventAttendee.id).filter_by(event_id=event.id, user_id=user_id).first():
        raise HTTPException(status_code=404, detail="Esa persona no está en este evento")
    result = privacy.erase_person(db, event, user_id, "biometric")          # vector, foto (todas las versiones), is_biometric_enabled=false y la `revocation` en audit_consent_logs
    if not result["found"]:
        raise HTTPException(status_code=404, detail="Esa persona no está en este evento")
    had = bool(result.get("had_biometrics"))
    audit_actions.record(db, staff, "purge_biometrics", "event", event.id, event.name, "alcance biometric; rostro de una persona (ruta de la ficha)")
    db.commit()
    ops.record_system_event("person_purge", f"event:{event.id}", f"por {staff.username} (id {staff.id}); alcance biometric")
    return {"deleted": had, "message": "Rostro borrado" if had else "Esa persona no tenía datos biométricos guardados"}


@router.delete("/attendees/{user_id}/purge-data")
def purge_data(user_id: str, event_id: int = Query(...), scope: str = Query(...), confirm: bool = Query(False), db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Supresión individual (Habeas Data). Solo admin y super_admin. `scope=biometric` = revocación (vector y foto; sigue entrando por cédula/QR). `scope=all` = además todos sus datos
    personales (ver `privacy.erase_person`). Exige `confirm=true` (la interfaz lo pide con una confirmación). Deja constancia (quién, cuándo, alcance; nada personal) y devuelve lo que NO se
    pudo borrar al instante."""
    if scope not in ("all", "biometric"):
        raise HTTPException(status_code=400, detail="El alcance debe ser «all» o «biometric»")
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirma la supresión: este borrado no se puede deshacer")
    event = get_event_for_staff(event_id, db, staff)
    result = privacy.erase_person(db, event, user_id, scope)
    if not result["found"]:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    ops.record_system_event("person_purge", f"event:{event.id}", f"por {staff.username} (id {staff.id}); alcance {scope}")
    return result
