"""Versión del programa y comparación con producción (Fase 6, servidores locales; decisión de Juan David del 9-nov-2026): el servidor local avisa si NO tiene la misma versión que producción.

La versión son DOS cosas: el commit desplegado (`ops.build_info`) y la última migración de la base (`schema_head`, se lee de `alembic/versions` sin tocar la base). Para decidir lo importante basta el esquema:
  igual            → todo bien
  desactualizada   → producción tiene un esquema más nuevo: ESTE servidor debe actualizarse (la nube rechazaría sus subidas)
  adelantada       → este servidor tiene un esquema más nuevo que producción (raro: se probó algo sin desplegar)
  distinta_version → mismo esquema pero otro commit: se recomienda actualizar, no es obligatorio
  desconocida      → no se pudo comparar (sin internet o producción sin versión)
Módulo sin base de datos. `PRODUCTION_URL` (solo en servidores locales) dice a quién se compara; en la nube no se define y no se consulta nada.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app import ops

_REV = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.M)
_DOWN = re.compile(r'^down_revision\s*=\s*(?:["\']([^"\']+)["\']|None)', re.M)
_cache = {"head": None}
_remote_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()
REMOTE_TTL = 300.0
FETCH_TIMEOUT = 4.0


def schema_head(versions_dir: Optional[Path] = None) -> str:
    """Revisión más nueva de las migraciones (la que ninguna otra tiene como anterior); «desconocida» si no se pueden leer."""
    if versions_dir is None and _cache["head"]:
        return _cache["head"]
    folder = versions_dir or Path(__file__).resolve().parent.parent / "alembic" / "versions"
    revs, downs = [], set()
    try:
        for f in folder.glob("*.py"):
            text = f.read_text(encoding="utf-8")
            m = _REV.search(text)
            if not m:
                continue
            revs.append(m.group(1))
            d = _DOWN.search(text)
            if d and d.group(1):
                downs.add(d.group(1))
    except OSError:
        return "desconocida"
    heads = [r for r in revs if r not in downs]
    head = sorted(heads)[-1] if heads else "desconocida"
    if versions_dir is None:
        _cache["head"] = head
    return head


def local_version() -> dict:
    info = ops.build_info()
    return {"commit": info["commit"], "date": info["date"], "schema": schema_head()}


def _order(rev: str):
    m = re.match(r"^(\d+)", rev or "")
    return int(m.group(1)) if m else -1


def compare(local: dict, remote: Optional[dict]) -> dict:
    """{status, message}: compara este servidor con producción. `remote` None = no se pudo consultar."""
    if not remote or not remote.get("schema") or remote.get("schema") == "desconocida" or local.get("schema") in (None, "desconocida"):
        return {"status": "desconocida", "message": "No se pudo comparar la versión con producción (sin internet o sin dato)."}
    a, b = _order(local["schema"]), _order(remote["schema"])
    if a < b:
        return {"status": "desactualizada", "message": f"Este servidor está desactualizado (esquema {local['schema']}; producción tiene {remote['schema']}). Hay que actualizarlo antes de subir datos a la nube."}
    if a > b:
        return {"status": "adelantada", "message": f"Este servidor tiene un esquema más nuevo que producción ({local['schema']} frente a {remote['schema']})."}
    if remote.get("commit") not in (None, "desconocida") and local.get("commit") not in (None, "desconocida") and remote["commit"] != local["commit"]:
        return {"status": "distinta_version", "message": f"Producción tiene una versión distinta ({remote['commit']}; este servidor {local['commit']}). Se recomienda actualizar."}
    return {"status": "igual", "message": "Este servidor tiene la misma versión que producción."}


def production_url() -> str:
    return os.getenv("PRODUCTION_URL", "").strip().rstrip("/")


def fetch_production(url: str, timeout: float = FETCH_TIMEOUT) -> Optional[dict]:
    """GET {url}/api/ops/version; None si no responde. Solo HTTPS (salvo localhost para pruebas)."""
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/api/ops/version", headers={"Accept": "application/json"}), timeout=timeout) as resp:      # noqa: S310
            data = json.loads(resp.read(20000).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check(force: bool = False) -> dict:
    """Comparación con producción (resultado guardado 5 min para no consultar a cada página). Sin `PRODUCTION_URL` (la nube misma): {"configured": False}."""
    url = production_url()
    if not url:
        return {"configured": False}
    with _lock:
        now = time.monotonic()
        if force or _remote_cache["value"] is None or now - _remote_cache["at"] > REMOTE_TTL:
            _remote_cache.update(at=now, value=fetch_production(url))
        remote = _remote_cache["value"]
    local = local_version()
    return {"configured": True, "local": local, "production": remote, **compare(local, remote)}
