"""Cuentas de OTRA empresa (SaaS, decisión de Juan David del 23-nov-2026): el CRM es solo de Golden, no se ofrece, y «Estado del sistema» (semáforos de la infraestructura de Golden)
tampoco lo ven. Esta lista es de NEGADOS (lo demás sigue por sus permisos de siempre y por el aislamiento por cliente). Si hay duda sobre si una pantalla nueva es para otra empresa, se le
pregunta a Juan David. Módulo puro (sin base de datos).

Se aplica con lo que hay en la sesión (`staff_external`, puesto al ingresar cuando ENFORCE_STAFF_TENANT=1 y la cuenta tiene cliente) en `app/main.py`, como el coordinador temporal."""

BLOCKED_PAGE_PREFIXES = ("/sistema", "/crm", "/plataforma")
BLOCKED_API_PREFIXES = ("/api/ops/status", "/api/crm", "/crm/", "/api/gastos/infra", "/api/system-alerts", "/api/platform")


def _starts(path: str, prefixes) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p if p.endswith("/") else p + "/") or path == p for p in prefixes)


def page_blocked(path: str) -> bool:
    return _starts(path, BLOCKED_PAGE_PREFIXES)


def api_blocked(path: str) -> bool:
    return _starts(path, BLOCKED_API_PREFIXES)
