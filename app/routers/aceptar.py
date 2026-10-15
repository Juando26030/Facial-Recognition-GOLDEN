"""CAMINO B: /aceptar/<código del evento>: la persona acepta (o no) el reconocimiento facial y, según el evento, da su selfie desde su celular, ANTES del evento. Página pública y sin sesión.

Tres formas de llegar (canal que luego dice la constancia): el enlace personal `/aceptar/<código>/<token>` (B2a; el correo del enlace identifica a la persona), el QR del cartel (`?c=qr`) y el
portal web (la dirección sin más). Reglas: solo quien YA está inscrito en el evento (no se crean personas aquí); el texto que firma es el literal de la auditora (versión `v1.1_web`) y la huella
del texto se registra; la fecha de nacimiento se valida ANTES de mostrar el texto y de abrir la cámara (menores de 18 años quedan fuera, B2e); el vector se calcula DESPUÉS, por tarea, nunca antes
de aceptar; la fuente de la foto la define el evento (B2c): selfie de la persona, o la foto que entregó el cliente (entonces no se pide selfie). Como alguien podría aceptar con la cédula de otra
persona, la aceptación queda «por verificar» (`web_acceptances`) hasta que el personal confirme la identidad en puerta; SALVO el enlace personal que salió del listado del organizador (correo
propio de cada persona): abrirlo verifica (`verified_via='link'`)."""
import hashlib
import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import company, consent, consent_receipt, crypto, enroll, faces, jobs, legal_texts, liveness, minors, privacy, security
from app.database import get_db
from app.models import Event, EventAttendee, RateLimitEvent, User, WebAcceptance
from app.storage import get_storage, photo_key
from app.timeutil import utcnow
from app.ttlcache import SlidingLimiter

router = APIRouter()
_limiter = SlidingLimiter()
MAX_SELFIE_BYTES = 8 * 1024 * 1024
GENERIC_NOT_FOUND = "No encontramos tu inscripción con ese documento y esa fecha. Acércate a la acreditación con tu cédula o QR."
LINK_NOT_FOUND = "Este enlace no es válido o ya no está vigente. Acércate a la acreditación con tu cédula o QR."
MINOR_MESSAGE = "No puedes usar el reconocimiento facial. Ingresa con tu cédula o QR en la acreditación."


def _already(db: Session, event: Event, uid: str):
    """Quien YA aceptó no puede volver a tomar, cambiar ni renovar la selfie por esta página (enlace personal o portal): solo ve el estado. El cambio de foto lo hace el personal en acreditación; revocar, por el correo de privacidad o con el personal."""
    if not consent.has_acceptance(db, event.tenant_id, uid, event.id):
        return None
    return {"status": "already", "message": ("Tu autorización ya quedó registrada. Esta página no permite cambiar tu foto: si quieres actualizarla, acércate a la acreditación; "
                                             f"si quieres revocar tu autorización, escribe a {company.get('PRIVACY_EMAIL')} o díselo al personal.")}
DEVICE = {"link": "web-link", "qr": "web-qr", "web": "web-portal"}


LINK_MAX_FAILS, LINK_WINDOW = 5, timedelta(minutes=15)      # intentos fallidos por enlace personal y pausa (sin guardar IP ni User-Agent: la clave es la huella del enlace)
LINK_DOC_NOT_FOUND = "No encontramos tu inscripción con ese documento. Acércate a la acreditación con tu cédula o QR."
LINK_BLOCKED = "Demasiados intentos con este enlace. Espera unos 15 minutos o ingresa con tu cédula o QR en la acreditación."


def _link_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _link_failures(db: Session, token: str) -> int:
    return db.query(RateLimitEvent).filter(RateLimitEvent.kind == "aceptar_link_fail", RateLimitEvent.key == _link_key(token), RateLimitEvent.created_at > utcnow() - LINK_WINDOW).count()


class NeedBirth(Exception):
    """Enlace personal: la cédula coincide pero la base no tiene la fecha de nacimiento de esa persona: hay que pedirla (y bloquear si es menor)."""


