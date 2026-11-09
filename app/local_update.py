"""«Actualizar ahora» en un servidor local (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md §Actualización).

La app NO se actualiza a sí misma: pide la actualización dejando un archivo de petición en `LOCAL_UPDATE_DIR`; un servicio aparte que instala el instalador de Windows (deploy/windows/updater-service.ps1)
lo recoge y hace lo delicado: 1) respaldo de la base, 2) descarga del paquete y verificación de su huella SHA-256, 3) cambio de archivos, 4) migraciones, 5) reinicio; si algo falla, vuelve a la versión
anterior y a la copia de la base. Escribe su avance en `update-status.json`, que la pantalla consulta.

Dónde se publica el paquete: producción responde en `/api/ops/update-manifest` con la dirección HTTPS del paquete y su huella (variables UPDATE_PACKAGE_URL / UPDATE_PACKAGE_SHA256 de la nube).
Reglas: solo servidores locales (LOCAL_SERVER=1); solo con HTTPS; nunca en medio de un turno sin confirmación explícita de la persona. Módulo sin base de datos (el que cuenta turnos se la pasa a quien llama).
"""
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app import versioning
from app.timeutil import utcnow

REQUEST_FILE = "update-request.json"
STATUS_FILE = "update-status.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STATES = ("idle", "pending", "backup", "download", "apply", "migrate", "restart", "ok", "error", "rolledback")
BUSY_STATES = ("pending", "backup", "download", "apply", "migrate", "restart")
RECENT_ACTIVITY_MINUTES = 15          # ingresos en los últimos 15 minutos = hay un turno en marcha


def is_local_server() -> bool:
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def update_dir() -> Path:
    return Path(os.getenv("LOCAL_UPDATE_DIR") or "data/update")


# ------------------------------------------------------------------ lo que PUBLICA producción
def published_manifest() -> dict:
    """Lo que la nube dice de su versión publicada para que los locales se actualicen. `available` es falso si la nube no tiene paquete configurado."""
    url = (os.getenv("UPDATE_PACKAGE_URL") or "").strip()
    sha = (os.getenv("UPDATE_PACKAGE_SHA256") or "").strip().lower()
    v = versioning.local_version()
    ok = url.startswith("https://") and bool(SHA256_RE.match(sha))
    return {"available": ok, "commit": v["commit"], "schema": v["schema"], "package_url": url if ok else None, "sha256": sha if ok else None}


def validate_manifest(m: Optional[dict]) -> Optional[str]:
    """Devuelve el motivo si el manifiesto no sirve para actualizar; None si está bien."""
    if not isinstance(m, dict) or not m.get("available"):
        return "Producción todavía no publicó un paquete de actualización."
    if not str(m.get("package_url") or "").startswith("https://"):
        return "El paquete de actualización no tiene una dirección segura (HTTPS)."
    if not SHA256_RE.match(str(m.get("sha256") or "")):
        return "El paquete de actualización no trae una huella de verificación válida."
    if not m.get("schema") or m.get("schema") == "desconocida":
        return "El paquete de actualización no dice su versión."
    return None


def fetch_manifest(timeout: float = versioning.FETCH_TIMEOUT) -> Optional[dict]:
    base = versioning.production_url()
    if not base or not (base.startswith("https://") or base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        return None
    try:
        from app.cloud_client import open_no_redirect
        with open_no_redirect(urllib.request.Request(base + "/api/ops/update-manifest", headers={"Accept": "application/json"}), timeout=timeout) as resp:      # F5-9 A-10: sin redirecciones
            data = json.loads(resp.read(20000).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ------------------------------------------------------------------ estado y petición (archivos)
def read_status(folder: Optional[Path] = None) -> dict:
    path = (folder or update_dir()) / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("state") in STATES:
            return data
    except (OSError, ValueError):
        pass
    return {"state": "idle", "message": ""}


def is_busy(folder: Optional[Path] = None) -> bool:
    return read_status(folder).get("state") in BUSY_STATES or (folder or update_dir()).joinpath(REQUEST_FILE).exists()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class UpdateRefused(Exception):
    """No se puede (o todavía no) actualizar. `code`: not_local | busy | up_to_date | no_manifest | bad_manifest | shift_active | offline."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def shift_in_progress(events_in_progress: int, recent_checkins: int) -> bool:
    """Hay un turno en marcha si algún evento está «En proceso» Y se registró gente hace poco (un evento abierto sin movimiento no impide actualizar tras una confirmación normal)."""
    return events_in_progress > 0 and recent_checkins > 0


def request_update(*, staff_id: int, events_in_progress: int, recent_checkins: int, confirm_shift: bool = False, folder: Optional[Path] = None) -> dict:
    """Valida todo y deja la petición para el servicio de actualización. Lanza UpdateRefused con un código para que la pantalla sepa qué preguntar."""
    if not is_local_server():
        raise UpdateRefused("not_local", "Solo un servidor local se actualiza desde aquí; la nube se publica por el proceso normal.")
    folder = folder or update_dir()
    if is_busy(folder):
        raise UpdateRefused("busy", "Ya hay una actualización en curso.")
    check = versioning.check(force=True)
    if not check.get("configured"):
        raise UpdateRefused("offline", "Este servidor no sabe dónde está producción (falta PRODUCTION_URL).")
    if check.get("status") in ("igual", "adelantada"):
        raise UpdateRefused("up_to_date", "Este servidor ya tiene la versión de producción.")
    if check.get("status") == "desconocida":
        raise UpdateRefused("offline", "No se pudo hablar con producción: revisa la conexión a internet e inténtalo de nuevo.")
    manifest = fetch_manifest()
    reason = validate_manifest(manifest)
    if reason:
        raise UpdateRefused("no_manifest" if not manifest else "bad_manifest", reason)
    if shift_in_progress(events_in_progress, recent_checkins) and not confirm_shift:
        raise UpdateRefused("shift_active", f"Hay un turno en marcha ({recent_checkins} ingresos en los últimos {RECENT_ACTIVITY_MINUTES} minutos). Actualizar detiene el sistema unos minutos.")
    req = {"requested_at": utcnow().isoformat(), "by_staff_id": staff_id, "package_url": manifest["package_url"], "sha256": manifest["sha256"],
           "target_commit": manifest.get("commit"), "target_schema": manifest["schema"], "from_commit": check["local"]["commit"], "from_schema": check["local"]["schema"],
           "confirmed_during_shift": bool(confirm_shift)}
    _atomic_write(folder / STATUS_FILE, {"state": "pending", "message": "Petición enviada; el servicio de actualización la recogerá en unos segundos.", "at": req["requested_at"]})
    _atomic_write(folder / REQUEST_FILE, req)
    return {"state": "pending"}
