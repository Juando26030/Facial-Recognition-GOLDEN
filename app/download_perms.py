"""Quién puede descargar las «bases de datos de cuentas» (Fase 4). UN solo lugar: agregar un rol nuevo (p. ej. «contabilidad», «inventario») es una línea en el conjunto de la base que le corresponda,
más el nombre del rol en `STAFF_ROLES` cuando exista. Se evalúa sobre `effective_roles` (el doble rol coordinador+comercial recibe la unión). Digitador temporal y cliente nunca están."""
from fastapi import Depends, HTTPException

from app.auth import effective_roles, get_current_staff
from app.models import StaffUser

KIND_DIGITADORES = "digitadores"
KIND_CLIENTES = "clientes"

DOWNLOAD_ROLES = {
    KIND_DIGITADORES: {"coordinador", "comercial", "admin", "super_admin"},          # futuro: agregar "contabilidad", "inventario"
    KIND_CLIENTES: {"comercial", "admin", "super_admin"},                           # futuro: agregar "contabilidad" si se define
}

# 6 descargas por hora y por usuario (rate_limit_events, sin IP).
RATE_KIND = "export_base"
RATE_MAX = 6


def can_download(staff, kind: str) -> bool:
    return bool(effective_roles(staff) & DOWNLOAD_ROLES.get(kind, set()))


def can_download_roles(role, secondary_role, kind: str) -> bool:
    """Para las páginas (que solo traen los roles de la sesión)."""
    return bool({r for r in (role, secondary_role) if r} & DOWNLOAD_ROLES.get(kind, set()))


def require_download(kind: str):
    def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if not can_download(staff, kind):
            raise HTTPException(status_code=403, detail="No tienes permiso para descargar esta base")
        return staff
    return checker
