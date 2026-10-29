"""Exportar / importar un evento COMPLETO entre entornos (docs/18_EXPORTAR_EVENTOS.md). F1: configuración, personas, registros, formularios, ruleta y consentimientos,
SIN biometría y SIN archivos del storage (llegan en F2/F3).

Paquete = un .zip con `manifest.json` (formato, versión de Alembic de origen, entorno, fecha UTC, conteos y SHA-256 por tabla), `data/<tabla>.jsonl` (una fila por línea,
con los ids de ORIGEN) y `LEEME.txt`. Importar:
  - SIEMPRE crea un evento NUEVO (nunca sobrescribe), con un mapa de ids origen→destino por tabla; los identificadores de negocio (cédulas, `client_id`, slugs, tokens,
    referencias de pago, id de los consentimientos) y las horas (UTC, sin convertir) se conservan;
  - las cuentas del personal NO se copian y nunca se crean: «quién lo hizo» viaja como nombre de usuario; si no existe en el destino el enlace queda vacío y el texto se guarda
    en `event_import_actors`;
  - SIN EFECTOS SECUNDARIOS: no envía correos, no llama a Wompi, no encola trabajos ni crea pagos nuevos (los pagos y respuestas entran como histórico, `origin/source = 'importado'`);
  - todo en UNA transacción (el simulacro corre lo mismo y la deshace); las personas suprimidas en el destino no se vuelven a crear; una persona que ya existe NO se sobrescribe;
  - un evento «en proceso» queda en espera (estado «creado») hasta confirmarlo, para no activar el congelamiento de despliegues; los formularios entran en «pruebas».
Nada de datos personales en logs: aquí solo se loguean conteos."""
import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import Date, DateTime, Float, Numeric, select, text
from sqlalchemy.orm import Session

from app import consent, crypto, minors
from app import models as m
from app.storage import badge_asset_key, form_file_key, get_storage, key_of, normalize_key, photo_key
from app.timeutil import utcnow

log = logging.getLogger("golden.event_transfer")

FORMAT = "goldenweb-evento"
FORMAT_VERSION = 1
MAX_ZIP_BYTES = int(os.getenv("EVENT_TRANSFER_MAX_ZIP_MB", "512")) * 1024 * 1024
MAX_UNZIPPED_BYTES = MAX_ZIP_BYTES * 4        # lo que de verdad sale al descomprimir (contra «zip bomb»); se cuenta leyendo, no lo que diga el zip
MAX_ENTRIES = 200
MAX_ENTRIES_WITH_FILES = int(os.getenv("EVENT_TRANSFER_MAX_ENTRIES", "20000"))
CHUNK = 500
ASSET_EXT = r"(?:png|jpe?g|webp|gif|svg)"
FILE_NAME_RE = re.compile(r"^files/[0-9a-f]{64}$")
KDF_ITERATIONS = int(os.getenv("EVENT_TRANSFER_KDF_ITERATIONS", "600000"))
BIO_CHECK = b"goldenweb-biometria"
MIN_PASSPHRASE = 8
OPTIONAL_TABLES = ("event_documents", "event_expenses")          # los paquetes de la fase F1 no las traen
BIOMETRIC_USER_COLUMNS = ("face_encoding", "face_captured_at", "biometric_consent_at", "biometric_consent_source", "is_biometric_enabled")


class TransferError(Exception):
    """Paquete o destino que no se pueden usar: el mensaje va al usuario (en español, sin datos personales)."""


# ------------------------------------------------------------------------------------------------ qué se copia y cómo
# `kind` dice cómo se buscan las filas del evento; `remap` {columna: tabla} se traduce con el mapa origen→destino; `staff` columnas con id de personal (viajan como nombre);
# `unique` columnas con un valor único que se conserva si está libre en el destino; `null` columnas que se anulan; `user` columna con la cédula (personas suprimidas se omiten).
TABLES = [
    {"name": "events", "kind": "self"},
    {"name": "event_field_configs", "kind": "event"},
    {"name": "event_areas", "kind": "event"},
    {"name": "inventory_items", "kind": "event"},
    {"name": "badge_templates", "kind": "event", "null": ("imported_from_saved_template_id",)},
    {"name": "web_forms", "kind": "event", "staff": ("created_by_id",), "drop": ("test_key",)},
    {"name": "form_discount_codes", "kind": "form", "remap": {"form_id": "web_forms"}},
    {"name": "form_invites", "kind": "form", "remap": {"form_id": "web_forms"}, "unique": {"token": "regen"}, "user": "person_id"},
    {"name": "form_people", "kind": "form", "remap": {"form_id": "web_forms"}, "user": "person_id"},
    {"name": "form_events", "kind": "form", "remap": {"form_id": "web_forms"}},
    {"name": "users", "kind": "people"},
    {"name": "event_attendees", "kind": "event", "unique": {"digital_token": "null", "accept_token": "null"}, "user": "user_id"},
    {"name": "form_submissions", "kind": "event", "remap": {"form_id": "web_forms", "invite_id": "form_invites?", "discount_code_id": "form_discount_codes?"},
     "set": {"source": "importado"}, "user": "person_id"},
    {"name": "form_payments", "kind": "event", "remap": {"form_id": "web_forms", "submission_id": "form_submissions?"}, "unique": {"reference": "skip"},
     "set": {"origin": "importado"}, "user": "person_id"},
    {"name": "form_refunds", "kind": "refund", "remap": {"payment_id": "form_payments"}, "staff": ("created_by_id",)},
    {"name": "roulette_configs", "kind": "event", "unique": {"display_token": "null"}, "null": ("authorized_json",)},
    {"name": "roulette_draws", "kind": "event", "staff": ("created_by_id",)},
    {"name": "access_logs", "kind": "event", "staff": ("registered_by_staff_id",), "user": "user_id"},
    {"name": "area_movements", "kind": "event", "remap": {"area_id": "event_areas"}, "staff": ("registered_by_staff_id",), "user": "user_id"},
    {"name": "inventory_deliveries", "kind": "event", "remap": {"item_id": "inventory_items"}, "staff": ("delivered_by_staff_id",), "user": "user_id"},
    {"name": "print_logs", "kind": "event", "staff": ("printed_by_staff_id",), "user": "user_id"},
    {"name": "person_changes", "kind": "event", "staff": ("staff_user_id",), "user": "user_id"},
    {"name": "audit_consent_logs", "kind": "event", "user": "user_id"},
    {"name": "web_acceptances", "kind": "event", "staff": ("verified_by_staff_id",), "user": "user_id"},
    {"name": "event_documents", "kind": "event", "staff": ("uploaded_by_id",)},
    {"name": "event_expenses", "kind": "event", "staff": ("created_by_id",)},
]
SPEC = {t["name"]: t for t in TABLES}
PERSON_TABLES = ("event_attendees", "access_logs", "area_movements", "inventory_deliveries", "print_logs", "person_changes", "audit_consent_logs", "web_acceptances")
STAFF_EVENT_COLUMNS = ("coordinator_staff_id", "commercial_staff_id", "created_by_id")
TABLE_NAMES = tuple(t["name"] for t in TABLES)


