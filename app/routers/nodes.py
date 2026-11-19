"""Servidores locales vistos desde la NUBE (Fase 6): crear/revocar su token (admin) y recibir lo que suben (con el token del nodo).

Lo que sube un nodo reutiliza la lógica idempotente que ya existe (`access-logs/sync`, `outbox/sync`: cada registro trae su identificador único, repetir un lote nunca duplica). El nodo
solo puede escribir en eventos que la nube tiene ARRENDADOS a su nombre (`Event.local_node_name`). Nada de datos personales en logs.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import event_lease, node_auth, versioning
from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, Event, LocalNode, StaffUser
from app.routers import api
from app.timeutil import utcnow

log = logging.getLogger("golden.nodes")
router = APIRouter()
ADMIN = require_role("admin")


# ------------------------------------------------------------------------------------------------ administración (sesión de admin / super_admin)
def _row(n: LocalNode) -> dict:
    return {"id": n.id, "name": n.name, "created_at": n.created_at.isoformat() if n.created_at else None, "revoked": n.revoked_at is not None,
            "last_seen_at": n.last_seen_at.isoformat() if n.last_seen_at else None, "last_version": n.last_version,
            "created_by_name": (n.created_by.full_name or n.created_by.username) if n.created_by else None}


@router.get("/nodes")
def list_nodes(db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    return {"nodes": [_row(n) for n in db.query(LocalNode).order_by(LocalNode.created_at.desc(), LocalNode.id.desc()).all()]}


@router.post("/nodes")
def create_node(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Crea un servidor local y devuelve su token UNA sola vez (después solo queda el hash): se pega en la configuración del servidor local."""
    name = event_lease.clean_node_name((data or {}).get("name"))
    if db.query(LocalNode).filter(LocalNode.name == name).first():
        raise HTTPException(status_code=409, detail="Ya existe un servidor local con ese nombre")
    token, digest = node_auth.generate_token()
    node = LocalNode(name=name, token_hash=digest, created_by_id=staff.id)
    db.add(node)
    db.flush()
    db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action="node_create", entity="local_node", entity_id=str(node.id), entity_name=name, detail="Servidor local creado"))
    db.commit()
    return {**_row(node), "token": token, "notice": "Guarda este token ahora: no se vuelve a mostrar."}


ENROLL_ROLES = ("coordinador", "comercial", "admin", "super_admin")


@router.post("/node/enroll")
def enroll_node(data: dict, request: Request, db: Session = Depends(get_db)):
    """Vinculación del servidor local la PRIMERA vez: una cuenta de producción con rol de coordinación en adelante entrega usuario y contraseña y recibe el token del nodo
    (se devuelve una sola vez; en la nube solo queda el hash). Mismos límites y bloqueo que el login; nunca dice cuál de los dos datos falló."""
    from app import security
    from app.auth import effective_roles, verify_password
    username = str((data or {}).get("username") or "").strip()[:150]
    password = str((data or {}).get("password") or "")[:200]
    ip = security.limit_ip(request)
    if security.login_minutes_locked(db, username, ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos fallidos. Espera unos minutos.")
    staff = db.query(StaffUser).filter(StaffUser.username == username, StaffUser.is_active == True).first() if username else None   # noqa: E712
    security.record_event(db, "login_fail", username or "-", ip)
    if staff is None or staff.event_only or not verify_password(password, staff.password_hash) or not (effective_roles(staff) & set(ENROLL_ROLES)):
        db.commit()
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos, o la cuenta no puede vincular un servidor local")
    security.clear_events(db, "login_fail", username)
    base = event_lease.clean_node_name((data or {}).get("name") or "Servidor local")
    name, n = base, 1
    while db.query(LocalNode).filter(LocalNode.name == name).first():          # cada instalación es un nodo propio: nunca pisa a otro
        n += 1
        name = f"{base[:50]} ({n})"
    token, digest = node_auth.generate_token()
    node = LocalNode(name=name, token_hash=digest, created_by_id=staff.id)
    db.add(node)
    db.flush()
    db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action="node_enroll", entity="local_node", entity_id=str(node.id), entity_name=name, detail="Servidor local vinculado con su cuenta"))
    db.commit()
    return {"token": token, "name": name}


