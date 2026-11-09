"""API de la NUBE para los servidores locales (Fase 6). Todo con el token de nodo (`X-Node-Token`, app/node_auth.py): lista de eventos (solo metadatos), paquete del evento sin biometría,
arrendamiento («en servidor local») y su liberación. Ninguna respuesta lleva datos de personas salvo el paquete que el nodo pide a propósito; en los logs solo conteos."""
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app import event_lease, event_transfer
from app.database import get_db
from app.models import AuditAction, Event
from app.models import LocalNode
from app.node_auth import require_node
from app.timeutil import utcnow

log = logging.getLogger("golden.node_api")
router = APIRouter()
ABORT_WINDOW = timedelta(hours=2)          # F5-9 A-07: «deshacer» solo sirve para una descarga fallida (recién tomado y sin nada subido); lo demás es «Pasar a internet» (0 pendientes)


def _meta(e: Event) -> dict:
    return {
        "id": e.id, "event_code": e.event_code, "name": e.name, "tenant_id": e.tenant_id, "tenant_name": e.tenant.name if e.tenant else None,
        "city": e.city, "start_date": e.start_date.isoformat() if e.start_date else None, "end_date": e.end_date.isoformat() if e.end_date else None,
        "status": e.status, "state_name": e.state.name if e.state else None, "local": event_lease.serialize(e),
    }


def _event(db: Session, event_id: int, lock: bool = False) -> Event:
    q = db.query(Event).filter(Event.id == event_id)
    event = (q.with_for_update() if lock else q).first()          # F5-9 A-06: tomar/soltar con la fila bloqueada: dos servidores no se quedan los dos con el mismo evento
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return event


def _audit(db: Session, node: LocalNode, action: str, event: Event, detail: str) -> None:
    db.add(AuditAction(actor_id=node.created_by_id, actor_role="nodo", action=action, entity="event", entity_id=str(event.id), entity_name=event.name, detail=detail[:500]))


@router.get("/node/events")
def node_events(db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    rows = db.query(Event).options(joinedload(Event.tenant), joinedload(Event.state)).filter(Event.archived_at.is_(None)).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).all()
    return {"events": [_meta(e) for e in rows]}


@router.get("/node/events/{event_id}/package")
def node_package(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """El paquete del evento (sin biometría: en un servidor local no hay reconocimiento facial)."""
    event = _event(db, event_id)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado")
    if event.local_node_name != node.name:          # F5-9 A-05: el paquete (datos de personas) solo sale hacia el servidor que TIENE el evento arrendado (se toma antes con /lease, queda auditado)
        raise HTTPException(status_code=409, detail="Este evento no está asignado a este servidor local: tómalo primero.")
    data, _ = event_transfer.export_event(db, event, staff_username=f"nodo:{node.name}"[:60])
    log.info("node_package event=%s bytes=%s", event_id, len(data))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", event.event_code or "evento")
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="evento_{name}.zip"', "Cache-Control": "no-store"})


@router.post("/node/events/{event_id}/lease")
def node_take_lease(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    event = _event(db, event_id, lock=True)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo antes de llevarlo a un servidor local")
    already = event_lease.is_leased(event) and event.local_node_name == node.name
    event_lease.take(event, node.name, None)
    if not already:
        _audit(db, node, "lease_local", event, f"Pasó a servidor local «{node.name}» (descarga desde el servidor)")
    db.commit()
    return {**event_lease.serialize(event), "already_mine": already}


def abort_allowed(event, now=None) -> bool:
    """Solo se deshace un arrendamiento recién tomado (descarga fallida): sin ninguna subida confirmada y dentro de ABORT_WINDOW."""
    now = now or utcnow()
    return event.local_last_upload_at is None and event.local_since is not None and now - event.local_since <= ABORT_WINDOW


@router.post("/node/events/{event_id}/abort")
def node_abort(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """Deshace el arrendamiento si la descarga falló a medias (NO es «pasar a internet»: eso es /release de nodes.py, que exige 0 pendientes): solo el servidor que lo tiene puede soltarlo (p. ej. si la descarga falló a medias)."""
    event = _event(db, event_id, lock=True)
    if event_lease.is_leased(event):
        if event.local_node_name != node.name:
            raise HTTPException(status_code=409, detail=f"El evento está en el servidor local «{event.local_node_name}», no en este.")
        if not abort_allowed(event):
            raise HTTPException(status_code=409, detail="El evento ya está trabajando en este servidor local: para devolverlo usa «Pasar a internet» (sube todo antes de soltarlo).")
        event_lease.release(event)
        _audit(db, node, "lease_release", event, f"Volvió a internet desde el servidor local «{node.name}»")
        db.commit()
    return event_lease.serialize(event)
