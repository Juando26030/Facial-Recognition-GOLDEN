"""Privacidad de los datos biométricos (Ley 1581 de 2012, art. 5: dato sensible).

Qué se borra: el `face_encoding` de la persona, la constancia de consentimiento asociada y su foto (`known_people/<cédula>.jpg`, la única copia: no
hay miniaturas). Todo lo demás (nombre, cédula, ingresos, formularios…) se conserva.

Retención automática (política de Golden, 2026-09-29; debe coincidir con la Política de Privacidad publicada):
  * Una persona (`User`) vive a nivel de CLIENTE y puede estar en varios eventos. Su rostro se borra cuando TODOS sus eventos llevan al menos
    `BIOMETRIC_RETENTION_DAYS_AFTER_EVENT` (7) días finalizados (`events.finalized_at`; reabrir un evento reinicia su reloj). Si sigue en un evento
    abierto o finalizado hace menos de 7 días, se conserva y la regla se aplica cuando cierre ese otro evento.
  * Tope: `BIOMETRIC_MAX_DAYS` (180) días desde la captura (`users.face_captured_at`) aunque algún evento siga abierto (eventos que nunca se finalizan).
  * Una persona sin ningún evento (huérfana) solo se borra por el tope.
  * (2026-10-06, auditora) «Sigue en otro evento abierto» solo cuenta en los eventos donde la persona tiene una aceptación vigente en `audit_consent_logs`; si nunca aceptó en ninguno, cuentan todos
    los suyos. El tope de 180 días no cambia.
Borrado manual: el admin puede borrar lo biométrico de un evento (`purge_event`); ahí solo se respeta a quien está en OTRO evento abierto CON reconocimiento
facial (el principio: no romper un evento en curso que usa rostros). El derecho de supresión de UNA persona (`purge_person`) no tiene salvedades.
"""
import logging
import os
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Event, EventAttendee, User
from app.storage import get_storage, photo_key
from app.timeutil import utcnow

log = logging.getLogger("golden.privacy")
DEFAULT_DAYS_AFTER_EVENT = 7
DEFAULT_MAX_DAYS = 180


def _days(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.isdigit() else default


def days_after_event() -> int:
    """Días tras finalizar TODOS los eventos de la persona (BIOMETRIC_RETENTION_DAYS_AFTER_EVENT, 7 por defecto)."""
    return _days("BIOMETRIC_RETENTION_DAYS_AFTER_EVENT", DEFAULT_DAYS_AFTER_EVENT)


def max_days() -> int:
    """Tope en días desde la captura aunque el evento siga abierto (BIOMETRIC_MAX_DAYS, 180 por defecto)."""
    return _days("BIOMETRIC_MAX_DAYS", DEFAULT_MAX_DAYS)


def stats(db: Session, event: Event) -> dict:
    """Cuántas personas de este evento tienen datos biométricos guardados y con qué constancia de autorización."""
    people = (db.query(User).join(EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id))
              .filter(EventAttendee.event_id == event.id).all())
    with_face = [u for u in people if u.face_encoding or get_storage().exists(photo_key(u.tenant_id, u.id))]
    from app import crypto
    return {"attendees": len(people), "with_biometrics": len(with_face), "encrypted": crypto.enabled(),
            "with_consent": sum(1 for u in with_face if u.biometric_consent_at), "without_consent": sum(1 for u in with_face if not u.biometric_consent_at)}


def _erase(user: User) -> bool:
    key = photo_key(user.tenant_id, user.id)
    had = bool(user.face_encoding) or get_storage().exists(key)
    get_storage().delete(key)                                # primero la foto: si falla, el encoding sigue y se puede reintentar
    user.face_encoding = None
    user.biometric_consent_at = None
    user.biometric_consent_source = None
    return had


def purge_person(db: Session, tenant_id: str, user_id: str) -> bool:
    """Derecho de supresión: borra el rostro de UNA persona (no su identidad ni su registro de asistencia)."""
    user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if not user:
        return False
    had = _erase(user)
    db.commit()
    return had


