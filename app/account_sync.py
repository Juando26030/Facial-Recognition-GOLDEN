"""Sincronización de CUENTAS de la nube hacia un servidor local (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md, aclaración 2).

La nube manda: el local nunca sube cuentas. Se sincroniza el HASH de la contraseña (nunca la contraseña), junto con altas, bajas, desactivaciones y roles, de modo que en el local se entra con
el mismo usuario y contraseña de la nube. Las cuentas son pocas (cientos): la nube entrega la lista completa y una VERSIÓN (huella de todo lo sincronizable); si el local ya tiene esa versión
no se manda nada más. Las cuentas se emparejan por `username` (los ids pueden ser distintos en cada base). Una cuenta que ya no está en la nube se desactiva y archiva en el local (no se borra:
hay llaves que le apuntan). Nada de esto va a los registros: ni usuarios, ni correos, ni hashes.
"""
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AppSetting, StaffUser, Tenant
from app.timeutil import utcnow

log = logging.getLogger("golden.account_sync")
VERSION_KEY = "account_sync_version"
SYNCED_AT_KEY = "account_sync_at"
STAFF_FIELDS = ("username", "password_hash", "full_name", "role", "secondary_role", "extra_roles", "tenant_id", "email", "phone", "is_active", "must_change_password", "print_station", "tours_auto_off")
TENANT_FIELDS = ("id", "client_code", "legacy_client_code", "name", "contact_name", "contact_phone", "contact_email")          # CRM C1a: legacy_client_code = el hexadecimal anterior (alias)
FETCH_TIMEOUT = 20.0
MAX_BYTES = 5_000_000
NO_PASSWORD = "!"          # F5-9 A-08: una cuenta inactiva o archivada viaja SIN su hash (no sirve para entrar en el local y no se expone si el token del nodo se filtra); bcrypt nunca acepta «!»


def _tenant_row(t: Tenant) -> dict:
    return {f: getattr(t, f) for f in TENANT_FIELDS} | {"archived": t.archived_at is not None}


def _staff_row(s: StaffUser) -> dict:
    row = {f: getattr(s, f) for f in STAFF_FIELDS} | {"archived": s.archived_at is not None}
    if not s.is_active or s.archived_at is not None:
        row["password_hash"] = NO_PASSWORD
    return row


def snapshot(db: Session) -> dict:
    """Lo que la nube entrega: empresas (solo las que usan las cuentas) y todas las cuentas, ordenadas, con su huella."""
    staff = [_staff_row(s) for s in db.query(StaffUser).order_by(StaffUser.username).all()]
    used = {s["tenant_id"] for s in staff if s["tenant_id"]}
    tenants = [_tenant_row(t) for t in db.query(Tenant).order_by(Tenant.id).all() if t.id in used]
    return {"version": version_of(tenants, staff), "tenants": tenants, "staff": staff}


