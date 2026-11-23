"""Inscripción del rostro DESPUÉS de la aceptación de la persona (camino A del quiosco y camino B de /aceptar): la foto (captura en vivo o selfie) se guarda cifrada y el VECTOR se calcula
en una tarea en segundo plano, con 25 jitters: la puerta nunca espera ese cálculo. Reglas:
  * Nunca se calcula el vector de alguien sin una aceptación vigente registrada en `audit_consent_logs` para ese evento (se vuelve a comprobar al ejecutar la tarea).
  * Menores de 18 años: nada (ni foto ni vector).
  * Si no se detecta un rostro, la foto se borra: no queda nada guardado.
Idempotente (una tarea repetida da el mismo resultado)."""
import json
import logging

from sqlalchemy import text

from app import consent, faces, jobs, minors, personform
from app.database import SessionLocal
from app.models import Event, User
from app.storage import get_storage, photo_key
from app.timeutil import utcnow

log = logging.getLogger("golden.enroll")
SOURCE = "aceptacion_persona"


PENDING_SUFFIX = ".pending.jpg"


def pending_photo_key(tenant_id: str, user_id: str) -> str:
    """Clave de la selfie «pendiente de verificar» (revisión de seguridad 22-nov, hallazgo 5): la misma carpeta y prefijo biométrico que la foto de registro, con sufijo `.pending.jpg`. Nunca se muestra al operador ni viaja entre entornos."""
    return photo_key(tenant_id, str(user_id))[: -len(".jpg")] + PENDING_SUFFIX


SELFIE_SUFFIX = ".selfie.jpg"


def selfie_photo_key(tenant_id: str, user_id: str) -> str:
    """Clave de la selfie desde el celular YA VERIFICADA por el personal cuando la persona tenía otra foto de registro (23-nov-2026, pedido de Juan David): NO reemplaza a la de registro, se conservan las dos y «Editar»
    las muestra como historial. Mismo prefijo biométrico que la vigente, así que toda purga, supresión y cambio de cédula la cubre por `photo_keys`."""
    return photo_key(tenant_id, str(user_id))[: -len(".jpg")] + SELFIE_SUFFIX


def photo_keys(tenant_id: str, user_id: str) -> tuple:
    """Todas las claves biométricas de imagen de una persona: la vigente, la pendiente y la selfie verificada."""
    return (photo_key(tenant_id, str(user_id)), pending_photo_key(tenant_id, user_id), selfie_photo_key(tenant_id, user_id))


def has_any_photo(tenant_id: str, user_id: str) -> bool:
    return any(get_storage().exists(k) for k in photo_keys(tenant_id, user_id))


def delete_photos(tenant_id: str, user_id: str, all_versions: bool = False) -> int:
    """Borra la foto vigente Y la pendiente (helper único de todas las purgas y supresiones). Con `all_versions` también las versiones no vigentes del bucket; devuelve cuántas no se pudieron borrar."""
    st, failed = get_storage(), 0
    for k in photo_keys(tenant_id, user_id):
        if all_versions:
            failed += st.delete_all_versions(k)
        else:
            st.delete(k)
    return failed


def move_photos(tenant_id: str, old_id: str, new_id: str) -> None:
    """Cambio de cédula: la foto vigente y la pendiente siguen a la persona."""
    st = get_storage()
    for old, new in zip(photo_keys(tenant_id, old_id), photo_keys(tenant_id, new_id)):
        if st.exists(old):
            st.move(old, new)


def promote_pending(db, tenant_id: str, user_id: str, event_id: int) -> bool:
    """La persona quedó verificada: la selfie pendiente se CONSERVA como segunda foto (`selfie_photo_key`) junto a la de registro, que sigue vigente (no se reemplaza nada; «Editar» muestra las dos). Si aún no hay vector,
    se encola su cálculo desde la foto vigente. No hace commit. False si no había pendiente."""
    st, pend = get_storage(), pending_photo_key(tenant_id, user_id)
    if not st.exists(pend):
        return False
    st.move(pend, selfie_photo_key(tenant_id, user_id))
    db.execute(text("UPDATE users SET face_captured_at = COALESCE(face_captured_at, :n) WHERE id = :u AND tenant_id = :t"), {"n": utcnow(), "u": str(user_id), "t": tenant_id})
    jobs.enqueue(db, "face_enroll", {"tenant_id": tenant_id, "uref": jobs.person_ref(user_id), "event_id": int(event_id)}, max_attempts=3)      # idempotente: si ya hay vector, la tarea no hace nada
    return True


def status(db, tenant_id: str, user_id: str) -> str:
    """'ready' (hay vector) | 'pending' (hay foto, falta el vector) | 'none'."""
    row = db.execute(text("SELECT face_encoding IS NOT NULL FROM users WHERE id = :u AND tenant_id = :t"), {"u": str(user_id), "t": tenant_id}).first()
    if row and row[0]:
        return "ready"
    return "pending" if get_storage().exists(photo_key(tenant_id, str(user_id))) else "none"      # la pendiente NO cuenta: no es la foto de registro


@jobs.handler("face_enroll")
def run_enroll(payload: dict) -> None:
    tenant, uid, event_id = payload["tenant_id"], jobs.payload_user_id(payload), int(payload["event_id"])
    from app import crypto
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == uid, User.tenant_id == tenant).first()
        key = photo_key(tenant, uid)
        if user is not None and user.face_encoding:
            return                                             # idempotente: un reintento (o una tarea repetida) no recalcula ni duplica el vector
        event = db.get(Event, event_id)
        if user is None or minors.is_minor(user.birth_date) or not consent.has_acceptance(db, tenant, uid, event_id) or (event is not None and personform.user_flow(db, event, uid).get("facial_off")):
            delete_photos(tenant, uid)                         # sin aceptación vigente (o revocó entre tanto, o es menor, o su categoría no usa reconocimiento facial): no se calcula nada y no queda foto
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
    jobs.enqueue(db, "face_enroll", {"tenant_id": tenant_id, "uref": jobs.person_ref(user_id), "event_id": int(event_id)}, max_attempts=3)
    return True
