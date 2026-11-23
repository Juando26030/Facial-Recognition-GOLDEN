"""Autorización biométrica voluntaria (L1): texto del evento, estado por persona, registro (también por lotes, desde la cola sin conexión) y configuración del evento.

La aceptación NO la da el digitador: la da la persona al pulsar el botón 1 de la pantalla (o en la preinscripción web) y queda en `audit_consent_logs` (app/consent.py).
Sin una aceptación registrada, el reconocimiento facial no se usa con esa persona (app/faces.py). Ningún dato personal va a los logs."""
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import localmode
from app import acceptmail, audit_actions, biometric_setup, event_history, consent, consent_receipt, enroll, faces, jobs, legal_texts, privacy, status_changes
from app.timeutil import utcnow
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app import event_archive
from app.database import get_db
from app.routers.api import SYNC_HASH_RE, _event_for_sync, _roster_map
from app.models import StaffUser, SystemEvent, User

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
    event_archive.require_data_open(event, staff)
    last = consent.latest(db, event.tenant_id, user_id, event.id)
    blocked = consent.biometric_blocked(db, event.tenant_id, user_id)
    return {"accepted": not blocked and consent.has_acceptance(db, event.tenant_id, user_id, event.id), "last": last.reason if last else None, "mode": event.consent_prompt_mode, "blocked": blocked,
            "face": enroll.status(db, event.tenant_id, user_id), "verify": consent.web_pending(db, event.tenant_id, user_id, event.id)}


MAX_AGE = timedelta(days=8)           # un dispositivo sin red puede sincronizar hasta 7 días después del evento
MAX_AHEAD = timedelta(minutes=5)      # tolerancia de reloj del dispositivo


def _when(raw):
    """Fecha de la decisión según el dispositivo. Fuera de [ahora-8 días, ahora+5 min] no es creíble (E1: un digitador no puede fechar a voluntad ni «blindar»
    una aceptación con una fecha futura): se descarta y `consent.record` usa la hora del servidor."""
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    now = datetime.now(timezone.utc)
    return d if now - MAX_AGE <= d <= now + MAX_AHEAD else None


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
    inserted = duplicated = unknown = doubtful = after_revert = 0
    reverted_at = event.sync_revert[0] if event.sync_revert else None          # devuelto a «Creado»: se guardan SIEMPRE (son la prueba de la PERSONA), solo se cuentan los dudosos y los posteriores
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
        if ok and reverted_at is not None:
            verdict = status_changes.classify(e.get("at"), utcnow(), reverted_at)[0]
            doubtful, after_revert = doubtful + (verdict == "no_hour"), after_revert + (verdict == "after")
            if verdict != "ok":          # `audit_consent_logs` es solo INSERT (no se le puede agregar una marca): el aviso queda aparte, por entrada, sin datos personales (solo el UUID del dispositivo)
                db.add(SystemEvent(kind=status_changes.CONSENT_FLAGS[verdict], ref=str(event.id), detail=entry_id, at=utcnow()))
        if ok and accepted:
            consent_receipt.enqueue(db, entry_id, event.tenant_id, event.id, uid, consent_receipt.channel_of(str(e.get("device") or "")))      # constancia por correo (si tiene correo); en segundo plano
        if ok and accepted:                                     # volvió a aceptar tras una revocación: el reconocimiento vuelve a estar habilitado para esta persona (adulta)
            enroll.maybe_enqueue(db, event.tenant_id, uid, event.id)      # si ya tenía una foto guardada, ahora sí se calcula su vector
            db.execute(text("UPDATE users SET is_biometric_enabled = true WHERE id = :u AND tenant_id = :t AND is_biometric_enabled = false"), {"u": uid, "t": event.tenant_id})
        if ok and not accepted and not consent.has_any_acceptance(db, event.tenant_id, uid):
            privacy.purge_person(db, event.tenant_id, uid)      # regla A: quien no acepta no conserva un vector pre-calculado (ni su foto); purge_person hace el commit
    db.commit()
    if inserted:
        jobs.kick(pool="faces")
        jobs.kick()                                             # la constancia por correo (consent_receipt) va por la cola GENERAL: sin este aviso esperaba al barrido horario (igual que aceptar.py)
    return {"inserted": inserted, "duplicated": duplicated, "unknown": unknown, **({"doubtful": doubtful, "after_revert": after_revert} if reverted_at is not None else {})}