def _in_other_open_facial_event(db: Session, user: User, event_id: int):
    """Eventos abiertos (no finalizados) CON reconocimiento facial, distintos de `event_id`, donde sigue la persona."""
    from app import consent
    rows = (db.query(Event.id, Event.event_code, Event.name).join(EventAttendee, EventAttendee.event_id == Event.id)
            .filter(EventAttendee.user_id == user.id, EventAttendee.tenant_id == user.tenant_id, Event.id != event_id,
                    Event.status != "finalizado", Event.facial_enabled.is_(True)).all())
    return [(code, name) for eid, code, name in rows if consent.has_acceptance(db, user.tenant_id, user.id, eid)]      # solo cuentan los eventos donde aceptó


def purge_event(db: Session, event: Event) -> dict:
    """Borrado manual (admin+): lo biométrico de las personas de este evento, salvo quien sigue en otro evento ABIERTO con reconocimiento facial.
    Devuelve cuántas se borraron y cuántas se omitieron, con el motivo (nombres de eventos, nunca de personas)."""
    deleted = kept = 0
    other_events = set()
    people = (db.query(User).join(EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id))
              .filter(EventAttendee.event_id == event.id).all())
    for user in people:
        if not (user.face_encoding or get_storage().exists(photo_key(user.tenant_id, user.id))):
            continue
        elsewhere = _in_other_open_facial_event(db, user, event.id)
        if elsewhere:
            kept += 1
            other_events.update(f"{code} · {name}" for code, name in elsewhere)
            continue
        _erase(user)
        deleted += 1
    event.biometrics_purged_at = utcnow()
    db.commit()
    reason = ("siguen en otro evento abierto con reconocimiento facial: " + "; ".join(sorted(other_events)[:5])) if kept else ""
    return {"deleted": deleted, "kept_in_other_events": kept, "kept_reason": reason}


# Quién tiene lo biométrico vencido. Regla A: tiene eventos y NINGUNO está abierto ni finalizado hace menos de :after días. Regla B (tope): capturado
# hace más de :cap días. `(tenant_id, id) > (...)` recorre por claves: una persona que falla no se vuelve a pedir en esta corrida.
_EXPIRED_SQL = text("""
WITH last AS (
  SELECT DISTINCT ON (tenant_id, user_id, event_id) tenant_id, user_id, event_id, (reason = 'consent' AND accepted_biometric AND confirmed_adult) AS ok
  FROM audit_consent_logs ORDER BY tenant_id, user_id, event_id, consent_timestamp_utc DESC, id DESC),
acc AS (SELECT tenant_id, user_id, event_id FROM last WHERE ok),
-- Eventos que RETIENEN el rostro de una persona: aquellos donde tiene una aceptación vigente; si no tiene aceptación en ninguno (nunca aceptó), todos los suyos (regla de siempre).
holding AS (
  SELECT u.tenant_id, u.id AS user_id, a.event_id
  FROM users u JOIN event_attendees a ON a.user_id = u.id AND a.tenant_id = u.tenant_id
  WHERE EXISTS (SELECT 1 FROM acc WHERE acc.tenant_id = u.tenant_id AND acc.user_id = u.id AND acc.event_id = a.event_id)
     OR NOT EXISTS (SELECT 1 FROM acc WHERE acc.tenant_id = u.tenant_id AND acc.user_id = u.id))
SELECT u.tenant_id, u.id,
       (EXISTS (SELECT 1 FROM event_attendees a WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id)
        AND NOT EXISTS (SELECT 1 FROM holding h JOIN events e ON e.id = h.event_id
                        WHERE h.user_id = u.id AND h.tenant_id = u.tenant_id
                          AND NOT (e.status = 'finalizado' AND e.finalized_at IS NOT NULL AND e.finalized_at <= :after_cut))) AS by_event
FROM users u
WHERE (u.face_encoding IS NOT NULL OR u.biometric_consent_at IS NOT NULL)
  AND (u.tenant_id, u.id) > (:last_tenant, :last_id)
  AND ((EXISTS (SELECT 1 FROM event_attendees a WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id)
        AND NOT EXISTS (SELECT 1 FROM holding h JOIN events e ON e.id = h.event_id
                        WHERE h.user_id = u.id AND h.tenant_id = u.tenant_id
                          AND NOT (e.status = 'finalizado' AND e.finalized_at IS NOT NULL AND e.finalized_at <= :after_cut)))
       OR u.face_captured_at <= :cap_cut)
ORDER BY u.tenant_id, u.id
LIMIT :batch
""")


