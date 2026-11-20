"""Autenticación de servidores locales por token (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md).

Un servidor local manda la cabecera `X-Node-Token`. El token es aleatorio (256 bits), se muestra UNA vez al crearlo y en la base solo está su SHA-256 (con un secreto de esa
entropía no hace falta un hash lento). Revocado = no entra. Uso en las rutas de la NUBE:

    node: LocalNode = Depends(node_auth.require_node)
    node_auth.require_compatible(request)        # 409 si el esquema del servidor local es más viejo que el de la nube

`last_seen_at` se actualiza a lo sumo cada 5 minutos por nodo (el nodo habla cada ~30 min: no se escribe a la base a cada petición).
"""
import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import server_keys
from app.database import get_db
from app.models import LocalNode, StaffUser
from app.timeutil import utcnow

TOKEN_PREFIX = "gwn_"
SEEN_EVERY = timedelta(minutes=5)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def generate_token() -> tuple:
    """(token en claro, su hash). El claro se entrega una sola vez y no se guarda."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def find_node(db: Session, token: Optional[str]) -> Optional[LocalNode]:
    token = (token or "").strip()
    if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    node = db.query(LocalNode).filter(LocalNode.token_hash == hash_token(token)).first()
    return node if node is not None and node.revoked_at is None else None


DISABLED_DETAIL = server_keys.DISABLED_DETAIL


def is_disabled(db: Session, token: Optional[str]) -> bool:
    """¿El token es de un servidor que un administrador DESHABILITÓ (su llave está deshabilitada)? Sin esto un token revocado por otro motivo y uno deshabilitado se verían igual."""
    token = (token or "").strip()
    if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return False
    node = db.query(LocalNode).filter(LocalNode.token_hash == hash_token(token)).first()
    if node is None or node.revoked_at is None:
        return False
    from app.models import LocalServerKey
    return db.query(LocalServerKey.id).filter(LocalServerKey.node_id == node.id, LocalServerKey.disabled_at.isnot(None)).first() is not None


def require_node(request: Request, db: Session = Depends(get_db)) -> LocalNode:
    node = find_node(db, request.headers.get("X-Node-Token"))
    if node is None:
        if is_disabled(db, request.headers.get("X-Node-Token")):
            raise HTTPException(status_code=403, detail=DISABLED_DETAIL)
        raise HTTPException(status_code=401, detail="Servidor local no autorizado (token ausente, no válido o revocado)")
    now = utcnow()
    version = (request.headers.get("X-Node-Version") or "")[:80] or None
    if node.last_seen_at is None or now - node.last_seen_at > SEEN_EVERY or (version and version != node.last_version):
        node.last_seen_at = now
        if version:
            node.last_version = version
        db.commit()
    return node


def node_staff(db: Session, node: LocalNode, via: bool = False) -> StaffUser:
    """La cuenta (admin/super_admin) que creó el token: con su alcance se aplican los lotes del nodo. Con `via`, la marca (atributo de paso, no se guarda) como «llega por el
    servidor local `node.name`»: así `api._event_for_sync` deja subir a ESE servidor en un evento arrendado y a nadie más (F5-9 A-09)."""
    staff = db.get(StaffUser, node.created_by_id) if node.created_by_id else None
    if staff is None or staff.role not in ("admin", "super_admin") or not getattr(staff, "is_active", True) or getattr(staff, "archived_at", None) is not None:
        raise HTTPException(status_code=403, detail="La cuenta que creó este servidor local ya no existe o no es de administración: crea el servidor de nuevo")
    if via:
        staff.via_node_name = node.name
    return staff


def schema_compatible(node_schema: Optional[str]) -> tuple:
    """(ok, mensaje). Solo se rechaza un servidor local con esquema más VIEJO que el de la nube (la nube ya tiene columnas que él no conoce)."""
    from app import versioning
    mine = versioning.schema_head()
    if not node_schema or node_schema == "desconocida":
        return False, "El servidor local no informó su versión: actualízalo antes de subir."
    if versioning._order(node_schema) < versioning._order(mine):
        return False, f"El servidor local está desactualizado (esquema {node_schema}; la nube tiene {mine}). Actualízalo antes de subir datos."
    return True, ""


def require_compatible(request: Request) -> None:
    ok, msg = schema_compatible(request.headers.get("X-Node-Schema"))
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
