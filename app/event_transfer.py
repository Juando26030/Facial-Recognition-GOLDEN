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
import hashlib
import io
import json
import logging
import os
import secrets
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Numeric, select, text
from sqlalchemy.orm import Session

from app import consent
from app import models as m
from app.timeutil import utcnow

log = logging.getLogger("golden.event_transfer")

FORMAT = "goldenweb-evento"
FORMAT_VERSION = 1
MAX_ZIP_BYTES = int(os.getenv("EVENT_TRANSFER_MAX_ZIP_MB", "512")) * 1024 * 1024
MAX_UNZIPPED_BYTES = MAX_ZIP_BYTES * 4        # lo que de verdad sale al descomprimir (contra «zip bomb»); se cuenta leyendo, no lo que diga el zip
MAX_ENTRIES = 200
CHUNK = 500
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


def export_event(db: Session, event, *, staff_username: Optional[str] = None, include_biometrics: bool = False) -> tuple:
    """Arma el paquete de un evento. Devuelve (bytes del .zip, manifest). Escribe una fila en la bitácora (sin datos personales). `include_biometrics` llega en F3."""
    if include_biometrics:
        raise TransferError("Exportar con biometría todavía no está disponible (fase F3).")
    names = _staff_names(db)
    states = {sid: n for sid, n in db.execute(select(m.EventState.id, m.EventState.name)).all()}
    supers = {sid: n for sid, n in db.execute(select(m.SuperEvent.id, m.SuperEvent.name)).all()}
    ctx = {"people": _person_ids(db, event), "form_ids": [r[0] for r in db.execute(select(m.WebForm.id).where(m.WebForm.event_id == event.id)).all()], "payment_ids": []}
    ctx["payment_ids"] = [r[0] for r in db.execute(select(m.FormPayment.id).where(m.FormPayment.event_id == event.id)).all()] if ctx["form_ids"] else []
    tenant = db.get(m.Tenant, event.tenant_id)
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "alembic_revision": _revision(db), "source_env": os.getenv("DEPLOY_ENV", "").strip().lower() or "local",
                "created_at": utcnow().isoformat(), "tenant": {"id": tenant.id, "client_code": tenant.client_code, "name": tenant.name} if tenant else {"id": event.tenant_id},
                "event": {"event_code": event.event_code, "name": event.name, "status": event.status}, "options": {"include_biometrics": False}, "includes_files": False,
                "tables": {}, "staff_usernames": [], "warnings": []}
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
        if event.logo_path or event.report_pdf_path:
            manifest["warnings"].append("El logo propio y el informe PDF del evento no viajan en esta versión del paquete (llegan con los archivos, F2).")
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
    allowed = {"manifest.json", "LEEME.txt"} | {f"data/{n}.jsonl" for n in TABLE_NAMES}
    if len(infos) > MAX_ENTRIES or any(i.filename not in allowed for i in infos):
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
    return manifest, rows


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
                   keep_original_state: bool = False, dry_run: bool = True) -> dict:
    """Importa un paquete creando un evento NUEVO. `dry_run=True` (por defecto) hace TODO y lo deshace: lista qué entraría y qué conflictos hay. Devuelve el informe."""
    from app.routers.events import EVENT_CODE_RE                     # el mismo formato de código que al crear un evento a mano
    manifest, rows = read_package(data)
    src_event = rows["events"][0]
    report = {"dry_run": dry_run, "event_code": None, "name": None, "event_id": None, "source_env": manifest.get("source_env"), "tables": {}, "skipped": {}, "warnings": list(manifest.get("warnings", [])),
              "conflicts": [], "persons": {"new": 0, "existing_kept": 0, "existing_different": 0, "suppressed_skipped": 0}, "staff_without_link": [], "pending_confirm": False, "package_sha256": _package_hash(manifest)}

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
    if db.query(m.Event.id).filter(m.Event.tenant_id == src_event["tenant_id"], func.lower(func.btrim(m.Event.name)) == name.lower()).first():
        report["conflicts"].append(f"Ya existe un evento con el nombre «{name}» en ese cliente: escribe un nombre nuevo.")
    if report["conflicts"]:
        db.rollback()
        report["ok"] = False
        return report

    try:
        _do_import(db, manifest, rows, report, skip, code=code, name=name, staff_username=staff_username, keep_original_state=keep_original_state)
    except Exception:
        db.rollback()
        raise
    report["ok"] = True
    if dry_run:
        db.rollback()
    else:
        db.commit()
    log.info("event_import dry_run=%s tables=%s", dry_run, {k: v["imported"] for k, v in report["tables"].items()})
    return report