def purge_expired(db: Session, now=None, batch: int = 200, dry_run: bool = False) -> dict:
    """Aplica la retención (ver el encabezado). Idempotente, por lotes y sin bloquear eventos en curso (no toma bloqueos sobre `events`).
    Por persona: PRIMERO se borra la foto del almacenamiento; si eso falla se cuenta el error y NO se toca el encoding (se reintenta en la
    siguiente corrida: nunca queda un encoding sin su foto ni al revés sin haberse contado). Solo devuelve conteos, jamás datos personales."""
    now = now or utcnow()
    params = {"after_cut": now - timedelta(days=days_after_event()), "cap_cut": now - timedelta(days=max_days())}
    total = {"people": 0, "objects": 0, "errors": 0, "by_cap": 0}
    last = ("", "")
    while True:
        rows = db.execute(_EXPIRED_SQL, {**params, "last_tenant": last[0], "last_id": last[1], "batch": batch}).all()
        if not rows:
            break
        for tenant_id, user_id, by_event in rows:
            last = (tenant_id, user_id)
            user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
            if user is None:
                continue
            key = photo_key(tenant_id, user_id)
            try:
                if get_storage().exists(key):
                    total["objects"] += 1
                    if not dry_run:
                        get_storage().delete(key)
            except Exception:  # noqa: BLE001 — se reintenta en la siguiente hora
                total["errors"] += 1
                log.error("no se pudo borrar una foto biométrica (se reintenta en la siguiente corrida)", exc_info=True)
                continue
            if not dry_run:
                user.face_encoding = None
                user.biometric_consent_at = None
                user.biometric_consent_source = None
            total["people"] += 1
            total["by_cap"] += 0 if by_event else 1
        db.commit()
    return total


# ------------------------------------------------------------------ supresión individual y revocación (L4)
REVOCATION_TEXT = "Revocación de la autorización o supresión de datos solicitada por la persona y atendida por el personal autorizado de Golden."
NOT_IMMEDIATE = ["versiones no vigentes de las fotos en Cloud Storage (se eliminan solas en 1 día)", "historial de la base de datos (Neon, 1 día)",
                 "copias de seguridad de recuperación técnica (se sobrescriben en un ciclo de hasta 30 días)",
                 "dispositivos sin conexión: su copia local se actualiza en la próxima sincronización"]
_FILE_KEYS = ("stored",)


def is_suppressed(db: Session, tenant_id: str, cedula: str) -> bool:
    """¿Esta cédula pidió la supresión total? (evita volver a crearla por error en una carga, un alta o una inscripción)."""
    from app import consent
    from app.models import SuppressedPerson
    return db.get(SuppressedPerson, (tenant_id, consent.cedula_hash(cedula))) is not None


def _stored_files(data_json: str) -> list:
    """Archivos adjuntos (`stored`) dentro del JSON de una inscripción, a cualquier profundidad."""
    import json
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("stored"):
                out.append(str(x["stored"]))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    try:
        walk(json.loads(data_json or "{}"))
    except ValueError:
        pass
    return out


