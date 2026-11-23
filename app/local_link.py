"""Vinculación del servidor LOCAL con producción, la primera vez (sin pegar tokens a mano).

La base local nace vacía. Al primer intento de ingreso, con usuario y contraseña de PRODUCCIÓN: se piden a la nube (`/api/node/enroll`) un token de este servidor, se guarda en
config\\local.env (y en el entorno de este proceso), se bajan las cuentas (`account_sync`) y arranca la subida automática. La contraseña viaja solo por HTTPS a la nube y no se guarda ni se registra.
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app import account_sync, cloud_client, local_env, localmode, node_sync, versioning
from app.local_env import env_file, save as _save  # noqa: F401

log = logging.getLogger("golden.local_link")


def linked() -> bool:
    local_env.refresh()
    return bool((os.getenv("NODE_TOKEN") or "").strip())


def _post(url: str, body: dict, timeout: float = 20.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with cloud_client.open_no_redirect(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read(100_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read(20000).decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        return e.code, body if isinstance(body, dict) else {}
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}


def link(db: Session, username: str, password: str) -> dict:
    """Devuelve {"ok": True} o {"ok": False, "status": 401|429|503, "message": ...}."""
    base = versioning.production_url()
    if not base or not (base.startswith("https://") or base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        return {"ok": False, "status": 503, "message": "Este servidor no tiene la dirección de producción configurada."}
    name = (os.getenv("NODE_NAME") or "").strip() or f"Servidor local {socket.gethostname()}"[:60]
    local_env.refresh()                                                  # SERVER_KEY e INSTALLATION_ID los dejó el instalador en config\\local.env
    key = (os.getenv("SERVER_KEY") or "").strip()
    if not key:
        return {"ok": False, "status": 403, "message": "Este servidor no tiene llave de producto. Instálalo con el instalador de Golden y la llave que te da un administrador."}
    status, body = _post(base + "/api/node/enroll", {"username": username, "password": password, "name": name, "key": key, "installation_id": (os.getenv("INSTALLATION_ID") or "").strip()})
    if status == 0:
        return {"ok": False, "status": 503, "message": "Primer ingreso: este servidor necesita internet UNA vez para vincularse con producción. Conéctalo e intenta de nuevo."}
    if status == 429:
        return {"ok": False, "status": 429, "message": "Demasiados intentos fallidos. Espera unos minutos e intenta de nuevo."}
    token = body.get("token") if status == 200 else None
    detail = body.get("detail") if isinstance(body.get("detail"), str) else ""
    if not token and status in (400, 403, 404) and detail:          # problema con la LLAVE (usada, vencida, deshabilitada…): se muestra tal cual
        return {"ok": False, "status": status, "message": detail}
    if not token:
        return {"ok": False, "status": 401, "message": "Usuario o contraseña incorrectos, o la cuenta no puede vincular un servidor local (coordinador en adelante)."}
    values = {"NODE_TOKEN": token, "CLOUD_BASE_URL": base, "NODE_NAME": body.get("name") or name, "SERVER_KEY": body.get("server_id") or key}
    try:
        _save(values)
    except OSError:
        log.warning("local_link: no se pudo guardar la vinculación en el archivo de configuración")
    os.environ.update(values)
    try:
        account_sync.run_once(db)
    except Exception as e:          # noqa: BLE001 — la vinculación ya quedó; las cuentas llegan en el siguiente ciclo
        log.warning("local_link: account_sync %s", type(e).__name__)
    try:
        node_sync.start()
    except Exception as e:          # noqa: BLE001
        log.warning("local_link: node_sync %s", type(e).__name__)
    log.info("servidor local vinculado con producción")
    return {"ok": True}


def maybe_link_on_login(db: Session, username: str, password: str):
    """Para el login: si este es un servidor local sin vincular, intenta vincular con lo escrito. None = seguir con el login normal; dict con ok False = mostrar ese error."""
    if not localmode.is_local_server() or linked():
        return None
    res = link(db, username, password)
    return None if res["ok"] else res
