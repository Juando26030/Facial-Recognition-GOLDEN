"""Aislamiento por cliente (tenant) para lo que NO es un evento: cuentas del personal, clientes, supereventos (cierre de seguridad P4/P5, 6-nov-2026).

Mismo interruptor que `app.auth.assert_event_tenant` (ENFORCE_STAFF_TENANT=1): apagado no cambia nada; encendido, quien tiene `tenant_id` solo ve y toca lo de su cliente
(nulo = global, p. ej. el personal de Golden y el super_admin)."""
import os

from fastapi import HTTPException

from app.models import StaffUser


def staff_tenant_enforced(staff: StaffUser) -> bool:
    """¿Este usuario del personal queda limitado a su cliente?"""
    return os.getenv("ENFORCE_STAFF_TENANT", "0") == "1" and staff.tenant_id is not None


def assert_same_tenant(staff: StaffUser, tenant_id, detail: str = "No encontrado") -> None:
    """404 (no 403, para no confirmar que existe) si el usuario está limitado a su cliente y `tenant_id` es de otro."""
    if staff_tenant_enforced(staff) and tenant_id != staff.tenant_id:
        raise HTTPException(status_code=404, detail=detail)