def _verify(db: Session, event: Event, cedula: str, token: str, birth_raw: str):
    """(persona, asistente, vino_por_enlace, fecha_de_nacimiento).
    * Página general (sin enlace): cédula + fecha, como siempre.
    * Enlace personal: SOLO la cédula de ESA persona (la del código); la mayoría de edad sale de la fecha de nacimiento ya cargada en la base. Si la base no la tiene, entonces y solo
      entonces se pide (NeedBirth) y se bloquea si es menor. Cédula equivocada = el mismo mensaje genérico; tras LINK_MAX_FAILS fallos en LINK_WINDOW el enlace se pausa
      (conteo en `rate_limit_events` con la huella del enlace, sin IP)."""
    if not token:
        user, att, by_link = _resolve(db, event, cedula, token)
        return user, att, by_link, _check_birth(user, birth_raw)
    if _link_failures(db, token) >= LINK_MAX_FAILS:
        raise HTTPException(status_code=429, detail=LINK_BLOCKED)
    user, att, by_link = _resolve(db, event, "", token)
    if re.sub(r"[\s.]", "", cedula or "") != user.id:
        security.record_event(db, "aceptar_link_fail", _link_key(token), None)
        raise HTTPException(status_code=404, detail=LINK_DOC_NOT_FOUND)
    security.clear_events(db, "aceptar_link_fail", _link_key(token))
    if user.birth_date is not None:
        return user, att, by_link, user.birth_date
    if not (birth_raw or "").strip():
        raise NeedBirth()
    return user, att, by_link, _check_birth(user, birth_raw)


def _event(db: Session, code: str) -> Event:
    event = db.query(Event).filter(Event.event_code == code).first()
    if not event or not event.aceptar_enabled or not event.facial_enabled or event.biometrics_locked or event.status == "finalizado":
        raise HTTPException(status_code=404, detail="Esta página no está disponible")
    return event


def _limit(request: Request, kind: str, max_hits: int) -> None:
    ip = security.limit_ip(request)
    if ip is not None and not _limiter.hit((kind, ip), max_hits, timedelta(minutes=10).total_seconds()):
        raise HTTPException(status_code=429, detail="Demasiados intentos seguidos — espera unos minutos.")


def _by_token(db: Session, event: Event, token: str):
    att = db.query(EventAttendee).filter(EventAttendee.accept_token == token, EventAttendee.event_id == event.id).first() if token else None
    user = db.query(User).filter(User.id == att.user_id, User.tenant_id == att.tenant_id).first() if att else None
    return (user, att) if user is not None else (None, None)


def _by_cedula(db: Session, event: Event, cedula: str):
    uid = re.sub(r"[\s.]", "", cedula or "")
    if not uid:
        return None, None
    att = db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id == uid, EventAttendee.tenant_id == event.tenant_id).first()
    user = db.query(User).filter(User.id == uid, User.tenant_id == event.tenant_id).first() if att else None
    return (user, att) if user is not None else (None, None)


def _resolve(db: Session, event: Event, cedula: str, token: str):
    """(persona, asistente, vino_por_enlace). 404 genérico: no revela quién está inscrito."""
    if token:
        user, att = _by_token(db, event, token)
        if user is None:
            raise HTTPException(status_code=404, detail=LINK_NOT_FOUND)
        return user, att, True
    user, att = _by_cedula(db, event, cedula)
    if user is None:
        raise HTTPException(status_code=404, detail=GENERIC_NOT_FOUND)
    return user, att, False


def _check_birth(user: User, birth_raw: str):
    """La fecha de nacimiento escrita: válida y, si ya hay una registrada, la misma. 400 si falta o no se entiende; 404 genérico si no coincide."""
    birth = minors.parse_birth(birth_raw)
    if birth is None:
        raise HTTPException(status_code=400, detail="Escribe tu fecha de nacimiento")
    if user.birth_date is not None and user.birth_date != birth:
        raise HTTPException(status_code=404, detail=GENERIC_NOT_FOUND)
    return birth


def _need_selfie(event: Event) -> bool:
    """B2c: fuente B (la persona se toma la selfie) salvo que el cliente entregue las fotos antes (fuente A)."""
    return not event.client_photos_before


