"""Bloqueo por entorno para scripts DESTRUCTIVOS (borrar datos, vaciar la base…). Lista de lo permitido, no de lo prohibido:

1. Si `DEPLOY_ENV` o `ENVIRONMENT` valen `production`, SIEMPRE se niega (aunque la base parezca local).
2. Si no, solo se permite con una base LOCAL (`localhost` / `127.0.0.1`) o con `DEPLOY_ENV=staging`.
3. Cualquier otro caso se niega con un mensaje en español.

Uso en un script destructivo, ANTES de tocar la base y antes de pedir confirmación:
    from app.script_guard import require_destructive_allowed
    require_destructive_allowed(engine.url.host)
Es pura (no importa nada de la base de datos): se prueba sin conexión (tests/test_script_guard_texto.py).
"""
import os
import sys
from typing import Mapping, Optional

LOCAL_HOSTS = ("localhost", "127.0.0.1")


def _env(environ: Mapping[str, str], name: str) -> str:
    return (environ.get(name) or "").strip().lower()


def destructive_block_reason(host: Optional[str], environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Devuelve el motivo (en español) por el que NO se puede correr un script destructivo, o None si se permite."""
    env = os.environ if environ is None else environ
    if _env(env, "DEPLOY_ENV") == "production" or _env(env, "ENVIRONMENT") == "production":
        return "Se niega: este es un entorno de PRODUCCIÓN (DEPLOY_ENV o ENVIRONMENT valen «production»). Un script destructivo nunca corre aquí."
    if (host or "").strip().lower() in LOCAL_HOSTS or _env(env, "DEPLOY_ENV") == "staging":
        return None
    shown = (host or "").strip() or "sin servidor"
    return (f"Se niega: la base de datos no es local (servidor «{shown}») y el entorno no es staging (DEPLOY_ENV=staging). "
            "Solo se permite con una base en localhost/127.0.0.1 o con DEPLOY_ENV=staging.")


def require_destructive_allowed(host: Optional[str], environ: Optional[Mapping[str, str]] = None) -> None:
    """Termina el script (código 2) con el motivo si no se permite; si se permite, no hace nada."""
    reason = destructive_block_reason(host, environ)
    if reason:
        print(reason)
        sys.exit(2)