def erase_person(db: Session, event: Event, user_id: str, scope: str) -> dict:
    """`scope='biometric'` = REVOCACIÓN: borra vector y foto (todas las versiones posibles), `is_biometric_enabled=false` y registra la `revocation`; la persona sigue entrando por cédula/QR.
    `scope='all'` además borra sus datos personales (users, asistencia al evento, impresiones, movimientos de áreas, entregas de inventario, invitaciones, listas de formularios y adjuntos),
    vacía los datos de sus inscripciones (la inscripción y su pago se conservan) y deja `payer_email` en NULL, ANONIMIZA sus `access_logs` de forma irreversible (se desvincula la persona; queda
    hora, tipo de ingreso y evento) y guarda solo la huella de la cédula para no re-cargarla. NO toca `audit_consent_logs` (3 años, bloqueado) ni lo demás de `form_payments` (10 años, bloqueado).
    Devuelve conteos y lo que NO se pudo borrar al instante; nunca datos personales."""
    from app import consent, faces_version
    from app.models import SuppressedPerson
    tenant, uid = event.tenant_id, str(user_id)
    user = db.query(User).filter(User.id == uid, User.tenant_id == tenant).first()
    if user is None:
        return {"found": False}
    result = {"found": True, "scope": scope, "had_biometrics": bool(user.face_encoding), "versions_not_deleted": 0}
    result["versions_not_deleted"] += get_storage().delete_all_versions(photo_key(tenant, uid))
    user.face_encoding = None
    user.biometric_consent_at = None
    user.biometric_consent_source = None
    user.is_biometric_enabled = False
    consent.record(db, tenant_id=tenant, user_id=uid, event_id=event.id, version="revocation", legal_text_hash=consent.text_hash(REVOCATION_TEXT), accepted=False, adult=True, reason="revocation",
                   device="purga")
    if scope == "all":
        p = {"t": tenant, "u": uid}
        events_of_tenant = "(SELECT id FROM events WHERE tenant_id = :t)"
        subs = db.execute(text(f"SELECT id, form_id, data_json FROM form_submissions WHERE person_id = :u AND event_id IN {events_of_tenant}"), p).all()
        for _sid, form_id, data_json in subs:
            for stored in _stored_files(data_json):
                from app.storage import form_file_key
                result["versions_not_deleted"] += get_storage().delete_all_versions(form_file_key(tenant, form_id, stored))
        result["submissions_emptied"] = db.execute(text(f"UPDATE form_submissions SET data_json = '{{}}', person_id = NULL WHERE person_id = :u AND event_id IN {events_of_tenant}"), p).rowcount
        forms_of_tenant = f"(SELECT id FROM web_forms WHERE event_id IN {events_of_tenant})"
        db.execute(text(f"DELETE FROM form_people WHERE person_id = :u AND form_id IN {forms_of_tenant}"), p)
        db.execute(text(f"DELETE FROM form_invites WHERE person_id = :u AND form_id IN {forms_of_tenant}"), p)
        db.execute(text(f"UPDATE form_payments SET payer_email = NULL WHERE person_id = :u AND event_id IN {events_of_tenant}"), p)      # contacto fuera; el resto del pago se conserva (10 años, bloqueado)
        for table in ("event_attendees", "print_logs", "area_movements", "inventory_deliveries"):
            db.execute(text(f"DELETE FROM {table} WHERE user_id = :u AND tenant_id = :t"), p)
        result["access_logs_anonymized"] = db.execute(text("UPDATE access_logs SET user_id = NULL WHERE user_id = :u AND tenant_id = :t"), p).rowcount
        db.flush()
        db.delete(user)
        if db.get(SuppressedPerson, (tenant, consent.cedula_hash(uid))) is None:
            db.add(SuppressedPerson(tenant_id=tenant, cedula_hash=consent.cedula_hash(uid)))
    faces_version.bump(db, tenant_id=tenant)                       # el reconocimiento recarga su matriz; la versión del roster local cambia sola (cambia lo que contiene)
    db.commit()
    result["not_immediate"] = NOT_IMMEDIATE if scope == "all" or result["had_biometrics"] else NOT_IMMEDIATE[2:]
    return result
