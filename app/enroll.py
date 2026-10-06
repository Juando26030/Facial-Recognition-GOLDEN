"""Inscripción del rostro DESPUÉS de la aceptación de la persona (camino A del quiosco y camino B de /aceptar): la foto (captura en vivo o selfie) se guarda cifrada y el VECTOR se calcula
en una tarea en segundo plano, con 25 jitters: la puerta nunca espera ese cálculo. Reglas:
  * Nunca se calcula el vector de alguien sin una aceptación vigente registrada en `audit_consent_logs` para ese evento (se vuelve a comprobar al ejecutar la tarea).
  * Menores de 18 años: nada (ni foto ni vector).
  * Si no se detecta un rostro, la foto se borra: no queda nada guardado.
Idempotente (una tarea repetida da el mismo resultado)."""
import json
import logging

from sqlalchemy import text

from app import consent, faces, jobs, minors
from app.database import SessionLocal
from app.models import User
from app.storage import get_storage, photo_key
from app.timeutil import utcnow

log = logging.getLogger("golden.enroll")
SOURCE = "aceptacion_persona"


def status(db, tenant_id: str, user_id: str) -> str:
    """'ready' (hay vector) | 'pending' (hay foto, falta el vector) | 'none'."""
    row = db.execute(text("SELECT face_encoding IS NOT NULL FROM users WHERE id = :u AND tenant_id = :t"), {"u": str(user_id), "t": tenant_id}).first()
    if row and row[0]:
        return "ready"
    return "pending" if get_storage().exists(photo_key(tenant_id, str(user_id))) else "none"


@jobs.handler("face_enroll")
def run_enroll(payload: dict) -> None:
    tenant, uid, event_id = payload["tenant_id"], str(payload["user_id"]), int(payload["event_id"])
    from app import crypto
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == uid, User.tenant_id == tenant).first()
        key = photo_key(tenant, uid)
        if user is not None and user.face_encoding:
            return                                             # idempotente: un reintento (o una tarea repetida) no recalcula ni duplica el vector
        if user is None or minors.is_minor(user.birth_date) or not consent.has_acceptance(db, tenant, uid, event_id):
            get_storage().delete(key)                          # sin aceptación vigente (o revocó entre tanto, o es menor): no se calcula nada y no queda foto
            return
        arr = crypto.read_array(key)
        encodings = faces.extract(arr, is_registration=True) if arr is not None else None
        if not encodings:
            get_storage().delete(key)
            log.info("inscripción facial: no se detectó un rostro (se borró la foto)")
            return
        user.face_encoding = json.dumps(encodings)
        user.biometric_consent_at, user.biometric_consent_source = utcnow(), SOURCE
        user.is_biometric_enabled = True
        db.commit()


def maybe_enqueue(db, tenant_id: str, user_id: str, event_id: int) -> bool:
    """Tras una aceptación: si la persona ya tiene una FOTO guardada (carga masiva o alta) pero aún no vector, se encola el cálculo (el vector nunca se calcula antes de aceptar). No hace commit."""
    if status(db, tenant_id, user_id) != "pending":
        return False
    jobs.enqueue(db, "face_enroll", {"tenant_id": tenant_id, "user_id": str(user_id), "event_id": int(event_id)}, max_attempts=3)
    return True
