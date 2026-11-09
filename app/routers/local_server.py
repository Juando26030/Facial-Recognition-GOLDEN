"""Pantalla y API del SERVIDOR LOCAL (Fase 6; solo con LOCAL_SERVER=1): lista de todos los eventos de la nube (sin sus datos) y «Descargar a local»: exportar desde la nube + importar aquí
en UN paso (sin biometría) y dejar el evento marcado «en servidor local» en la nube. Quién: los mismos roles que bajan eventos (app/event_lease.LEASE_ROLES). Ver docs/FASE_6_SERVIDOR_LOCAL.md."""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import cloud_client, event_lease, event_transfer
from app.auth import require_role_or_any
from app.database import get_db
from app.models import Event, StaffUser

log = logging.getLogger("golden.local_server")
router = APIRouter()
_who = require_role_or_any("coordinador", event_lease.LEASE_ROLES)


def is_local_server() -> bool:
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def _only_local() -> None:
    if not is_local_server():
        raise HTTPException(status_code=404, detail="No encontrado")


def _fail(e: cloud_client.CloudError) -> HTTPException:
    return HTTPException(status_code=502 if e.status is None else (e.status if e.status in (400, 404, 409) else 502), detail=str(e))


@router.get("/local/cloud-events")
def cloud_events(db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Todos los eventos de la nube (metadatos) + si ya están aquí. Sin conexión devuelve `offline` y la lista vacía (la pantalla lo explica)."""
    _only_local()
    if not cloud_client.configured():
        return {"configured": False, "offline": False, "node_name": cloud_client.node_name(), "events": []}
    try:
        events = cloud_client.list_events()
    except cloud_client.CloudError as e:
        return {"configured": True, "offline": True, "error": str(e), "node_name": cloud_client.node_name(), "events": []}
    here = {(code or "").strip().lower(): eid for eid, code in db.query(Event.id, Event.event_code).all()}
    node = cloud_client.node_name()
    out = []
    for ev in events:
        lease = ev.get("local") or {}
        mine = bool(lease.get("leased")) and lease.get("node_name") == node
        out.append({**ev, "downloaded": (ev.get("event_code") or "").strip().lower() in here, "local_event_id": here.get((ev.get("event_code") or "").strip().lower()),
                    "leased_here": mine, "leased_elsewhere": bool(lease.get("leased")) and not mine})
    return {"configured": True, "offline": False, "node_name": node, "events": out}


@router.post("/local/cloud-events/{cloud_event_id}/download")
def download_event(cloud_event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Un paso: 1) la nube reserva el evento para este servidor, 2) baja el paquete, 3) lo importa aquí. Si algo falla antes de importar, el evento se devuelve a la nube."""
    _only_local()
    try:
        lease = cloud_client.take_lease(cloud_event_id)
    except cloud_client.CloudError as e:
        raise _fail(e)
    newly_taken = not lease.get("already_mine")
    try:
        data = cloud_client.download_event(cloud_event_id)
        report = event_transfer.import_package(db, data, staff_username=staff.username, keep_original_state=True, dry_run=False, import_biometrics=False)
    except cloud_client.CloudError as e:
        _give_back(cloud_event_id, newly_taken)
        raise _fail(e)
    except event_transfer.TransferError as e:
        _give_back(cloud_event_id, newly_taken)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        log.exception("descarga a local falló (evento de la nube %s)", cloud_event_id)
        _give_back(cloud_event_id, newly_taken)
        raise HTTPException(status_code=500, detail="No se pudo importar el evento en este servidor. El evento sigue en la nube.")
    if not report.get("ok"):
        if newly_taken:
            _give_back(cloud_event_id, True)
        raise HTTPException(status_code=409, detail="No se importó nada: " + " ".join(report.get("conflicts") or ["hay conflictos."]))
    log.info("descarga a local ok (evento de la nube %s)", cloud_event_id)
    return {"ok": True, "event_id": report.get("event_id"), "event_code": report.get("event_code"), "name": report.get("name"), "warnings": report.get("warnings", []),
            "message": "El evento quedó en este servidor. En la nube ahora se ve en solo lectura."}


def _give_back(cloud_event_id: int, newly_taken: bool) -> None:
    if not newly_taken:
        return
    try:
        cloud_client.release_lease(cloud_event_id)
    except cloud_client.CloudError:
        log.warning("no se pudo devolver el evento %s a la nube tras una descarga fallida", cloud_event_id)
