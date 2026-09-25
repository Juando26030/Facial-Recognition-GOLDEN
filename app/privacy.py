"""Privacidad de los datos biométricos (Ley 1581 de 2012, art. 5: dato sensible).

Qué se borra: el `face_encoding` de la persona, la constancia de consentimiento asociada y su foto (`data/<tenant>/known_people/<cédula>.jpg`).
Una persona (`User`) vive a nivel de CLIENTE y puede estar en varios eventos, así que al borrar los datos biométricos de un evento se CONSERVAN los de
quienes siguen en otro evento que no ha finalizado (se cuentan aparte para avisarlo). El derecho de supresión de UNA persona (`purge_person`) no tiene esa
salvedad: si la persona lo pide, se borra su rostro.

Retención automática: 180 días (6 meses) después del fin de un evento finalizado, por decisión de Golden (2026-09-25); se puede cambiar con la variable
`BIOMETRIC_RETENTION_DAYS` (`0` la apaga) y debe coincidir con la Política de Privacidad publicada. `scripts/purge_biometrics.py` la aplica (cron diario).
"""
import os
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Event, EventAttendee, User


DEFAULT_RETENTION_DAYS = 180


def retention_days():
    """Días de retención tras la fecha de fin de un evento finalizado (180 por defecto), o None si se apagó con BIOMETRIC_RETENTION_DAYS=0."""
    raw = os.getenv("BIOMETRIC_RETENTION_DAYS", "").strip()
    if raw == "0":
        return None
    return int(raw) if raw.isdigit() else DEFAULT_RETENTION_DAYS


def photo_path(tenant_id: str, user_id: str) -> str:
    return os.path.join("data", tenant_id, "known_people", f"{user_id}.jpg")


def stats(db: Session, event: Event) -> dict:
    """Cuántas personas de este evento tienen datos biométricos guardados y con qué constancia de autorización."""
    people = (db.query(User).join(EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id))
              .filter(EventAttendee.event_id == event.id).all())
    with_face = [u for u in people if u.face_encoding or os.path.isfile(photo_path(u.tenant_id, u.id))]
    from app import crypto
    return {"attendees": len(people), "with_biometrics": len(with_face), "encrypted": crypto.enabled(),
            "with_consent": sum(1 for u in with_face if u.biometric_consent_at), "without_consent": sum(1 for u in with_face if not u.biometric_consent_at)}


def _erase(user: User) -> bool:
    had = bool(user.face_encoding) or os.path.isfile(photo_path(user.tenant_id, user.id))
    user.face_encoding = None
    user.biometric_consent_at = None
    user.biometric_consent_source = None
    try:
        os.remove(photo_path(user.tenant_id, user.id))
    except OSError:
        pass
    return had


def purge_person(db: Session, tenant_id: str, user_id: str) -> bool:
    """Derecho de supresión: borra el rostro de UNA persona (no su identidad ni su registro de asistencia)."""
    user = db.query(User).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if not user:
        return False
    had = _erase(user)
    db.commit()
    return had


def purge_event(db: Session, event: Event) -> dict:
    """Borra los datos biométricos de las personas de este evento, salvo quienes siguen en otro evento del cliente que NO está finalizado."""
    deleted = kept = 0
    people = (db.query(User).join(EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id))
              .filter(EventAttendee.event_id == event.id).all())
    for user in people:
        if not (user.face_encoding or os.path.isfile(photo_path(user.tenant_id, user.id))):
            continue
        elsewhere = (db.query(EventAttendee.id).join(Event, Event.id == EventAttendee.event_id)
                     .filter(EventAttendee.user_id == user.id, EventAttendee.tenant_id == user.tenant_id, EventAttendee.event_id != event.id, Event.status != "finalizado").first())
        if elsewhere:
            kept += 1
            continue
        _erase(user)
        deleted += 1
    event.biometrics_purged_at = datetime.utcnow()
    db.commit()
    return {"deleted": deleted, "kept_in_other_events": kept}


def purge_expired(db: Session, days: int, today: date = None) -> dict:
    """Aplica la retención: eventos finalizados cuyo fin fue hace más de `days` días y que aún no se han purgado."""
    limit = (today or date.today()) - timedelta(days=days)
    total = {"events": 0, "deleted": 0, "kept_in_other_events": 0}
    for event in db.query(Event).filter(Event.status == "finalizado", Event.end_date < limit, Event.biometrics_purged_at.is_(None)).all():
        r = purge_event(db, event)
        total["events"] += 1
        total["deleted"] += r["deleted"]
        total["kept_in_other_events"] += r["kept_in_other_events"]
    return total
