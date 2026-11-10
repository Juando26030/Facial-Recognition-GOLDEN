"""Descarga del instalador del SERVIDOR LOCAL desde Configuración (Fase 10, bloque E · docs/EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md).

El instalador (`GoldenLocal-Setup-<versión>.exe`) NO se arma en la nube: lo construye Juan David en un computador con Windows (`deploy/windows/build_installer.ps1`, docs/FASE_6_SERVIDOR_LOCAL.md) y lo sube
UNA vez al almacenamiento de la app (`app/storage.py`), en la carpeta `system/local-installer/` (con Cloud Storage: `gsutil cp GoldenLocal-Setup-<versión>.exe gs://<bucket>/<prefijo>/system/local-installer/`).
No pasa por la app al subirse (pesa cientos de MB). Mientras no haya archivo, la tarjeta de Configuración dice «aún no disponible» y no ofrece botón.

* Quién: todos los roles del personal EXCEPTO el digitador temporal y el cliente (el instalador es el programa completo; el cliente es externo). Misma regla que el resto de la preparación del servidor local.
* Descarga: con Cloud Storage se redirige a una URL firmada de 10 minutos (el archivo es grande y la app no lo transporta); con disco local lo sirve la app. Cada descarga queda en `audit_actions` (sin datos personales).
* Opcional: `LOCAL_INSTALLER_URL` (HTTPS) apunta a un instalador publicado en otro lugar (p. ej. una versión en GitHub) si no se quiere subir el archivo al almacenamiento; el archivo del almacenamiento manda.
"""
import os
import re
from typing import Optional

from fastapi import Depends, HTTPException

from app.auth import effective_roles, get_current_staff
from app.models import StaffUser
from app.storage import get_storage, key_of

PREFIX = key_of("system", "local-installer")
NAME_RE = re.compile(r"^GoldenLocal-Setup-([0-9][0-9A-Za-z._-]*)\.exe$")
EXCLUDED_ROLES = frozenset({"digitador", "cliente"})
MEDIA_TYPE = "application/vnd.microsoft.portable-executable"
SIGNED_SECONDS = 600


def roles_allowed(roles) -> bool:
    """True si ALGUNO de los roles de la cuenta puede ver la tarjeta y descargar (todos menos digitador temporal y cliente)."""
    return any(r not in EXCLUDED_ROLES for r in (roles or ()))


def require_installer_access(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if not roles_allowed(effective_roles(staff)):
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")
    return staff


def _version_key(version: str):
    return [int(p) if p.isdigit() else -1 for p in re.split(r"[._-]", version)]


def latest_name() -> Optional[tuple]:
    """(nombre, versión) del instalador más nuevo guardado en el almacenamiento, o None."""
    found = []
    for key in get_storage().list(PREFIX):
        name = key.rsplit("/", 1)[-1]
        m = NAME_RE.match(name)
        if m:
            found.append((_version_key(m.group(1)), name, m.group(1)))
    if not found:
        return None
    _, name, version = max(found)
    return name, version


def external_url() -> Optional[str]:
    url = (os.getenv("LOCAL_INSTALLER_URL") or "").strip()
    return url if url.startswith("https://") else None


def status() -> dict:
    """Lo que la tarjeta necesita: `available` (hay con qué descargar), `version`, `filename`. Nunca rutas internas."""
    found = latest_name()
    if found:
        return {"available": True, "version": found[1], "filename": found[0], "source": "storage"}
    ext = external_url()
    if ext:
        return {"available": True, "version": (os.getenv("LOCAL_INSTALLER_VERSION") or "").strip() or None, "filename": ext.rsplit("/", 1)[-1].split("?")[0] or "GoldenLocal-Setup.exe", "source": "external"}
    return {"available": False, "version": None, "filename": None, "source": None}