def _do_import(db: Session, manifest: dict, rows: dict, report: dict, skip, *, code: str, name: str, staff_username: Optional[str], keep_original_state: bool) -> None:
    tenant_src = manifest.get("tenant") or {}
    ev_src = rows["events"][0]
    tenant_id = ev_src["tenant_id"]
    # ---- cliente (solo nombre y código si falta)
    if not db.get(m.Tenant, tenant_id):
        client_code = tenant_src.get("client_code") or tenant_id
        if db.query(m.Tenant.id).filter(m.Tenant.client_code == client_code).first():
            raise TransferError("El código de cliente del paquete ya existe en este sistema con otro identificador: crea el cliente a mano y vuelve a importar.")
        db.add(m.Tenant(id=tenant_id, client_code=client_code, name=tenant_src.get("name") or tenant_id))
        db.flush()
        report["warnings"].append("El cliente no existía en el destino: se creó solo con su nombre y código.")
    staff_by_name = {un: sid for sid, un in db.execute(select(m.StaffUser.id, m.StaffUser.username)).all()}
    states = {n: sid for sid, n in db.execute(select(m.EventState.id, m.EventState.name)).all()}
    supers = {n: sid for sid, n in db.execute(select(m.SuperEvent.id, m.SuperEvent.name).where(m.SuperEvent.tenant_id == tenant_id)).all()}
    suppressed = {r[0] for r in db.execute(select(m.SuppressedPerson.cedula_hash).where(m.SuppressedPerson.tenant_id == tenant_id)).all()}
    log_row = m.EventTransferLog(kind="import", staff_username=staff_username, event_code=code, package_sha256=report["package_sha256"], status="done",
                                 options_json=json.dumps({"keep_original_state": keep_original_state, "source_env": manifest.get("source_env")}))
    db.add(log_row)
    db.flush()
    actors = []                                                   # (tabla, referencia de la fila, columna, nombre de usuario sin cuenta aquí)
    new_ids = {}                                                  # tabla → {id origen: id nuevo}
    pending = {"forms": []}

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
    banned = set()
    for r in rows["users"]:
        if consent.cedula_hash(r["id"]) in suppressed:
            banned.add(r["id"])
    report["persons"]["suppressed_skipped"] = len(banned)

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
            d.update({"id": new_id, "event_code": code, "name": name, "faces_version": 0})
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
            d["biometrics_purged_at"] = _parse(t.c["biometrics_purged_at"], ev_src.get("biometrics_purged_at"))
            if not manifest.get("includes_files"):
                if d.get("logo_path"):
                    d["logo_path"] = None
                    if d.get("logo_mode") == "custom":
                        d["logo_mode"] = "default"
                d["report_pdf_path"] = None
                d["report_uploaded_at"] = None
            src_status = d.get("status")
            if src_status == "en_proceso":
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
                report["persons"]["new"] += 1
                out.append(d)
                continue
            d = {k: _parse(t.c[k], v) for k, v in r.items() if k in t.c}
            if has_int_id:
                d["id"] = ids[i]
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
            if tname == "web_forms":
                d["test_key"] = secrets.token_urlsafe(12)           # la clave de pruebas nunca se copia
                pending["forms"].append({"id": d["id"], "manual_status": d.get("manual_status"), "use_schedule": d.get("use_schedule")})
                d["manual_status"], d["use_schedule"] = "pruebas", False
            staff_link(r, d, tname, d.get("id") if has_int_id else f"{d.get('tenant_id')}|{d.get('user_id')}|{d.get('event_id')}")
            out.append(d)
        rep["imported"] = len(out)
        _insert(db, tname, out)

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
