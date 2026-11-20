"""Bloqueo del servidor LOCAL cuando un administrador deshabilita su llave de producto (20-nov-2026).

Sin internet el servidor sigue trabajando (un evento no se corta por esto). En cuanto la nube responde 403 con el texto fijo de `server_keys.DISABLED_DETAIL`, se escribe `SERVER_DISABLED=1`
en config\\local.env y la aplicación entera queda cerrada (middleware de app/main.py). No hay forma de reabrirla desde la app: hace falta una llave nueva y reinstalar.
Módulo sin dependencias de la app (solo lee/escribe local.env)."""
import os
import re
import time

from app import local_env, server_keys

LOCKED_MSG = "Este servidor local fue deshabilitado por un administrador de Golden. Ya no se puede usar; para instalar de nuevo hace falta una llave de producto nueva."
_cache = {"at": 0.0, "locked": False}
CHECK_EVERY = 10.0


def _read_flag() -> bool:
    try:
        with open(local_env.env_file(), encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*SERVER_DISABLED\s*=\s*(.*?)\s*$", line)
                if m and m.group(1).strip().lower() in ("1", "true", "yes", "si"):
                    return True
    except OSError:
        pass
    return False


def is_locked() -> bool:
    """¿Este servidor local está deshabilitado? Mira la variable del proceso y, cada 10 s, el archivo (los varios procesos del servidor se enteran entre sí)."""
    if (os.getenv("SERVER_DISABLED") or "").strip().lower() in ("1", "true", "yes", "si"):
        return True
    now = time.monotonic()
    if now - _cache["at"] > CHECK_EVERY:
        _cache["at"] = now
        _cache["locked"] = _read_flag()
    return _cache["locked"]


def lock() -> None:
    """Marca este servidor como deshabilitado (en el archivo y en este proceso)."""
    os.environ["SERVER_DISABLED"] = "1"
    _cache.update(at=time.monotonic(), locked=True)
    try:
        local_env.save({"SERVER_DISABLED": "1"})
    except OSError:
        pass


def note_cloud_error(status, detail) -> None:
    """Para quien habla con la nube: si la respuesta es «servidor deshabilitado», bloquea."""
    if status == 403 and detail == server_keys.DISABLED_DETAIL:
        lock()
