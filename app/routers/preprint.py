"""Preimpresiones (18-nov-2026): elegir a qué personas se les imprime la escarapela ANTES de que lleguen (VIPs, expositores…).

La selección es a mano (buscador) o por filtro (los mismos campos y condiciones de la ruleta, más «¿ya está preimpresa?»). La impresión usa la ventana de siempre
(`/kiosk/{evento}/escarapela/imprimir/{id}?users=…&preprint=1`, parámetros inamovibles); aquí solo se listan, se validan y se deja constancia (`print_logs.kind = 'pre'`).
Coordinador o superior (la comercial pura no imprime). Con el evento «finalizado» no hay preimpresión."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import audit_actions, event_archive, preprint, testperson
from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import EventAttendee, PrintLog, StaffUser
from app.routers import roulette

router = APIRouter(tags=["preprint"])

_ROLE = require_role_excluding("coordinador", ("comercial",))


def _event(event_id: int, db: Session, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return event


def _printed_info(db: Session, event) -> tuple:
    """({id: cuándo se preimprimió por primera vez}, {id: cuántas impresiones tiene en total, normales y preimpresas})."""
    base = db.query(PrintLog.user_id).filter(PrintLog.event_id == event.id, PrintLog.tenant_id == event.tenant_id)
    pre = {uid: when for uid, when in base.with_entities(PrintLog.user_id, func.min(PrintLog.printed_at)).filter(PrintLog.kind == preprint.KIND_PRE).group_by(PrintLog.user_id)}
    total = {uid: n for uid, n in base.with_entities(PrintLog.user_id, func.count(PrintLog.id)).group_by(PrintLog.user_id)}
    return pre, total


def _people(db: Session, event) -> list:
    pre, total = _printed_info(db, event)
    people = roulette.candidates(db, event)
    for p in people:
        p["preprinted_at"] = pre.get(p["id"])
        p["times_printed"] = int(total.get(p["id"], 0))
    return people


def _iso(value):
    return (value.isoformat() + "Z") if value else None


@router.get("/events/{event_id}/preprint/fields")
def preprint_fields(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_ROLE)):
    """Campos por los que se puede filtrar: los de la ruleta + «Preimpresa»."""
    _event(event_id, db, staff)
    fields = roulette.filter_fields(event_id, db, staff)
    fields.append({"key": preprint.PREPRINTED_FIELD, "label": "Escarapela preimpresa", "type": "choice", "choices": [["no", "Aún no"], ["si", "Ya está preimpresa"]]})
    return fields


@router.get("/events/{event_id}/preprint/people")
def preprint_people(event_id: int, filter: str = "", q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(_ROLE)):
    """La base del evento (sin la persona de prueba), recortada por el filtro (JSON `{"conditions":[...]}`) y por el texto del buscador."""
    import json
    event = _event(event_id, db, staff)
    people = _people(db, event)
    if filter:
        try:
            filt = json.loads(filter)
        except ValueError:
            raise HTTPException(status_code=400, detail="Filtro con formato inválido")
        people = preprint.apply_filter(people, filt, roulette._match)
    people = [p for p in people if preprint.matches_text(p, q)]
    return {
        "event_status": event.status, "can_preprint": preprint.can_preprint(event.status), "max_batch": preprint.MAX_BATCH,
        **preprint.summarize(people),
        "people": [{"id": p["id"], "name": p["name"], "entity": p["entity"], "role": p["role"], "categories": p["categories"], "status": p["status"],
                    "preprinted_at": _iso(p["preprinted_at"]), "times_printed": p["times_printed"]} for p in people[:preprint.MAX_PEOPLE]],
    }


class MarkBody(BaseModel):
    user_ids: List[str]


@router.post("/events/{event_id}/preprint/mark")
def preprint_mark(event_id: int, body: MarkBody, db: Session = Depends(get_db), staff: StaffUser = Depends(_ROLE)):
    """Deja constancia de que se preimprimieron estas escarapelas (la pantalla lo llama cuando quien imprime confirma que salieron). Hasta 50 por llamada, todas de ESTE evento."""
    event = _event(event_id, db, staff)
    if not preprint.can_preprint(event.status):
        raise HTTPException(status_code=400, detail="Con el evento finalizado ya no se preimprimen escarapelas")
    ids = preprint.clean_ids(body.user_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="Elige al menos una persona")
    if len(ids) > preprint.MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Máximo {preprint.MAX_BATCH} escarapelas por impresión")
    if testperson.TEST_ID in ids:
        raise HTTPException(status_code=400, detail="La persona de prueba no se preimprime")
    known = {uid for (uid,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(ids))}
    if len(known) != len(ids):
        raise HTTPException(status_code=400, detail="Hay personas que no son de este evento")
    for uid in ids:
        db.add(PrintLog(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, printed_by_staff_id=staff.id, kind=preprint.KIND_PRE))
    audit_actions.record(db, staff, "preprint", "event", event.id, event.name, f"{len(ids)} escarapelas preimpresas")          # sin nombres ni cédulas
    db.commit()
    return {"marked": len(ids), "ids": ids}