def version_of(tenants: list, staff: list) -> str:
    raw = json.dumps({"t": tenants, "s": staff}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def delta(db: Session, since: Optional[str]) -> dict:
    """Respuesta del endpoint de la nube: sin cambios si el local ya tiene la versión actual."""
    snap = snapshot(db)
    if since and since == snap["version"]:
        return {"unchanged": True, "version": snap["version"]}
    return {"unchanged": False, **snap}


# ------------------------------------------------------------------------------------------------ lado local
def current_version(db: Session) -> Optional[str]:
    row = db.get(AppSetting, VERSION_KEY)
    return row.value if row else None


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()


def apply(db: Session, payload: dict) -> dict:
    """Aplica la lista de la nube en UNA transacción (el que llama hace commit; si algo falla, rollback y no queda nada a medias). Devuelve solo conteos."""
    if payload.get("unchanged"):
        return {"unchanged": True}
    staff_rows, tenant_rows, version = payload.get("staff"), payload.get("tenants"), payload.get("version")
    if not isinstance(staff_rows, list) or not isinstance(tenant_rows, list) or not version:
        raise ValueError("Respuesta de cuentas no válida")
    if version != version_of(tenant_rows, staff_rows):
        raise ValueError("La huella de las cuentas no coincide: respuesta dañada")
    if not any(r.get("is_active") and not r.get("archived") for r in staff_rows):
        raise ValueError("La nube no entregó ninguna cuenta activa: no se cambia nada")          # nunca dejar el servidor sin quién entre
    counts = {"created": 0, "updated": 0, "deactivated": 0}
    for t in tenant_rows:
        row = db.get(Tenant, t["id"])
        if row is None:
            row = Tenant(id=t["id"], client_code=t["client_code"], name=t["name"])
            db.add(row)
        for f in ("client_code", "legacy_client_code", "name", "contact_name", "contact_phone", "contact_email"):
            if f == "legacy_client_code" and f not in t:
                continue                       # carga de una nube anterior al CRM: no trae el alias, el que ya hay aquí se conserva
            setattr(row, f, t.get(f))
        row.archived_at = (row.archived_at or utcnow()) if t.get("archived") else None
    db.flush()
    seen = set()
    for r in staff_rows:
        seen.add(r["username"])
        row = db.query(StaffUser).filter(StaffUser.username == r["username"]).first()
        new = row is None
        if new:
            row = StaffUser(username=r["username"], password_hash=r["password_hash"], role=r["role"])
            db.add(row)
        changed = new or any(getattr(row, f) != r.get(f) for f in STAFF_FIELDS) or (row.archived_at is not None) != bool(r.get("archived"))
        for f in STAFF_FIELDS:
            setattr(row, f, r.get(f))
        row.archived_at = (row.archived_at or utcnow()) if r.get("archived") else None
        if changed:
            counts["created" if new else "updated"] += 1
            if not new:
                row.session_epoch = (row.session_epoch or 0) + 1          # una contraseña, un rol o una baja nuevos cierran las sesiones abiertas de esa cuenta (app/sessions.py)
    for row in db.query(StaffUser).filter(StaffUser.username.notin_(seen)).all():
        if row.is_active or row.archived_at is None:
            row.is_active = False
            row.archived_at = row.archived_at or utcnow()
            row.session_epoch = (row.session_epoch or 0) + 1
            counts["deactivated"] += 1
    _put(db, VERSION_KEY, version)
    _put(db, SYNCED_AT_KEY, utcnow().isoformat())
    return counts


def fetch(url: str, token: str, since: Optional[str], timeout: float = FETCH_TIMEOUT) -> Optional[dict]:
    """GET {url}/api/node/accounts?since=… con X-Node-Token. Solo HTTPS (salvo localhost para pruebas). None si no hay conexión; el token no se registra."""
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        return None
    q = f"?since={since}" if since else ""
    req = urllib.request.Request(f"{url}/api/node/accounts{q}", headers={"Accept": "application/json", "X-Node-Token": token})
    from app.cloud_client import open_no_redirect
    try:
        with open_no_redirect(req, timeout=timeout) as resp:      # F5-9 A-10: sin seguir redirecciones (llevarían el token a otro sitio)
            data = json.loads(resp.read(MAX_BYTES).decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def run_once(db: Session) -> dict:
    """Un ciclo en el servidor local: pide a la nube, aplica y confirma. Lo llama el ciclo de sincronización (~30 min) y se puede llamar al conectarse. Nunca lanza por falta de red."""
    from app import versioning          # PRODUCTION_URL ya existe para el aviso de versión
    url, token = versioning.production_url(), (os.getenv("NODE_TOKEN") or "").strip()
    if not url or not token:
        return {"ok": False, "reason": "sin_configurar"}
    payload = fetch(url, token, current_version(db))
    if payload is None:
        return {"ok": False, "reason": "sin_conexion"}
    try:
        counts = apply(db, payload)
        db.commit()
    except Exception as e:          # noqa: BLE001 — cualquier fallo: nada a medias
        db.rollback()
        log.warning("account_sync fallo: %s", type(e).__name__)
        return {"ok": False, "reason": "respuesta_invalida"}
    log.info("account_sync ok %s", counts)
    return {"ok": True, **counts}
