"""«Borrar la base cargada» (16-nov-2026): quita de UN evento a las personas que entraron por «Adjuntar base de datos» (origen `base`), para corregir una carga equivocada.
Reglas: solo se borran las de origen `base` que NO tienen ningún registro de ingreso en el evento (nunca se pierde un registro real); las creadas a mano, por autoregistro, la persona de
prueba y las que ya tienen ingresos se conservan y se cuentan en la respuesta. Por cada persona se hace lo mismo que «Eliminar del evento» (api.py, DELETE /users/{id}): historial de impresión,
áreas, entregas, correos, cambios, firmas; y si no queda en ningún otro evento del cliente, también su ficha y su foto. Lo legal (audit_consent_logs, web_acceptances) NO se toca.
Por conjuntos (de a 500), no persona por persona: una base de miles de filas se borra en segundos. Sin commit: quien llama confirma."""
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import enroll, testperson
from app.models import (AcceptMailLog, AccessLog, AreaMovement, Event, EventAttendee, InventoryDelivery, PersonChange, PersonChangeLog, PrintJob, PrintLog, ReprintRequest, User)
from app.storage import get_storage

log = logging.getLogger("golden.roster_delete")
CHUNK = 500
EVENT_MODELS = (PrintLog, AreaMovement, InventoryDelivery, AcceptMailLog, PersonChange, ReprintRequest)
TENANT_MODELS = (PrintLog, AreaMovement, InventoryDelivery)
LOADED = "base"


def _loaded_ids(db: Session, event: Event) -> List[str]:
    rows = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.origin == LOADED).all()
    return testperson.drop_test([r[0] for r in rows])


def _registered(db: Session, event: Event, ids: List[str]) -> set:
    out = set()
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        out.update(r[0] for r in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.user_id.in_(part)).distinct())
    return out


def preview(db: Session, event: Event) -> dict:
    """Cuántas personas entraron por la base, cuántas se borrarían y cuántas se conservan por tener ingresos."""
    ids = _loaded_ids(db, event)
    kept = _registered(db, event, ids)
    total = db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id).count()
    return {"loaded": len(ids), "deletable": len(ids) - len(kept), "kept_registered": len(kept), "event_total": total}


def delete_loaded(db: Session, event: Event) -> dict:
    ids = _loaded_ids(db, event)
    keep = _registered(db, event, ids)
    todo = [i for i in ids if i not in keep]
    st = get_storage()
    sig_keys = []
    if todo:
        from app.routers import signatures
        try:
            sig_keys = list(st.list(signatures.key_of(event.tenant_id, "signatures", event.id)))
        except Exception:  # noqa: BLE001  — sin firmas o sin acceso a la carpeta: no impide el borrado
            sig_keys = []
    removed = fully = 0
    photos: List[str] = []
    for i in range(0, len(todo), CHUNK):
        part = todo[i:i + CHUNK]
        att_ids = [a for (a,) in db.query(EventAttendee.id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part))]
        if att_ids:
            db.query(PrintJob).filter(PrintJob.event_id == event.id, PrintJob.attendee_id.in_(att_ids)).delete(synchronize_session=False)
        for model in EVENT_MODELS:
            db.query(model).filter(model.event_id == event.id, model.user_id.in_(part)).delete(synchronize_session=False)
        db.query(PersonChangeLog).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.event_id == event.id, PersonChangeLog.user_id.in_(part)).delete(synchronize_session=False)
        removed += db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part)).delete(synchronize_session=False)
        from app import dependents
        dependents.delete_for_holders(db, event.id, part)          # 0161: sus dependientes se van con ellas
        db.flush()
        still_att = {r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.tenant_id == event.tenant_id, EventAttendee.user_id.in_(part)).distinct()}
        still_log = {r[0] for r in db.query(AccessLog.user_id).filter(AccessLog.tenant_id == event.tenant_id, AccessLog.user_id.in_(part)).distinct()}
        gone = [u for u in part if u not in still_att and u not in still_log]          # ya no están en ningún otro evento del cliente
        if gone:
            for model in TENANT_MODELS:
                db.query(model).filter(model.tenant_id == event.tenant_id, model.user_id.in_(gone)).delete(synchronize_session=False)
            db.query(PersonChangeLog).filter(PersonChangeLog.tenant_id == event.tenant_id, PersonChangeLog.user_id.in_(gone)).delete(synchronize_session=False)
            fully += db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(gone)).delete(synchronize_session=False)
            photos.extend(gone)
    # archivos al final y solo de lo que ya salió de la base: firmas de este evento y foto de quien quedó sin ficha
    gone_set = set(todo)
    for key in sig_keys:
        if key.rsplit("/", 1)[-1].split("__", 1)[0] in gone_set:
            try:
                st.delete(key)
            except Exception:  # noqa: BLE001
                log.warning("no se pudo borrar una firma al borrar la base cargada")
    for uid in photos:
        try:
            enroll.delete_photos(event.tenant_id, uid)
        except Exception:  # noqa: BLE001
            log.warning("no se pudo borrar una foto al borrar la base cargada")
    return {"removed": removed, "people_removed_entirely": fully, "kept_registered": len(keep)}
