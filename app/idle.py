"""Cierre de sesión por inactividad del personal (3-nov-2026, docs/22_SESION_INACTIVIDAD.md).

La última actividad vive DENTRO de la cookie de sesión firmada (`__session`), sin tocar la base: `la` (segundos desde la época de la última acción real de la persona),
`idle_m` (minutos propios del evento en proceso en el que trabaja, o ausente) e `idle_off` (cuentas de puesto de impresión / que atienden a otros equipos: no se les cierra la sesión,
porque su equipo queda imprimiendo sin que nadie toque la pantalla). El middleware de app/main.py (`idle_gate`) hace cumplir el tiempo en CADA petición.

Qué cuenta como «uso»: una navegación del navegador (página nueva o formulario enviado) y `POST /api/session/touch`, que la página manda cuando la persona hizo clic, teclas, toque o scroll.
Los sondeos de fondo, latidos, balizas y refrescos NO renuevan la sesión (tampoco con el encabezado `X-Gw-Passive: 1`, que además lo declara).
"""
import contextvars
import os
import time
from typing import Optional

DEFAULT_MINUTES = 10
EVENT_MIN, EVENT_MAX = 5, 60          # rango permitido para el tiempo propio de un evento (Parámetros)
WARN_SECONDS = 60                     # el aviso sale 1 minuto antes de cerrar
PASSIVE_HEADER = "x-gw-passive"
TOUCH_PATH = "/api/session/touch"
# No se exige ni se renueva en: archivos estáticos, salud, tareas internas (token de Google), formularios y páginas públicas, webhooks, cierre/inicio de sesión.
EXEMPT_PREFIXES = ("/static/", "/health", "/ready", "/internal/", "/f/", "/b/", "/c/", "/r/", "/aceptar", "/api/aceptar/", "/webhooks/", "/privacidad", "/terminos", "/reembolsos", "/login", "/logout", "/cambiar-contrasena")

_current: contextvars.ContextVar = contextvars.ContextVar("gw_idle_session", default=None)


def now() -> int:
    return int(time.time())


def general_minutes() -> int:
    """Tiempo general (SESSION_IDLE_MINUTES, 10 por defecto). 0 = apagado. Un valor ilegible vuelve a 10."""
    raw = os.getenv("SESSION_IDLE_MINUTES", "").strip()
    if not raw:
        return DEFAULT_MINUTES
    try:
        return max(0, min(int(raw), 24 * 60))
    except ValueError:
        return DEFAULT_MINUTES


def event_minutes(event) -> Optional[int]:
    """Minutos propios del evento: solo si está EN PROCESO y tiene un valor dentro del rango; si no, None (rige el general)."""
    value = getattr(event, "idle_minutes", None)
    if getattr(event, "status", None) != "en_proceso" or value is None:
        return None
    return value if EVENT_MIN <= value <= EVENT_MAX else None


def exempt_path(path: str) -> bool:
    return path.startswith(EXEMPT_PREFIXES)


def is_navigation(method: str, headers) -> bool:
    """¿La petición la hizo el navegador al abrir/enviar una página (no un fetch de fondo)?"""
    mode = (headers.get("sec-fetch-mode") or "").lower()
    if mode:
        return mode == "navigate"
    return method == "GET" and (headers.get("accept") or "").lower().startswith("text/html")


def limit_seconds(session) -> int:
    """Segundos de inactividad permitidos para esta sesión; 0 = sin límite."""
    if session.get("idle_off"):
        return 0
    own = session.get("idle_m")
    if isinstance(own, int) and EVENT_MIN <= own <= EVENT_MAX:
        return own * 60
    return general_minutes() * 60


def start(session, db=None, staff=None) -> None:
    """Al iniciar sesión: marca la última actividad y si la cuenta queda exenta (puesto de impresión o anfitrión de otros equipos)."""
    session["la"] = now()
    session.pop("idle_m", None)
    session.pop("idle_off", None)
    if staff is not None and db is not None:
        from app import sessions
        if staff.print_station or sessions._hosts_others(db, staff):
            session["idle_off"] = True


def expired(session, at: Optional[int] = None) -> bool:
    limit = limit_seconds(session)
    if limit <= 0:
        return False
    last = session.get("la")
    if not isinstance(last, int):          # sesión creada antes de este cambio: desde ahora corre su tiempo (desplegar no expulsa a nadie)
        return False
    return (at if at is not None else now()) - last > limit


def renew(session, reset_event: bool = False, at: Optional[int] = None) -> None:
    session["la"] = at if at is not None else now()
    if reset_event:
        session.pop("idle_m", None)       # navegó a otra página: si es de un evento, get_event_for_staff vuelve a fijar su tiempo


def snapshot(session, at: Optional[int] = None) -> dict:
    limit = limit_seconds(session)
    if limit <= 0:
        return {"enabled": False}
    last = session.get("la") if isinstance(session.get("la"), int) else (at if at is not None else now())
    remaining = max(0, limit - ((at if at is not None else now()) - last))
    return {"enabled": True, "idle_seconds": limit, "remaining": remaining, "warn_seconds": min(WARN_SECONDS, limit // 3), "event_limit": isinstance(session.get("idle_m"), int)}


def bind(session):
    return _current.set(session)


def unbind(token) -> None:
    _current.reset(token)


def note_event(event) -> None:
    """Lo llama `get_event_for_staff`: si la persona trabaja en un evento en proceso con tiempo propio, la sesión lo recuerda (si no, rige el general). Sin sesión ligada, no hace nada."""
    session = _current.get()
    if session is None:
        return
    own = event_minutes(event)
    if own is None:
        session.pop("idle_m", None)
    elif session.get("idle_m") != own:
        session["idle_m"] = own
