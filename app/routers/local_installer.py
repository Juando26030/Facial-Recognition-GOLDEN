"""Tarjeta «Servidor local» de Configuración: estado y descarga del instalador (Fase 10 E, app/local_installer.py)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import audit_actions, local_installer
from app.database import get_db
from app.models import StaffUser
from app.storage import get_storage, key_of

log = logging.getLogger("golden.local_installer")
router = APIRouter()


@router.get("/local-installer")
def installer_status(staff: StaffUser = Depends(local_installer.require_installer_access)):
    """¿Hay instalador para descargar y de qué versión? (`available: false` = «aún no disponible»). No toca la base de datos."""
    return local_installer.status()


@router.get("/local-installer/download")
def installer_download(db: Session = Depends(get_db), staff: StaffUser = Depends(local_installer.require_installer_access)):
    """Descarga el instalador. Con Cloud Storage redirige a una URL firmada de 10 minutos; con disco local lo sirve la app; sin archivo propio usa `LOCAL_INSTALLER_URL`. 404 con mensaje claro si aún no hay."""
    found = local_installer.latest_name()
    if not found:
        ext = local_installer.external_url()
        if not ext:
            raise HTTPException(status_code=404, detail="El instalador del servidor local aún no está disponible.")
        audit_actions.record(db, staff, "download", "local_installer", "externo", None, "instalador del servidor local (enlace externo)")
        db.commit()
        return RedirectResponse(ext, status_code=302, headers={"Cache-Control": "no-store"})
    name, version = found
    key = key_of("system", "local-installer", name)
    audit_actions.record(db, staff, "download", "local_installer", version, None, "instalador del servidor local")
    db.commit()
    store = get_storage()
    signer = getattr(store, "signed_get_url", None)
    if signer is not None:
        try:
            return RedirectResponse(signer(key, name, local_installer.SIGNED_SECONDS), status_code=302, headers={"Cache-Control": "no-store"})
        except Exception:                      # sin poder firmar (credenciales) se transmite desde la app: más lento, pero entrega
            log.warning("no se pudo firmar la descarga del instalador; se transmite desde la app")
    return store.response(key, filename=name, media_type=local_installer.MEDIA_TYPE, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