# ------------------------------------------------------------------------------------------------ serialización
def _ser(v):
    if isinstance(v, datetime):
        if v.tzinfo is not None:                                  # columnas con zona horaria (p. ej. el consentimiento): siempre en UTC, sin depender de la zona de la sesión
            v = v.astimezone(timezone.utc)
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _parse(col, v):
    if v is None:
        return None
    t = col.type
    if isinstance(t, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(t, Date):
        return date.fromisoformat(v)
    if isinstance(t, Numeric) and not isinstance(t, Float):
        return Decimal(str(v))
    return v


def _line(row: dict) -> bytes:
    return (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _revision(db: Session) -> str:
    try:
        return db.execute(text("select version_num from alembic_version")).scalar() or ""
    except Exception:                                    # base sin alembic_version (pruebas con create_all)
        db.rollback()
        return ""


def _known_revisions() -> list:
    """Revisiones de Alembic de ESTE código, de la más vieja a la más nueva."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic"))
    return [r.revision for r in reversed(list(ScriptDirectory.from_config(cfg).walk_revisions()))]


# ------------------------------------------------------------------------------------------------ biometría (F3)
def _transport_fernet(passphrase: str, salt: bytes, iterations: int) -> Fernet:
    """Clave de transporte derivada de la frase (PBKDF2-HMAC-SHA256 + Fernet, como app/crypto.py). La frase NO se guarda en ninguna parte."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8"))))


def _export_biometrics(db: Session, event, people: set, zf, manifest: dict, passphrase: str) -> None:
    """Vectores y fotos de registro del evento, TODO cifrado con la clave de transporte (nada biométrico viaja en claro). Las fotos van por huella como el resto de archivos."""
    salt = os.urandom(16)
    kf = _transport_fernet(passphrase, salt, KDF_ITERATIONS)
    manifest["biometrics"] = {"kdf": "pbkdf2-sha256", "iterations": KDF_ITERATIONS, "salt": base64.b64encode(salt).decode(), "check": kf.encrypt(BIO_CHECK).decode()}
    st, h, n, pending_photos = get_storage(), hashlib.sha256(), 0, []
    written = {f["sha256"] for f in manifest["files"]}
    with zf.open("data/biometrics.jsonl", "w") as out:
        users = db.execute(select(m.User).where(m.User.tenant_id == event.tenant_id, m.User.id.in_(sorted(people) or [""])).order_by(m.User.id)).scalars().all()
        for u in users:
            key = photo_key(u.tenant_id, u.id)
            photo = crypto.read_bytes(key) if st.exists(key) else None
            if not (u.face_encoding or photo):
                continue
            rec = {"face_encoding": u.face_encoding, "face_captured_at": _ser(u.face_captured_at), "biometric_consent_at": _ser(u.biometric_consent_at),
                   "biometric_consent_source": u.biometric_consent_source, "is_biometric_enabled": bool(u.is_biometric_enabled), "has_photo": photo is not None}
            line = _line({"id": u.id, "token": kf.encrypt(json.dumps(rec, ensure_ascii=False).encode("utf-8")).decode()})
            out.write(line)
            h.update(line)
            n += 1
            if photo is not None:
                enc = kf.encrypt(photo)
                sha = hashlib.sha256(enc).hexdigest()
                if sha not in written:
                    pending_photos.append((sha, enc))                  # zipfile no deja escribir otra entrada con una abierta: se escriben al cerrar la de los vectores
                    written.add(sha)
                manifest["files"].append({"role": "biometric_photo", "ref": {"name": u.id}, "sha256": sha, "size": len(enc)})
    for sha, enc in pending_photos:
        zf.writestr(f"files/{sha}", enc)
    manifest["tables"]["biometrics"] = {"count": n, "sha256": h.hexdigest()}
    manifest["options"]["include_biometrics"] = True


def _open_biometrics(manifest: dict, passphrase: Optional[str]) -> Fernet:
    info = manifest.get("biometrics") or {}
    if not passphrase:
        raise TransferError("El paquete lleva biometría: escribe la frase de transporte con la que se exportó.")
    try:
        kf = _transport_fernet(passphrase, base64.b64decode(info["salt"]), int(info["iterations"]))
        if kf.decrypt(info["check"].encode()) != BIO_CHECK:
            raise InvalidToken()
    except (InvalidToken, KeyError, ValueError):
        raise TransferError("La frase de transporte no es la correcta.")
    return kf


# ------------------------------------------------------------------------------------------------ archivos del storage (F2)
ASSET_COLUMNS = {"badge_templates": ("elements_json", "background_value"), "web_forms": ("design_json", "settings_json"), "roulette_configs": ("style_json",)}
MAX_FILE_BYTES = int(os.getenv("EVENT_TRANSFER_MAX_FILE_MB", "100")) * 1024 * 1024


