"""¿Este servidor es un servidor LOCAL sin internet (Fase 6)? Se decide solo por la variable de entorno LOCAL_SERVER=1 (nunca por la base ni por la petición)."""
import os

from fastapi import HTTPException

PASSWORD_ONLY_CLOUD = "La contraseña solo se cambia en la nube"
ACCOUNTS_ONLY_CLOUD = "Las cuentas se crean en la nube: aquí llegan solas al conectarse"


def is_local_server() -> bool:
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def assert_passwords_allowed() -> None:
    """En un servidor local NINGÚN camino cambia una contraseña (la nube manda y la copia hacia acá): 403 con el mensaje de siempre."""
    if is_local_server():
        raise HTTPException(status_code=403, detail=PASSWORD_ONLY_CLOUD)


LOCAL_READONLY_MSG = "Esto solo se cambia en internet: el servidor local no modifica el catálogo de inventario. Los datos se actualizan solos al conectarse."
CATALOG_WRITE_RE = None


def is_catalog_write(method: str, path: str) -> bool:
    """¿Es una edición del CATÁLOGO de inventario (categorías, productos, gestión, asignación global)? En un servidor local no se permite: se cambia en la nube y baja sola.
    Entregas y movimientos de un evento (areas_inventory, inventario del evento) siguen funcionando."""
    import re
    global CATALOG_WRITE_RE
    if CATALOG_WRITE_RE is None:
        CATALOG_WRITE_RE = re.compile(r"^/api/inventory/(categories|products|assign)(/|$)")
    return method.upper() in ("POST", "PUT", "PATCH", "DELETE") and bool(CATALOG_WRITE_RE.match(path))


LOCAL_NO_FACE_MSG = "El reconocimiento facial no está disponible en el servidor local: aquí se registra por cédula, QR o búsqueda."
LOCAL_NO_MODULE_PAGES = ("/inventario", "/cuentas-de-cobro", "/gastos")          # solo existen en internet; el inventario del EVENTO (lo alistado) se consulta desde el quiosco del evento


def is_face_call(method: str, path: str) -> bool:
    """¿Es una llamada de reconocimiento/enrolamiento facial? En un servidor local no se atienden (la biometría solo corre en la nube)."""
    import re
    return method.upper() == "POST" and bool(re.match(r"^/api/(recognize(/|$)|events/\d+/enroll-face(/|$))", path))


def is_cloud_only_page(method: str, path: str) -> bool:
    """¿Es una página de módulos que solo existen en internet (inventario global, cuentas de cobro, gastos)?"""
    return method.upper() == "GET" and any(path == base or path.startswith(base + "/") for base in LOCAL_NO_MODULE_PAGES)


def mail_disabled() -> bool:
    """En un servidor local no se envían correos ni notificaciones externas (las manda la nube)."""
    return is_local_server()
