"""Arrendamiento de un evento por un servidor local (Fase 6): ponerlo en local, marcar lo subido y devolverlo a internet. Ver app/event_lease.py y docs/FASE_6_SERVIDOR_LOCAL.md.
Quién: cualquiera de la empresa (coordinador, comercial, admin, super_admin, almacén, contabilidad; rol principal o sumado) sobre CUALQUIER evento de su empresa; digitadores y clientes no."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import event_lease
from app.auth import assert_event_tenant, require_role, require_role_or_any
from app.database import get_db
from app.models import AuditAction, Event, StaffUser

router = APIRouter()
_who = require_role_or_any("coordinador", event_lease.LEASE_ROLES)


def _event(db: Session, event_id: int, staff: StaffUser, lock: bool = False) -> Event:
    q = db.query(Event).filter(Event.id == event_id)
    event = (q.with_for_update() if lock else q).first()          # F5-9 A-06: tomar/soltar con la fila bloqueada (FOR UPDATE sirve con el pooler de Neon)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    return event


def _audit(db: Session, staff: StaffUser, action: str, event: Event, detail: str) -> None:
    db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action=action, entity="event", entity_id=str(event.id), entity_name=event.name, detail=detail[:500]))


@router.get("/events/{event_id}/lease")
def get_lease(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    return event_lease.serialize(_event(db, event_id, staff))


@router.post("/events/{event_id}/lease")
def take_lease(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Pone el evento en un servidor local: desde ya la nube lo muestra en solo lectura. El paquete del evento lo baja el servidor local (exportar + importar en un paso)."""
    event = _event(db, event_id, staff, lock=True)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo antes de llevarlo a un servidor local")
    name = event_lease.clean_node_name((data or {}).get("node_name"))
    event_lease.take(event, name, staff.id)
    _audit(db, staff, "lease_local", event, f"Pasó a servidor local «{name}»")
    db.commit()
    return event_lease.serialize(event)


@router.post("/events/{event_id}/lease/uploaded")
def lease_uploaded(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """El servidor local avisa que subió lo suyo (cada ~30 min): solo actualiza «última subida»."""
    event = _event(db, event_id, staff)
    event_lease.mark_uploaded(event)
    db.commit()
    return event_lease.serialize(event)


@router.post("/events/{event_id}/lease/release")
def release_lease(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """«Pasar a internet»: el evento vuelve a editarse en la nube. El servidor local sube lo pendiente ANTES de llamar aquí (sincronizar con la nube)."""
    event = _event(db, event_id, staff, lock=True)
    if not event_lease.is_leased(event):
        return event_lease.serialize(event)
    node = event.local_node_name
    event_lease.release(event)
    _audit(db, staff, "lease_release", event, f"Volvió a internet desde el servidor local «{node}»")
    db.commit()
    return event_lease.serialize(event)


def _apply_mode(db: Session, event, staff: StaffUser, mode: str):
    """Fija «Usará servidores locales» y cómo se conectan. `""` = apagado (un solo servidor local, como siempre); `cloud` = compartido con la nube como puente
    (docs/23_EVENTO_COMPARTIDO_NUBE.md). Se puede encender aunque el evento ya esté en un servidor (ese pasa a ser el primero del grupo). Apagarlo solo con uno o ningún
    servidor: si hay varios, cada uno debe «Pasar a internet» antes."""
    mode = (mode or "").strip().lower()
    if mode and mode not in event_lease.MODES:
        raise HTTPException(status_code=400, detail="Forma de conexión desconocida")
    if mode and mode not in event_lease.READY_MODES:
        raise HTTPException(status_code=409, detail=f"«{event_lease.MODES[mode]}» todavía no está disponible. Por ahora usa «{event_lease.MODES['cloud']}».")
    want = mode == "cloud"
    if (event.local_mode or "") == mode and bool(event.local_shared) == want:
        return event_lease.serialize(event)
    if want and not event.local_shared:
        event.local_shared = True
        if event_lease.is_leased(event):
            event_lease._join(event, event.local_node_name)
    elif not want and event.local_shared:
        if len(event_lease.writers(event)) > 1:
            raise HTTPException(status_code=409, detail="El evento está en varios servidores locales: cada uno debe «Pasar a internet» antes de cambiar cómo se conectan.")
        event.shared_nodes.clear()
        event.local_shared = False
    event.local_mode = mode or None
    _audit(db, staff, "lease_shared", event, f"Usará servidores locales: {event_lease.MODES[mode]}" if mode else "Ya no usará varios servidores locales")
    db.commit()
    return event_lease.serialize(event)


@router.post("/events/{event_id}/lease/mode")
def set_mode(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """«Usará servidores locales» (Editar evento › Servidor local): {"mode": "" | "cloud" | "peer" | "hub"}."""
    event = _event(db, event_id, staff, lock=True)
    return _apply_mode(db, event, staff, str((data or {}).get("mode") or ""))


@router.post("/events/{event_id}/lease/shared")
def set_shared(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Compatibilidad (0160, primera versión): {"enabled": true} = puente por la nube; false = apagado."""
    event = _event(db, event_id, staff, lock=True)
    return _apply_mode(db, event, staff, "cloud" if (data or {}).get("enabled") else "")


@router.get("/events/{event_id}/local-backups")
def list_local_backups(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """0160: copias completas que subieron los servidores locales de este evento (app/local_backup.py). Solo super_admin (llevan datos personales)."""
    from app import local_backup
    from app.storage import get_storage
    event = _event(db, event_id, staff)
    return {"backups": local_backup.listing(get_storage(), event.tenant_id, event.id)}


@router.get("/events/{event_id}/local-backups/download")
def download_local_backup(event_id: int, key: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    from app import audit_actions, local_backup
    from app.storage import get_storage
    event = _event(db, event_id, staff)
    if not key.startswith(local_backup.prefix(event.tenant_id, event.id)) or ".." in key or not key.endswith(".json.gz"):
        raise HTTPException(status_code=404, detail="Copia no encontrada")
    st = get_storage()
    if not st.exists(key):
        raise HTTPException(status_code=404, detail="Copia no encontrada")
    audit_actions.record(db, staff, "download", "local_backup", event.id, event.name, "Descargó una copia completa de un servidor local")
    db.commit()
    return st.response(key, filename=f"copia-local-{event.event_code or event.id}-{key.rsplit('/', 1)[-1]}", media_type="application/gzip")