def _asset_re(tenant: str):
    return re.compile(r"(?:/api/badge-assets/)?" + re.escape(tenant) + r"/(?P<name>[A-Za-z0-9._-]+\." + ASSET_EXT + ")", re.IGNORECASE)


def _rewrite_assets(text_, tenant_src: str, tenant_dst: str, mapping: dict):
    """Cambia, en un JSON de diseño, las referencias a imágenes del cliente de origen por las del destino (otro cliente y/o nombre nuevo si chocó con otra imagen distinta)."""
    if not text_:
        return text_

    def sub(mt):
        name = mt.group("name")
        prefix = "/api/badge-assets/" if mt.group(0).startswith("/api/badge-assets/") else ""
        return f"{prefix}{tenant_dst}/{mapping.get(name, name)}"
    return _asset_re(tenant_src).sub(sub, text_)


def _collect_files(db: Session, event, form_ids: list, warnings: list) -> list:
    """(rol, referencia, clave de storage) de cada archivo que cuelga del evento. Solo lo que EXISTE en el storage."""
    st, tenant, out, seen = get_storage(), event.tenant_id, [], set()

    def add(role, ref, key):
        if not key:
            return
        try:
            key = normalize_key(key)
        except ValueError:
            return
        if (role, key) in seen:
            return
        seen.add((role, key))
        if st.exists(key):
            out.append((role, ref, key))
        else:
            warnings.append(f"Un archivo de «{role}» está en la base pero no en el almacenamiento: no viaja.")

    names = set()
    for table, cols in ASSET_COLUMNS.items():
        t = _table(table)
        where = t.c.event_id == event.id if table != "web_forms" else t.c.event_id == event.id
        for row in db.execute(select(*[t.c[c] for c in cols]).where(where)).all():
            for val in row:
                names.update(mt.group("name") for mt in _asset_re(tenant).finditer(val or ""))
    for n in sorted(names):
        add("badge_asset", {"name": n}, badge_asset_key(tenant, n))
    for fid in form_ids:
        for key in sorted(st.list(form_file_key(tenant, fid))):
            add("form_file", {"form_id": fid, "name": key.rsplit("/", 1)[-1]}, key)
    for key in sorted(st.list(key_of(tenant, "signatures", event.id))):
        add("signature", {"name": key.rsplit("/", 1)[-1]}, key)
    for (path,) in db.execute(select(m.EventDocument.stored_path).where(m.EventDocument.event_id == event.id)).all():
        add("event_doc", {"path": path}, path)
    for (path,) in db.execute(select(m.EventExpense.evidence_path).where(m.EventExpense.event_id == event.id, m.EventExpense.evidence_path.isnot(None))).all():
        add("expense", {"path": path}, path)
    add("logo", {"path": event.logo_path}, event.logo_path)
    add("report", {"path": event.report_pdf_path}, event.report_pdf_path)
    return out


# ------------------------------------------------------------------------------------------------ exportar
def _table(name):
    return m.Base.metadata.tables[name]


def _staff_names(db: Session) -> dict:
    return {sid: un for sid, un in db.execute(select(m.StaffUser.id, m.StaffUser.username)).all()}


def _select_rows(db: Session, spec: dict, event, ctx: dict):
    t = _table(spec["name"])
    kind = spec["kind"]
    cols = [c for c in t.columns if not (spec["name"] == "users" and c.name in BIOMETRIC_USER_COLUMNS) and c.name not in spec.get("drop", ())]
    q = select(*cols)
    if kind == "self":
        q = q.where(t.c.id == event.id)
    elif kind == "event":
        q = q.where(t.c.event_id == event.id)
    elif kind == "form":
        q = q.where(t.c.form_id.in_(ctx["form_ids"]))
    elif kind == "refund":
        q = q.where(t.c.payment_id.in_(ctx["payment_ids"]))
    elif kind == "people":
        q = q.where(t.c.tenant_id == event.tenant_id)
        if ctx["people"]:
            q = q.where(t.c.id.in_(sorted(ctx["people"])))
        else:
            q = q.where(text("1=0"))
    pk = [c for c in t.primary_key.columns]
    return db.execute(q.order_by(*pk)).mappings()


def _person_ids(db: Session, event) -> set:
    ids = set()
    for name in PERSON_TABLES:
        t = _table(name)
        ids.update(r[0] for r in db.execute(select(t.c.user_id).where(t.c.event_id == event.id).distinct()).all() if r[0])
    return ids


