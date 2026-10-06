"""CAMINO B: /aceptar/<código del evento>: la persona acepta (o no) el reconocimiento facial y da su selfie desde su celular, ANTES del evento. Página pública y sin sesión.

Reglas: solo quien YA está inscrito en el evento (no se crean personas aquí); el texto que firma es el literal de la auditora (versión `v1.1_web`) y la huella del texto se registra;
menores de 18 años quedan fuera; el vector se calcula DESPUÉS, por tarea, nunca antes de aceptar; y como alguien podría aceptar con la cédula de otra persona, la aceptación queda «por
verificar» (`web_acceptances`): no vale para el reconocimiento hasta que el personal confirme la identidad en puerta con el documento o el QR."""
import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import consent, crypto, jobs, legal_texts, minors, privacy, security
from app.database import get_db
from app.models import Event, EventAttendee, User, WebAcceptance
from app.storage import photo_key
from app.timeutil import utcnow
from app.ttlcache import SlidingLimiter

router = APIRouter()
_limiter = SlidingLimiter()
MAX_SELFIE_BYTES = 8 * 1024 * 1024
GENERIC_NOT_FOUND = "No encontramos tu inscripción con ese documento y esa fecha. Acércate a la acreditación con tu cédula o QR."


def _event(db: Session, code: str) -> Event:
    event = db.query(Event).filter(Event.event_code == code).first()
    if not event or not event.aceptar_enabled or not event.facial_enabled or event.status == "finalizado":
        raise HTTPException(status_code=404, detail="Esta página no está disponible")
    return event


def _limit(request: Request, kind: str, max_hits: int) -> None:
    ip = security.limit_ip(request)
    if ip is not None and not _limiter.hit((kind, ip), max_hits, timedelta(minutes=10).total_seconds()):
        raise HTTPException(status_code=429, detail="Demasiados intentos seguidos — espera unos minutos.")


@router.get("/aceptar/{code}", response_class=HTMLResponse)
def page(code: str, request: Request, db: Session = Depends(get_db)):
    from app.main import templates
    event = _event(db, code)
    return templates.TemplateResponse(request=request, name="aceptar.html", context={"event_name": event.name, "code": code})


@router.get("/api/aceptar/{code}/text")
def consent_text(code: str, request: Request, db: Session = Depends(get_db)):
    _limit(request, "aceptar_text", 60)
    event = _event(db, code)
    t = legal_texts.render(event, web=True)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="Esta página aún no está disponible")
    return {k: t[k] for k in ("version", "hash", "title", "body", "buttons", "adult_checkbox")}


@router.post("/api/aceptar/{code}")
def submit(code: str, request: Request, cedula: str = Form(...), birth_date: str = Form(""), decision: str = Form(...), text_hash: str = Form(...), adult: bool = Form(False),
           file: UploadFile = File(None), db: Session = Depends(get_db)):
    _limit(request, "aceptar_post", 15)
    event = _event(db, code)
    t = legal_texts.render(event, web=True)
    if t["blocked"]:
        raise HTTPException(status_code=503, detail="Esta página aún no está disponible")
    if text_hash != t["hash"]:
        raise HTTPException(status_code=409, detail="El texto cambió: recarga la página")
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="Decisión no válida")
    uid = re.sub(r"[\s.]", "", cedula)
    birth = minors.parse_birth(birth_date)
    if not uid or birth is None:
        raise HTTPException(status_code=400, detail="Escribe tu documento y tu fecha de nacimiento")
    user = (db.query(User).join(EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id))
            .filter(EventAttendee.event_id == event.id, User.id == uid, User.tenant_id == event.tenant_id).first())
    if user is None or (user.birth_date is not None and user.birth_date != birth):      # mismo mensaje en ambos casos: no se revela quién está inscrito
        raise HTTPException(status_code=404, detail=GENERIC_NOT_FOUND)
    user.birth_date = birth
    if minors.is_minor(birth):
        user.is_biometric_enabled = False
        privacy.purge_person(db, event.tenant_id, uid)
        return {"status": "minor", "message": "No puedes usar el reconocimiento facial. Ingresa con tu cédula o QR en la acreditación."}
    if decision == "reject" or (t["adult_checkbox"] and not adult):
        consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=t["version"], legal_text_hash=t["hash"], accepted=False, adult=bool(adult), reason="rejection", device="web")
        if not consent.has_any_acceptance(db, event.tenant_id, uid):
            privacy.purge_person(db, event.tenant_id, uid)
        db.commit()
        return {"status": "rejected", "message": "Listo: ingresarás con tu cédula o QR, sin restricción alguna."}
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
    consent.record(db, tenant_id=event.tenant_id, user_id=uid, event_id=event.id, version=t["version"], legal_text_hash=t["hash"], accepted=True, adult=True, reason="consent", device="web",
                   entry_id=str(uuid.uuid4()))
    if db.get(WebAcceptance, (event.tenant_id, uid, event.id)) is None:
        db.add(WebAcceptance(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, created_at=utcnow()))
    db.execute(text("UPDATE users SET is_biometric_enabled = true WHERE id = :u AND tenant_id = :t"), {"u": uid, "t": event.tenant_id})
    crypto.save_image(Image.fromarray(arr), photo_key(event.tenant_id, uid))
    jobs.enqueue(db, "face_enroll", {"tenant_id": event.tenant_id, "user_id": uid, "event_id": event.id}, max_attempts=3)
    db.commit()
    jobs.kick()
    return {"status": "accepted", "message": "¡Gracias! Cuando llegues, muestra tu cédula o QR en la acreditación: el personal confirmará tu identidad y desde ahí podrás entrar con tu rostro."}
