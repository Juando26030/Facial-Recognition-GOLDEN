"""Llaves de producto del servidor local (20-nov-2026; lógica pura en app/server_keys.py).

Administración (sesión de admin / super_admin): crear, ver y deshabilitar llaves; cada fila muestra el servidor asociado (último contacto y versión).
Instalador (sin sesión, limitado por IP): `POST /api/node/key/claim` reclama la llave para ESA instalación y entrega el permiso para bajar el paquete de la app. La activación (vincular el
servidor con usuario y contraseña) está en `nodes.enroll_node`, que ahora exige la llave. Nada de datos personales en logs ni en la auditoría.
"""
import logging
import os
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import local_update, security, server_keys, versioning
from app.auth import require_platform_role
from app.database import get_db
from app.models import AuditAction, LocalNode, LocalServerKey, StaffUser
from app.timeutil import utcnow

log = logging.getLogger("golden.server_keys")
router = APIRouter()
ADMIN = require_platform_role("admin")
CLAIM_MAX_HITS = 10                                  # intentos por IP en la ventana (una llave de 60 bits no se adivina; esto frena el barrido)
CLAIM_WINDOW = timedelta(minutes=15)


def _iso(v):
    return v.isoformat() if v else None


def _freshness(node, cloud: dict) -> dict:
    """¿El servidor tiene la última versión de producción? Lo que reportó en su última conexión («commit|esquema») frente a lo que corre hoy en la nube."""
    raw = (node.last_version or "") if node is not None else ""
    if "|" not in raw:
        return {"status": "desconocida", "message": "Aún no ha reportado su versión."}
    commit, schema = raw.split("|", 1)
    r = versioning.compare({"commit": commit, "schema": schema}, cloud)
    return {"status": r["status"], "message": r["message"], "commit": commit, "schema": schema}


def _row(k: LocalServerKey, now=None, cloud: Optional[dict] = None) -> dict:
    now = now or utcnow()
    st = server_keys.status(k, now)
    node = k.node
    return {"id": k.id, "code": k.code, "label": k.label, "status": st, "status_label": server_keys.STATUS_LABEL[st],
            "created_at": _iso(k.created_at), "expires_at": _iso(k.expires_at), "claimed_at": _iso(k.claimed_at), "activated_at": _iso(k.activated_at), "disabled_at": _iso(k.disabled_at),
            "created_by_name": (k.created_by.full_name or k.created_by.username) if k.created_by else None,
            "node": ({"id": node.id, "name": node.name, "last_seen_at": _iso(node.last_seen_at), "last_version": node.last_version, "revoked": node.revoked_at is not None,
                     "freshness": _freshness(node, cloud or versioning.local_version())} if node else None)}


def _audit(db: Session, staff, action: str, k: LocalServerKey, detail: str) -> None:
    db.add(AuditAction(actor_id=staff.id if staff else None, actor_role=staff.role if staff else None, action=action, entity="local_server_key", entity_id=str(k.id),
                       entity_name=k.code, detail=detail[:500]))