def export_event(db: Session, event, *, staff_username: Optional[str] = None, include_biometrics: bool = False, passphrase: Optional[str] = None) -> tuple:
    """Arma el paquete de un evento. Devuelve (bytes del .zip, manifest). Escribe una fila en la bitácora (sin datos personales). `include_biometrics` (solo super_admin: lo exige el
    endpoint) lleva vectores y fotos CIFRADOS con la frase de transporte `passphrase`, que no se guarda."""
    if include_biometrics and len(passphrase or "") < MIN_PASSPHRASE:
        raise TransferError(f"La frase de transporte debe tener al menos {MIN_PASSPHRASE} caracteres.")
    names = _staff_names(db)
    states = {sid: n for sid, n in db.execute(select(m.EventState.id, m.EventState.name)).all()}
    supers = {sid: n for sid, n in db.execute(select(m.SuperEvent.id, m.SuperEvent.name)).all()}
    ctx = {"people": _person_ids(db, event), "form_ids": [r[0] for r in db.execute(select(m.WebForm.id).where(m.WebForm.event_id == event.id)).all()], "payment_ids": []}
    ctx["payment_ids"] = [r[0] for r in db.execute(select(m.FormPayment.id).where(m.FormPayment.event_id == event.id)).all()] if ctx["form_ids"] else []
    tenant = db.get(m.Tenant, event.tenant_id)
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "alembic_revision": _revision(db), "source_env": os.getenv("DEPLOY_ENV", "").strip().lower() or "local",
                "created_at": utcnow().isoformat(), "tenant": {"id": tenant.id, "client_code": tenant.client_code, "name": tenant.name} if tenant else {"id": event.tenant_id},
                "event": {"event_code": event.event_code, "name": event.name, "status": event.status}, "options": {"include_biometrics": False}, "includes_files": True,
                "tables": {}, "files": [], "staff_usernames": [], "warnings": []}
    used_staff = set()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for spec in TABLES:
            n, h = 0, hashlib.sha256()
            with zf.open(f"data/{spec['name']}.jsonl", "w") as out:
                for row in _select_rows(db, spec, event, ctx):
                    d = {k: _ser(v) for k, v in row.items()}
                    extra = {}
                    for col in tuple(spec.get("staff", ())) + (STAFF_EVENT_COLUMNS if spec["name"] == "events" else ()):
                        if d.get(col) is not None:
                            un = names.get(d[col])
                            if un:
                                extra[col] = un
                                used_staff.add(un)
                            d[col] = None
                    if spec["name"] == "events":
                        if d.get("state_id") is not None:
                            extra["state_id"] = states.get(d["state_id"])
                        if d.get("super_event_id") is not None:
                            extra["super_event_id"] = supers.get(d["super_event_id"])
                        d["state_id"] = d["super_event_id"] = None
                    if extra:
                        d["@names"] = extra
                    line = _line(d)
                    out.write(line)
                    h.update(line)
                    n += 1
            manifest["tables"][spec["name"]] = {"count": n, "sha256": h.hexdigest()}
        manifest["staff_usernames"] = sorted(used_staff)
        written = set()
        st = get_storage()
        for role, ref, key in _collect_files(db, event, ctx["form_ids"], manifest["warnings"]):
            raw = st.get(key)
            if len(raw) > MAX_FILE_BYTES:
                manifest["warnings"].append(f"Un archivo de «{role}» pesa más de {MAX_FILE_BYTES // (1024 * 1024)} MB y no viaja.")
                continue
            sha = hashlib.sha256(raw).hexdigest()
            if sha not in written:
                zf.writestr(f"files/{sha}", raw)
                written.add(sha)
            manifest["files"].append({"role": role, "ref": ref, "sha256": sha, "size": len(raw)})
        if include_biometrics:
            _export_biometrics(db, event, ctx["people"], zf, manifest, passphrase)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        zf.writestr("LEEME.txt", "Paquete de evento de GoldenWeb (docs/18_EXPORTAR_EVENTOS.md).\nContiene DATOS PERSONALES: guárdalo y envíalo con cuidado, bórralo al terminar.\n"
                                 "Se importa desde «Importar evento» (solo super_admin); siempre crea un evento NUEVO.\n")
    data = buf.getvalue()
    counts = {k: v["count"] for k, v in manifest["tables"].items()}
    db.add(m.EventTransferLog(kind="export", staff_username=staff_username, event_id=event.id, event_code=event.event_code, package_sha256=_package_hash(manifest),
                              status="done", counts_json=json.dumps(counts), options_json=json.dumps(manifest["options"])))
    db.commit()
    log.info("event_export event_id=%s tables=%s rows=%s", event.id, len(counts), sum(counts.values()))
    return data, manifest