@router.post("/nodes/{node_id}/revoke")
def revoke_node(node_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    node = db.get(LocalNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Servidor local no encontrado")
    if node.revoked_at is None:
        node.revoked_at = utcnow()
        db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action="node_revoke", entity="local_node", entity_id=str(node.id), entity_name=node.name, detail="Token revocado"))
        db.commit()
    return _row(node)


# ------------------------------------------------------------------------------------------------ lo que usa el servidor local (token de nodo)
def _leased_event(db: Session, event_id: int, node: LocalNode, lock: bool = False) -> Event:
    q = db.query(Event).filter(Event.id == event_id)
    event = (q.with_for_update() if lock else q).first()          # F5-9 A-06: liberar con la fila bloqueada
    if event is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    if event.local_node_name != node.name:
        raise HTTPException(status_code=409, detail="Este evento no está asignado a este servidor local")
    return event


@router.get("/node/ping")
def node_ping(request: Request, node: LocalNode = Depends(node_auth.require_node)):
    """El servidor local pregunta si la nube lo acepta: versión de la nube y si la suya es compatible. Una sola lectura (el token)."""
    ok, msg = node_auth.schema_compatible(request.headers.get("X-Node-Schema"))
    return {"ok": True, "node": node.name, "cloud": versioning.local_version(), "compatible": ok, "message": msg}


@router.post("/node/events/{event_id}/access-logs")
def node_access_logs(event_id: int, body: dict, request: Request, db: Session = Depends(get_db), node: LocalNode = Depends(node_auth.require_node)):
    node_auth.require_compatible(request)
    _leased_event(db, event_id, node)
    return api.sync_access_logs(event_id, body, db, node_auth.node_staff(db, node, via=True))


@router.post("/node/events/{event_id}/outbox")
def node_outbox(event_id: int, body: dict, request: Request, db: Session = Depends(get_db), node: LocalNode = Depends(node_auth.require_node)):
    node_auth.require_compatible(request)
    _leased_event(db, event_id, node)
    return api.outbox_sync(event_id, body, db, node_auth.node_staff(db, node, via=True))


@router.post("/node/events/{event_id}/uploaded")
def node_uploaded(event_id: int, request: Request, db: Session = Depends(get_db), node: LocalNode = Depends(node_auth.require_node)):
    """El nodo avisa que terminó una subida completa: solo actualiza «última subida» (la que ve el equipo en la nube)."""
    node_auth.require_compatible(request)
    event = _leased_event(db, event_id, node)
    event_lease.mark_uploaded(event)
    db.commit()
    return event_lease.serialize(event)


@router.post("/node/events/{event_id}/release")
def node_release(event_id: int, body: dict, request: Request, db: Session = Depends(get_db), node: LocalNode = Depends(node_auth.require_node)):
    """«Pasar a internet»: el nodo ya subió TODO (`pending` = 0 que él mismo contó tras la última confirmación) y la nube libera el evento. Con pendientes no se libera."""
    node_auth.require_compatible(request)
    event = _leased_event(db, event_id, node, lock=True)
    pending = (body or {}).get("pending")
    if not isinstance(pending, int) or pending != 0:
        raise HTTPException(status_code=409, detail="Todavía hay datos pendientes de subir: no se puede pasar a internet")
    event_lease.mark_uploaded(event)
    name = event.local_node_name
    event_lease.release(event)
    db.add(AuditAction(actor_id=node.created_by_id, actor_role="nodo", action="lease_release", entity="event", entity_id=str(event.id), entity_name=event.name, detail=f"Volvió a internet desde el servidor local «{name}» (sincronizado)"))
    db.commit()
    log.info("node_release event=%s node=%s", event.id, node.id)
    return event_lease.serialize(event)
