"""Cuentas para los servidores locales (Fase 6): la NUBE entrega la lista (con el hash de la contraseña) a un nodo autenticado con su token (X-Node-Token). Solo lectura; el local nunca sube cuentas."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import account_sync, localmode
from app.database import get_db

try:
    from app.node_auth import require_node          # agente B (0112): valida X-Node-Token de un nodo vigente
except ImportError:          # rama sin el módulo de tokens: el endpoint queda cerrado, nunca abierto
    def require_node():
        raise HTTPException(status_code=503, detail="Los nodos locales no están habilitados en esta versión")

router = APIRouter()


@router.get("/node/accounts")
def node_accounts(since: Optional[str] = None, db: Session = Depends(get_db), _node=Depends(require_node)):
    if localmode.is_local_server():
        raise HTTPException(status_code=404, detail="No disponible")          # un servidor local no reparte cuentas
    return account_sync.delta(db, (since or "")[:64] or None)