def _package_hash(manifest: dict) -> str:
    return hashlib.sha256("|".join(f"{k}:{v['sha256']}" for k, v in sorted(manifest["tables"].items())).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ leer y validar un paquete
def read_package(data: bytes) -> tuple:
    """Valida el .zip (tamaños, nombres, formato, versión, huellas, conteos) y devuelve (manifest, {tabla: [filas]})."""
    if len(data) > MAX_ZIP_BYTES:
        raise TransferError("El paquete es demasiado grande.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise TransferError("El archivo no es un paquete de evento válido (.zip).")
    infos = zf.infolist()
    allowed = {"manifest.json", "LEEME.txt", "data/biometrics.jsonl"} | {f"data/{n}.jsonl" for n in TABLE_NAMES}
    if len(infos) > MAX_ENTRIES_WITH_FILES or any(i.filename not in allowed and not FILE_NAME_RE.fullmatch(i.filename) for i in infos):
        raise TransferError("El paquete trae archivos que no corresponden a un evento exportado.")
    total = 0

    def _read(name: str) -> bytes:
        nonlocal total
        raw = b""
        with zf.open(name) as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                raw += chunk
                total += len(chunk)
                if total > MAX_UNZIPPED_BYTES:
                    raise TransferError("El paquete es demasiado grande al descomprimirse.")
        return raw

    if "manifest.json" not in zf.namelist():
        raise TransferError("Al paquete le falta el manifest.json.")
    try:
        manifest = json.loads(_read("manifest.json").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TransferError("El manifest.json del paquete está dañado.")
    if manifest.get("format") != FORMAT:
        raise TransferError("El archivo no es un paquete de evento de GoldenWeb.")
    if int(manifest.get("format_version", 0)) > FORMAT_VERSION:
        raise TransferError(f"El paquete usa una versión de formato más nueva ({manifest.get('format_version')}) que la de este sistema ({FORMAT_VERSION}): actualiza el destino y vuelve a intentar.")
    known = _known_revisions()
    rev = manifest.get("alembic_revision") or ""
    if rev and rev not in known:
        raise TransferError(f"El paquete viene de una versión de la base de datos más nueva ({rev}) que la de este sistema: actualiza el destino y vuelve a intentar.")
    rows = {}
    for spec in TABLES:
        name = spec["name"]
        info = manifest.get("tables", {}).get(name)
        if info is None and name in OPTIONAL_TABLES:                       # paquetes de F1: sin documentos ni gastos
            rows[name] = []
            continue
        if info is None:
            raise TransferError(f"Al paquete le falta la tabla «{name}».")
        raw = _read(f"data/{name}.jsonl")
        if hashlib.sha256(raw).hexdigest() != info["sha256"]:
            raise TransferError(f"La tabla «{name}» del paquete no coincide con su suma de control: el archivo está dañado o fue modificado.")
        items = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if len(items) != info["count"]:
            raise TransferError(f"La tabla «{name}» trae {len(items)} filas y el manifest dice {info['count']}.")
        rows[name] = items
    if len(rows["events"]) != 1:
        raise TransferError("El paquete debe traer exactamente un evento.")
    names = set(zf.namelist())
    bio = manifest.get("tables", {}).get("biometrics")
    if bio is not None:
        raw = _read("data/biometrics.jsonl")
        if hashlib.sha256(raw).hexdigest() != bio["sha256"]:
            raise TransferError("La tabla «biometrics» del paquete no coincide con su suma de control: el archivo está dañado o fue modificado.")
        rows["biometrics"] = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if len(rows["biometrics"]) != bio["count"]:
            raise TransferError("La tabla «biometrics» no trae las filas que dice el manifest.")
    for f in manifest.get("files", []):
        if f.get("sha256") is None or f"files/{f['sha256']}" not in names:
            raise TransferError("Al paquete le falta un archivo que el manifest declara.")

    def opener(sha: str) -> bytes:
        """Contenido de un archivo del paquete, verificando su huella al leerlo."""
        raw = _read(f"files/{sha}")
        if hashlib.sha256(raw).hexdigest() != sha:
            raise TransferError("Un archivo del paquete no coincide con su suma de control: está dañado o fue modificado.")
        return raw
    return manifest, rows, opener


# ------------------------------------------------------------------------------------------------ importar
def _alloc_ids(db: Session, table: str, n: int) -> list:
    if n == 0:
        return []
    seq = db.execute(text("select pg_get_serial_sequence(:t, 'id')"), {"t": table}).scalar()
    return [r[0] for r in db.execute(text(f"select nextval('{seq}') from generate_series(1, :n)"), {"n": n}).all()]


def _existing(db: Session, table: str, col: str, values) -> set:
    values = [v for v in values if v is not None]
    out = set()
    t = _table(table)
    for i in range(0, len(values), 1000):
        out.update(r[0] for r in db.execute(select(t.c[col]).where(t.c[col].in_(values[i:i + 1000]))).all())
    return out


def _insert(db: Session, table: str, rows: list) -> None:
    t = _table(table)
    for i in range(0, len(rows), CHUNK):
        sp = db.begin_nested()
        try:
            db.execute(t.insert(), rows[i:i + CHUNK])
            sp.commit()
        except Exception:
            sp.rollback()
            raise


def _clean_user_row(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k != "@names" and k not in BIOMETRIC_USER_COLUMNS}
    out["is_biometric_enabled"] = False
    return out


def import_package(db: Session, data: bytes, *, staff_username: Optional[str] = None, new_event_code: Optional[str] = None, new_name: Optional[str] = None,
                   keep_original_state: bool = False, dry_run: bool = True, target_tenant_id: Optional[str] = None, transport_passphrase: Optional[str] = None,
                   import_biometrics: bool = True) -> dict:
    """Importa un paquete creando un evento NUEVO. `dry_run=True` (por defecto) hace TODO y lo deshace (sin escribir archivos): lista qué entraría y qué conflictos hay.
    `target_tenant_id`: el cliente del destino (por defecto el mismo del paquete; si es otro, todo lo del evento pasa a ese cliente). Devuelve el informe."""
    from app.routers.events import EVENT_CODE_RE                     # el mismo formato de código que al crear un evento a mano
    manifest, rows, opener = read_package(data)
    src_event = rows["events"][0]
    tenant_dst = target_tenant_id or src_event["tenant_id"]
    report = {"dry_run": dry_run, "event_code": None, "name": None, "event_id": None, "source_env": manifest.get("source_env"), "tables": {}, "skipped": {}, "warnings": list(manifest.get("warnings", [])),
              "conflicts": [], "persons": {"new": 0, "existing_kept": 0, "existing_different": 0, "suppressed_skipped": 0}, "staff_without_link": [], "pending_confirm": False,
              "package_sha256": _package_hash(manifest), "files": {"planned": 0, "written": 0, "by_role": {}}, "tenant": tenant_dst,
              "biometrics": {"in_package": 0, "imported": 0, "skipped": {}}}

    def skip(table, why, n=1):
        report["skipped"].setdefault(table, {})
        report["skipped"][table][why] = report["skipped"][table].get(why, 0) + n

    # ---- código y nombre del evento nuevo
    code = (new_event_code or src_event["event_code"] or "").strip()
    name = (new_name or src_event["name"] or "").strip()
    report["event_code"], report["name"] = code, name
    if not EVENT_CODE_RE.fullmatch(code):
        report["conflicts"].append("El código del evento solo puede llevar letras, números, punto, guion y guion bajo.")
    from sqlalchemy import func
    if db.query(m.Event.id).filter(func.lower(func.btrim(m.Event.event_code)) == code.lower()).first():
        report["conflicts"].append(f"Ya existe un evento con el código «{code}»: escribe un código nuevo para el evento importado.")
    if db.query(m.Event.id).filter(m.Event.tenant_id == tenant_dst, func.lower(func.btrim(m.Event.name)) == name.lower()).first():
        report["conflicts"].append(f"Ya existe un evento con el nombre «{name}» en ese cliente: escribe un nombre nuevo.")
    if tenant_dst != src_event["tenant_id"] and not db.get(m.Tenant, tenant_dst):
        report["conflicts"].append("El cliente elegido no existe en este sistema.")
    bio_key = None
    if "biometrics" in rows and import_biometrics:
        bio_key = _open_biometrics(manifest, transport_passphrase)                  # frase equivocada o ausente: se rechaza ANTES de tocar nada
    if report["conflicts"]:
        db.rollback()
        report["ok"] = False
        return report

    written = []
    try:
        written = _do_import(db, manifest, rows, opener, report, skip, code=code, name=name, staff_username=staff_username, keep_original_state=keep_original_state,
                             tenant_dst=tenant_dst, dry_run=dry_run, bio_key=bio_key)
        report["ok"] = True
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        for key in written:                                                    # lo que ya se escribió en el almacenamiento se quita: nada a medias
            try:
                get_storage().delete(key)
            except Exception:  # noqa: BLE001
                log.warning("no se pudo quitar un archivo de una importación fallida")
        raise
    log.info("event_import dry_run=%s tables=%s files=%s", dry_run, {k: v["imported"] for k, v in report["tables"].items()}, report["files"]["planned"])
    return report


def _do_import(db: Session, manifest: dict, rows: dict, opener, report: dict, skip, *, code: str, name: str, staff_username: Optional[str], keep_original_state: bool,
               tenant_dst: str, dry_run: bool, bio_key: Optional[Fernet] = None) -> list:
    ev_src = rows["events"][0]
    tenant_src = ev_src.get("tenant_id")
    tenant_info = manifest.get("tenant") or {}
    tenant_id = tenant_dst
    # ---- cliente (solo nombre y código si falta, y solo cuando es el mismo del paquete)
    if not db.get(m.Tenant, tenant_id):
        client_code = tenant_info.get("client_code") or tenant_id
        if db.query(m.Tenant.id).filter(m.Tenant.client_code == client_code).first():
            raise TransferError("El código de cliente del paquete ya existe en este sistema con otro identificador: crea el cliente a mano y vuelve a importar.")
        db.add(m.Tenant(id=tenant_id, client_code=client_code, name=tenant_info.get("name") or tenant_id))
        db.flush()
        report["warnings"].append("El cliente no existía en el destino: se creó solo con su nombre y código.")
    staff_by_name = {un: sid for sid, un in db.execute(select(m.StaffUser.id, m.StaffUser.username)).all()}
    states = {n: sid for sid, n in db.execute(select(m.EventState.id, m.EventState.name)).all()}
    supers = {n: sid for sid, n in db.execute(select(m.SuperEvent.id, m.SuperEvent.name).where(m.SuperEvent.tenant_id == tenant_id)).all()}
    suppressed = {r[0] for r in db.execute(select(m.SuppressedPerson.cedula_hash).where(m.SuppressedPerson.tenant_id == tenant_id)).all()}
    log_row = m.EventTransferLog(kind="import", staff_username=staff_username, event_code=code, package_sha256=report["package_sha256"], status="done",
                                 options_json=json.dumps({"keep_original_state": keep_original_state, "source_env": manifest.get("source_env"), "tenant": tenant_id}))
    db.add(log_row)
    db.flush()
    actors = []                                                   # (tabla, referencia de la fila, columna, nombre de usuario sin cuenta aquí)
    new_ids = {}                                                  # tabla → {id origen: id nuevo}
    pending = {"forms": []}
    files = manifest.get("files", []) if manifest.get("includes_files") else []
    file_by_ref = {(f["role"], f["ref"].get("path") or f["ref"].get("name")): f for f in files if f["role"] != "biometric_photo"}
    writes = []                                                   # (clave de destino, sha256, rol)
    st = get_storage()

    # ---- imágenes de diseño (badge_assets): se reutiliza la misma imagen; si hay otra DISTINTA con el mismo nombre, la nueva se guarda con otro nombre y se reescriben las referencias
    assets_map = {}
    for f in files:
        if f["role"] != "badge_asset":
            continue
        fname = f["ref"]["name"]
        dest = badge_asset_key(tenant_id, fname)
        if st.exists(dest):
            if hashlib.sha256(st.get(dest)).hexdigest() == f["sha256"]:
                continue
            stem, ext = os.path.splitext(fname)
            assets_map[fname] = f"{stem}-{f['sha256'][:8]}{ext}"
            dest = badge_asset_key(tenant_id, assets_map[fname])
            report["warnings"].append("Una imagen del diseño ya existía con otro contenido: se guardó con otro nombre y el diseño la usa.")
        writes.append((dest, f["sha256"], "badge_asset"))

    def staff_link(row, d, table, ref):
        for col, un in (row.get("@names") or {}).items():
            if col in ("state_id", "super_event_id"):
                continue
            sid = staff_by_name.get(un)
            d[col] = sid
            if sid is None:
                actors.append((table, str(ref), col, un))
                if un not in report["staff_without_link"]:
                    report["staff_without_link"].append(un)

    # ---- personas suprimidas (se omiten ellas y todo lo que las menciona)
    banned, biometric_new = set(), set()
    for r in rows["users"]:
        if consent.cedula_hash(r["id"]) in suppressed:
            banned.add(r["id"])
    report["persons"]["suppressed_skipped"] = len(banned)

    # ---- biometría (F3): solo para personas NUEVAS en el destino, mayores de edad y con consentimiento aceptado registrado en el paquete (sin él no hay reconocimiento facial)
    bio = {}
    if bio_key is not None:
        report["biometrics"]["in_package"] = len(rows.get("biometrics", []))
        accepted = {c["user_id"] for c in rows["audit_consent_logs"] if c.get("accepted_biometric") and c.get("confirmed_adult")}
        birth = {u["id"]: u.get("birth_date") for u in rows["users"]}

        def bskip(why):
            report["biometrics"]["skipped"][why] = report["biometrics"]["skipped"].get(why, 0) + 1
        for b in rows.get("biometrics", []):
            uid = b["id"]
            if uid in banned:
                bskip("persona suprimida en el destino")
            elif birth.get(uid) and minors.is_minor(date.fromisoformat(birth[uid])):
                bskip("menor de 18 años")
            elif uid not in accepted:
                bskip("sin consentimiento aceptado registrado")
            else:
                try:
                    bio[uid] = json.loads(bio_key.decrypt(b["token"].encode()))
                except InvalidToken:
                    raise TransferError("Un registro biométrico del paquete no se pudo descifrar: el archivo está dañado o fue modificado.")

    for spec in TABLES:
        tname = spec["name"]
        t = _table(tname)
        src = rows[tname]
        rep = {"source": len(src), "imported": 0}
        report["tables"][tname] = rep
        out = []
        if tname == "events":
            new_id = _alloc_ids(db, "events", 1)[0]
            new_ids["events"] = {ev_src["id"]: new_id}
            d = {k: _parse(t.c[k], v) for k, v in ev_src.items() if k in t.c}
            d.update({"id": new_id, "event_code": code, "name": name, "faces_version": 0, "tenant_id": tenant_id})
            staff_link(ev_src, d, "events", new_id)
            names = ev_src.get("@names") or {}
            d["state_id"] = states.get(names.get("state_id")) if names.get("state_id") else None
            d["super_event_id"] = supers.get(names.get("super_event_id")) if names.get("super_event_id") else None
            if names.get("state_id") and d["state_id"] is None:
                report["warnings"].append(f"El estado configurable «{names['state_id']}» no existe en el destino: el evento queda con su estado base.")
            if names.get("super_event_id") and d["super_event_id"] is None:
                report["warnings"].append(f"El super-evento «{names['super_event_id']}» no existe en el destino: el evento queda sin super-evento.")
            if d.get("certificates_token") and _existing(db, "events", "certificates_token", [d["certificates_token"]]):
                d["certificates_token"] = None
                report["warnings"].append("El token de certificados ya existía en el destino: se dejó vacío (se genera de nuevo desde Parámetros).")
            logo, rpt = ev_src.get("logo_path"), ev_src.get("report_pdf_path")
            d["logo_path"] = d["report_pdf_path"] = None
            if logo and ("logo", logo) in file_by_ref:
                d["logo_path"] = key_of(tenant_id, "event_logos", uuid.uuid4().hex + os.path.splitext(logo)[1])
                writes.append((d["logo_path"], file_by_ref[("logo", logo)]["sha256"], "logo"))
            if rpt and ("report", rpt) in file_by_ref:
                d["report_pdf_path"] = key_of(tenant_id, "event_reports", new_id, os.path.basename(rpt))
                writes.append((d["report_pdf_path"], file_by_ref[("report", rpt)]["sha256"], "report"))
            else:
                d["report_uploaded_at"] = None
            if d.get("logo_mode") == "custom" and not d["logo_path"]:
                d["logo_mode"] = "default"
            if d.get("status") == "en_proceso":
                d["status"] = "creado"                              # en espera: no activa el congelamiento de despliegues hasta confirmar
                pending["event_status"] = "en_proceso"
                report["pending_confirm"] = True
            out.append(d)
            rep["imported"] = 1
            _insert(db, tname, out)
            log_row.event_id = new_id
            report["event_id"] = new_id
            continue

        # ---- tablas con id entero: se reservan los ids nuevos antes de insertar (así los hijos ya conocen el mapa)
        has_int_id = "id" in t.c and t.c["id"].type.python_type is int
        keep = []
        for r in src:
            if spec.get("user") and r.get(spec["user"]) in banned:
                skip(tname, "persona suprimida en el destino")
                continue
            if tname == "users" and r["id"] in banned:
                continue
            if tname == "event_documents" and ("event_doc", r.get("stored_path")) not in file_by_ref:
                skip(tname, "su archivo no viajó")
                continue
            keep.append(r)
        ids = _alloc_ids(db, tname, len(keep)) if has_int_id else []
        if has_int_id:
            new_ids[tname] = {r["id"]: ids[i] for i, r in enumerate(keep)}
        # valores únicos que se conservan si están libres
        taken = {}
        for col in spec.get("unique", {}):
            taken[col] = _existing(db, tname, col, [r.get(col) for r in keep])
        if tname == "audit_consent_logs":
            already = _existing(db, tname, "id", [r["id"] for r in keep])
        users_existing = {}
        if tname == "users":
            have = db.execute(select(m.User).where(m.User.tenant_id == tenant_id, m.User.id.in_([r["id"] for r in keep] or [""]))).scalars().all()
            users_existing = {u.id: u for u in have}

        for i, r in enumerate(keep):
            if tname == "users":
                u = users_existing.get(r["id"])
                if u is not None:
                    report["persons"]["existing_kept"] += 1
                    if any((getattr(u, c) or None) != (r.get(c) or None) for c in ("first_name", "last_name", "entity", "phone", "email", "opt_1", "opt_2", "extra_fields")):
                        report["persons"]["existing_different"] += 1
                    continue
                d = {k: _parse(t.c[k], v) for k, v in _clean_user_row(r).items() if k in t.c}
                d["is_biometric_enabled"] = False
                d["tenant_id"] = tenant_id
                b = bio.get(r["id"])
                if b:                                                   # la clave de este entorno vuelve a cifrar el vector al insertarlo (EncryptedText)
                    d["face_encoding"] = b.get("face_encoding")
                    d["face_captured_at"] = _parse(t.c["face_captured_at"], b.get("face_captured_at"))
                    d["biometric_consent_at"] = _parse(t.c["biometric_consent_at"], b.get("biometric_consent_at"))
                    d["biometric_consent_source"] = b.get("biometric_consent_source")
                    d["is_biometric_enabled"] = bool(b.get("is_biometric_enabled"))
                    report["biometrics"]["imported"] += 1
                    biometric_new.add(r["id"])
                for c in ("face_encoding", "face_captured_at", "biometric_consent_at", "biometric_consent_source"):
                    d.setdefault(c, None)                          # executemany pide las mismas columnas en todas las filas
                report["persons"]["new"] += 1
                out.append(d)
                continue
            d = {k: _parse(t.c[k], v) for k, v in r.items() if k in t.c}
            if has_int_id:
                d["id"] = ids[i]
            if "tenant_id" in t.c and d.get("tenant_id") is not None:
                d["tenant_id"] = tenant_id
            drop = False
            for col, target in spec.get("remap", {}).items():
                optional = target.endswith("?")
                target = target.rstrip("?")
                if d.get(col) is None:
                    continue
                mapped = new_ids.get(target, {}).get(r[col])
                if mapped is None:
                    if optional:
                        d[col] = None
                    else:
                        drop = True
                        break
                else:
                    d[col] = mapped
            if drop:
                skip(tname, "depende de una fila que no entró")
                if has_int_id:
                    new_ids[tname].pop(r["id"], None)
                continue
            if "event_id" in t.c:
                d["event_id"] = new_ids["events"][ev_src["id"]]
            for col in spec.get("null", ()):
                d[col] = None
            for col, mode in spec.get("unique", {}).items():
                val = d.get(col)
                if val is not None and val in taken[col]:
                    if mode == "skip":
                        skip(tname, f"«{col}» ya existe en el destino")
                        if has_int_id:
                            new_ids[tname].pop(r["id"], None)
                        drop = True
                        break
                    d[col] = secrets.token_urlsafe(16) if mode == "regen" else None
                    report["warnings"].append(f"{tname}.{col}: un valor ya existía en el destino y se {'generó de nuevo' if mode == 'regen' else 'dejó vacío'}.")
                elif val is not None:
                    taken[col].add(val)
            if drop:
                continue
            if tname == "audit_consent_logs" and r["id"] in already:
                skip(tname, "ya estaba registrado en el destino")
                continue
            for col, val in spec.get("set", {}).items():
                d[col] = val
            for col in ASSET_COLUMNS.get(tname, ()):
                d[col] = _rewrite_assets(d.get(col), tenant_src, tenant_id, assets_map)
            if tname == "web_forms":
                d["test_key"] = secrets.token_urlsafe(12)           # la clave de pruebas nunca se copia
                pending["forms"].append({"id": d["id"], "manual_status": d.get("manual_status"), "use_schedule": d.get("use_schedule")})
                d["manual_status"], d["use_schedule"] = "pruebas", False
            if tname == "event_documents":
                meta = file_by_ref[("event_doc", r["stored_path"])]
                d["stored_path"] = key_of(tenant_id, "event_docs", d["event_id"], uuid.uuid4().hex + os.path.splitext(r["stored_path"])[1].lower())
                writes.append((d["stored_path"], meta["sha256"], "event_doc"))
            if tname == "event_expenses" and r.get("evidence_path"):
                meta = file_by_ref.get(("expense", r["evidence_path"]))
                if meta:
                    d["evidence_path"] = key_of(tenant_id, "event_expenses", d["event_id"], uuid.uuid4().hex + os.path.splitext(r["evidence_path"])[1].lower())
                    writes.append((d["evidence_path"], meta["sha256"], "expense"))
                else:
                    d["evidence_path"] = d["evidence_name"] = None
                    report["warnings"].append("Un comprobante de gasto no viajó con el paquete: el gasto entra sin comprobante.")
            staff_link(r, d, tname, d.get("id") if has_int_id else f"{d.get('tenant_id')}|{d.get('user_id')}|{d.get('event_id')}")
            out.append(d)
        rep["imported"] = len(out)
        _insert(db, tname, out)

    # ---- archivos que dependen de los ids nuevos: respuestas de formularios y firmas (y las fotos biométricas de las personas que entraron con biometría)
    for f in files:
        if f["role"] == "biometric_photo" and bio_key is not None and f["ref"]["name"] in biometric_new:
            writes.append((photo_key(tenant_id, f["ref"]["name"]), f["sha256"], "biometric_photo"))
            continue
        if f["role"] == "form_file":
            new_form = new_ids.get("web_forms", {}).get(f["ref"]["form_id"])
            if new_form is not None:
                writes.append((form_file_key(tenant_id, new_form, f["ref"]["name"]), f["sha256"], "form_file"))
        elif f["role"] == "signature":
            writes.append((key_of(tenant_id, "signatures", new_ids["events"][ev_src["id"]], f["ref"]["name"]), f["sha256"], "signature"))

    if not keep_original_state:
        pending["forms"] = []
    if pending.get("event_status") or pending["forms"]:
        log_row.status = "pending_confirm"
        log_row.state_json = json.dumps({"event_status": pending.get("event_status"), "forms": pending["forms"]})
        report["pending_confirm"] = True
    log_row.counts_json = json.dumps({k: v["imported"] for k, v in report["tables"].items()})
    for tname, ref, col, un in actors:
        db.add(m.EventImportActor(import_id=log_row.id, table_name=tname, row_ref=ref, column_name=col, username=un))
    report["import_id"] = log_row.id
    db.flush()

    # ---- escribir los archivos (solo en la importación de verdad; el simulacro solo los cuenta)
    for _, _, role in writes:
        report["files"]["by_role"][role] = report["files"]["by_role"].get(role, 0) + 1
    report["files"]["planned"] = len(writes)
    written = []
    if not dry_run:
        for key, sha, role in writes:
            raw = opener(sha)
            if role == "biometric_photo":
                try:
                    raw = crypto.encrypt_bytes(bio_key.decrypt(raw))      # sale de la clave de transporte y entra con la de este entorno
                except InvalidToken:
                    raise TransferError("Una foto del paquete no se pudo descifrar: el archivo está dañado o fue modificado.")
            st.put(key, raw)
            written.append(key)
        report["files"]["written"] = len(written)
    return written


def confirm_import(db: Session, import_id: int, staff_username: Optional[str] = None) -> dict:
    """Aplica el estado ORIGINAL que quedó en espera al importar (evento «en proceso» y, si se pidió conservarlo, el de los formularios). Es el único paso que puede activar el congelamiento."""
    row = db.get(m.EventTransferLog, import_id)
    if not row or row.kind != "import" or row.status != "pending_confirm":
        raise TransferError("No hay una importación en espera con ese número.")
    state = json.loads(row.state_json or "{}")
    event = db.get(m.Event, row.event_id)
    if not event:
        raise TransferError("El evento importado ya no existe.")
    if state.get("event_status"):
        event.status = state["event_status"]
    for f in state.get("forms") or []:
        form = db.get(m.WebForm, f["id"])
        if form:
            form.manual_status, form.use_schedule = f.get("manual_status") or "pruebas", bool(f.get("use_schedule"))
    row.status = "confirmed"
    db.commit()
    log.info("event_import_confirm import_id=%s by=%s", import_id, bool(staff_username))
    return {"event_id": event.id, "status": event.status}
