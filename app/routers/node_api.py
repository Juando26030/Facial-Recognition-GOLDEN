"""API de la NUBE para los servidores locales (Fase 6). Todo con el token de nodo (`X-Node-Token`, app/node_auth.py): lista de eventos (solo metadatos), paquete del evento sin biometría,
arrendamiento («en servidor local») y su liberación. Ninguna respuesta lleva datos de personas salvo el paquete que el nodo pide a propósito; en los logs solo conteos."""
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app import event_checklist, event_lease, event_transfer, peer_changes
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
        # Para que la lista del servidor local se vea como la de Eventos de la nube (solo metadatos del evento, nada de personas)
        "location": e.location, "report_uploaded": bool(e.report_pdf_path),
        "commercial_name": (e.commercial.full_name or e.commercial.username) if e.commercial else None,
        "coordinator_name": (e.coordinator.full_name or e.coordinator.username) if e.coordinator else None,
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
    rows = db.query(Event).options(joinedload(Event.tenant), joinedload(Event.state), joinedload(Event.commercial), joinedload(Event.coordinator)).filter(Event.archived_at.is_(None)).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).all()
    return {"events": [_meta(e) for e in rows]}


@router.get("/node/events/{event_id}/package")
def node_package(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """El paquete del evento (sin biometría: en un servidor local no hay reconocimiento facial)."""
    event = _event(db, event_id)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado")
    if not event_lease.is_writer(event, node.name):          # F5-9 A-05: el paquete (datos de personas) solo sale hacia el servidor que TIENE el evento arrendado (se toma antes con /lease, queda auditado)
        raise HTTPException(status_code=409, detail="Este evento no está asignado a este servidor local: tómalo primero.")
    data, _ = event_transfer.export_event(db, event, staff_username=f"nodo:{node.name}"[:60])
    log.info("node_package event=%s bytes=%s", event_id, len(data))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", event.event_code or "evento")
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="evento_{name}.zip"', "Cache-Control": "no-store"})


@router.get("/node/events/{event_id}/inventory-checklist")
def node_inventory_checklist(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """El checklist de inventario del evento (lo alistado), para consultarlo en el servidor local. Solo hacia el servidor que TIENE el evento; sin datos de personas."""
    event = _event(db, event_id)
    if not event_lease.is_writer(event, node.name):
        raise HTTPException(status_code=409, detail="Este evento no está asignado a este servidor local.")
    return {"lines": event_checklist.cloud_lines(db, event.id)}


@router.post("/node/events/{event_id}/lease")
def node_take_lease(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    event = _event(db, event_id, lock=True)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo antes de llevarlo a un servidor local")
    already = event_lease.is_writer(event, node.name)
    joined = event_lease.is_leased(event) and not already          # evento compartido que ya estaba en otro servidor (0160)
    event_lease.take(event, node.name, None)
    if not already:
        _audit(db, node, "lease_local", event, (f"El servidor local «{node.name}» se sumó al evento compartido" if joined else f"Pasó a servidor local «{node.name}» (descarga desde el servidor)"))
    db.commit()
    # Compartido: hasta dónde llega HOY la nube (antes de exportar el paquete). El servidor baja después solo lo que llegue desde aquí (lo que caiga en medio se repite y no duplica).
    cursor = peer_changes.current_cursor(db, event.id) if event_lease.is_shared(event) else None
    return {**event_lease.serialize(event), "already_mine": already, "joined": joined, "peer_cursor": cursor}


def abort_allowed(event, now=None) -> bool:
    """Solo se deshace un arrendamiento recién tomado (descarga fallida): sin ninguna subida confirmada y dentro de ABORT_WINDOW."""
    now = now or utcnow()
    return event.local_last_upload_at is None and event.local_since is not None and now - event.local_since <= ABORT_WINDOW


@router.post("/node/events/{event_id}/abort")
def node_abort(event_id: int, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """Deshace el arrendamiento si la descarga falló a medias (NO es «pasar a internet»: eso es /release de nodes.py, que exige 0 pendientes): solo el servidor que lo tiene puede soltarlo (p. ej. si la descarga falló a medias)."""
    event = _event(db, event_id, lock=True)
    if event_lease.is_leased(event):
        if not event_lease.is_writer(event, node.name):
            raise HTTPException(status_code=409, detail=f"El evento está en el servidor local «{event.local_node_name}», no en este.")
        if event_lease.is_shared(event) and event.local_node_name != node.name:
            event_lease.leave(event, node.name)          # compartido: este servidor se sumó y su descarga falló; los demás siguen (0160)
            _audit(db, node, "lease_release", event, f"El servidor local «{node.name}» se retiró del evento compartido (descarga fallida)")
            db.commit()
            return event_lease.serialize(event)
        if not abort_allowed(event):
            raise HTTPException(status_code=409, detail="El evento ya está trabajando en este servidor local: para devolverlo usa «Pasar a internet» (sube todo antes de soltarlo).")
        if event_lease.leave(event, node.name):
            _audit(db, node, "lease_release", event, f"Volvió a internet desde el servidor local «{node.name}»")
        db.commit()
    return event_lease.serialize(event)


@router.post("/node/events/{event_id}/precheck")
def node_precheck(event_id: int, body: dict, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """Evento COMPARTIDO (0161): antes de entregar o de dejar entrar a una zona sin reingreso, el servidor local pregunta qué tiene ya la nube de esa persona (lo suyo y lo que
    subieron los demás). Solo conteos de esa persona; solo para servidores del grupo."""
    from app import node_precheck as precheck
    event = _event(db, event_id)
    if not event_lease.is_shared(event) or not event_lease.is_writer(event, node.name):
        raise HTTPException(status_code=409, detail="Este evento no es compartido o no está en este servidor local")
    return precheck.cloud_answer(db, event, body or {})


@router.get("/node/events/{event_id}/changes")
def node_changes(event_id: int, request: Request, db: Session = Depends(get_db), node: LocalNode = Depends(require_node)):
    """Evento COMPARTIDO (0160): lo que hay en la nube DESPUÉS del cursor del servidor (un número por sección, claves `peer_changes.KEYS`: `l` registros, `a` personas, `p` impresiones, `c` cambios, `e` ediciones, `m` áreas, `d` entregas, `t` turnos, `q` llamados, `r` ruleta, `x` contactos), para que cada
    servidor vea lo que hicieron los demás. Solo para servidores del grupo y con el evento compartido. Páginas de hasta `peer_changes.PAGE`; `more` = hay más."""
    from app import node_auth
    node_auth.require_compatible(request)
    event = _event(db, event_id)
    if not event_lease.is_shared(event) or not event_lease.is_writer(event, node.name):
        raise HTTPException(status_code=409, detail="Este evento no es compartido o no está en este servidor local")
    out = peer_changes.changes_since(db, event, peer_changes.clean_cursor(dict(request.query_params)))
    out["nodes"] = event_lease.writers(event)
    return out
