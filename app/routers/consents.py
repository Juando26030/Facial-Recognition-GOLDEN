"""Autorización biométrica voluntaria (L1): texto del evento, estado por persona, registro (también por lotes, desde la cola sin conexión) y configuración del evento.

La aceptación NO la da el digitador: la da la persona al pulsar el botón 1 de la pantalla (o en la preinscripción web) y queda en `audit_consent_logs` (app/consent.py).
Sin una aceptación registrada, el reconocimiento facial no se usa con esa persona (app/faces.py). Ningún dato personal va a los logs."""
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import consent, enroll, faces, jobs, legal_texts, privacy
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.routers.api import SYNC_HASH_RE, _event_for_sync, _roster_map
from app.models import StaffUser, User

router = APIRouter()
DIGITADOR = require_role("digitador")
COORD = require_role_excluding("coordinador", ("comercial",))
SUPER = require_role("super_admin")
MAX_BATCH = 200


@router.get("/events/{event_id}/consent-text")
def consent_text(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    event = get_event_for_staff(event_id, db, staff)
    t = legal_texts.render(event)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="El texto de autorización aún tiene datos de la empresa sin completar: este evento ingresa por cédula o QR")
    return {**{k: t[k] for k in ("version", "variant", "hash", "title", "body", "buttons", "adult_checkbox")}, "mode": event.consent_prompt_mode, "click_mode": bool(event.precalculo_autorizado), "every_scan": legal_texts.every_scan_prompt()}


