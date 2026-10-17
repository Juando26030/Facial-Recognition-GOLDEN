"""URL pública de la aplicación: UNA sola fuente (la variable `PUBLIC_BASE_URL`) para todo enlace absoluto que sale del sistema (correos, QR, enlaces personales, política, formularios, escarapela digital).

* Con la variable puesta, siempre se usa (sin «/» al final).
* Sin ella en PRODUCCIÓN (`DEPLOY_ENV=production`): se avisa en el log (WARNING) y NO se cae en silencio al host de Cloud Run: se devuelve vacío, y quien arma un enlace que debe ser absoluto lo
  rechaza con «Falta PUBLIC_BASE_URL» (los correos y la política ya lo hacen).
* Sin ella fuera de producción (pruebas, desarrollo local): se usa el host de la petición, como siempre.
* Si en producción apunta a un host `*.run.app` también se avisa: el dominio público debe ser el de la aplicación."""
import logging
import os
import time
from urllib.parse import urlsplit

log = logging.getLogger("golden.publicurl")
_last_warn = {"missing": 0.0, "run_app": 0.0}
_WARN_EVERY = 300          # segundos: sin inundar el log, pero visible


def _production() -> bool:
    return os.getenv("DEPLOY_ENV", "").strip().lower() == "production"


def _warn(kind: str, message: str) -> None:
    now = time.time()
    if now - _last_warn[kind] >= _WARN_EVERY:
        _last_warn[kind] = now
        log.warning(message)


def configured() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def base(request_base: str = "") -> str:
    """Dirección pública sin «/» final. `request_base` = `str(request.base_url)` de la petición (solo se usa fuera de producción y sin la variable)."""
    url = configured()
    if url:
        if _production() and (urlsplit(url).hostname or "").endswith(".run.app"):
            _warn("run_app", f"PUBLIC_BASE_URL apunta al host de Cloud Run ({urlsplit(url).hostname}) en PRODUCCIÓN: los enlaces de correos y QR saldrían con ese host. Debe ser el dominio público.")
        return url
    if _production():
        _warn("missing", "Falta PUBLIC_BASE_URL en PRODUCCIÓN: no se arman enlaces absolutos (correos, QR, enlaces personales). Defínela en el despliegue (deploy/gcp/config.sh).")
        return ""
    return (request_base or "").rstrip("/")


def check_at_startup() -> None:
    """Al arrancar: deja constancia en el log si la URL pública falta o es del host de Cloud Run en producción."""
    if _production():
        base()
