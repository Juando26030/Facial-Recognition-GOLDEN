"""Cliente del servidor LOCAL hacia la nube (Fase 6). Habla con `/api/node/*` con la cabecera `X-Node-Token` (app/node_auth.py).

Configuración SOLO por variables de entorno: CLOUD_BASE_URL (https://… o http://localhost para pruebas), NODE_TOKEN y NODE_NAME (nombre que se ve en la nube: «en el servidor local X»).
Nunca se escribe el token ni datos personales en los logs: solo método, ruta y código de estado."""
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("golden.cloud_client")
TIMEOUT = float(os.getenv("CLOUD_TIMEOUT_SECONDS", "30"))
DOWNLOAD_TIMEOUT = float(os.getenv("CLOUD_DOWNLOAD_TIMEOUT_SECONDS", "900"))
MAX_PACKAGE_BYTES = int(os.getenv("CLOUD_MAX_PACKAGE_MB", "500")) * 1024 * 1024


class CloudError(Exception):
    """Mensaje en español, listo para mostrar. `status` = código HTTP de la nube (None si no hubo conexión)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def base_url() -> str:
    return os.getenv("CLOUD_BASE_URL", "").strip().rstrip("/")


def node_name() -> str:
    return " ".join((os.getenv("NODE_NAME") or "Servidor local").split())[:60] or "Servidor local"


def configured() -> bool:
    return bool(base_url() and os.getenv("NODE_TOKEN", "").strip())


def _allowed(url: str) -> bool:
    return url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")


def _request(method: str, path: str, body: Optional[dict] = None, timeout: float = TIMEOUT, raw: bool = False):
    url = base_url()
    if not configured():
        raise CloudError("Este servidor no está configurado para hablar con la nube (faltan CLOUD_BASE_URL y NODE_TOKEN).")
    if not _allowed(url):
        raise CloudError("La dirección de la nube debe ser HTTPS.")
    data = json.dumps(body or {}).encode() if method != "GET" else None
    headers = {"X-Node-Token": os.getenv("NODE_TOKEN", "").strip(), "X-Node-Name": node_name(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 — solo HTTPS o localhost (arriba)
            payload = resp.read(MAX_PACKAGE_BYTES + 1) if raw else resp.read(5_000_000)
            if raw and len(payload) > MAX_PACKAGE_BYTES:
                raise CloudError("El paquete del evento es más grande de lo permitido para bajarlo en un paso: usa exportar e importar a mano.")
    except urllib.error.HTTPError as e:
        log.info("cloud %s %s -> %s", method, path.split("?")[0], e.code)
        detail = ""
        try:
            detail = json.loads(e.read(20000).decode("utf-8")).get("detail", "")
        except (ValueError, OSError, AttributeError):
            pass
        raise CloudError(detail if isinstance(detail, str) and detail else f"La nube respondió con un error ({e.code}).", e.code)
    except (urllib.error.URLError, OSError):
        log.info("cloud %s %s -> sin conexión", method, path.split("?")[0])
        raise CloudError("No hay conexión con la nube. Revisa el internet del servidor e inténtalo de nuevo.")
    if raw:
        return payload
    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError:
        raise CloudError("La nube respondió algo que no se entiende.")


def list_events() -> list:
    """Todos los eventos de la nube, solo metadatos (nada de personas)."""
    return _request("GET", "/api/node/events").get("events", [])


def download_event(cloud_event_id: int) -> bytes:
    """Paquete del evento SIN biometría (el .zip de app/event_transfer.py)."""
    return _request("GET", f"/api/node/events/{int(cloud_event_id)}/package", timeout=DOWNLOAD_TIMEOUT, raw=True)


def take_lease(cloud_event_id: int) -> dict:
    """Pone el evento en ESTE servidor (la nube lo muestra en solo lectura). Idempotente para el mismo nombre; 409 si ya está en otro."""
    return _request("POST", f"/api/node/events/{int(cloud_event_id)}/lease", {"node_name": node_name()})


def release_lease(cloud_event_id: int) -> dict:
    return _request("POST", f"/api/node/events/{int(cloud_event_id)}/abort", {"node_name": node_name()})
