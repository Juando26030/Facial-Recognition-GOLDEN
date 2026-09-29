"""Privacidad de los datos biométricos (Ley 1581 de 2012, art. 5: dato sensible).

Qué se borra: el `face_encoding` de la persona, la constancia de consentimiento asociada y su foto (`known_people/<cédula>.jpg`, la única copia: no
hay miniaturas). Todo lo demás (nombre, cédula, ingresos, formularios…) se conserva.

Retención automática (política de Golden, 2026-09-29; debe coincidir con la Política de Privacidad publicada):
  * Una persona (`User`) vive a nivel de CLIENTE y puede estar en varios eventos. Su rostro se borra cuando TODOS sus eventos llevan al menos
    `BIOMETRIC_RETENTION_DAYS_AFTER_EVENT` (7) días finalizados (`events.finalized_at`; reabrir un evento reinicia su reloj). Si sigue en un evento
    abierto o finalizado hace menos de 7 días, se conserva y la regla se aplica cuando cierre ese otro evento.
  * Tope: `BIOMETRIC_MAX_DAYS` (180) días desde la captura (`users.face_captured_at`) aunque algún evento siga abierto (eventos que nunca se finalizan).
  * Una persona sin ningún evento (huérfana) solo se borra por el tope.
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
    return (db.query(Event.event_code, Event.name).join(EventAttendee, EventAttendee.event_id == Event.id)
            .filter(EventAttendee.user_id == user.id, EventAttendee.tenant_id == user.tenant_id, Event.id != event_id,
                    Event.status != "finalizado", Event.facial_enabled.is_(True)).all())


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
SELECT u.tenant_id, u.id,
       (EXISTS (SELECT 1 FROM event_attendees a WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id)
        AND NOT EXISTS (SELECT 1 FROM event_attendees a JOIN events e ON e.id = a.event_id
                        WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id
                          AND NOT (e.status = 'finalizado' AND e.finalized_at IS NOT NULL AND e.finalized_at <= :after_cut))) AS by_event
FROM users u
WHERE (u.face_encoding IS NOT NULL OR u.biometric_consent_at IS NOT NULL)
  AND (u.tenant_id, u.id) > (:last_tenant, :last_id)
  AND ((EXISTS (SELECT 1 FROM event_attendees a WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id)
        AND NOT EXISTS (SELECT 1 FROM event_attendees a JOIN events e ON e.id = a.event_id
                        WHERE a.user_id = u.id AND a.tenant_id = u.tenant_id
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
