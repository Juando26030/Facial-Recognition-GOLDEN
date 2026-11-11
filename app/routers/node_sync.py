"""Panel de sincronización del servidor LOCAL (Fase 6): estado de lo bajado y lo subido, subir ahora y «Pasar a internet». Solo existe con LOCAL_SERVER=1; en la nube responde 404.
Quién: los mismos roles que llevan eventos a local (coordinador, comercial, admin, super_admin, almacén, contabilidad)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import event_lease, node_sync, versioning
from app.auth import require_role_or_any
from app.database import get_db
from app.models import Event, StaffUser

router = APIRouter()
_who = require_role_or_any("coordinador", event_lease.LEASE_ROLES)


def _only_local() -> None:
    if not node_sync.is_local_server():
        raise HTTPException(status_code=404, detail="No disponible")


def _event_row(db: Session, e: Event) -> dict:
    return {"id": e.id, "name": e.name, "code": e.event_code, "cloud_event_id": e.cloud_event_id,
            "package_at": e.sync_package_at.isoformat() if e.sync_package_at else None,
            "last_upload_at": e.local_last_upload_at.isoformat() if e.local_last_upload_at else None,
            "last_attempt_at": e.sync_attempt_at.isoformat() if e.sync_attempt_at else None,
            "error": e.sync_error, "pending": node_sync.pending_counts(db, e), "local_only": node_sync.local_only_changes(db, e)}


@router.get("/node-sync/status")
def status(db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    _only_local()
    rows = [_event_row(db, e) for e in node_sync.synced_events(db)]
    return {"configured": node_sync.configured(), "interval_minutes": node_sync.interval_minutes(), "version": versioning.check(),
            "events": rows, "pending_total": sum(r["pending"]["total"] for r in rows)}


@router.post("/node-sync/run")
def run_now(db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """«Subir ahora»: un ciclo completo sin esperar los 30 minutos."""
    _only_local()
    if not node_sync.configured():
        raise HTTPException(status_code=400, detail="Este servidor no tiene configurado el token ni la dirección de producción (NODE_TOKEN y PRODUCTION_URL)")
    return node_sync.upload_all(db, force=True)


@router.post("/node-sync/events/{event_id}/release")
def release(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """«Pasar a internet»: sube todo y, si quedó todo confirmado, la nube libera el evento. Si algo falla no se libera y se explica por qué."""
    _only_local()
    event = db.get(Event, event_id)
    if event is None or event.cloud_event_id is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado entre los bajados de la nube")
    out = node_sync.release_event(db, event)
    if not out["ok"]:
        raise HTTPException(status_code=409, detail=out["error"])
    return out
