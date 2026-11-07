"""Archivar eventos (Fase 3, oleada 2) y archivado automático de la BASE DE DATOS a los 90 días (L7: el evento NO sale de las listas; se archiva su base, semanalmente).

Archivar = ocultar de listas, calendario y selectores, dejar el evento de SOLO LECTURA (sin registro, sin reconocimiento, sin formularios públicos) y poder restaurarlo. NO se borra nada: el contrato con el
cliente exige poder entregar y restaurar la base. La purga biométrica de 7 días (app/privacy.py) es independiente y no se toca.

Fecha de cierre usada por L7: `events.finalized_at` (la estampa el listener de models.py al pasar a «finalizado»); si falta (eventos finalizados antes de existir la columna), el final de `end_date`.
Un evento restaurado a mano NO vuelve a archivarse solo mientras no se reabra y se vuelva a finalizar (se detecta por la marca «restore» posterior al cierre en `audit_actions`).
"""
import logging
import os
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app import audit_actions
from app.models import AuditAction, Event, StaffUser, WebForm
from app.timeutil import utcnow

log = logging.getLogger("golden.archive")
DEFAULT_AUTO_DAYS = 90


def auto_days() -> int:
    try:
        return max(1, int(os.getenv("EVENT_AUTO_ARCHIVE_DAYS", str(DEFAULT_AUTO_DAYS))))
    except ValueError:
        return DEFAULT_AUTO_DAYS


def active_only(query):
    """Filtro de TODAS las listas y selectores: sin archivados."""
    return query.filter(Event.archived_at.is_(None))


def closed_at(event: Event) -> Optional[datetime]:
    """Cuándo se cerró el evento (UTC): `finalized_at`, o el final del día de `end_date` si falta."""
    if event.finalized_at is not None:
        return event.finalized_at
    if event.end_date is not None:
        return datetime.combine(event.end_date, time(23, 59, 59))
    return None


def block_reason(event: Event) -> Optional[str]:
    """None si se puede archivar; si no, el motivo en palabras simples."""
    if event.archived_at is not None:
        return "El evento ya está archivado"
    if event.status != "finalizado":
        return "Solo se pueden archivar eventos finalizados"
    return None


def close_public_forms(db: Session, event: Event) -> int:
    """Los formularios públicos del evento dejan de recibir envíos (estado «finalizado» = 404 para el público). Las inscripciones ya recibidas no se tocan."""
    n = 0
    for form in db.query(WebForm).filter(WebForm.event_id == event.id).all():
        if form.manual_status != "finalizado" or form.use_schedule:
            form.manual_status, form.use_schedule = "finalizado", False
            n += 1
    return n


def archive(db: Session, event: Event, staff: Optional[StaffUser], detail: Optional[str] = None) -> None:
    """Sin commit propio: el que llama confirma (la acción y su registro en audit_actions van juntos)."""
    event.archived_at = utcnow()
    event.archived_by_id = getattr(staff, "id", None)
    forms = close_public_forms(db, event)
    audit_actions.record(db, staff, "archive", "event", event.id, event.name, detail or (f"{forms} formulario(s) cerrado(s)" if forms else None))


def restore(db: Session, event: Event, staff: StaffUser) -> None:
    """Quita la marca. Los formularios públicos siguen cerrados: se reabren a mano si hace falta."""
    event.archived_at = None
    event.archived_by_id = None
    audit_actions.record(db, staff, "restore", "event", event.id, event.name)


def data_open_for(event: Event, staff: Optional[StaffUser]) -> bool:
    """¿Puede este usuario ver las personas y respuestas del evento? Con la base archivada (L7) solo un super_admin; el evento en sí sigue visible para todos."""
    return event.data_archived_at is None or getattr(staff, "role", None) == "super_admin"


DATA_ARCHIVED_MSG = "La base de datos de este evento está archivada (pasaron 90 días desde su cierre). Un super administrador puede desarchivarla si se necesita."


def archive_data(db: Session, event: Event, staff: Optional[StaffUser], detail: Optional[str] = None) -> None:
    """Archiva SOLO la base del evento: el evento sigue en las listas. Cierra los formularios públicos. Sin commit propio."""
    event.data_archived_at = utcnow()
    forms = close_public_forms(db, event)
    audit_actions.record(db, staff, "archive_data", "event", event.id, event.name, detail or (f"{forms} formulario(s) cerrado(s)" if forms else None))


def restore_data(db: Session, event: Event, staff: StaffUser) -> None:
    event.data_archived_at = None
    audit_actions.record(db, staff, "restore_data", "event", event.id, event.name)


def _restored_after_close(db: Session, event: Event) -> bool:
    closed = closed_at(event)
    q = db.query(AuditAction.id).filter(AuditAction.entity == "event", AuditAction.entity_id == str(event.id), AuditAction.action == "restore_data")
    if closed is not None:
        q = q.filter(AuditAction.at >= closed)
    return q.first() is not None


def auto_archive_due(db: Session, now: Optional[datetime] = None, days: Optional[int] = None) -> dict:
    """L7: archiva la BASE DE DATOS de los eventos finalizados con más de `days` (90) días desde su cierre. El evento no sale de las listas. Una sola consulta; idempotente (solo toca los
    que aún tienen la base abierta), NUNCA borra, un commit por evento. Registra en audit_actions con actor NULL (sistema). Devuelve solo conteos e ids. Corre UNA vez por semana
    (app/ops_runner.py) para no despertar la base de Neon."""
    now = now or utcnow()
    days = days or auto_days()
    cut = now - timedelta(days=days)
    due = (db.query(Event).filter(Event.data_archived_at.is_(None), Event.archived_at.is_(None), Event.status == "finalizado",
                                  or_(Event.finalized_at <= cut, and_(Event.finalized_at.is_(None), Event.end_date.isnot(None), Event.end_date <= cut.date())))
           .order_by(Event.id).all())
    done, skipped, errors = [], 0, 0
    for event in due:
        try:
            if _restored_after_close(db, event):
                skipped += 1
                continue
            archive_data(db, event, None, f"automático: más de {days} días desde el cierre ({'finalized_at' if event.finalized_at else 'end_date'})")
            db.commit()
            done.append(event.id)
        except Exception:  # noqa: BLE001 — un evento con problema no frena a los demás
            db.rollback()
            errors += 1
            log.error("no se pudo archivar la base del evento %s", event.id, exc_info=True)
    return {"archived": len(done), "ids": done, "skipped_restored": skipped, "errors": errors, "days": days}
