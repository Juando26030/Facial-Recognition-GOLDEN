"""API de la NUBE para los servidores locales (Fase 6). Todo con el token de nodo (`X-Node-Token`, app/node_auth.py): lista de eventos (solo metadatos), paquete del evento sin biometría,
arrendamiento («en servidor local») y su liberación. Ninguna respuesta lleva datos de personas salvo el paquete que el nodo pide a propósito; en los logs solo conteos."""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app import event_lease, event_transfer
from app.database import get_db
from app.models import AuditAction, Event
from app.node_auth import require_node

log = logging.getLogger("golden.node_api")
router = APIRouter()


def _meta(e: Event) -> dict:
    return {
        "id": e.id, "event_code": e.event_code, "name": e.name, "tenant_id": e.tenant_id, "tenant_name": e.tenant.name if e.tenant else None,
        "city": e.city, "start_date": e.start_date.isoformat() if e.start_date else None, "end_date": e.end_date.isoformat() if e.end_date else None,
        "status": e.status, "state_name": e.state.name if e.state else None, "local": event_lease.serialize(e),
    }


def _event(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return event


def _audit(db: Session, node: dict, action: str, event: Event, detail: str) -> None:
    db.add(AuditAction(actor_id=None, actor_role="nodo", action=action, entity="event", entity_id=str(event.id), entity_name=event.name, detail=detail[:500]))


@router.get("/node/events")
def node_events(db: Session = Depends(get_db), node: dict = Depends(require_node)):
    rows = db.query(Event).options(joinedload(Event.tenant), joinedload(Event.state)).filter(Event.archived_at.is_(None)).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).all()
    return {"events": [_meta(e) for e in rows]}


@router.get("/node/events/{event_id}/package")
def node_package(event_id: int, db: Session = Depends(get_db), node: dict = Depends(require_node)):
    """El paquete del evento (sin biometría: en un servidor local no hay reconocimiento facial)."""
    event = _event(db, event_id)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado")
    data, _ = event_transfer.export_event(db, event, staff_username=f"nodo:{node['name']}"[:60])
    log.info("node_package event=%s bytes=%s", event_id, len(data))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", event.event_code or "evento")
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="evento_{name}.zip"', "Cache-Control": "no-store"})


@router.post("/node/events/{event_id}/lease")
def node_take_lease(event_id: int, db: Session = Depends(get_db), node: dict = Depends(require_node)):
    event = _event(db, event_id)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo antes de llevarlo a un servidor local")
    already = event_lease.is_leased(event) and event.local_node_name == node["name"]
    event_lease.take(event, node["name"], None)
    if not already:
        _audit(db, node, "lease_local", event, f"Pasó a servidor local «{node['name']}» (descarga desde el servidor)")
    db.commit()
    return {**event_lease.serialize(event), "already_mine": already}


@router.post("/node/events/{event_id}/release")
def node_release(event_id: int, db: Session = Depends(get_db), node: dict = Depends(require_node)):
    """Suelta el arrendamiento: solo el servidor que lo tiene puede soltarlo (p. ej. si la descarga falló a medias)."""
    event = _event(db, event_id)
    if event_lease.is_leased(event):
        if event.local_node_name != node["name"]:
            raise HTTPException(status_code=409, detail=f"El evento está en el servidor local «{event.local_node_name}», no en este.")
        event_lease.release(event)
        _audit(db, node, "lease_release", event, f"Volvió a internet desde el servidor local «{node['name']}»")
        db.commit()
    return event_lease.serialize(event)
