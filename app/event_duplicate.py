"""«Duplicar evento» (16-nov-2026): crea en el mismo sistema un evento NUEVO igual al elegido, con otro código y el nombre «… (copia)». Reutiliza el motor de exportar/importar eventos
(app/event_transfer.py, docs/18) en memoria, sin paquete ni descarga. Qué copia: configuración y parámetros, campos, áreas, inventario (ítems), plantilla de escarapela y su diseño, formularios web
(quedan en «pruebas»), ruleta (su configuración), las personas del evento con sus categorías, y quién tiene acceso. Qué NO copia, a propósito: la historia del evento original (ingresos y áreas, impresiones,
entregas, historial de cambios, pagos y reembolsos, respuestas de formularios, sorteos hechos, gastos y documentos) ni lo biométrico ni las aceptaciones legales: cada persona acepta de nuevo en su evento.
El evento nuevo siempre nace «creado». Sin commit propio salvo el de la importación."""
import logging
import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import event_transfer as et
from app.models import Event, EventAttendee, EventStaffAuthorization, EventTransferLog, StaffUser

log = logging.getLogger("golden.event_duplicate")
MAX_PEOPLE = 5000          # por encima de esto la copia no cabe en una petición (Cloud Run corta a los 60 s): se usa «Importar evento»
EXCLUDE = frozenset({"access_logs", "area_movements", "inventory_deliveries", "print_logs", "person_changes", "person_change_log", "audit_consent_logs", "web_acceptances",
                     "form_submissions", "form_payments", "form_refunds", "form_events", "roulette_draws", "event_documents", "event_expenses"})
SUFFIX = " (copia)"


def _code_taken(db: Session, code: str) -> bool:
    return db.query(Event.id).filter(func.lower(func.btrim(Event.event_code)) == code.lower()).first() is not None


def _name_taken(db: Session, tenant_id: str, name: str) -> bool:
    return db.query(Event.id).filter(Event.tenant_id == tenant_id, func.lower(func.btrim(Event.name)) == name.lower()).first() is not None


def suggest(db: Session, event: Event) -> dict:
    """Código y nombre libres para la copia: «CÓDIGO-COPIA», «CÓDIGO-COPIA-2»…; «Nombre (copia)», «Nombre (copia 2)»…"""
    base_code = re.sub(r"-COPIA(-\d+)?$", "", event.event_code or "").strip() or "EVENTO"
    base_name = re.sub(r"\s*\(copia( \d+)?\)$", "", event.name or "").strip() or "Evento"
    code, n = f"{base_code}-COPIA", 1
    while _code_taken(db, code):
        n += 1
        code = f"{base_code}-COPIA-{n}"
    name, k = f"{base_name}{SUFFIX}"[:200], 1
    while _name_taken(db, event.tenant_id, name):
        k += 1
        name = f"{base_name} (copia {k})"[:200]
    return {"event_code": code, "name": name}


def duplicate(db: Session, event: Event, staff: StaffUser, *, event_code: Optional[str] = None, name: Optional[str] = None) -> Event:
    people = db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id).count()
    if people > MAX_PEOPLE:
        raise et.TransferError(f"Este evento tiene {people} personas: es demasiado grande para duplicarlo de un clic. Pídele al administrador del sistema exportarlo e importarlo.")
    s = suggest(db, event)
    code, new_name = (event_code or s["event_code"]).strip(), (name or s["name"]).strip()
    data, _ = et.export_event(db, event, staff_username=staff.username, include_biometrics=False, record=False, exclude_tables=EXCLUDE)
    report = et.import_package(db, data, staff_username=staff.username, new_event_code=code, new_name=new_name, keep_original_state=False, dry_run=False, import_biometrics=False)
    if not report.get("ok") or not report.get("event_id"):
        raise et.TransferError(" ".join(report.get("conflicts") or []) or "No se pudo duplicar el evento.")
    new = db.get(Event, report["event_id"])
    new.status, new.finalized_at, new.archived_at, new.archived_by_id, new.data_archived_at = "creado", None, None, None, None          # nace como un evento nuevo, abierto y en «creado»
    for a in db.query(EventStaffAuthorization).filter(EventStaffAuthorization.event_id == event.id):          # quién puede operar el original, puede operar la copia
        db.add(EventStaffAuthorization(event_id=new.id, staff_user_id=a.staff_user_id, authorized_by_id=staff.id))
    row = db.get(EventTransferLog, report.get("import_id")) if report.get("import_id") else None
    if row is not None and row.status == "pending_confirm":
        row.status, row.state_json = "done", None                  # no hay nada que «confirmar»: la copia no hereda el estado «en proceso»
    log.info("event_duplicate event_id=%s new_event_id=%s", event.id, new.id)
    return new
