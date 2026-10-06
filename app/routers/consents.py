"""Autorización biométrica voluntaria (L1): texto del evento, estado por persona, registro (también por lotes, desde la cola sin conexión) y configuración del evento.

La aceptación NO la da el digitador: la da la persona al pulsar el botón 1 de la pantalla (o en la preinscripción web) y queda en `audit_consent_logs` (app/consent.py).
Sin una aceptación registrada, el reconocimiento facial no se usa con esa persona (app/faces.py). Ningún dato personal va a los logs."""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import consent, legal_texts
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import StaffUser

router = APIRouter()
DIGITADOR = require_role("digitador")
COORD = require_role_excluding("coordinador", ("comercial",))
MAX_BATCH = 200


@router.get("/events/{event_id}/consent-text")
def consent_text(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    event = get_event_for_staff(event_id, db, staff)
    t = legal_texts.render(event)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="El texto de autorización aún tiene datos de la empresa sin completar: este evento ingresa por cédula o QR")
    return {**{k: t[k] for k in ("version", "variant", "hash", "title", "body", "buttons", "adult_checkbox")}, "mode": event.consent_prompt_mode, "every_scan": legal_texts.every_scan_prompt()}


@router.get("/events/{event_id}/consent-status/{user_id}")
def consent_status(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """¿Hay aceptación vigente de esta persona en este evento? `last`: 'consent' | 'rejection' | 'revocation' | None."""
    event = get_event_for_staff(event_id, db, staff)
    last = consent.latest(db, event.tenant_id, user_id, event.id)
    return {"accepted": consent.has_acceptance(db, event.tenant_id, user_id, event.id), "last": last.reason if last else None, "mode": event.consent_prompt_mode}


def _when(raw):
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@router.post("/events/{event_id}/consents")
def record_consents(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """Registra decisiones de la persona: {entries: [{id (UUID del dispositivo), user_id, decision: 'accept'|'reject', adult, text_hash, version, device, at}]}.
    Idempotente por `id`: reintentar o sincronizar dos veces no duplica. `accept` exige la declaración de mayoría de edad (`adult`); sin ella se registra como rechazo."""
    event = get_event_for_staff(event_id, db, staff)
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Envía entre 1 y {MAX_BATCH} registros")
    inserted = duplicated = 0
    for e in entries:
        uid = re.sub(r"[\s.]", "", str(e.get("user_id") or ""))
        entry_id, text_hash = str(e.get("id") or ""), str(e.get("text_hash") or "")
        try:
            uuid.UUID(entry_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Cada registro necesita un identificador UUID generado en el dispositivo")
        if not uid or not re.fullmatch(r"[0-9a-f]{64}", text_hash) or e.get("decision") not in ("accept", "reject"):
            raise HTTPException(status_code=400, detail="Registro incompleto")
        accepted = e["decision"] == "accept" and bool(e.get("adult"))
        ok = consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=str(e.get("version") or "")[:40] or legal_texts.render(event)["version"],
                            legal_text_hash=text_hash, accepted=accepted, adult=bool(e.get("adult")), reason="consent" if accepted else "rejection",
                            device=(str(e.get("device") or f"staff:{staff.id}"))[:120], entry_id=entry_id, at=_when(e.get("at")))
        inserted, duplicated = inserted + ok, duplicated + (not ok)
    db.commit()
    return {"inserted": inserted, "duplicated": duplicated}


@router.put("/events/{event_id}/consent-config")
def set_consent_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Quién es el Responsable del evento (golden | tercero + datos del organizador) y cada cuánto se pide la autorización (once | every_scan)."""
    event = get_event_for_staff(event_id, db, staff)
    mode = str(data.get("controller_mode", event.controller_mode))
    name, nit, email = (str(data.get(k, getattr(event, k)) or "").strip() or None for k in ("organizer_name", "organizer_nit", "organizer_privacy_email"))
    err = legal_texts.validate_event_config(mode, name, nit, email)
    prompt = str(data.get("consent_prompt_mode", event.consent_prompt_mode))
    if err or prompt not in ("once", "every_scan"):
        raise HTTPException(status_code=400, detail=err or "El modo de la autorización debe ser «once» o «every_scan»")
    event.controller_mode, event.organizer_name, event.organizer_nit, event.organizer_privacy_email, event.consent_prompt_mode = mode, name, nit, email, prompt
    db.commit()
    return {"controller_mode": mode, "organizer_name": name, "organizer_nit": nit, "organizer_privacy_email": email, "consent_prompt_mode": prompt}
