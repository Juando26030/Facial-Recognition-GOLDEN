"""Configuración del servidor LOCAL que cambia en caliente (la vinculación con producción escribe NODE_TOKEN, CLOUD_BASE_URL y NODE_NAME en config\\local.env).
El servidor corre con varios procesos: solo el que vinculó tiene esas claves en su entorno; los demás las toman del archivo cuando les faltan (`refresh`). Módulo sin dependencias de la app."""
import os
import re

KEYS = ("NODE_TOKEN", "CLOUD_BASE_URL", "NODE_NAME")


def env_file() -> str:
    return os.getenv("LOCAL_ENV_FILE", "").strip() or os.path.join(os.getenv("GOLDEN_LOCAL_ROOT", r"C:\GoldenLocal"), "config", "local.env")


def refresh() -> None:
    """Solo en un servidor local y solo si falta el token: lee del archivo las claves de vinculación (una lectura pequeña; no toca la base)."""
    if (os.getenv("LOCAL_SERVER") or "").strip().lower() not in ("1", "true", "yes", "si") or (os.getenv("NODE_TOKEN") or "").strip():
        return
    try:
        with open(env_file(), encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
                if m and m.group(1) in KEYS and m.group(2):
                    os.environ[m.group(1)] = m.group(2)
    except OSError:
        pass


def save(values: dict) -> None:
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