@router.get("/events/{event_id}/consent-status/{user_id}")
def consent_status(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """¿Hay aceptación vigente de esta persona en este evento? `last`: 'consent' | 'rejection' | 'revocation' | None."""
    event = get_event_for_staff(event_id, db, staff)
    last = consent.latest(db, event.tenant_id, user_id, event.id)
    blocked = consent.biometric_blocked(db, event.tenant_id, user_id)
    return {"accepted": not blocked and consent.has_acceptance(db, event.tenant_id, user_id, event.id), "last": last.reason if last else None, "mode": event.consent_prompt_mode, "blocked": blocked,
            "face": enroll.status(db, event.tenant_id, user_id), "verify": consent.web_pending(db, event.tenant_id, user_id, event.id)}


def _when(raw):
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@router.post("/events/{event_id}/consents")
def record_consents(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """Registra decisiones de la persona: {entries: [{id (UUID del dispositivo), user_id O h (huella del roster local: el dispositivo sin red no guarda la cédula), decision: 'accept'|'reject',
    adult, text_hash, version, device, at}]}. Idempotente por `id`: reintentar o sincronizar dos veces no duplica. `accept` exige la declaración de mayoría de edad (`adult`); sin ella se
    registra como rechazo. Un digitador puede sincronizar hasta 7 días después de finalizado el evento. Una huella que no está en el evento cuenta como `unknown` (no se registra)."""
    event = _event_for_sync(db, event_id, staff)
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Envía entre 1 y {MAX_BATCH} registros")
    rmap = _roster_map(db, event) if any(e.get("h") and not e.get("user_id") for e in entries if isinstance(e, dict)) else {}
    inserted = duplicated = unknown = 0
    for e in entries:
        e = e if isinstance(e, dict) else {}
        h = str(e.get("h") or "").strip().lower()
        uid = re.sub(r"[\s.]", "", str(e.get("user_id") or ""))
        if not uid and SYNC_HASH_RE.match(h):
            uid = rmap.get(h) or _roster_map(db, event, force=True).get(h, "")
            if not uid:
                unknown += 1
                continue
        entry_id, text_hash = str(e.get("id") or ""), str(e.get("text_hash") or "")
        try:
            uuid.UUID(entry_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Cada registro necesita un identificador UUID generado en el dispositivo")
        if not uid or not re.fullmatch(r"[0-9a-f]{64}", text_hash) or e.get("decision") not in ("accept", "reject"):
            raise HTTPException(status_code=400, detail="Registro incompleto")
        accepted = e["decision"] == "accept" and bool(e.get("adult")) and not consent.biometric_blocked(db, event.tenant_id, uid)      # un menor nunca queda como aceptado
        ok = consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=str(e.get("version") or "")[:40] or legal_texts.render(event)["version"],
                            legal_text_hash=text_hash, accepted=accepted, adult=bool(e.get("adult")), reason="consent" if accepted else "rejection",
                            device=(str(e.get("device") or f"staff:{staff.id}"))[:120], entry_id=entry_id, at=_when(e.get("at")))
        inserted, duplicated = inserted + ok, duplicated + (not ok)
        if ok and accepted:                                     # volvió a aceptar tras una revocación: el reconocimiento vuelve a estar habilitado para esta persona (adulta)
            enroll.maybe_enqueue(db, event.tenant_id, uid, event.id)      # si ya tenía una foto guardada, ahora sí se calcula su vector
            db.execute(text("UPDATE users SET is_biometric_enabled = true WHERE id = :u AND tenant_id = :t AND is_biometric_enabled = false"), {"u": uid, "t": event.tenant_id})
        if ok and not accepted and not consent.has_any_acceptance(db, event.tenant_id, uid):
            privacy.purge_person(db, event.tenant_id, uid)      # regla A: quien no acepta no conserva un vector pre-calculado (ni su foto); purge_person hace el commit
    db.commit()
    if inserted:
        jobs.kick(pool="faces")
    return {"inserted": inserted, "duplicated": duplicated, "unknown": unknown}


@router.post("/events/{event_id}/consent-click")
def consent_click(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """CAMINO 2 (un clic y rostro): la persona pulsó «Acepto…» en la pantalla del quiosco. Devuelve un token de corta vida (CONSENT_CLICK_TTL) que `/api/recognize` acepta para comparar
    1 a N con los vectores pre-calculados del evento. NO registra nada todavía: la aceptación se registra solo si hay coincidencia, atribuida a la persona identificada.
    Solo existe en eventos con `precalculo_autorizado`."""
    event = get_event_for_staff(event_id, db, staff)
    if not event.precalculo_autorizado:
        raise HTTPException(status_code=409, detail="Este evento no tiene autorizado el pre-cálculo de vectores: identifica a la persona por cédula o QR")
    t = legal_texts.render(event)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="El texto de autorización aún tiene datos de la empresa sin completar")
    at = datetime.now(timezone.utc).isoformat()
    return {"click_token": faces.make_click_token(event.id, staff.id, t["hash"], legal_texts.VERSION_CLICK, at), "ttl_s": faces.CLICK_TOKEN_TTL}


@router.put("/events/{event_id}/precalculo-autorizado")
def set_precalc(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(SUPER)):
    """Solo super_admin. Para activarlo: evento de un tercero y referencia + fecha (AAAA-MM-DD) del anexo firmado con las declaraciones, garantías e indemnidad."""
    event = get_event_for_staff(event_id, db, staff)
    if not data.get("enabled"):
        event.precalculo_autorizado = False
    else:
        ref = str(data.get("anexo_ref") or "").strip()
        try:
            fecha = date.fromisoformat(str(data.get("anexo_fecha") or ""))
        except ValueError:
            fecha = None
        if event.controller_mode != "tercero":
            raise HTTPException(status_code=400, detail="El pre-cálculo solo se autoriza en eventos de un tercero (con anexo firmado)")
        if not ref or not fecha:
            raise HTTPException(status_code=400, detail="Registra la referencia y la fecha del anexo firmado")
        event.precalculo_autorizado, event.precalculo_anexo_ref, event.precalculo_anexo_fecha = True, ref[:200], fecha
    db.commit()
    return {"precalculo_autorizado": event.precalculo_autorizado, "anexo_ref": event.precalculo_anexo_ref, "anexo_fecha": event.precalculo_anexo_fecha.isoformat() if event.precalculo_anexo_fecha else None}


@router.put("/events/{event_id}/consent-config")
def set_consent_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Quién es el Responsable del evento (golden | tercero + datos del organizador) y cada cuánto se pide la autorización (once | every_scan)."""
    event = get_event_for_staff(event_id, db, staff)
    mode = str(data.get("controller_mode", event.controller_mode))
    name, nit, email = (str(data.get(k, getattr(event, k)) or "").strip() or None for k in ("organizer_name", "organizer_nit", "organizer_privacy_email"))
    aceptar = bool(data.get("aceptar_enabled", event.aceptar_enabled))
    err = legal_texts.validate_event_config(mode, name, nit, email)
    prompt = str(data.get("consent_prompt_mode", event.consent_prompt_mode))
    if err or prompt not in ("once", "every_scan"):
        raise HTTPException(status_code=400, detail=err or "El modo de la autorización debe ser «once» o «every_scan»")
    event.controller_mode, event.organizer_name, event.organizer_nit, event.organizer_privacy_email, event.consent_prompt_mode = mode, name, nit, email, prompt
    event.aceptar_enabled = aceptar
    db.commit()
    return {"controller_mode": mode, "organizer_name": name, "organizer_nit": nit, "organizer_privacy_email": email, "consent_prompt_mode": prompt, "aceptar_enabled": aceptar}


@router.post("/events/{event_id}/enroll-face")
def enroll_face(event_id: int, user_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """CAMINO A: la persona ya aceptó en la pantalla y se captura su rostro en vivo. Guarda la foto cifrada y ENCOLA el cálculo del vector (25 jitters): responde al instante, la puerta no espera.
    Exige aceptación vigente de ESA persona en ESTE evento y que no sea menor de 18 años. Cuando el vector esté listo, las siguientes entradas son por rostro."""
    from PIL import Image

    from app import crypto
    from app.biometrics import BiometricEngine
    from app.storage import photo_key
    event = get_event_for_staff(event_id, db, staff)
    uid = re.sub(r"[\s.]", "", user_id)
    if not event.facial_enabled:
        raise HTTPException(status_code=409, detail="Este evento no usa reconocimiento facial")
    if consent.biometric_blocked(db, event.tenant_id, uid) or not consent.has_acceptance(db, event.tenant_id, uid, event.id):
        raise HTTPException(status_code=403, detail="Sin autorización registrada de la persona: no se capta su rostro")
    if not db.query(User.id).filter(User.id == uid, User.tenant_id == event.tenant_id).first():
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    try:
        arr = BiometricEngine.process_image_stream(file.file.read())
    except Exception:  # noqa: BLE001 — imagen ilegible
        raise HTTPException(status_code=400, detail="La imagen no es válida")
    crypto.save_image(Image.fromarray(arr), photo_key(event.tenant_id, uid))
    jobs.enqueue(db, "face_enroll", {"tenant_id": event.tenant_id, "user_id": uid, "event_id": event.id}, max_attempts=3)
    db.commit()
    jobs.kick(pool="faces")
    return {"queued": True, "face": "pending"}


@router.post("/events/{event_id}/web-acceptance/{user_id}/verify")
def verify_web_acceptance(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """El personal confirma, con el documento físico o el QR de la persona, que quien aceptó desde el celular es ella: desde aquí el reconocimiento facial puede usarla."""
    from app import faces_version
    from app.models import WebAcceptance
    from app.timeutil import utcnow
    event = get_event_for_staff(event_id, db, staff)
    uid = re.sub(r"[\s.]", "", user_id)
    row = db.get(WebAcceptance, (event.tenant_id, uid, event.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Esta persona no tiene una aceptación pendiente de verificar")
    if row.verified_at is None:
        row.verified_at, row.verified_by_staff_id = utcnow(), staff.id
        faces_version.bump(db, event_ids=[event.id])
        db.commit()
    return {"verified": True}