# ------------------------------------------------------------------------------------------------ administración
@router.get("/server-keys")
def list_keys(db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    now = utcnow()
    rows = db.query(LocalServerKey).order_by(LocalServerKey.created_at.desc(), LocalServerKey.id.desc()).limit(500).all()
    cloud = versioning.local_version()
    items = [_row(k, now, cloud) for k in rows]
    counts = {"active": 0, "unused": 0, "claimed": 0, "expired": 0, "disabled": 0}
    for it in items:
        counts[it["status"]] += 1
    return {"keys": items, "counts": counts, "valid_days": server_keys.VALID_DAYS, "cloud": cloud}


@router.post("/server-keys")
def create_key(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Crea una llave nueva (de un solo uso, vence a los 7 días si no se usa). `label` (opcional): para quién o para qué equipo es."""
    label = " ".join(str((data or {}).get("label") or "").split())[:60] or None
    now = utcnow()
    for _ in range(5):                                # el choque de dos llaves iguales es astronómico; se reintenta por si acaso
        code = server_keys.generate()
        if not db.query(LocalServerKey.id).filter(LocalServerKey.code == code).first():
            break
    else:
        raise HTTPException(status_code=500, detail="No se pudo generar la llave. Inténtalo de nuevo.")
    k = LocalServerKey(code=code, label=label, created_by_id=staff.id, created_at=now, expires_at=server_keys.expires_at(now))
    db.add(k)
    db.flush()
    _audit(db, staff, "server_key_create", k, "Llave de servidor local creada" + (f" ({label})" if label else ""))
    db.commit()
    return _row(k, now)


@router.post("/server-keys/{key_id}/disable")
def disable_key(key_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Deshabilita la llave PARA SIEMPRE y apaga el servidor asociado: en cuanto vuelva a tener internet deja de funcionar (el token del nodo queda revocado). No se puede volver a habilitar:
    para instalar de nuevo en ese computador hace falta una llave nueva."""
    k = db.query(LocalServerKey).filter(LocalServerKey.id == key_id).with_for_update().first()
    if k is None:
        raise HTTPException(status_code=404, detail="Llave no encontrada")
    if k.disabled_at is None:
        now = utcnow()
        k.disabled_at, k.disabled_by_id = now, staff.id
        node = db.get(LocalNode, k.node_id) if k.node_id else None
        if node is not None and node.revoked_at is None:
            node.revoked_at = now
        _audit(db, staff, "server_key_disable", k, "Llave deshabilitada" + (f"; servidor «{node.name}» revocado" if node is not None else " (no tenía servidor)"))
        db.commit()
    return _row(k)


# ------------------------------------------------------------------------------------------------ instalador (sin sesión)
@router.post("/node/key/claim")
def claim_key(data: dict, request: Request, db: Session = Depends(get_db)):
    """El instalador reclama la llave para ESA instalación (`installation_id`, un identificador al azar que genera el instalador) y recibe el permiso (firmado, 2 h) para bajar el paquete de la app.
    Repetir con la misma instalación vale (si se cortó la descarga); otra instalación no. El permiso solo sirve con esa instalación y mientras la llave siga sin deshabilitar."""
    security.enforce_public_limit(db, request, "key_claim", "-", CLAIM_MAX_HITS, CLAIM_WINDOW)
    code = server_keys.normalize((data or {}).get("key"))
    inst = server_keys.clean_install_id((data or {}).get("installation_id"))
    if not code or not inst:
        db.commit()                                   # conserva el intento contado
        raise HTTPException(status_code=400, detail=server_keys.MSG["format"] if not code else server_keys.MSG["bad_install"])
    k = db.query(LocalServerKey).filter(LocalServerKey.code == code).with_for_update().first()
    if k is None:
        db.commit()                                   # conserva el intento contado
        raise HTTPException(status_code=404, detail=server_keys.MSG["unknown"])
    now = utcnow()
    ok, why, msg = server_keys.check_claim(k, inst, now)
    if not ok:
        db.commit()
        raise HTTPException(status_code=403, detail=msg)
    manifest = local_update.published_manifest()
    if not manifest.get("available"):
        db.commit()
        raise HTTPException(status_code=503, detail="El paquete de la app todavía no está listo. Inténtalo de nuevo en unos minutos.")
    if k.claimed_at is None:
        k.claimed_at, k.installation_id = now, inst
        _audit(db, None, "server_key_claim", k, "Llave reclamada por un instalador")
    db.commit()
    ticket = server_keys.make_ticket(_secret(), k.id, inst, int(now.timestamp()))
    return {"ok": True, "ticket": ticket, "expires_in": server_keys.TICKET_SECONDS, "package_url": manifest["package_url"], "sha256": manifest["sha256"],
            "commit": manifest.get("commit"), "schema": manifest.get("schema")}


def _secret() -> str:
    secret = (os.getenv("SECRET_KEY") or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="Falta la configuración de seguridad del servidor (SECRET_KEY).")
    return secret


# ------------------------------------------------------------------------------------------------ quién puede bajar el paquete de la app
def package_auth_required() -> bool:
    """`UPDATE_PACKAGE_AUTH=1` cierra la descarga del paquete (y su dirección en el manifiesto) a quien no tenga un token de servidor o el permiso de un instalador. Apagado por defecto: los servidores
    que ya están instalados todavía no mandan su token al actualizar; se enciende cuando todos tengan la versión que lo hace."""
    return (os.getenv("UPDATE_PACKAGE_AUTH") or "").strip().lower() in ("1", "true", "yes", "si")


def package_allowed(request: Request) -> bool:
    if not package_auth_required():
        return True
    from app import node_auth
    from app.database import SessionLocal
    token = request.headers.get("X-Node-Token")
    ticket = request.headers.get("X-Install-Ticket")
    if not token and not ticket:
        return False
    with SessionLocal() as db:
        if token and node_auth.find_node(db, token) is not None:
            return True
        inst = server_keys.clean_install_id(request.headers.get("X-Install-Id"))
        if ticket and inst:
            kid = server_keys.read_ticket(_secret(), ticket, inst, int(utcnow().timestamp()))
            k = db.get(LocalServerKey, kid) if kid else None
            if k is not None and k.installation_id == inst and server_keys.status(k, utcnow()) in ("claimed", "active"):
                return True
    return False
