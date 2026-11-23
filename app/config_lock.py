"""Bloquear la configuración del digitador (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md).

Tres candados independientes por evento: el engranaje del REGISTRO (la opción de siempre «Mostrar la configuración del registro a los digitadores», ahora: apagada = el
engranaje se ve pero pide contraseña), el control de ZONAS (la tableta queda fija en la zona y el movimiento elegidos) y el control de INVENTARIO (queda fija en lo marcado
para entregar). Solo frena al digitador: coordinador, administrador y super administrador nunca quedan bloqueados. Se desbloquea con la contraseña del evento (se guarda
con hash; nunca el texto) o apagando el candado en Parámetros. Es una ayuda contra errores, no un permiso de la API: lo que la pantalla deja hacer, el servidor lo valida igual."""
import time
from typing import Iterable

from app import registro_gear

SCOPES = ("registro", "areas", "inventory")
FREE_ROLES = {"coordinador", "admin", "super_admin"}
MIN_PASSWORD = 4
MAX_PASSWORD = 64
MAX_TRIES = 5
WINDOW_SECONDS = 300
_tries = {}          # (event_id, staff_id) -> [hora de cada intento fallido]; en memoria del proceso, basta para frenar el adivinar a mano


def locked(db, event, scope: str, roles: Iterable[str]) -> bool:
    """¿Esta pantalla está bloqueada para esta persona?"""
    roles = set(roles or ())
    if roles & FREE_ROLES or "digitador" not in roles:
        return False
    if scope == "registro":
        return not registro_gear.digitadores_enabled(db, event.id)
    if scope == "areas":
        return bool(event.areas_config_locked)
    if scope == "inventory":
        return bool(event.inventory_config_locked)
    return False


def state_for(db, event, roles) -> dict:
    """Lo que la pantalla necesita saber (va en un bloque JSON de la plantilla)."""
    return {"event_id": event.id, "has_password": bool(event.config_unlock_hash), **{s: locked(db, event, s, roles) for s in SCOPES}}


def admin_state(db, event) -> dict:
    return {"registro_open": registro_gear.digitadores_enabled(db, event.id), "areas_locked": bool(event.areas_config_locked),
            "inventory_locked": bool(event.inventory_config_locked), "has_password": bool(event.config_unlock_hash)}


def clean_password(raw) -> str:
    text = str(raw or "")
    if text != text.strip():
        raise ValueError("La contraseña no puede empezar ni terminar con espacios")
    if not (MIN_PASSWORD <= len(text) <= MAX_PASSWORD):
        raise ValueError(f"La contraseña de desbloqueo debe tener entre {MIN_PASSWORD} y {MAX_PASSWORD} caracteres")
    return text


def set_password(event, raw) -> None:
    from app.auth import hash_password
    event.config_unlock_hash = hash_password(clean_password(raw))


def clear_password(event) -> None:
    event.config_unlock_hash = None


def _recent(key) -> list:
    now = time.time()
    tries = [t for t in _tries.get(key, []) if now - t < WINDOW_SECONDS]
    _tries[key] = tries
    return tries


def check(event, staff_id: int, raw) -> str:
    """'' si la contraseña es correcta; si no, el motivo (sin contraseña definida, demasiados intentos o incorrecta)."""
    from app.auth import verify_password
    if not event.config_unlock_hash:
        return "Este evento no tiene contraseña de desbloqueo. Pide a un coordinador que desbloquee la configuración en Parámetros del evento."
    key = (event.id, staff_id)
    if len(_recent(key)) >= MAX_TRIES:
        return "Demasiados intentos. Espera 5 minutos o pide a un coordinador que la desbloquee."
    if verify_password(str(raw or ""), event.config_unlock_hash):
        _tries.pop(key, None)
        return ""
    _tries.setdefault(key, []).append(time.time())
    return "Contraseña incorrecta."