@router.post("/events/{event_id}/consent-click")
def consent_click(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """CAMINO 2 (un clic y rostro): la persona pulsó «Acepto…» en la pantalla del quiosco. Devuelve un token de corta vida (CONSENT_CLICK_TTL) que `/api/recognize` acepta para comparar
    1 a N con los vectores pre-calculados del evento. NO registra nada todavía: la aceptación se registra solo si hay coincidencia, atribuida a la persona identificada.
    Solo existe en eventos con `precalculo_autorizado`."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
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
        blockers = biometric_setup.precalc_blockers(event, ref, fecha, data.get("garantia") is True)
        if blockers:
            raise HTTPException(status_code=400, detail="Para autorizar el pre-cálculo falta: " + ", ".join(blockers))
        event.precalculo_autorizado, event.precalculo_anexo_ref, event.precalculo_anexo_fecha, event.precalculo_garantia = True, ref[:200], fecha, True
    db.commit()
    return {"precalculo_autorizado": event.precalculo_autorizado, "anexo_ref": event.precalculo_anexo_ref, "anexo_fecha": event.precalculo_anexo_fecha.isoformat() if event.precalculo_anexo_fecha else None}


@router.put("/events/{event_id}/consent-config")
def set_consent_config(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Quién es el Responsable del evento (golden | tercero + datos del organizador) y cada cuánto se pide la autorización (once | every_scan)."""
    event = get_event_for_staff(event_id, db, staff)
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    mode = str(data.get("controller_mode", event.controller_mode))
    name, nit, email = (str(data.get(k, getattr(event, k)) or "").strip() or None for k in ("organizer_name", "organizer_nit", "organizer_privacy_email"))
    aceptar = bool(data.get("aceptar_enabled", event.aceptar_enabled))
    err = legal_texts.validate_event_config(mode, name, nit, email)
    prompt = str(data.get("consent_prompt_mode", event.consent_prompt_mode))
    if err or prompt not in ("once", "every_scan"):
        raise HTTPException(status_code=400, detail=err or "El modo de la autorización debe ser «once» o «every_scan»")
    event.controller_mode, event.organizer_name, event.organizer_nit, event.organizer_privacy_email, event.consent_prompt_mode = mode, name, nit, email, prompt
    event.aceptar_enabled = aceptar
    _hr = event_history.record(db, event, _hb, staff, "switch")
    db.commit()
    event_history.kick_after(_hr)
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
    event_archive.require_data_open(event, staff)
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
    db.execute(text("UPDATE users SET face_captured_at = COALESCE(face_captured_at, :n) WHERE id = :u AND tenant_id = :t"), {"n": utcnow(), "u": uid, "t": event.tenant_id})      # 0C (E5): arranca el reloj de retención aunque el vector aún no exista
    jobs.enqueue(db, "face_enroll", {"tenant_id": event.tenant_id, "uref": jobs.person_ref(uid), "event_id": event.id}, max_attempts=3)
    db.commit()
    jobs.kick(pool="faces")
    return {"queued": True, "face": "pending"}


@router.post("/events/{event_id}/web-acceptance/{user_id}/verify")
def verify_web_acceptance(event_id: int, user_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """El personal confirma, con el documento físico o el QR de la persona, que quien aceptó desde el celular es ella: desde aquí el reconocimiento facial puede usarla."""
    from app import faces_version
    from app.models import WebAcceptance
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    uid = re.sub(r"[\s.]", "", user_id)
    row = db.get(WebAcceptance, (event.tenant_id, uid, event.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Esta persona no tiene una aceptación pendiente de verificar")
    if row.verified_at is None:
        row.verified_at, row.verified_by_staff_id = utcnow(), staff.id
        faces_version.bump(db, event_ids=[event.id])
        db.commit()
    return {"verified": True}


def _setup_config(event) -> dict:
    return {"facial_enabled": event.facial_enabled, "controller_mode": event.controller_mode, "organizer_name": event.organizer_name, "organizer_nit": event.organizer_nit,
            "organizer_privacy_email": event.organizer_privacy_email, "client_photos_before": event.client_photos_before, "consent_prompt_mode": event.consent_prompt_mode,
            "aceptar_enabled": event.aceptar_enabled, "precalculo_autorizado": event.precalculo_autorizado, "biometrics_locked": bool(event.biometrics_locked),
            "accept_link_email": bool(event.accept_link_email), "face_door_enabled": bool(event.face_door_enabled),
            "accept_no_birth_mode": event.accept_no_birth_mode or "any"}


@router.get("/events/{event_id}/biometric-setup")
def get_biometric_setup(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Paso guiado de biometría: la configuración actual y el resumen en lenguaje simple (qué pasará en la puerta y qué falta)."""
    event = get_event_for_staff(event_id, db, staff)
    return {"config": _setup_config(event), **biometric_setup.summary(event)}


@router.put("/events/{event_id}/biometric-setup")
def put_biometric_setup(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Guarda el paso guiado de una vez y validado EN EL SERVIDOR (esto es lo que protege; la pantalla solo guía). Todo o nada. El pre-cálculo NO se activa aquí (solo un super_admin, con anexo y garantía);
    si la nueva configuración lo deja sin sustento (evento propio, sin fotos previas o rostro apagado) se APAGA solo."""
    event = get_event_for_staff(event_id, db, staff)
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    cur = _setup_config(event)
    new = {**cur, **{k: data[k] for k in cur if k in data and k != "precalculo_autorizado"}}
    if localmode.is_local_server():          # 19-nov-2026: en el servidor local NO hay rostro ni nada de su flujo (aceptación por celular, fotos previas, entrada con rostro): se rechaza activarlo y se deja apagado
        if any(bool(data.get(k)) for k in ("facial_enabled", "aceptar_enabled", "client_photos_before", "accept_link_email", "face_door_enabled")):
            raise HTTPException(status_code=403, detail=localmode.LOCAL_NO_FACE_MSG)
        for k in ("facial_enabled", "aceptar_enabled", "client_photos_before", "accept_link_email", "face_door_enabled"):
            new[k] = False
    if new["biometrics_locked"] and not cur["biometrics_locked"]:      # al poner el candado, lo que no se pidió expresamente se apaga solo
        for k in ("facial_enabled", "aceptar_enabled", "client_photos_before", "accept_link_email", "face_door_enabled"):
            if k not in data:
                new[k] = False
    for k in ("organizer_name", "organizer_nit", "organizer_privacy_email"):
        new[k] = (str(new[k] or "").strip() or None)
    errors = biometric_setup.validate(str(new["controller_mode"]), bool(new["facial_enabled"]), new["organizer_name"], new["organizer_nit"], new["organizer_privacy_email"],
                                      bool(new["client_photos_before"]), bool(new["aceptar_enabled"]), str(new["consent_prompt_mode"]), locked=bool(new["biometrics_locked"]), accept_link=bool(new["accept_link_email"]))
    if new["accept_no_birth_mode"] not in ("any", "require_personal_link"):
        errors.append("La aceptación cuando la base no trae fecha de nacimiento debe ser «cualquier fecha adulta» o «exigir el enlace personal»")
    if new["face_door_enabled"] and (not new["facial_enabled"] or new["biometrics_locked"]):
        errors.append("La entrada con rostro (autoservicio) necesita el reconocimiento facial activo y sin candado")
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    event.biometrics_locked = bool(new["biometrics_locked"])
    event.face_door_enabled = bool(new["face_door_enabled"])
    event.accept_link_email = bool(new["accept_link_email"])
    if str(new["accept_no_birth_mode"]) != (event.accept_no_birth_mode or "any"):
        audit_actions.record(db, staff, "update", "event_accept_no_birth_mode", event.id, event.name, f"{event.accept_no_birth_mode or 'any'} -> {new['accept_no_birth_mode']}")
    event.accept_no_birth_mode = str(new["accept_no_birth_mode"])
    event.facial_enabled, event.controller_mode = bool(new["facial_enabled"]), str(new["controller_mode"])
    event.organizer_name, event.organizer_nit, event.organizer_privacy_email = new["organizer_name"], new["organizer_nit"], new["organizer_privacy_email"]
    event.client_photos_before, event.consent_prompt_mode, event.aceptar_enabled = bool(new["client_photos_before"]), str(new["consent_prompt_mode"]), bool(new["aceptar_enabled"])
    if event.precalculo_autorizado and not (event.facial_enabled and event.controller_mode == "tercero" and event.client_photos_before):
        event.precalculo_autorizado = False
    _hr = event_history.record(db, event, _hb, staff, "switch")
    db.commit()
    event_history.kick_after(_hr)
    return {"config": _setup_config(event), **biometric_setup.summary(event)}


# ------------------------------------------------------------------------------------------------------------------------------------ envío masivo de enlaces personales (app/acceptmail.py)
def _csv(text: str, name: str) -> Response:
    return Response(content="﻿" + text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/events/{event_id}/accept-mail")
def accept_mail_status(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Vista previa y estado del envío masivo: cuántas personas recibirían el correo, cuántas se omiten y por qué."""
    return acceptmail.preview(db, get_event_for_staff(event_id, db, staff))


@router.post("/events/{event_id}/accept-mail/test")
def accept_mail_test(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Envío de prueba: el correo aprobado, solo a la dirección indicada."""
    r = acceptmail.send_test(db, get_event_for_staff(event_id, db, staff), str(data.get("to") or ""), staff.id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["detail"])
    return r


@router.post("/events/{event_id}/accept-mail/start")
def accept_mail_start(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    if data.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Falta la confirmación.")
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    r = acceptmail.start(db, event, staff.id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["detail"])
    return r


@router.post("/events/{event_id}/accept-mail/stop")
def accept_mail_stop(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    r = acceptmail.stop(db, get_event_for_staff(event_id, db, staff), staff.id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["detail"])
    return r


@router.get("/events/{event_id}/accept-links.csv")
def accept_links_csv(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Enlaces personales confiables de los adultos del listado (para enviarlos por otro medio). Cada enlace es la llave de una persona: se descarga con su sesión y no se guarda en caché."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    text = acceptmail.export_links(db, event, staff.id)
    if text is None:
        raise HTTPException(status_code=400, detail=acceptmail.blocked_reason(event))
    return _csv(text, f"enlaces_{event.event_code}.csv")


@router.get("/events/{event_id}/accept-mail/log.csv")
def accept_mail_log_csv(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return _csv(acceptmail.log_csv(db, event), f"registro_envios_{event.event_code}.csv")


@router.get("/events/{event_id}/accept-mail/pending")
def accept_mail_pending(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    """Personas «sin confirmar» (no se sabe si su correo salió): para reenviarlas a mano, una por una."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return {"pending": acceptmail.pending_list(db, event)}


@router.post("/events/{event_id}/accept-mail/resend")
def accept_mail_resend(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD)):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    r = acceptmail.resend(db, event, str(data.get("user_id") or ""), staff.id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["detail"])
    return r


@router.put("/events/{event_id}/badge-bio-photo")
def set_badge_bio_photo(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(SUPER)):
    """Interruptor de seguridad (A1): permitir imprimir la foto BIOMÉTRICA en la escarapela (física y digital). Apagado por defecto; solo un super administrador lo cambia."""
    event = get_event_for_staff(event_id, db, staff)
    event.badge_bio_photo_allowed = bool(data.get("enabled"))
    db.commit()
    return {"badge_bio_photo_allowed": event.badge_bio_photo_allowed}
