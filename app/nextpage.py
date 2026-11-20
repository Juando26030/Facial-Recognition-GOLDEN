"""Volver a la misma página después de que la sesión se cerró por tiempo (20-nov-2026, pedido de Juan David).

El servidor (`idle_gate` de app/main.py) y la página (static/js/idle-session.js) llevan a `/login?expirada=1&next=<dónde estaba>`; el inicio de sesión devuelve a esa dirección.
Solo se acepta una dirección DEL MISMO SITIO (empieza por una sola «/»), sin esquema, sin barras invertidas ni caracteres de control, y nunca el inicio/cierre de sesión ni la API: así `next` no sirve
para mandar a nadie a otro sitio (redirección abierta). El permiso de la página lo sigue decidiendo la propia página al abrirse.
"""
from typing import Optional
from urllib.parse import quote

MAX_LEN = 600
# Nunca se vuelve a: el inicio y cierre de sesión, el cambio de contraseña, la espera de autorización, la API y las tareas internas (no son «pestañas»).
BLOCKED_PREFIXES = ("/login", "/logout", "/cambiar-contrasena", "/ingreso", "/api/", "/internal/", "/static/", "/webhooks/")


def safe_next(raw) -> Optional[str]:
    """La dirección si es segura; si no, None."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > MAX_LEN or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    path = value.split("?", 1)[0].split("#", 1)[0]
    if "://" in path or any(path == p.rstrip("/") or path.startswith(p) for p in BLOCKED_PREFIXES):
        return None
    return value


def login_url_back(path: str, query: str = "") -> str:
    """`/login?expirada=1` con `next` cuando la página donde estaba la persona es una de las que se pueden recordar."""
    here = safe_next(path + (("?" + query) if query else ""))
    if here == "/":
        here = None          # el inicio ya es el destino de siempre
    return "/login?expirada=1" + (("&next=" + quote(here, safe="")) if here else "")