def _logo_url(event: Event, code: str) -> str:
    """Logo de la página pública: el propio del evento si lo tiene cargado; si no (o si en el panel está oculto), el de Golden."""
    from app.main import default_logo_url
    if event.logo_mode == "custom" and event.logo_path:
        return f"/api/aceptar/{code}/logo"
    return default_logo_url()


def _page(request: Request, event: Event, code: str, token: str, channel: str, already: str = ""):
    from app.main import templates
    return templates.TemplateResponse(request=request, name="aceptar.html", context={"event_name": event.name, "code": code, "token": token, "channel": channel, "need_selfie": _need_selfie(event), "already": already,
                                                                                     "logo_url": _logo_url(event, code)})


@router.get("/api/aceptar/{code}/logo")
def public_logo(code: str, db: Session = Depends(get_db)):
    """El logo propio del evento para la página pública de aceptación (sin sesión): solo mientras la página esté disponible."""
    event = _event(db, code)
    if event.logo_mode != "custom" or not event.logo_path or not get_storage().exists(event.logo_path):
        raise HTTPException(status_code=404, detail="Sin logo propio")
    return get_storage().response(event.logo_path, headers={"Cache-Control": "public, max-age=300"})


@router.get("/aceptar/{code}", response_class=HTMLResponse)
def page(code: str, request: Request, c: str = "", db: Session = Depends(get_db)):
    event = _event(db, code)
    return _page(request, event, code, "", "qr" if c == "qr" else "web")


@router.get("/aceptar/{code}/{token}", response_class=HTMLResponse)
def personal_page(code: str, token: str, request: Request, db: Session = Depends(get_db)):
    _limit(request, "aceptar_link", 60)
    event = _event(db, code)
    user, _att = _by_token(db, event, token)
    if user is not None:                                       # quien ya aceptó ve de inmediato su estado: sin pedir cédula ni fecha y sin ningún dato personal
        done = _already(db, event, user.id)
        if done:
            return _page(request, event, code, token, "link", already=done["message"])
    if user is None:
        return HTMLResponse("<meta name='viewport' content='width=device-width, initial-scale=1'><h3 style='font-family:system-ui,sans-serif;text-align:center;margin:20vh 1rem 0'>" + LINK_NOT_FOUND + "</h3>", status_code=404)
    return _page(request, event, code, token, "link")


@router.get("/api/aceptar/{code}/text")
def consent_text(code: str, request: Request, db: Session = Depends(get_db)):
    _limit(request, "aceptar_text", 60)
    event = _event(db, code)
    t = legal_texts.render(event, web=True)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="Esta página aún no está disponible")
    return {k: t[k] for k in ("version", "hash", "title", "body", "buttons", "adult_checkbox")}


@router.post("/api/aceptar/{code}/check")
def check(code: str, request: Request, cedula: str = Form(""), token: str = Form(""), birth_date: str = Form(""), db: Session = Depends(get_db)):
    """B2e: la fecha de nacimiento se valida ANTES de mostrar el texto y de abrir la cámara. Un menor nunca ve la cámara ni se guarda nada suyo."""
    _limit(request, "aceptar_check", 30)
    event = _event(db, code)
    try:
        user, _att, _link, birth = _verify(db, event, cedula, token, birth_date)
    except NeedBirth:
        return {"status": "need_birth"}
    if minors.is_minor(birth):
        user.birth_date = birth
        user.is_biometric_enabled = False
        privacy.purge_person(db, event.tenant_id, user.id)
        return {"status": "minor", "message": MINOR_MESSAGE}
    return _already(db, event, user.id) or {"status": "ok", "selfie": _need_selfie(event)}


