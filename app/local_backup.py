"""COPIA COMPLETA de cada evento del servidor local en la nube (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md §3c). Pedido de Juan David el 20-nov-2026: «nada debe quedar solo en el
local: si el servidor se pierde, perdemos toda la información».

Además de la sincronización fila por fila (app/node_sync.py + app/node_extra.py, que FUSIONA en el evento de la nube), en cada ciclo de subida el servidor local arma una copia de TODO lo
que tiene del evento y la sube a la nube si cambió desde la última:
  - todas las tablas que tienen `event_id` (se descubren solas: una tabla nueva entra sin tocar este archivo), las que cuelgan de los formularios del evento (`form_id`) y las personas
    del evento (`users`, SIN rostro: el servidor local no guarda biometría y la columna se excluye igual),
  - los ARCHIVOS que esas filas nombran (documentos, evidencias, fotos…), cada uno una sola vez.
La nube la guarda en el almacenamiento privado bajo `<empresa>/local_backups/<evento>/<servidor>/` (las últimas KEEP copias; los archivos, una vez cada uno) y solo un super_admin la ve
y la descarga (Editar evento › Servidor local). No se fusiona sola: es el seguro para recuperar lo que la fusión no cubra. Nada de datos personales en los logs.
"""
import base64
import datetime as dt
import decimal
import gzip
import hashlib
import json
import re
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Base, Event

KEEP = 20
SKIP_TABLES = {"events"}                          # el evento va aparte (una sola fila)
SKIP_COLUMNS = {"face_encoding", "token_hash", "password_hash"}
FILE_COL = re.compile(r"(_path|_key)$|^stored_path$")
MAX_BACKUP_BYTES = 25 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024


def _plain(v):
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(v)).decode("ascii")}
    return v


def _rows(db: Session, table, where: str, params: dict) -> list:
    cols = [c.name for c in table.columns if c.name not in SKIP_COLUMNS]
    sql = text(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table.name}" WHERE {where}')
    return [{c: _plain(v) for c, v in zip(cols, r)} for r in db.execute(sql, params)]


def event_tables() -> list:
    return sorted((t for t in Base.metadata.tables.values() if "event_id" in t.columns and t.name not in SKIP_TABLES), key=lambda t: t.name)


def form_tables() -> list:
    return sorted((t for t in Base.metadata.tables.values() if "form_id" in t.columns and "event_id" not in t.columns), key=lambda t: t.name)


def dump_event(db: Session, event: Event) -> dict:
    """Todo lo del evento en este servidor, tabla por tabla (dict serializable a JSON)."""
    tables = {"events": _rows(db, Base.metadata.tables["events"], "id = :e", {"e": event.id})}
    for t in event_tables():
        try:
            tables[t.name] = _rows(db, t, "event_id = :e", {"e": event.id})
        except Exception:                                   # tabla que aún no existe en una base vieja: no frena la copia
            db.rollback()
    form_ids = [r["id"] for r in tables.get("web_forms", [])]
    if form_ids:
        for t in form_tables():
            try:
                tables[t.name] = _rows(db, t, "form_id = ANY(:f)", {"f": form_ids})
            except Exception:
                db.rollback()
    people = sorted({str(r["user_id"]) for r in tables.get("event_attendees", []) if r.get("user_id")})
    if people:
        tables["users"] = _rows(db, Base.metadata.tables["users"], "tenant_id = :t AND id = ANY(:p)", {"t": event.tenant_id, "p": people})
    return {"format": "golden-local-backup", "version": 1, "event_id": event.id, "event_code": event.event_code, "cloud_event_id": event.cloud_event_id,
            "tenant_id": event.tenant_id, "tables": tables}


def build(db: Session, event: Event) -> tuple:
    """(gzip de la copia, huella del contenido). La huella no incluye la hora: si nada cambió, no se vuelve a subir."""
    data = dump_event(db, event)
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return gzip.compress(raw, compresslevel=6), digest


def file_keys(dump: dict) -> list:
    """Claves de archivos que nombran las filas (documentos, evidencias, fotos…)."""
    out = set()
    for rows in (dump.get("tables") or {}).values():
        for r in rows:
            for c, v in r.items():
                if isinstance(v, str) and FILE_COL.search(c) and "/" in v and len(v) < 500 and ".." not in v:
                    out.add(v.strip().lstrip("/"))
    return sorted(out)


def safe_part(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or ""))[:60] or "servidor"


def prefix(tenant_id: str, event_id: int, node_name: str = "") -> str:
    base = f"{safe_part(tenant_id)}/local_backups/{int(event_id)}/"
    return base + (safe_part(node_name) + "/" if node_name else "")


def prune(storage, folder: str, keep: int = KEEP) -> None:
    """Deja solo las últimas `keep` copias de este servidor (los archivos sueltos no se tocan)."""
    copies = sorted(k for k in storage.list(folder) if k.endswith(".json.gz") and "/files/" not in k)
    for k in copies[:-keep] if len(copies) > keep else []:
        storage.delete(k)


def listing(storage, tenant_id: str, event_id: int) -> list:
    rows = []
    for k in storage.list(prefix(tenant_id, event_id)):
        if k.endswith(".json.gz") and "/files/" not in k:
            parts = k.split("/")
            rows.append({"key": k, "node": parts[-2] if len(parts) >= 2 else "", "name": parts[-1]})
    return sorted(rows, key=lambda r: r["name"], reverse=True)


def iter_new(keys: Iterable[str], already: set) -> list:
    return [k for k in keys if k not in already]
