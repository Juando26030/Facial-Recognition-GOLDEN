"""Configuración compartida de la prueba de carga contra STAGING (Cloud Run Jobs): la clave de la cuenta de carga no viaja por ningún lado, se DERIVA del `OPS_TOKEN`
del entorno (que el Job de siembra y los generadores leen de Secret Manager): así ni el repositorio, ni la salida de un comando, ni el chat la ven."""
import hashlib
import hmac
import os

TENANT = "carga-staging"
EVENT_CODE = "LOAD-STG"
USERNAME = "carga_dig"
FORM_SLUG = "carga"


def check_host(url: str, allowed=()):
    """None si `url` es un destino permitido para la prueba de carga; si no, el motivo. Doble candado: (1) el host debe ser de staging (contener «staging») y NO ser el
    dominio de producción; (2) si se dan `allowed` (LOAD_ALLOWED_HOSTS: los hosts EXACTOS de staging que calcula deploy/gcp/config.sh), debe coincidir con uno.
    Así una URL mal escrita (o la de producción) nunca recibe carga, aunque contenga la palabra «staging» en otro sitio."""
    from urllib.parse import urlsplit
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return f"la URL debe ser https://… (recibí {url!r})"
    if "golden-eventos" in host or "staging" not in host:
        return f"{host!r} no es de staging"
    allowed_hosts = [urlsplit(a if "//" in a else "https://" + a).hostname.lower() for a in allowed if a]
    if allowed_hosts and host not in allowed_hosts:
        return f"{host!r} no está entre los hosts permitidos de staging ({', '.join(allowed_hosts)})"
    return None


def derived_password() -> str:
    token = os.environ.get("OPS_TOKEN", "")
    if not token:
        raise SystemExit("Falta OPS_TOKEN: la clave de la cuenta de carga se deriva de él (ver scripts/load_cfg.py).")
    return "Ld" + hmac.new(token.encode(), b"golden-load-account", hashlib.sha256).hexdigest()[:30] + "!9"


def timing_token() -> str:
    """Valor de `X-Timing-Token` para que la app (SERVER_TIMING=1) devuelva `Server-Timing`. Misma fórmula que app/timing.py::token(); vacío sin OPS_TOKEN."""
    token = os.environ.get("OPS_TOKEN", "")
    return hmac.new(token.encode(), b"golden-server-timing", hashlib.sha256).hexdigest()[:20] if token else ""