@router.post("/api/aceptar/{code}")
def submit(code: str, request: Request, cedula: str = Form(""), token: str = Form(""), channel: str = Form("web"), birth_date: str = Form(""), decision: str = Form(...), text_hash: str = Form(...),
           adult: bool = Form(False), file: UploadFile = File(None), db: Session = Depends(get_db)):
    _limit(request, "aceptar_post", 15)
    event = _event(db, code)
    t = legal_texts.render(event, web=True)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="Esta página aún no está disponible")
    if text_hash != t["hash"]:
        raise HTTPException(status_code=409, detail="El texto cambió: recarga la página")
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="Decisión no válida")
    try:
        user, att, by_link, birth = _verify(db, event, cedula, token, birth_date)
    except NeedBirth:
        raise HTTPException(status_code=400, detail="Escribe tu fecha de nacimiento")
    uid = user.id
    ch = "link" if by_link else ("qr" if channel == "qr" else "web")
    user.birth_date = birth
    if minors.is_minor(birth):
        user.is_biometric_enabled = False
        privacy.purge_person(db, event.tenant_id, uid)
        return {"status": "minor", "message": MINOR_MESSAGE}
    done = _already(db, event, uid)
    if done:
        db.rollback()                                          # nada cambia: ni la foto, ni el registro, ni la fecha de nacimiento escrita
        return done
    device = DEVICE[ch]
    if decision == "reject" or (t["adult_checkbox"] and not adult):
        consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=t["version"], legal_text_hash=t["hash"], accepted=False, adult=bool(adult), reason="rejection", device=device)
        if not consent.has_any_acceptance(db, event.tenant_id, uid):
            privacy.purge_person(db, event.tenant_id, uid)
        db.commit()
        return {"status": "rejected", "message": "Listo: ingresarás con tu cédula o QR, sin restricción alguna."}
    arr = None
    if _need_selfie(event):                                   # fuente B: la persona se toma la selfie
        if file is None or not file.filename:
            raise HTTPException(status_code=400, detail="Falta tu selfie")
        raw = file.file.read(MAX_SELFIE_BYTES + 1)
        if len(raw) > MAX_SELFIE_BYTES:
            raise HTTPException(status_code=413, detail="La foto es demasiado grande")
        try:
            from app.biometrics import BiometricEngine
            arr = BiometricEngine.process_image_stream(raw)
        except Exception:  # noqa: BLE001 — imagen ilegible
            raise HTTPException(status_code=400, detail="La imagen no es válida")
        try:                                                  # B2d: una sola cara, de tamaño suficiente, nítida y con luz; si no, se repite y NADA queda registrado
            problem = liveness.selfie_problem(faces.analyze(arr))
        except faces.Busy:
            raise HTTPException(status_code=503, detail="Estamos recibiendo muchas fotos. Intenta de nuevo en unos segundos.", headers={"Retry-After": "3"})
        if problem:
            db.rollback()
            raise HTTPException(status_code=400, detail=problem)
    entry_id = str(uuid.uuid4())
    consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=t["version"], legal_text_hash=t["hash"], accepted=True, adult=True, reason="consent", device=device, entry_id=entry_id)
    now = utcnow()
    trusted = bool(by_link and att is not None and att.accept_trusted)
    wa = db.get(WebAcceptance, (event.tenant_id, uid, event.id))
    if wa is None:
        wa = WebAcceptance(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, created_at=now)
        db.add(wa)
    if trusted and wa.verified_at is None:                  # dueño del correo al que el organizador envió el enlace: verificada, sin confirmación del personal
        wa.verified_at, wa.verified_via = now, "link"
    db.execute(text("UPDATE users SET is_biometric_enabled = true WHERE id = :u AND tenant_id = :t"), {"u": uid, "t": event.tenant_id})
    if arr is not None:
        crypto.save_image(Image.fromarray(arr), photo_key(event.tenant_id, uid))
        jobs.enqueue(db, "face_enroll", {"tenant_id": event.tenant_id, "user_id": uid, "event_id": event.id}, max_attempts=3)
    else:
        enroll.maybe_enqueue(db, event.tenant_id, uid, event.id)      # fuente A: si el cliente ya entregó su foto, ahora sí se calcula el vector
    consent_receipt.enqueue(db, entry_id, event.tenant_id, event.id, uid, ch)
    db.commit()
    jobs.kick(pool="faces")
    jobs.kick()
    if trusted:
        return {"status": "accepted", "verified": True, "message": "¡Gracias! Tu autorización quedó registrada. Si tienes un correo registrado, te enviaremos tu constancia."}
    return {"status": "accepted", "verified": False, "message": "¡Gracias! Cuando llegues, muestra tu cédula o QR en la acreditación: el personal confirmará tu identidad y desde ahí podrás entrar con tu rostro."}
