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


def lan_addresses() -> list:
    """Direcciones IPv4 de ESTE equipo dentro de la red local (las que otros computadores/celulares usan para abrir el sistema), la de la ruta principal primero. Sin internet también funciona:
    no se envía nada, solo se pregunta al sistema por qué interfaz saldría. Se descartan 127.x y 169.254.x (sin red)."""
    import ipaddress
    import socket
    found = []

    def add(ip: str) -> None:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return
        if a.version == 4 and not a.is_loopback and not a.is_link_local and not a.is_unspecified and not a.is_multicast and ip not in found:
            found.append(ip)          # privadas y también otras (p. ej. 100.64.x de algunos operadores); 169.254.x = sin DHCP, no sirve

    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255", "8.8.8.8"):          # la interfaz que usaría para salir (UDP: no envía nada)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                sk.settimeout(0.2)
                sk.connect((probe, 9))
                add(sk.getsockname()[0])
        except OSError:
            continue
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    found.sort(key=lambda i: not ipaddress.ip_address(i).is_private)          # las privadas primero
    return found


FACE_FLAGS = ("facial_enabled", "face_door_enabled", "aceptar_enabled", "accept_link_email", "client_photos_before")


def enforce_no_face(db, event=None) -> int:
    """En un servidor local NO hay rostro: apaga las banderas del flujo facial de los eventos que ya estaban descargados con el rostro activado (antes de este cambio quedaban «atrapados»:
    Parámetros decía «no disponible» pero Registro seguía mostrando la cámara). Con `event` solo toca ese evento. Devuelve cuántos eventos cambió."""
    if not is_local_server():
        return 0
    from app.models import Event
    q = db.query(Event)
    if event is not None:
        q = q.filter(Event.id == event.id)
    changed = 0
    for ev in q.all():
        if any(getattr(ev, f, False) for f in FACE_FLAGS):
            for f in FACE_FLAGS:
                if getattr(ev, f, False):
                    setattr(ev, f, False)
            changed += 1
    if changed:
        db.commit()
    return changed
