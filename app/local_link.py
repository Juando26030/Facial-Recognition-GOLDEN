"""Vinculación del servidor LOCAL con producción, la primera vez (sin pegar tokens a mano).

La base local nace vacía. Al primer intento de ingreso, con usuario y contraseña de PRODUCCIÓN: se piden a la nube (`/api/node/enroll`) un token de este servidor, se guarda en
config\\local.env (y en el entorno de este proceso), se bajan las cuentas (`account_sync`) y arranca la subida automática. La contraseña viaja solo por HTTPS a la nube y no se guarda ni se registra.
"""
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app import account_sync, cloud_client, localmode, node_sync, versioning

log = logging.getLogger("golden.local_link")
KEYS = ("NODE_TOKEN", "CLOUD_BASE_URL", "NODE_NAME")


def env_file() -> str:
    return os.getenv("LOCAL_ENV_FILE", "").strip() or os.path.join(os.getenv("GOLDEN_LOCAL_ROOT", r"C:\GoldenLocal"), "config", "local.env")


def refresh_from_file() -> None:
    """Otro proceso (el servidor corre con 2) pudo vincular: se leen del archivo las claves que a este le faltan."""
    if (os.getenv("NODE_TOKEN") or "").strip():
        return
    try:
        with open(env_file(), encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
                if m and m.group(1) in KEYS and m.group(2):
                    os.environ[m.group(1)] = m.group(2)
    except OSError:
        pass


def linked() -> bool:
    refresh_from_file()
    return bool((os.getenv("NODE_TOKEN") or "").strip())


def _save(values: dict) -> None:
    path = env_file()
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for k, v in values.items():
        new = f"{k}={v}"
        for i, ln in enumerate(lines):
            if re.match(rf"^\s*{k}\s*=", ln):
                lines[i] = new
                break
        else:
            lines.append(new)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def _post(url: str, body: dict, timeout: float = 20.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with cloud_client.open_no_redirect(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read(100_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}


def link(db: Session, username: str, password: str) -> dict:
    """Devuelve {"ok": True} o {"ok": False, "status": 401|429|503, "message": ...}."""
    base = versioning.production_url()
    if not base or not (base.startswith("https://") or base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        return {"ok": False, "status": 503, "message": "Este servidor no tiene la dirección de producción configurada."}
    name = (os.getenv("NODE_NAME") or "").strip() or f"Servidor local {socket.gethostname()}"[:60]
    status, body = _post(base + "/api/node/enroll", {"username": username, "password": password, "name": name})
    if status == 0:
        return {"ok": False, "status": 503, "message": "Primer ingreso: este servidor necesita internet UNA vez para vincularse con producción. Conéctalo e intenta de nuevo."}
    if status == 429:
        return {"ok": False, "status": 429, "message": "Demasiados intentos fallidos. Espera unos minutos e intenta de nuevo."}
    token = body.get("token") if status == 200 else None
    if not token:
        return {"ok": False, "status": 401, "message": "Usuario o contraseña incorrectos, o la cuenta no puede vincular un servidor local (coordinador en adelante)."}
    values = {"NODE_TOKEN": token, "CLOUD_BASE_URL": base, "NODE_NAME": body.get("name") or name}
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
