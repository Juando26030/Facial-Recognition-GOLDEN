import contextlib
import os
from datetime import datetime, timedelta
from app.timeutil import utcnow
import re
import json
from typing import List, Optional
import zipfile
import tempfile
import csv
import io
import hashlib
import hmac
import time
import logging
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import UnidentifiedImageError
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Event, EventStaffAuthorization, User, AccessLog, EventAttendee, PersonChange, PrintLog, StaffUser, BulkJob
from app.biometrics import BiometricEngine
from app.reports import ReportManager
from app.auth import ROLE_HIERARCHY, effective_roles, get_current_staff, get_event_for_staff, require_event_in_progress, require_role, require_role_excluding, require_role_or_client
from app import formsvc, status_changes, regtime, roster_append, biometric_setup, bulk_jobs, bulk_steps, crypto, event_rules, faces_version, minors, privacy, roster_columns, security, digital_badge, faces, heavy, legal_texts, uploads, safe_limits
from app import consent as consent_mod
from app.storage import get_storage, photo_key
from app.email_check import check_email
from app.routers import parametros, signatures
from app.routers.super_events import sibling_attendance
from app.routers.events import _typo_match, _words

log = logging.getLogger("golden.api")


SKIP_REQUIRED_TYPES = ("signature", "categories")       # se guardan aparte (archivo por evento / inscripción): no se pueden comprobar con los datos de la persona


def person_missing_required(db: Session, event: Event, user: User) -> list:
    """A3 (26-oct-2026): los campos OBLIGATORIOS del evento que esta persona tiene vacíos ({key, label}), con los mismos valores que comprueba «Editar persona» (update_user). Sirve para
    no acreditar a quien le falta un obligatorio (p. ej. se marcó obligatorio después de cargar la base): el escaneo, la fila y el autoregistro responden MISSING_REQUIRED."""
    field_configs = [c for c in parametros.field_configs_for_event(db, event) if c["field_type"] not in SKIP_REQUIRED_TYPES and not c.get("locked")]
    if not any(c["required"] for c in field_configs):
        return []
    values = {"role": user.role, "entity": user.entity, "phone": user.phone, "email": user.email, "opt_1": user.opt_1, **user.get_extras(),
              "birth_date": user.birth_date.isoformat() if getattr(user, "birth_date", None) else ""}
    attendee = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
    values["certificate"] = "true" if (attendee and attendee.certificate) else ""
    values["digital_contact"] = (attendee.digital_contact if attendee else "") or ""
    labels = set(_missing_required_fields(field_configs, values))
    return [{"key": c["key"], "label": c["label"]} for c in field_configs if c["required"] and c["label"] in labels]


def missing_required_message(missing: list) -> str:
    return ("Falta el campo obligatorio: " if len(missing) == 1 else "Faltan los campos obligatorios: ") + ", ".join(m["label"] for m in missing)


def _missing_required_fields(field_configs: list, values: dict) -> list:
    """Nombres (rótulos) de los campos marcados obligatorios en Parámetros del Evento que no
    vienen con valor en `values` — usado por manual_register y update_user (PATCH) para no dejar
    guardar un perfil incompleto. NO se usa en bulk_register (ver parametros.py, decisión de
    alcance). Un campo booleano "obligatorio" exige estar marcado (true), no solo presente."""
    missing = []
    for cfg in field_configs:
        if not cfg["required"]:
            continue
        value = values.get(cfg["key"])
        if cfg["field_type"] == "boolean":
            # Sí/No/sin elegir (2026-09-23): "obligatorio" = haber respondido, sea Sí o No.
            ok = str(value).strip().lower() in ("true", "false", "1", "0", "si", "sí", "no")
        elif cfg["field_type"] in ("consent", "certificate"):
            ok = str(value).strip().lower() in ("true", "1", "si", "sí")
        else:
            ok = value is not None and str(value).strip() != ""
        if not ok:
            missing.append(cfg["label"])
    return missing


def _invalid_email_fields(field_configs: list, values: dict) -> list:
    """Mensajes de los campos de tipo "correo" (Parámetros del Evento) cuyo valor no es un correo real
    (formato + dominio que recibe correo, ver app/email_check.py). Vacío no se marca acá: eso lo cubre
    "obligatorio" (`_missing_required_fields`)."""
    problems = []
    for cfg in field_configs:
        if cfg["field_type"] != "email":
            continue
        value = str(values.get(cfg["key"]) or "").strip()
        if not value:
            continue
        ok, reason = check_email(value)
        if not ok:
            problems.append(f"{cfg['label']}: «{value}» {reason}")
    return problems


def _cell_text(cell) -> str:
    """Texto de una celda de Excel. Las fechas (datetime/date) se pasan a AAAA-MM-DD —con hora solo si la trae—, así «fecha de nacimiento» (y cualquier otra columna de fechas) llega legible."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.strftime("%Y-%m-%d") if (cell.hour, cell.minute, cell.second) == (0, 0, 0) else cell.isoformat(sep=" ")
    if hasattr(cell, "isoformat") and not isinstance(cell, str):
        return cell.isoformat()
    return str(cell).strip()


def _read_roster_rows(filename: str, content: bytes):
    """Lee un roster en .csv o .xlsx y devuelve (header_columns, rows): filas normalizadas
    (claves en minúscula, sin espacios) sin importar el formato de origen, y un mapeo
    {header: 'A'|'B'|...} de en qué columna venía cada campo — así bulk_register puede señalar
    la celda exacta (ej. "B7") de un error, sea el archivo .xlsx o .csv."""
    filename = (filename or "").lower()
    if filename.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h).strip().lower() if h is not None else "" for h in next(rows_iter, [])]
        header_columns = {h: get_column_letter(i + 1) for i, h in enumerate(headers) if h}
        rows = []
        for row in rows_iter:
            if row is None or all(cell is None for cell in row):
                continue
            rows.append({
                headers[i]: _cell_text(cell)
                for i, cell in enumerate(row) if i < len(headers) and headers[i]
            })
        return header_columns, rows
    else:
        decoded = content.decode("utf-8-sig")
        delimiter = ";" if ";" in decoded.split("\n", 1)[0] else ","
        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
        headers = [h.strip().lower() if h else "" for h in (reader.fieldnames or [])]
        header_columns = {h: get_column_letter(i + 1) for i, h in enumerate(headers) if h}
        rows = [
            {k.strip().lower() if k else "": (v or "").strip() for k, v in row.items() if k}
            for row in reader
        ]
        return header_columns, rows

MAX_OPTIONAL_FIELDS = 30
_OPTIONAL_FIELD_RE = re.compile(r"^opcional[\s_]*([0-9]{1,2})$")


def _normalize_optional_key(raw_key: str):
    """Reconoce cualquier variante de encabezado 'opcional 1'..'opcional 30' (con espacio, guion
    bajo, o pegado — 'opcional1') y la normaliza a la forma canónica 'opcional_N' que usamos para
    guardar en User.extra_fields y Event.optional_field_labels. None si no matchea o el número
    está fuera de rango."""
    if not raw_key:
        return None
    match = _OPTIONAL_FIELD_RE.match(raw_key.strip())
    if not match:
        return None
    n = int(match.group(1))
    return f"opcional_{n}" if 1 <= n <= MAX_OPTIONAL_FIELDS else None


def _optional_field_examples(rows: list, keys) -> dict:
    """Hasta 2 valores no vacíos (sin repetir) de cada campo opcional en `keys`, tal como vienen
    en el archivo — 2026-09-16, pedido explícito, para no tener que abrir el Excel a ver qué es
    'opcional_1'. `rows` ya viene con las claves originales del archivo (no normalizadas), así
    que hay que normalizar cada `raw_key` para saber a cuál "opcional_N" corresponde."""
    examples = {key: [] for key in keys}
    for row in rows:
        if all(len(v) >= 2 for v in examples.values()):
            break
        for raw_key, value in row.items():
            norm = _normalize_optional_key(raw_key)
            if norm not in examples:
                continue
            val = (value or "").strip()
            if val and val not in examples[norm] and len(examples[norm]) < 2:
                examples[norm].append(val)
    return examples


def _parse_extra_fields(raw: str) -> dict:
    """Parsea el JSON de extra_fields que manda el frontend (bulk_register por fila, o
    manual_register para una sola persona) y devuelve solo las claves 'opcional_N' válidas con
    valor no vacío, normalizadas."""
    if not raw:
        return {}
    try:
        provided = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    extras = {}
    for raw_key, value in (provided or {}).items():
        norm = _normalize_optional_key(raw_key)
        val = str(value or "").strip()
        if norm and val:
            extras[norm] = val
    return extras


def _apply_optional_labels(event, used_keys: set, field_labels_raw: str) -> dict:
    """Fusiona field_labels_raw (JSON, ej. {"opcional_1": "Talla de camisa"}) dentro de
    Event.optional_field_labels — cualquier clave de used_keys que quede sin nombre después del
    merge recibe un rótulo por defecto ("Opcional N") para no dejar el diccionario incompleto.
    Compartido por bulk_register (carga de Excel) y manual_register (alta individual) para no
    duplicar el flujo de 'pregúntame a qué corresponde cada opcional'. No hace commit — quien
    llama decide cuándo."""
    existing = event.get_optional_labels()
    merged = dict(existing)
    try:
        provided = json.loads(field_labels_raw) if field_labels_raw else {}
    except (json.JSONDecodeError, TypeError):
        provided = {}
    for raw_key, label in (provided or {}).items():
        norm = _normalize_optional_key(raw_key)
        if norm and label and str(label).strip():
            merged[norm] = str(label).strip()
    for key in used_keys - set(merged.keys()):
        merged[key] = f"Opcional {key.split('_')[1]}"
    event.set_optional_labels(merged)
    return merged


_ID_KEYS = ('id', 'identificación', 'cedula', 'cédula')
_FLOAT_LOOKING_ID_RE = re.compile(r'^(\d+)\.0+$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^[\d\s+()\-]+$')


def _field_lookup(clean_row: dict, header_columns: dict, row_num: int, *keys: str):
    """Busca el primer valor no vacío entre varios encabezados alternativos (ej. 'nombres' o
    'nombre') y devuelve (valor, referencia_de_celda) — ej. ('Juan', 'B7'). Si ninguno tiene
    valor pero al menos uno de esos encabezados sí vino en el archivo, igual devuelve su celda
    (útil para señalar dónde falta el dato); si el archivo ni siquiera trae esa columna, la
    referencia es None y quien llama debe caer de vuelta a "fila N"."""
    for key in keys:
        val = clean_row.get(key, '')
        if val:
            col = header_columns.get(key)
            return val, (f"{col}{row_num}" if col else None)
    for key in keys:
        if key in header_columns:
            return '', f"{header_columns[key]}{row_num}"
    return '', None


def _extract_identificador(clean_row: dict, header_columns: dict, row_num: int):
    """Saca la cédula/ID de la fila (probando los encabezados alternativos de siempre) y de paso
    corrige el problema clásico de Excel de convertir una columna de cédulas en números, que
    entonces llegan como '1020304050.0' en vez de '1020304050'. Devuelve (identificador_limpio,
    celda, nota_o_None) — la nota, si existe, se le muestra al usuario explicando la corrección."""
    raw_val, cell_ref = _field_lookup(clean_row, header_columns, row_num, *_ID_KEYS)
    val = raw_val.strip()
    note = None
    match = _FLOAT_LOOKING_ID_RE.match(val)
    if match:
        corrected = match.group(1)
        where = cell_ref or f"fila {row_num}"
        note = f"ℹ️ Fila {row_num} ({where}): la cédula venía como '{val}' — Excel la convirtió a número. Se corrigió automáticamente a '{corrected}'."
        val = corrected
    return val, cell_ref, note


router = APIRouter()

BIOMETRIC_CONSENT_REQUIRED = "Falta la autorización expresa de la persona para guardar su rostro (dato biométrico sensible, Ley 1581). Si no la da, regístrala por cédula, sin foto."




def _send_digital(db: Session, event: Event, user: User, request: Optional[Request]) -> dict:
    """Envío automático de la escarapela digital (ítem 17) tras guardar a la persona."""
    att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
    result = digital_badge.send_digital_badge(db, event, att, user.first_name or "", str(request.base_url) if request else "", user.last_name or "")
    db.commit()
    return result


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "si", "sí", "x", "yes")


def _send_now(value) -> bool:
    """Casilla «Enviar ahora la escarapela» (2026-09-23): por defecto SÍ. Guardar a una persona ya no reenvía
    el enlace por sí solo; solo se envía si la casilla viene marcada. Ausente (una pantalla vieja en caché) = enviar,
    para no dejar de mandar; el formulario nuevo siempre manda el valor explícito."""
    if value is None:
        return True
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def _upsert_attendee(db: Session, event_id: int, user_id: str, tenant_id: str, categories: Optional[list] = None, certificate: Optional[bool] = None, digital_contact: Optional[str] = None, origin: Optional[str] = "manual", touch: bool = False) -> None:
    """Asegura que esta persona quede en la lista del evento, se haya precargado o no (ej. un
    'Nuevo' dado de alta sobre la marcha el día del evento) — ver EventAttendee en models.py.
    `categories` (ítem 14): si viene, fija las categorías de la persona EN este evento.
    `touch=True` (cola compartida): es una alta o una acreditación; marca `last_action_at` con la hora del SERVIDOR (nunca la del dispositivo)."""
    row = db.query(EventAttendee).filter_by(event_id=event_id, user_id=user_id).first()
    if not row:
        row = EventAttendee(event_id=event_id, user_id=user_id, tenant_id=tenant_id, origin=origin)       # B1: el origen se asigna al CREAR y nunca cambia con el estado
        db.add(row)
    if touch:
        row.last_action_at = utcnow()
    if categories is not None:
        row.set_categories(categories)
    if certificate is not None:
        row.certificate = certificate  # ítem 5: ¿le corresponde certificado en este evento?
    if digital_contact is not None:
        row.digital_contact = digital_contact or None  # ítem 17: '' lo borra


ROSTER_MAX_ROWS = int(os.getenv("ROSTER_MAX_ROWS", "20000"))      # filas por archivo de la carga masiva
class _RetryRowByRow(SQLAlchemyError):
    """Una fila falló dentro de un lote (sin SAVEPOINT propio): el lote se deshace y se repite fila por fila."""


class _Phases:
    """Tiempos por fase de una carga (sin datos personales): milisegundos de reloj y de CPU por fase y por cada lote de filas; se anota UNA línea JSON al terminar (orden del 24-oct-2026)."""

    def __init__(self):
        self.t = time.perf_counter()
        self.cpu = time.process_time()
        self.ms, self.cpu_ms, self.chunks = {}, {}, []

    def mark(self, name: str) -> None:
        now, cpu = time.perf_counter(), time.process_time()
        self.ms[name] = round(self.ms.get(name, 0) + (now - self.t) * 1000)
        self.cpu_ms[name] = round(self.cpu_ms.get(name, 0) + (cpu - self.cpu) * 1000)
        self.t, self.cpu = now, cpu

    def lap(self) -> None:
        now = time.perf_counter()
        self.chunks.append(round((now - self.t) * 1000))
        self.mark("filas")

    def emit(self, rows: int, queries: Optional[int] = None) -> None:
        log.info("carga masiva: fases " + json.dumps({"filas": rows, "ms": self.ms, "cpu_ms": self.cpu_ms, "ms_por_lote": self.chunks}))


_PHOTO_LISTING_AFTER = 8      # tras tantas consultas de «¿tiene foto?» una por una, se lista la carpeta de fotos del cliente UNA vez (en la nube cada consulta es una petición a Cloud Storage)
_BULK_CHUNK = 500             # filas por lote al guardar la carga masiva
_LOOKUP_CHUNK = 2000          # cédulas por consulta al traer lo que ya existe


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _upsert_attendee_cached(db: Session, event_id: int, user_id: str, tenant_id: str, cache: dict, created: list, categories: Optional[list] = None, certificate: Optional[bool] = None) -> None:
    """Igual que `_upsert_attendee`, pero sin consultar la base: la inscripción sale de `cache` (traída de una vez al empezar la carga) y la nueva se agrega a él."""
    row = cache.get(user_id)
    if row is None:
        row = EventAttendee(event_id=event_id, user_id=user_id, tenant_id=tenant_id, origin="base")       # B1: carga masiva = «Base (Excel)»
        db.add(row)
        cache[user_id] = row
        created.append(user_id)
    if categories is not None:
        row.set_categories(categories)
    if certificate is not None:
        row.certificate = certificate


def _clean_categories(event: Event, raw, auto_add: bool = False) -> list:
    """Categorías (ítem 14) de `raw` (lista o texto separado por , ; |) que existen en el evento,
    con la escritura oficial del evento. `auto_add=True` (carga de roster) agrega al evento las
    que no existían todavía, para que importar un Excel con categorías nuevas no las pierda."""
    if isinstance(raw, str):
        raw = re.split(r"[,;|]", raw)
    known = event.get_categories()
    by_lower = {c.lower(): c for c in known}
    result = []
    for name in (str(x).strip() for x in (raw or [])):
        if not name:
            continue
        canonical = by_lower.get(name.lower())
        if not canonical and auto_add:
            canonical = name
            known.append(name)
            by_lower[name.lower()] = name
        if canonical and canonical not in result:
            result.append(canonical)
    if auto_add:
        event.set_categories(known)
    return result


def _already_checked_in(db: Session, event_id: int, user_id: str) -> bool:
    """True si esta persona ya tiene al menos un AccessLog de ACREDITACIÓN real para ESTE evento
    — o sea, ya se acreditó por cualquier método (facial, cédula o alta manual). Excluye
    "Actualizado" (2026-09-17, mismo bug de fondo que el de get_all_users: ese record_type es solo
    una edición de perfil vía update_user, no una acreditación — contarlo acá haría que alguien
    que nunca se presentó, pero cuyo perfil ya se editó una vez, disparara el aviso de "ya
    registrado" en su primer check-in real, cuando en realidad es el primero)."""
    return db.query(AccessLog).filter(
        AccessLog.event_id == event_id, AccessLog.user_id == user_id, AccessLog.record_type != "Actualizado"
    ).first() is not None


def _duplicate_warning(db: Session, event_id: int, user: "User") -> dict:
    # times_registered (2026-09-16, pedido explícito): cuántas veces YA se acreditó esta persona
    # en este evento, para que el mensaje diga "ya se registró N veces" en vez de un genérico
    # "ya está registrada" — el operador decide con ese dato de más. Excluye "Actualizado"
    # (2026-09-17, mismo bug de fondo que _already_checked_in/get_all_users): son ediciones de
    # perfil, no acreditaciones — contarlas inflaría el número mostrado sin motivo real.
    times_registered = db.query(AccessLog).filter(
        AccessLog.event_id == event_id, AccessLog.user_id == user.id, AccessLog.record_type != "Actualizado"
    ).count()
    return {
        "result": "DUPLICADO", "details": "Esta persona ya había sido registrada en este evento",
        "times_registered": times_registered,
        "data": {
            "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
            "role": user.role, "entity": user.entity, "phone": user.phone,
            "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
        },
    }


def _directory_etag(db: Session, event_id: int, tenant_id: str, extra: str = "") -> str:
    """Huella barata del directorio de un evento: cuantos asistentes/registros hay, el ultimo id y la ultima transaccion que toco alguna de esas filas
    (`xmin` de Postgres). Cambia con CUALQUIER alta, baja o edicion, asi que un directorio que no cambio se responde con 304 sin construirlo."""
    att = db.execute(text("SELECT count(*), coalesce(max(id), 0), coalesce(max(xmin::text::bigint), 0) FROM event_attendees WHERE event_id = :e"), {"e": event_id}).one()
    logs = db.execute(text("SELECT count(*), coalesce(max(id), 0), coalesce(max(xmin::text::bigint), 0) FROM access_logs WHERE event_id = :e"), {"e": event_id}).one()
    usr = db.execute(text(
        "SELECT coalesce(max(u.xmin::text::bigint), 0) FROM users u WHERE u.tenant_id = :t AND u.id IN "
        "(SELECT user_id FROM event_attendees WHERE event_id = :e UNION SELECT user_id FROM access_logs WHERE event_id = :e)"), {"t": tenant_id, "e": event_id}).scalar()
    return hashlib.md5(f"{tuple(att)}|{tuple(logs)}|{usr}|{extra}".encode()).hexdigest()[:20]


def _masked_directory_id(tenant_id: str, user_id: str) -> str:
    """E4: identificador de fila para el rol `cliente` (solo lectura): últimas 3 cifras + huella HMAC corta. Estable y único (el navegador lo usa para no repetir filas), pero no es la cédula."""
    import hashlib
    import hmac

    from app.secretkey import secret_key
    tag = hmac.new(secret_key().encode(), f"dir|{tenant_id}|{user_id}".encode(), hashlib.sha256).hexdigest()[:8]
    return f"***{str(user_id)[-3:]}-{tag}"


def _directory_rows(db: Session, event: Event, limit: Optional[int] = None, offset: int = 0, changed_since: Optional[tuple] = None, only_ids: Optional[list] = None, mask: bool = False) -> list:
    """Filas del directorio (roster precargado + quien se presento). Un asistente no reconocido como registrado queda «No registrado»; «Actualizado» es una
    edicion de perfil, no una acreditacion (ver update_user). Sin `face_encoding` (columna diferida): no se descifra nada.
    `mask=True` (rol `cliente`, E4): sin cédula completa, correo, teléfono, fecha de nacimiento, contacto digital ni campos opcionales; solo nombre, entidad, categorías y estado."""
    event_id = event.id
    attendee_ids = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event_id)
    log_ids = db.query(AccessLog.user_id).filter(AccessLog.event_id == event_id)
    query = db.query(User).filter(User.tenant_id == event.tenant_id, or_(User.id.in_(attendee_ids), User.id.in_(log_ids)))
    if changed_since is not None:          # incremental: solo quien tuvo un registro o entro al evento despues del cursor
        since_log, since_att = changed_since
        touched = db.query(AccessLog.user_id).filter(AccessLog.event_id == event_id, AccessLog.id > since_log).union(
            db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event_id, EventAttendee.id > since_att))
        query = query.filter(User.id.in_(touched))
    if only_ids is not None:               # p. ej. el registro de un candidato del reconocimiento facial
        query = query.filter(User.id.in_(only_ids))
    if limit is not None:
        query = query.order_by(User.id).offset(offset).limit(limit)
    users = query.all()
    if not users:
        return []
    ids = [u.id for u in users] if (limit is not None or changed_since is not None or only_ids is not None) else None
    att_q = db.query(EventAttendee).filter(EventAttendee.event_id == event_id)
    log_q = db.query(AccessLog.user_id, func.count(AccessLog.id).filter(AccessLog.record_type != "Actualizado"),
                     func.count(AccessLog.id).filter(AccessLog.record_type == "Nuevo")).filter(AccessLog.event_id == event_id)
    if ids is not None:
        att_q, log_q = att_q.filter(EventAttendee.user_id.in_(ids)), log_q.filter(AccessLog.user_id.in_(ids))
    attendees = {a.user_id: a for a in att_q}
    counts = {uid: (real, new) for uid, real, new in log_q.group_by(AccessLog.user_id)}

    result = []
    for u in users:
        real, new = counts.get(u.id, (0, 0))
        att = attendees.get(u.id)
        status = "No registrado" if not real else ("Nuevo" if new else "Registrado")
        recent_at = (att.last_action_at.isoformat() + "Z") if att is not None and att.last_action_at else None      # cola compartida: hora del SERVIDOR de la última alta/acreditación (UTC)
        origin = (att.origin if att is not None and att.origin else ("manual" if new else "desconocido"))      # B1: origen aparte del estado
        if mask:
            result.append({
                "id": _masked_directory_id(event.tenant_id, u.id), "first_name": u.first_name, "last_name": u.last_name, "role": u.role, "entity": u.entity,
                "phone": "", "email": "", "opt_1": u.opt_1, "opt_2": None, "status": status, "origin": origin, "birth_date": "", "extra_fields": {},
                "categories": att.get_categories() if att else [], "certificate": bool(att.certificate) if att else False, "digital_contact": "", "digital_sent_at": None, "masked": True, "recent_at": recent_at,
            })
            continue
        result.append({
            "id": u.id, "first_name": u.first_name, "last_name": u.last_name,
            "role": u.role, "entity": u.entity, "phone": u.phone,
            "email": u.email, "opt_1": u.opt_1, "opt_2": u.opt_2, "status": status, "origin": origin,
            "birth_date": u.birth_date.isoformat() if (u.birth_date and event.facial_enabled) else "",
            # 2026-09-16: el modal de "Editar" del Directorio necesita los opcionales de esta persona.
            "extra_fields": u.get_extras(),
            "categories": att.get_categories() if att else [],
            "certificate": bool(att.certificate) if att else False,
            "digital_contact": (att.digital_contact or "") if att else "",
            "digital_sent_at": att.digital_sent_at.isoformat() if att and att.digital_sent_at else None,
            "recent_at": recent_at,
        })
    return result


@router.get("/users")
def get_all_users(
    event_id: int, request: Request, limit: Optional[int] = None, offset: int = 0,
    db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff),
):
    """Cualquier staff autenticado con acceso al evento puede VER el directorio (digitador y
    cliente incluidos) — get_event_for_staff abajo hace el chequeo real de autorizacion.
    El directorio es de ESTE evento: roster precargado (EventAttendee) unido con quien de hecho
    se presento (AccessLog filtrado por event_id).

    Fase 0 de escalabilidad: (1) `ETag` + `If-None-Match`: si nada cambio se responde 304 sin construir la lista; (2) `limit`/`offset` opcionales para
    paginar (sin ellos devuelve todo, como siempre; con ellos, ordenado por cedula y con el total en `X-Total-Count`); (3) la respuesta va comprimida (gzip)."""
    event = get_event_for_staff(event_id, db, staff)
    headers = {"Cache-Control": "private, no-cache"}
    masked = staff.role == "cliente"          # E4: el cliente recibe otra versión del directorio: no comparte la huella (ni la caché del navegador) con el personal
    etag = f'"{_directory_etag(db, event.id, event.tenant_id, f"{limit}:{offset}:{int(masked)}")}"'
    headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    rows = _directory_rows(db, event, limit=limit, offset=max(0, offset), mask=masked)
    if limit is not None:
        headers["X-Total-Count"] = str(_directory_total(db, event))
    return JSONResponse(rows, headers=headers)


def _directory_total(db: Session, event: Event) -> int:
    attendee_ids = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)
    log_ids = db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id)
    return db.query(func.count(User.id)).filter(User.tenant_id == event.tenant_id, or_(User.id.in_(attendee_ids), User.id.in_(log_ids))).scalar() or 0


@router.get("/users/changes")
def get_directory_changes(
    event_id: int, cursor: str = "0:0", db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff),
):
    """Directorio INCREMENTAL: solo las personas que tuvieron un registro nuevo (o entraron al evento) despues de `cursor` ("<ultimo log>:<ultimo asistente>",
    el que devolvio la llamada anterior; "0:0" = todo). Devuelve `total` para que el cliente detecte lo que este metodo no ve (bajas, estados revertidos):
    si su cuenta no coincide, pide la lista completa."""
    event = get_event_for_staff(event_id, db, staff)
    try:
        since_log, since_att = (int(x) for x in cursor.split(":"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Cursor invalido")
    last_log = db.query(func.coalesce(func.max(AccessLog.id), 0)).filter(AccessLog.event_id == event.id).scalar()
    last_att = db.query(func.coalesce(func.max(EventAttendee.id), 0)).filter(EventAttendee.event_id == event.id).scalar()
    rows = _directory_rows(db, event, changed_since=(since_log, since_att), mask=staff.role == "cliente")
    return {"cursor": f"{last_log}:{last_att}", "total": _directory_total(db, event), "users": rows}


@router.get("/email-validate")
def email_validate(email: str, staff: StaffUser = Depends(require_role("digitador"))):
    """¿Es un correo real (formato + dominio que recibe correo)? Lo usa el formulario al salir del campo,
    para avisar ANTES de guardar; el guardado lo vuelve a comprobar del lado del servidor."""
    ok, reason = check_email(email)
    return {"valid": ok, "reason": reason}


@router.get("/email-check")
def email_check(
    event_id: int, email: str, exclude_id: str = "", db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    """Aviso de correo ya existente (reunión 2026-09-21, ítem 20) — SOLO lectura: dice si otra
    persona de este cliente (las personas viven a nivel de tenant) ya tiene ese correo, para que
    quien digita lo vea ANTES de guardar. No bloquea nada. `exclude_id` = la propia persona al
    editar, para que su propio correo no cuente como duplicado."""
    event = get_event_for_staff(event_id, db, staff)
    wanted = email.strip().lower()
    if not wanted:
        return {"exists": False, "matches": []}
    query = db.query(User).filter(User.tenant_id == event.tenant_id, func.lower(User.email) == wanted)
    if exclude_id:
        query = query.filter(User.id != exclude_id)
    matches = [{"id": u.id, "name": f"{u.first_name or ''} {u.last_name or ''}".strip()} for u in query.limit(5).all()]
    return {"exists": bool(matches), "matches": matches}


def _mask_id(uid: str) -> str:
    """Cédula parcial para las listas de candidatos: solo las últimas 4 cifras."""
    return "***" + uid[-4:] if len(uid) > 4 else "***"


def _candidate_views(db: Session, event: Event, ranked: list, start: int = 0, masked: bool = True) -> list:
    """Vista legible de los candidatos `ranked[start:]` del MISMO cálculo del reconocimiento (sin tocar el rostro ni la foto): nombre, cédula (parcial si `masked`),
    categoría, estado de registro, distancia y confianza en palabras. `index` es la posición en el token: con ella se pide la foto o el registro (nunca se expone
    una cédula completa que el cliente pueda usar para pedir fotos de cualquiera)."""
    picked = list(enumerate(ranked))[start:]
    if not picked:
        return []
    ids = [uid for _, (uid, _d) in picked]
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids))}
    cats = {a.user_id: a.get_categories() for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(ids))}
    registered = {r[0] for r in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.user_id.in_(ids), AccessLog.record_type != "Actualizado").distinct()}
    views = []
    for i, (uid, dist) in picked:
        u = users.get(uid)
        if u is None:
            continue
        views.append({
            "index": i, "id": _mask_id(uid) if masked else uid, "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
            "categories": cats.get(uid, []), "registered": uid in registered,
            "distance": round(dist, 2), "confidence": faces.confidence(dist), "within_tolerance": dist < faces.FACE_TOLERANCE,
        })
    return views


def _private_json(payload: dict) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})       # nombres y fotos de personas: nunca a la caché


@router.post("/recognize")
def recognize(
    event_id: int = Form(...), file: Optional[UploadFile] = File(None), match_token: str = Form(""), force: bool = Form(False),
    confirm: bool = Form(False), click_token: str = Form(""),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """Sprint 2.2 Fase B (2026-09-16): un match facial YA NO acredita solo por defecto — antes
    creaba el AccessLog apenas encontraba la cara, sin que el digitador confirmara nada. Ahora,
    salvo que `Event.auto_register` este prendido (switch por evento) o venga `confirm=true` (el
    digitador ya confirmo en el modal "Guardar y autorizar acceso"), un match devuelve
    `result: "MATCH_PENDING"` con los datos de la persona SIN crear ningun log todavia.
    El flujo DUPLICADO/force sigue exactamente igual, se evalua ANTES de este chequeo nuevo.

    Fase 0 de escalabilidad: cada persona se reconoce UNA vez. La respuesta MATCH_PENDING/DUPLICADO trae un `match_token` (firmado, vale ~5 minutos, solo
    para este evento y este operador); para confirmar o forzar se manda ese token en vez de reenviar la foto y repetir el calculo facial.

    Verificacion del operador (docs/14 §6.3): el token lleva tambien los 6 candidatos mas cercanos del MISMO calculo (`/recognize/candidates|photo|person`).
    **DUDOSO**: si el mejor y el segundo candidato distan menos de MATCH_MARGIN (0,06 por defecto) el resultado es `result: "DUDOSO"` con los candidatos y NUNCA
    se registra solo, ni con autoregistro ni con `confirm`: el operador elige a la persona (el registro se confirma desde su ficha)."""
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    if match_token:
        payload = faces.read_match_payload(match_token, event.id, staff.id)
        user = db.get(User, (payload["u"], event.tenant_id)) if payload else None
        if not user:
            raise HTTPException(status_code=400, detail="La coincidencia venció. Escanea de nuevo.")
        ranked, doubtful = [(uid, dist) for uid, dist in payload["c"]], bool(payload["d"])
    else:
        if file is None:
            raise HTTPException(status_code=422, detail="Falta la foto")
        click = faces.read_click_token(click_token, event.id, staff.id) if (click_token and event.precalculo_autorizado) else None      # camino 2: UN clic válido de este quiosco
        try:
            status, ranked = faces.recognize(db, event, file.file.read(), ungated=bool(click))
        except faces.Busy:
            raise HTTPException(status_code=503, detail="Hay muchos escaneos en cola. Intenta de nuevo en unos segundos.", headers={"Retry-After": "3"})
        except UnidentifiedImageError:
            raise HTTPException(status_code=400, detail="La imagen no es válida")
        if status == "NO_FACE":
            return {"result": "NO", "details": "Rostro no detectado"}
        if status == "NO_MATCH":
            return {"result": "NO", "details": NOT_FOUND_FACE}
        user = db.get(User, (ranked[0][0], event.tenant_id))
        if not user:
            return {"result": "NO", "details": NOT_FOUND_FACE}
        doubtful = faces.is_doubtful(ranked)
        if click and not doubtful and not consent_mod.has_acceptance(db, event.tenant_id, user.id, event.id):
            # Coincidencia con un clic válido: AHORA sí consta la aceptación de la persona identificada (hora del clic, hash del texto exhibido). Sin coincidencia no se atribuye nada a nadie.
            consent_mod.record(db, tenant_id=event.tenant_id, user_id=user.id, event_id=event.id, version=click["v"], legal_text_hash=click["h"], accepted=True, adult=True, reason="consent",
                               device=f"staff:{staff.id}", at=datetime.fromisoformat(click["t"]))
            db.commit()

    token = faces.make_match_token(event.id, staff.id, user.id, ranked, doubtful)
    if doubtful:
        return _private_json({"result": "DUDOSO", "details": "Coincidencia dudosa: hay varias personas casi igual de parecidas. Verifica cuál es.", "match_token": token,
                              "candidates": _candidate_views(db, event, ranked)})
    principal = _candidate_views(db, event, ranked[:1], masked=False)
    extra = {"match_token": token, "match": principal[0] if principal else None, "has_candidates": len(ranked) > 1}
    if not force and _already_checked_in(db, event.id, user.id):
        return _private_json({**_duplicate_warning(db, event.id, user), **extra})
    data = {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "entity": user.entity, "phone": user.phone,
        "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
    }
    if not event.auto_register and not confirm:
        return _private_json({"result": "MATCH_PENDING", "data": data, **extra})
    missing = person_missing_required(db, event, user)
    if missing:                                         # A3: reconocida, pero no se acredita hasta completar el obligatorio
        return _private_json({"result": "MISSING_REQUIRED", "data": data, "missing": missing, "details": missing_required_message(missing), **extra})
    log = AccessLog(
        tenant_id=event.tenant_id, user_id=user.id, record_type="Existente",
        event_id=event.id, registered_by_staff_id=staff.id,
        registration_method="biometrico",  # Fase 16: este endpoint es SIEMPRE reconocimiento facial
    )
    db.add(log)
    _upsert_attendee(db, event.id, user.id, event.tenant_id, touch=True)
    db.commit()
    return _private_json({"result": "SÍ", "data": data, **extra})


def _recognition_from_token(db: Session, event_id: int, match_token: str, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    payload = faces.read_match_payload(match_token, event.id, staff.id)
    if not payload:
        raise HTTPException(status_code=400, detail="La coincidencia venció. Escanea de nuevo.")
    return event, [(uid, dist) for uid, dist in payload["c"]]


@router.post("/recognize/candidates")
def recognize_candidates(event_id: int = Form(...), match_token: str = Form(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """«Ver 5 más cercanos»: los candidatos siguientes del MISMO reconocimiento (los guarda el token: no se recalcula el rostro ni se reenvía la foto).
    Cédula parcial; los que quedan fuera de la tolerancia van marcados. Las fotos se piden aparte, una a una, solo cuando el operador abre la lista."""
    event, ranked = _recognition_from_token(db, event_id, match_token, staff)
    return _private_json({"candidates": _candidate_views(db, event, ranked, start=1)})


@router.post("/recognize/photo")
def recognize_photo(event_id: int = Form(...), match_token: str = Form(...), index: int = Form(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """Foto de registro de un candidato del reconocimiento (`index` 0 = la persona principal). Solo las personas que están en el token de ESTE operador y ESTE
    evento (no sirve para pedir la foto de cualquiera), `Cache-Control: private, no-store`, y la ruta no lleva cédulas (POST con token en el cuerpo)."""
    event, ranked = _recognition_from_token(db, event_id, match_token, staff)
    if not 0 <= index < len(ranked):
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    key = photo_key(event.tenant_id, ranked[index][0])
    content = crypto.read_bytes(key) if get_storage().exists(key) else None       # la foto puede estar cifrada en reposo
    if content is None:
        raise HTTPException(status_code=404, detail="Esta persona no tiene foto registrada")
    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/recognize/person")
def recognize_person(event_id: int = Form(...), match_token: str = Form(...), index: int = Form(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """El registro (fila del directorio) del candidato elegido, para abrir el modal «Editar»: desde ahí se corrigen datos o se confirma el ingreso de ESA persona."""
    event, ranked = _recognition_from_token(db, event_id, match_token, staff)
    if not 0 <= index < len(ranked):
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    rows = _directory_rows(db, event, only_ids=[ranked[index][0]])
    if not rows:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    return _private_json(rows[0])


def _identity_name_matches(db_name: str, scanned_name: str) -> bool:
    """Fuzzy-match de identidad (2026-09-16, Sprint 2.4 Fase 3 — corrección real) — distinto de
    `_matches_by_word_prefix` (que exige que TODAS las palabras de lo que se busca prefijen algo
    en el texto largo, pensado para búsquedas tipo "escribo un pedazo del nombre de un evento").
    Acá el caso real es al revés y en ambas direcciones a la vez: la base puede tener el nombre
    abreviado y lo escaneado el nombre completo real (`JHOAN SEBASTIAN ANGARITA ROJAS` escaneado
    vs. `Sebas Angarita` en la base), o viceversa (`Sebas Angarita` escaneado vs. `Sebastián
    Angarita` en la base, el caso original). Por eso se exige que CADA palabra del nombre en BASE
    (el lado casi siempre más corto/abreviado) tenga alguna palabra en lo escaneado que la
    prefije O que sea prefijada por ella — no al revés, y no en una sola dirección."""
    db_words = _words(db_name)
    scanned_words = _words(scanned_name)
    if not db_words or not scanned_words:
        return False
    # Ítem 2 (reunión 2026-09-21): además del prefijo en ambas direcciones, tolera errores de
    # tipeo ("Yuliana" en base vs "Juliana" escaneado) — ver `_typo_match`.
    return all(
        any(sw.startswith(dw) or dw.startswith(sw) or _typo_match(dw, sw) for sw in scanned_words)
        for dw in db_words
    )


@router.post("/checkin-cedula")
def checkin_cedula(
    event_id: int = Form(...), cedula: str = Form(...), force: bool = Form(False), confirm: bool = Form(False),
    first_name: str = Form(""), last_name: str = Form(""), method: str = Form(""), client_id: str = Form(""), took_ms: str = Form(""), ui_flow: str = Form(""),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """Acreditación por cédula (lector de código de barras o MRZ de la cédula nueva) — mismo
    shape de respuesta que /recognize (result + data), para reusar el mismo patrón de frontend.
    Si la persona ya es conocida en el tenant (estuviera o no precargada para este evento
    puntual), se acredita directo como 'Existente' y de paso queda asociada a este evento. Si ya
    tiene un AccessLog para este evento, se avisa (result: DUPLICADO) en vez de acreditar de
    nuevo, salvo que venga force=true (el operador ya confirmó que sí quiere repetirlo).

    Sprint 2.4, Fase 2/3 (2026-09-16, pedido explícito, corregido en la Fase 3): un match EXACTO
    por cédula SIEMPRE deja la fila filtrada/visible en el Directorio en Vivo, sin modal — pero
    solo ACREDITA de una vez (crea el AccessLog, la fila sale "verde") si `Event.auto_register`
    está prendido. Si está apagado, se devuelve `result: "FOUND_PENDING"` — la persona queda
    visible pero SIN acreditar (blanco/"No registrado"), y el frontend ofrece un botón puntual
    "Acreditar" en esa fila para confirmar con un clic (reintenta esta misma petición con
    `confirm=true`) — sin volver a un modal flotante aparte. El reconocimiento facial
    (`/recognize`) sigue con su propio flujo de confirmación, sin cambios, no es parte de esto.

    Si NO hay match exacto por cédula, ya NO se ofrece alta manual automática — se intenta un
    fallback por nombre (`first_name`/`last_name`, cuando el frontend los tiene: vienen del CSV
    de la cédula vieja o del OCR de la MRZ de la nueva) contra TODOS los `User` de este tenant,
    con `_identity_name_matches` (ver arriba — bidireccional, no `_matches_by_word_prefix`) — se
    devuelven como candidatos (`name_matches`), NINGUNO se acredita solo, es el operador quien
    decide desde el Directorio filtrado. Sin nombre (cédula suelta sin match), no hay con qué
    intentar el fallback."""
    cedula = cedula.strip()
    client_id = client_id.strip()[:64]
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    if client_id:
        replay = _replayed_checkin(db, event, client_id)
        if replay:
            return replay

    user = db.query(User).filter(User.id == cedula, User.tenant_id == event.tenant_id).first()
    if not user:
        full_name = f"{first_name} {last_name}".strip()
        name_matches = []
        if full_name:
            candidates = db.query(User).filter(User.tenant_id == event.tenant_id).all()
            for candidate in candidates:
                db_name = f"{candidate.first_name or ''} {candidate.last_name or ''}"
                if _identity_name_matches(db_name, full_name):
                    name_matches.append({"id": candidate.id, "first_name": candidate.first_name, "last_name": candidate.last_name})
        return {"result": "NO_MATCH", "details": "Cédula no encontrada", "name_matches": name_matches}

    if not force and _already_checked_in(db, event.id, user.id):
        return _duplicate_warning(db, event.id, user)

    data = {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "entity": user.entity, "phone": user.phone,
        "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
    }
    # Superevento (ítem 19): si ya asistió a un evento hermano, se avisa. Acá no hay que "capturar de
    # nuevo" nada: la persona ya existe y este flujo solo la vincula/acredita en este evento.
    data["sibling_events"] = [s["event_name"] for s in sibling_attendance(db, event, user.id)]

    if not event.auto_register and not confirm:
        return {"result": "FOUND_PENDING", "data": data}
    missing = person_missing_required(db, event, user)
    if missing:                                         # A3: NO se acredita; la página abre «Editar persona» en el primer campo vacío
        return {"result": "MISSING_REQUIRED", "data": data, "missing": missing, "details": missing_required_message(missing)}

    log = AccessLog(
        tenant_id=event.tenant_id, user_id=user.id, record_type="Existente",
        event_id=event.id, registered_by_staff_id=staff.id,
        # Fase 16 (2026-09-17): "tradicional" = cédula encontrada y confirmada a mano;
        # "autoregistro" = el mismo match, pero acreditado solo porque el evento tiene el switch
        # prendido — misma cédula, la diferencia es si hizo falta que alguien confirmara.
        # "qr" (Sprint 4): el código QR entregó la cédula por la cámara/lector — el mismo flujo, distinto origen.
        registration_method="qr" if method == "qr" else ("autoregistro" if event.auto_register else "tradicional"),
        client_id=client_id or None, **regtime.measured(took_ms, ui_flow),          # 1A: tiempo medido por el quiosco (acotado; ausente o inválido = vacío)
    )
    db.add(log)
    _upsert_attendee(db, event.id, user.id, event.tenant_id, touch=True)
    try:
        db.commit()
    except IntegrityError:        # dos envios con el mismo client_id a la vez: gana uno, el otro recibe el mismo resultado
        db.rollback()
        replay = _replayed_checkin(db, event, client_id) if client_id else None
        if not replay:
            raise
        return replay
    return {"result": "SÍ", "data": data}


ACCREDIT_UNDO_WINDOW = timedelta(seconds=15)          # «Deshacer» una acreditación: solo quien la hizo y hace menos de 15 s (la pantalla ofrece ~8 s; aquí se verifica en el SERVIDOR)


@router.post("/events/{event_id}/accreditations/undo")
def undo_accreditation(event_id: int, body: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """Deshace una acreditación recién hecha con el botón «✅ Acreditar» de la fila (docs/16, 7a). Reglas (decididas por J, 2026-10-05): SOLO quien acreditó (`registered_by_staff_id`), hasta
    `ACCREDIT_UNDO_WINDOW` (15 s) después y con el evento todavía abierto para registrar; se identifica por el `client_id` que generó la pantalla. Borra solo ESE ingreso (la persona vuelve a «No
    registrado» si era el único). Quien necesite deshacer más tarde o lo de otro usa Editar → Estado de registro (administrador o más), como siempre."""
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)
    client_id = str((body or {}).get("client_id") or "").strip()[:64]
    if not client_id:
        raise HTTPException(status_code=400, detail="Falta el identificador de la acreditación")
    log = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.client_id == client_id, AccessLog.record_type != "Actualizado").first()
    if not log:
        raise HTTPException(status_code=404, detail="Esa acreditación no existe (o ya se deshizo)")
    if log.registered_by_staff_id != staff.id:
        raise HTTPException(status_code=403, detail="Solo quien acreditó puede deshacerlo. Pide a un administrador cambiar el estado de registro.")
    if utcnow() - log.timestamp > ACCREDIT_UNDO_WINDOW:
        raise HTTPException(status_code=409, detail="Pasaron más de 15 segundos: ya no se puede deshacer desde aquí. Un administrador puede cambiar el estado en Editar.")
    user_id = log.user_id
    db.delete(log)
    db.commit()
    return {"undone": True, "user_id": user_id}


def _person_data(user: User) -> dict:
    return {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "entity": user.entity, "phone": user.phone,
        "email": user.email, "opt_1": user.opt_1, "opt_2": user.opt_2
    }


def _replayed_checkin(db: Session, event: Event, client_id: str) -> Optional[dict]:
    """Si ese `client_id` ya se registro en este evento, el mismo resultado de la primera vez (sin crear nada): un reintento de red, o la sincronizacion
    del modo contingencia, nunca duplica un ingreso."""
    prev = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.client_id == client_id).first()
    if not prev:
        return None
    user = db.get(User, (prev.user_id, event.tenant_id))
    return {"result": "SÍ", "data": _person_data(user) if user else {"id": prev.user_id}, "replayed": True}


SYNC_MAX_RECORDS = 500
SYNC_MAX_AGE = 30 * 24 * 3600                 # marcas de tiempo aceptadas: hasta 30 días atrás (el quiosco descarta lo que lleve más de 30 días sin sincronizar); más viejas = hora del servidor
SYNC_AFTER_FINISH = timedelta(days=7)         # un digitador puede sincronizar hasta 7 días después de finalizado el evento (coordinador+ siempre puede)
SYNC_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
# método del quiosco -> registration_method (el mismo vocabulario de siempre: «tradicional» = cédula/persona confirmada a mano). `manual` = acreditado desde Editar/la fila sin red.
SYNC_METHODS = {"qr": "qr", "cedula": "tradicional", "manual": "tradicional"}
_ROSTER_MAPS: dict = {}                       # event_id -> (momento, {huella: cédula}); caché por proceso (misma sal que el roster local)
ROSTER_MAP_TTL, ROSTER_MAP_MIN_REBUILD, ROSTER_MAP_MAX_EVENTS = 60.0, 5.0, 20


def _event_for_sync(db: Session, event_id: int, staff: StaffUser) -> Event:
    """Como `get_event_for_staff`, pero un digitador autorizado también puede sincronizar un evento FINALIZADO hasta 7 días después (los ingresos guardados sin red no se pierden por
    haber terminado el evento mientras el quiosco estaba desconectado)."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    if staff.role in ("digitador", "cliente"):
        if not db.query(EventStaffAuthorization).filter_by(event_id=event_id, staff_user_id=staff.id).first():
            raise HTTPException(status_code=403, detail="No estás autorizado para este evento")
        recent = event.status == "finalizado" and event.finalized_at is not None and utcnow() - event.finalized_at <= SYNC_AFTER_FINISH
        reverted = status_changes.revert_info(db, event)          # devuelto a «Creado»: los quioscos sin red sincronizan lo anterior al cambio durante 7 días (app/status_changes.py)
        if event.status != "en_proceso" and not recent and not (reverted and reverted[1]):
            raise HTTPException(status_code=403, detail="Este evento " + ("todavía no ha comenzado" if event.status == "creado" else "finalizó hace más de 7 días"))
    event.sync_revert = status_changes.revert_info(db, event)     # (momento, ventana abierta) o None; atributo de paso, no se guarda
    return event


def _roster_map(db: Session, event: Event, force: bool = False) -> dict:
    """{huella: cédula} de las personas del evento (las mismas del roster local), cacheado por proceso 60 s. `force` reconstruye (alguien se agregó después), pero no antes de 5 s
    desde la última construcción: una huella inventada no puede obligar a recorrer miles de personas en cada registro."""
    now = time.monotonic()
    hit = _ROSTER_MAPS.get(event.id)
    if hit and (now - hit[0] < (ROSTER_MAP_MIN_REBUILD if force else ROSTER_MAP_TTL)):
        return hit[1]
    salt = roster_salt(event)
    attendee_ids = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)
    log_ids = db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id)
    ids = [uid for (uid,) in db.query(User.id).filter(User.tenant_id == event.tenant_id, or_(User.id.in_(attendee_ids), User.id.in_(log_ids)))]
    mapping = {roster_fingerprint(salt, uid): uid for uid in ids}
    if len(_ROSTER_MAPS) >= ROSTER_MAP_MAX_EVENTS and event.id not in _ROSTER_MAPS:
        _ROSTER_MAPS.pop(min(_ROSTER_MAPS, key=lambda k: _ROSTER_MAPS[k][0]), None)
    _ROSTER_MAPS[event.id] = (now, mapping)
    return mapping


@router.get("/ping-auth")
def ping_auth(staff: StaffUser = Depends(get_current_staff)):
    """Sonda LIVIANA autenticada (la usa el quiosco para salir del modo contingencia): 200 = servidor alcanzable y sesión vigente; 401 = sesión vencida. Una sola lectura indexada."""
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


@router.post("/events/{event_id}/access-logs/sync")
def sync_access_logs(
    event_id: int, body: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """Sincronizacion por LOTES de ingresos que un kiosco guardo mientras no tenia conexion (base del modo contingencia, docs/13 §9). Cada registro trae el
    `client_id` que el kiosco genero: repetir el envio (o enviar el mismo lote dos veces) nunca duplica nada. Cuerpo:
    `{"records": [{"client_id", "h" (huella de la cedula, la del roster local) o "cedula" (compatibilidad), "timestamp" (ISO UTC, opcional), "method" ("qr"|"cedula"|"manual", opcional; otro valor = cedula)}]}`
    (maximo 500). Con `h` el servidor resuelve la persona con el mapa de huellas del evento (misma sal que `local-roster`): el quiosco nunca guarda la cedula en claro.
    Cada resultado dice `created` (nuevo), `replayed` (ya estaba), `unknown` (la cedula/huella no existe en ESTE evento) o `invalid`; `review: true` marca a quien ya
    tenia una acreditacion con OTRO client_id (la misma persona entro por dos kioscos durante la desconexion): se registra igual y queda para revision."""
    event = _event_for_sync(db, event_id, staff)
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="Falta la lista de registros")
    if len(records) > SYNC_MAX_RECORDS:
        raise HTTPException(status_code=400, detail=f"Maximo {SYNC_MAX_RECORDS} registros por lote")
    now = utcnow()
    clean = []
    for rec in records:
        rec = rec if isinstance(rec, dict) else {}
        client_id = str(rec.get("client_id") or "").strip()[:64]
        cedula = str(rec.get("cedula") or "").strip()
        h = str(rec.get("h") or "").strip().lower()
        clean.append((rec, client_id, cedula, h if SYNC_HASH_RE.match(h) else ""))
    # Un solo recorrido por tabla para todo el lote (500 registros no son 2.500 consultas): ids ya registrados, personas, quién ya tenía acreditación y quién ya está en la lista del evento.
    known_ids = {cid for (cid,) in db.query(AccessLog.client_id).filter(AccessLog.event_id == event.id, AccessLog.client_id.in_([c[1] for c in clean if c[1]]))}
    rmap = _roster_map(db, event) if any(c[3] and not c[2] for c in clean) else {}
    rebuilt = False
    resolved = []
    for rec, client_id, cedula, h in clean:
        if client_id and client_id not in known_ids and not cedula and h and h not in rmap and not rebuilt:
            rmap, rebuilt = _roster_map(db, event, force=True), True              # una huella desconocida: puede ser alguien agregado después de armar el mapa
        resolved.append(cedula or rmap.get(h, ""))
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_({c for c in resolved if c}))}
    checked = {uid for (uid,) in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado", AccessLog.user_id.in_(list(users)))}
    attendees = {uid for (uid,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(list(users)))}
    results = []
    reverted_at = event.sync_revert[0] if event.sync_revert else None
    for (rec, client_id, cedula, h), person_id in zip(clean, resolved):
        if not client_id or not (cedula or h):
            results.append({"client_id": client_id, "result": "invalid"})
            continue
        if client_id in known_ids:
            results.append({"client_id": client_id, "result": "replayed"})
            continue
        user = users.get(person_id) if person_id else None
        if not user:
            results.append({"client_id": client_id, "result": "unknown"})
            continue
        review = user.id in checked
        verdict, when = status_changes.classify(rec.get("timestamp"), now, reverted_at)
        if verdict == "after":          # hecho DESPUÉS de devolver el evento a «Creado»: no se guarda; el quiosco lo manda a su cola de revisión (como `unknown`)
            results.append({"client_id": client_id, "result": "unknown", "reason": "after_revert"})
            continue
        doubtful = status_changes.DOUBTFUL if verdict == "no_hour" else None
        try:
            with db.begin_nested():
                db.add(AccessLog(tenant_id=event.tenant_id, user_id=user.id, record_type="Existente", event_id=event.id, registered_by_staff_id=staff.id,
                                 registration_method=SYNC_METHODS.get(str(rec.get("method") or ""), "tradicional"), client_id=client_id, timestamp=when, doubtful_reason=doubtful,
                                 **regtime.measured(rec.get("took_ms"), rec.get("ui_flow"))))
                if user.id not in attendees:
                    db.add(EventAttendee(event_id=event.id, user_id=user.id, tenant_id=event.tenant_id, origin="manual", last_action_at=utcnow()))      # cola compartida: la hora en que el SERVIDOR recibe, no la `when` del dispositivo
                else:
                    db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).update({"last_action_at": utcnow()}, synchronize_session=False)
                db.flush()
        except IntegrityError:
            results.append({"client_id": client_id, "result": "replayed"})
            continue
        known_ids.add(client_id)
        checked.add(user.id)
        attendees.add(user.id)
        results.append({"client_id": client_id, "result": "created", **({"review": True} if review else {}), **({"doubtful": True} if doubtful else {})})
    db.commit()
    return {"results": results, "created": sum(r["result"] == "created" for r in results), "review": sum(bool(r.get("review")) for r in results),
            **({"doubtful": sum(bool(r.get("doubtful")) for r in results), "after_revert": sum(r.get("reason") == "after_revert" for r in results)} if reverted_at else {})}


# ----------------------------------------------------------------------------------------------------------------------- bandeja de salida (B8, rebanada R1)
OUTBOX_MAX_OPS = 50
OUTBOX_PERSON_KEYS = ("role", "entity", "phone", "email", "opt_1")


def _outbox_create_person(db: Session, event: Event, staff: StaffUser, op_id: str, f: dict, when, field_configs: list, doubtful: Optional[str] = None) -> dict:
    """Una operación `create_person` de la bandeja de salida de un quiosco que estaba sin red (docs/16, B8 R1): crea a la persona como «alta manual» (mismas reglas que `POST /register`, SIN foto).
    Resultados: `ok` (persona nueva creada y registrada), `existente` (la cédula YA existía: NO se pisan sus datos; solo se registra para este evento y el cliente muestra qué había), `duplicado`
    (ya estaba registrada en este evento: no se hace nada) o `error` (con el motivo, para corregirlo en el dispositivo). Idempotente por `op_id` (= `AccessLog.client_id`)."""
    person_id = str(f.get("id") or "").strip()
    first, last = str(f.get("first_name") or "").strip(), str(f.get("last_name") or "").strip()
    if not person_id or not first or not last:
        return {"op_id": op_id, "result": "error", "detail": "Faltan la cédula, los nombres o los apellidos"}
    if event.status != "en_proceso" and not (event.sync_revert and event.sync_revert[1]):      # `require_event_in_progress`, salvo lo anterior a un retroceso a «Creado» (la hora ya se verificó)
        return {"op_id": op_id, "result": "error", "detail": "El evento ya no está abierto para registrar personas nuevas"}
    extras = f.get("extra_fields") if isinstance(f.get("extra_fields"), dict) else {}
    extras = {str(k): str(v) for k, v in extras.items() if re.fullmatch(r"opcional_\d+", str(k)) and str(v).strip()}
    labels = f.get("field_labels") if isinstance(f.get("field_labels"), dict) else None
    missing_labels = set(extras) - set(event.get_optional_labels())
    if missing_labels and not labels:
        return {"op_id": op_id, "result": "error", "detail": "Hay campos opcionales sin nombre para este evento"}
    try:
        categories = _clean_categories(event, f.get("categories") if isinstance(f.get("categories"), list) else []) if f.get("categories") else []
        contact = digital_badge.normalize_contact(f.get("digital_contact")) if f.get("digital_contact") else None
    except ValueError as e:
        return {"op_id": op_id, "result": "error", "detail": str(e)}
    values = {k: str(f.get(k) or "") for k in OUTBOX_PERSON_KEYS}
    values.update({"certificate": str(f.get("certificate") or ""), "digital_contact": contact or "", **extras})
    if privacy.is_suppressed(db, event.tenant_id, person_id):
        return {"op_id": op_id, "result": "error", "detail": SUPPRESSED_MSG}          # L4: quien pidió la supresión no se vuelve a crear (tampoco desde la bandeja sin red)
    existing = db.query(User).filter(User.id == person_id, User.tenant_id == event.tenant_id).first()
    if existing:
        if _already_checked_in(db, event.id, existing.id):
            return {"op_id": op_id, "result": "duplicado", "existing_name": f"{existing.first_name or ''} {existing.last_name or ''}".strip()}
        kind = "Existente"
    else:
        missing = _missing_required_fields(field_configs, values)
        if missing:
            return {"op_id": op_id, "result": "error", "detail": f"Faltan campos obligatorios: {', '.join(missing)}"}
        bad = _invalid_email_fields(field_configs, values)
        if bad:
            return {"op_id": op_id, "result": "error", "detail": "Correo no válido — " + "; ".join(bad)}
        kind = "Nuevo"
    try:
        with db.begin_nested():
            if labels and missing_labels:
                _apply_optional_labels(event, set(extras), json.dumps(labels))
            if kind == "Nuevo":
                user = User(id=person_id, tenant_id=event.tenant_id, first_name=first, last_name=last, role=values["role"], entity=values["entity"], phone=values["phone"], email=values["email"], opt_1=values["opt_1"])
                user.set_extras(extras)
                db.add(user)
                db.flush()
            db.add(AccessLog(tenant_id=event.tenant_id, user_id=person_id, record_type=kind, event_id=event.id, registered_by_staff_id=staff.id, registration_method="tradicional",
                             client_id=op_id, timestamp=when, doubtful_reason=doubtful, **regtime.measured(f.get("took_ms"), f.get("ui_flow"))))
            _upsert_attendee(db, event.id, person_id, event.tenant_id, categories if f.get("categories") else None,
                             certificate=_truthy(f.get("certificate")) if f.get("certificate") else None, digital_contact=contact, touch=True)
            db.flush()
    except IntegrityError:
        return {"op_id": op_id, "result": "replayed"}
    flag = {"doubtful": True} if doubtful else {}
    if kind == "Existente":
        return {"op_id": op_id, "result": "existente", "existing_name": f"{existing.first_name or ''} {existing.last_name or ''}".strip(), **flag}
    return {"op_id": op_id, "result": "ok", **flag}


@router.post("/events/{event_id}/outbox/sync")
def outbox_sync(event_id: int, body: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """Sincroniza la BANDEJA DE SALIDA de un quiosco (docs/16, B8): operaciones hechas sin red, hasta `OUTBOX_MAX_OPS` por lote. Hoy solo `create_person` (R1: alta sin foto). Cuerpo:
    `{"ops": [{"op_id", "type": "create_person", "timestamp" (ISO UTC, opcional), "fields": {id, first_name, last_name, role, entity, phone, email, opt_1, extra_fields, categories, ...}}]}`.
    Devuelve `{"results": [{op_id, result, detail?, existing_name?}]}` con `ok | replayed | existente | duplicado | error`: un resultado por operación; repetir un lote nunca duplica (`replayed`)."""
    event = _event_for_sync(db, event_id, staff)
    ops = body.get("ops")
    if not isinstance(ops, list) or not ops:
        raise HTTPException(status_code=400, detail="Falta la lista de operaciones")
    if len(ops) > OUTBOX_MAX_OPS:
        raise HTTPException(status_code=400, detail=f"Máximo {OUTBOX_MAX_OPS} operaciones por lote")
    now = utcnow()
    field_configs = parametros.field_configs_for_event(db, event)
    known = {cid for (cid,) in db.query(AccessLog.client_id).filter(AccessLog.event_id == event.id, AccessLog.client_id.in_([str((o or {}).get("op_id") or "")[:64] for o in ops if isinstance(o, dict)]))}
    results = []
    reverted_at = event.sync_revert[0] if event.sync_revert else None
    for op in ops:
        op = op if isinstance(op, dict) else {}
        op_id = str(op.get("op_id") or "").strip()[:64]
        if not op_id or op.get("type") != "create_person" or not isinstance(op.get("fields"), dict):
            results.append({"op_id": op_id, "result": "error", "detail": "Operación no válida"})
            continue
        if op_id in known:
            results.append({"op_id": op_id, "result": "replayed"})
            continue
        verdict, when = status_changes.classify(op.get("timestamp"), now, reverted_at)
        if verdict == "after":          # alta hecha DESPUÉS de devolver el evento a «Creado»: no se crea (el quiosco la deja en su bandeja con este motivo)
            results.append({"op_id": op_id, "result": "error", "reason": "after_revert", "detail": status_changes.AFTER_REVERT_DETAIL})
            continue
        res = _outbox_create_person(db, event, staff, op_id, op["fields"], when, field_configs, doubtful=status_changes.DOUBTFUL if verdict == "no_hour" else None)
        if res["result"] in ("ok", "existente", "replayed"):
            known.add(op_id)
        results.append(res)
    db.commit()
    return {"results": results, "ok": sum(r["result"] in ("ok", "replayed") for r in results),
            **({"doubtful": sum(bool(r.get("doubtful")) for r in results), "after_revert": sum(r.get("reason") == "after_revert" for r in results)} if reverted_at else {})}


# ----------------------------------------------------------------------------------------------------------------------- roster local (modo contingencia, docs/13 §9)
NOT_FOUND_FACE = "No te encontramos en la lista con reconocimiento facial. Por favor dirígete a la acreditación con tu cédula o QR."      # texto de la auditora (6 oct): sin coincidencia no se guarda nada (ni el vector temporal ni la foto en vivo)
SUPPRESSED_MSG = "Esta persona solicitó la supresión de sus datos: no se puede registrar de nuevo sin su autorización."
OVERWRITE_BIRTH_LABEL = "Reemplazar las fechas de nacimiento que ya están guardadas"      # UN solo texto: la casilla de la carga y el aviso del resumen dicen lo mismo (kiosk_roster.html lo recibe del servidor)
_BIRTH_KEYS = ('fecha de nacimiento', 'fecha_nacimiento', 'fecha nacimiento', 'nacimiento', 'birth_date')      # columna opcional del Excel (L3)
ROSTER_MAX_AGE_S = 24 * 3600          # el cliente lo borra a más tardar 24 h después de este refresco (y antes si el evento finaliza o se cierra la sesión)
ROSTER_LIMIT, ROSTER_WINDOW = 12, timedelta(minutes=10)      # descargas por usuario y evento: un quiosco refresca cada pocos minutos; más que esto es un abuso o un bucle


def roster_normalize(value: str) -> str:
    """Misma normalización que el cliente (static/js/contingency.js): sin espacios ni puntos."""
    return re.sub(r"[\s.]", "", str(value or ""))


def roster_salt(event: Event) -> str:
    """Sal POR EVENTO derivada de SECRET_KEY (sin columna nueva, estable entre procesos). Viaja con el roster: la huella es MINIMIZACIÓN (no se descarga la cédula en claro ni se
    puede leer a simple vista), NO protección fuerte: quien tenga el roster puede probar cédulas por fuerza bruta (el espacio de cédulas es pequeño). Ver docs/15."""
    key = (os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production").encode()
    return hmac.new(key, f"roster-local:{event.tenant_id}:{event.id}".encode(), hashlib.sha256).hexdigest()[:32]


def roster_fingerprint(salt: str, cedula: str) -> str:
    """Huella de la cédula: los primeros 16 hex (64 bits) de SHA-256(sal + ":" + cédula normalizada). El QR propio de la escarapela trae la cédula, así que UNA huella cubre cédula y QR."""
    return hashlib.sha256(f"{salt}:{roster_normalize(cedula)}".encode()).hexdigest()[:16]


def consent_block(event: Event):
    """Texto de autorización biométrica del evento (con su huella) para que el quiosco lo muestre y registre SIN conexión; None si el evento no usa rostro."""
    if not event.facial_enabled:
        return None
    t = legal_texts.render(event)
    return {**{k: t[k] for k in ("version", "variant", "hash", "title", "body", "buttons", "adult_checkbox", "blocked")}, "mode": event.consent_prompt_mode, "click_mode": bool(event.precalculo_autorizado), "every_scan": legal_texts.every_scan_prompt()}


@router.get("/events/{event_id}/local-roster")
def local_roster(
    event_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """Roster mínimo del evento para el modo contingencia del quiosco (Fase 3): por persona SOLO huella de la cédula (`h`), nombre para mostrar (`n`), categorías (`c`) y estado (`s`:
    «No registrado» / «Registrado» / «Nuevo»). Sin fotos, encodings, teléfono ni correo. Mismos permisos que acreditar (digitador+ con acceso al evento; el cliente no), no se
    entrega de un evento finalizado, límite de `ROSTER_LIMIT` descargas por usuario y evento cada 10 min, `ETag` (304 si nada cambió) y gzip. `max_age_s`: vida máxima de la copia. `event.auto_register`: el «Modo autoregistro» del evento (el quiosco sin red solo acredita al escanear si está encendido)."""
    event = get_event_for_staff(event_id, db, staff)
    if event.status == "finalizado":
        raise HTTPException(status_code=409, detail="El evento ya finalizó: no hay roster local")
    key = f"{staff.id}:{event.id}"
    if security.minutes_locked(db, "roster_local", key, None, ROSTER_LIMIT, ROSTER_LIMIT, ROSTER_WINDOW):
        raise HTTPException(status_code=429, detail="Demasiadas descargas del roster local — espera unos minutos.")
    security.record_event(db, "roster_local", key, None)
    if event.facial_enabled:
        accepted = consent_mod.accepted_user_ids(db, event.tenant_id, event.id)
        web_pending = {r[0] for r in db.execute(text("SELECT user_id FROM web_acceptances WHERE tenant_id = :t AND event_id = :e AND verified_at IS NULL"), {"t": event.tenant_id, "e": event.id})}
        n_consents = db.execute(text("SELECT count(*) FROM audit_consent_logs WHERE tenant_id = :t AND event_id = :e"), {"t": event.tenant_id, "e": event.id}).scalar()
    else:          # sin rostro no hay aceptaciones que llevar al quiosco: ni consultas ni banderas
        accepted, web_pending, n_consents = set(), set(), 0
    version = _directory_etag(db, event.id, event.tenant_id, f"roster-local|{int(bool(event.auto_register))}|{n_consents}|{len(web_pending)}|{event.controller_mode}|{event.consent_prompt_mode}|{int(bool(event.facial_enabled))}|{int(bool(event.precalculo_autorizado))}")      # el modo autoregistro y la autorización biométrica viajan en la copia: si cambian, cambia la versión
    headers = {"Cache-Control": "private, no-cache", "ETag": f'"{version}"'}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    salt = roster_salt(event)
    attendee_ids = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)
    log_ids = db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id)
    people = db.query(User.id, User.first_name, User.last_name, EventAttendee.categories, User.birth_date).outerjoin(
        EventAttendee, (EventAttendee.user_id == User.id) & (EventAttendee.tenant_id == User.tenant_id) & (EventAttendee.event_id == event.id),
    ).filter(User.tenant_id == event.tenant_id, or_(User.id.in_(attendee_ids), User.id.in_(log_ids))).order_by(User.id).all()
    counts = {uid: (real, new) for uid, real, new in db.query(
        AccessLog.user_id, func.count(AccessLog.id).filter(AccessLog.record_type != "Actualizado"), func.count(AccessLog.id).filter(AccessLog.record_type == "Nuevo"),
    ).filter(AccessLog.event_id == event.id).group_by(AccessLog.user_id)}
    rows = []
    for uid, first, last, categories, birth in people:
        real, new = counts.get(uid, (0, 0))
        rows.append({"h": roster_fingerprint(salt, uid), "n": f"{first or ''} {last or ''}".strip(), "c": json.loads(categories) if categories else [],
                     "s": "No registrado" if not real else ("Nuevo" if new else "Registrado"), "a": 1 if uid in accepted and not minors.is_minor(birth) else 0, "b": 1 if (event.facial_enabled and minors.is_minor(birth)) else 0, "v": 1 if uid in web_pending else 0})      # `v`: aceptó desde el celular y falta verificar su identidad en puerta      # `a`: ya aceptó el reconocimiento facial en este evento (solo un 1/0, sin datos biométricos)
    return JSONResponse({"v": version, "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "max_age_s": ROSTER_MAX_AGE_S, "event": {"id": event.id, "status": event.status, "auto_register": bool(event.auto_register)},
                         "salt": salt, "count": len(rows), "people": rows, "consent": consent_block(event)}, headers=headers)


# A2 (0C): único conjunto de columnas de `User` que este endpoint escribe. Antes era `hasattr` + `setattr` sobre cualquier clave del cuerpo (asignación masiva): se podía tocar
# `face_encoding`, `biometric_consent_at`, `is_biometric_enabled`, `face_captured_at`… Lo biométrico y la cédula tienen sus propios caminos; `birth_date`, `extra_fields`, `categories` y demás se tratan aparte.
USER_EDITABLE_FIELDS = ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1")


def _clean_user_fields(data: dict) -> dict:
    """Solo las claves permitidas, con texto simple (o vacío). Lo demás se ignora; un valor que no sea texto/número/vacío es un error 400."""
    out = {}
    for key in USER_EDITABLE_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            out[key] = None
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            out[key] = str(value)[:500]
        else:
            raise HTTPException(status_code=400, detail=f"El valor de «{key}» no es válido")
    return out


@router.patch("/users/{user_id}")
def update_user(
    user_id: str, data: dict, event_id: int, request: Request, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),  # 2026-09-23: el digitador temporal también edita datos (no cédula, estado a "No registrado" ni eliminar)
):
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if user:
        # Fecha de nacimiento (base del control de menores): se valida ANTES de tocar nada. Vacía = borrarla.
        birth_change = False
        if "birth_date" in data and not event.facial_enabled:
            data.pop("birth_date")          # sin rostro la fecha de nacimiento no se usa: no se toca
        if "birth_date" in data:
            raw_birth = str(data.pop("birth_date") or "").strip()
            new_birth = minors.parse_birth(raw_birth) if raw_birth else None
            if raw_birth and new_birth is None:
                raise HTTPException(status_code=400, detail="La fecha de nacimiento no es válida (usa AAAA-MM-DD o DD/MM/AAAA, y no puede ser futura).")
            birth_change = new_birth != user.birth_date
        # extra_fields llega como un dict {opcional_N: valor} desde el modal de "Editar" del
        # Directorio (2026-09-16) — no puede pasar por el setattr genérico de abajo: la columna
        # real (`User.extra_fields`) es un Text con JSON serializado a mano (`get_extras()`/
        # `set_extras()`), no un dict crudo; asignarlo directo lo corrompería.
        categories = data.pop("categories", None)  # ítem 14: por evento (EventAttendee), no una columna de User
        if categories is not None:
            _upsert_attendee(db, event.id, user.id, event.tenant_id, _clean_categories(event, categories))
        digital_raw = data.pop("digital_contact", None)  # ítem 17: correo/teléfono de la escarapela digital (por evento)
        send_now = _send_now(data.pop("send_digital_now", None))
        new_digital = None
        if digital_raw is not None:
            try:
                new_digital = digital_badge.normalize_contact(digital_raw) or ""
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            _upsert_attendee(db, event.id, user.id, event.tenant_id, digital_contact=new_digital)
        certificate = data.pop("certificate", None)  # ítem 5: también por evento
        if certificate is not None:
            _upsert_attendee(db, event.id, user.id, event.tenant_id, certificate=_truthy(certificate))
        extra_fields = data.pop("extra_fields", None)
        if extra_fields is not None:
            merged = user.get_extras()
            merged.update(extra_fields)
            user.set_extras(merged)
        # Sprint 2.4 Fase 7 (2026-09-16, pedido explícito: "que no se pueda repetir para nadie el
        # id"): 'id'/'tenant_id' son la llave primaria compuesta de User, referenciada por FK
        # desde EventAttendee/AccessLog — un setattr genérico sobre ellas intentaría un UPDATE de
        # la propia PK, algo que este endpoint nunca tuvo pensado hacer (eso es exactamente lo que
        # resuelve PUT /users/{user_id}/cedula con su patrón seguro insertar-reapuntar-borrar, ver
        # abajo) y que solo terminaría en un IntegrityError sin manejar. Se ignoran acá — el único
        # camino válido para cambiar la cédula es ese otro endpoint.
        data.pop("id", None)
        data.pop("tenant_id", None)
        for key, value in _clean_user_fields(data).items():
            setattr(user, key, value)
        if birth_change:
            was_minor = minors.is_minor(user.birth_date)
            db.add(PersonChange(tenant_id=event.tenant_id, event_id=event.id, user_id=user.id, staff_user_id=staff.id, kind="birth_date",
                                old_value=user.birth_date.isoformat() if user.birth_date else "", new_value=new_birth.isoformat() if new_birth else ""))
            user.birth_date = new_birth
            if minors.is_minor(new_birth):            # pasó a ser menor: se retira lo biométrico (vector y foto) y solo entra por cédula/QR
                get_storage().delete_all_versions(photo_key(event.tenant_id, user.id))
                user.face_encoding = None
                user.biometric_consent_at = None
                user.biometric_consent_source = None
                user.is_biometric_enabled = False
                faces_version.bump(db, tenant_id=event.tenant_id)
            elif was_minor and new_birth is not None:
                user.is_biometric_enabled = True       # corrigieron un error de fecha: ya es mayor; podrá aceptar el reconocimiento facial como cualquiera

        field_configs = parametros.field_configs_for_event(db, event)
        final_values = {
            "role": user.role, "entity": user.entity, "phone": user.phone,
            "email": user.email, "opt_1": user.opt_1, **user.get_extras(),
        }
        attendee = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
        final_values["certificate"] = "true" if (attendee and attendee.certificate) else ""
        final_values["digital_contact"] = (attendee.digital_contact if attendee else "") or ""
        missing = _missing_required_fields(field_configs, final_values)
        if missing:
            raise HTTPException(status_code=400, detail=f"Faltan campos obligatorios: {', '.join(missing)}")
        bad_emails = _invalid_email_fields(field_configs, final_values)
        if bad_emails:
            raise HTTPException(status_code=400, detail="Correo no válido — " + "; ".join(bad_emails))

        log = AccessLog(
            tenant_id=event.tenant_id, user_id=user.id, record_type="Actualizado",
            event_id=event.id, registered_by_staff_id=staff.id,
        )
        db.add(log)
        db.commit()
        result = {"message": "Actualizado correctamente"}
        if new_digital and event.digital_badge_enabled:
            if send_now:
                att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
                result["digital"] = digital_badge.send_digital_badge(db, event, att, user.first_name or "", str(request.base_url), user.last_name or "")
                db.commit()
            else:
                result["digital"] = {"sent": False, "detail": "Correo guardado. La escarapela NO se envió (dejaste sin marcar «Enviar ahora la escarapela»)"}
        return result
    return {"error": "Usuario no encontrado"}

@router.put("/users/{user_id}/cedula")
def update_user_cedula(
    user_id: str, event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("admin")),
):
    """Corrige la cédula (User.id) de una persona ya registrada (2026-09-16, pedido explícito: a
    veces se acredita por nombre porque la cédula quedó mal escrita, y no había forma de
    arreglarla). User.id es parte de la llave primaria compuesta (id, tenant_id) y está referenciada
    por FK desde EventAttendee/AccessLog — renombrarla in-place violaría esa FK a mitad de camino,
    así que el patrón seguro es insertar una fila nueva con el id correcto, reapuntar las filas
    hijas, y recién ahí borrar la vieja, todo en una sola transacción. admin+ solamente: User vive
    a nivel de tenant (se comparte entre eventos, ver CLAUDE.md), así que este cambio afecta a la
    persona en TODOS los eventos de este cliente, no solo en este — más sensible que un campo
    normal del perfil."""
    event = get_event_for_staff(event_id, db, staff)
    old_id = user_id
    new_id = str(data.get("new_id", "")).strip()
    if not new_id:
        raise HTTPException(status_code=400, detail="La nueva cédula no puede estar vacía")
    if new_id == old_id:
        raise HTTPException(status_code=400, detail="La nueva cédula es igual a la actual")

    user = db.query(User).filter(User.id == old_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    conflict = db.query(User).filter(User.id == new_id, User.tenant_id == event.tenant_id).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Ya existe otra persona con esa cédula en este cliente")

    new_user = User(
        id=new_id, tenant_id=user.tenant_id, first_name=user.first_name, last_name=user.last_name,
        role=user.role, entity=user.entity, phone=user.phone, email=user.email,
        opt_1=user.opt_1, opt_2=user.opt_2, extra_fields=user.extra_fields, face_encoding=user.face_encoding,
        biometric_consent_at=user.biometric_consent_at, biometric_consent_source=user.biometric_consent_source,
    )
    db.add(new_user)
    db.flush()  # el nuevo User debe existir antes de reapuntar las filas hijas hacia él

    db.query(EventAttendee).filter(
        EventAttendee.user_id == old_id, EventAttendee.tenant_id == event.tenant_id
    ).update({"user_id": new_id}, synchronize_session=False)
    db.query(AccessLog).filter(
        AccessLog.user_id == old_id, AccessLog.tenant_id == event.tenant_id
    ).update({"user_id": new_id}, synchronize_session=False)
    # PrintLog (Sprint 2.4 Fase 3, 2026-09-16) tiene la misma FK compuesta (user_id, tenant_id)
    # que EventAttendee/AccessLog — bug real encontrado en Fase 7 (2026-09-16): faltaba
    # reapuntarlo acá también, así que renombrar la cédula de alguien que ya se había impreso
    # antes tumbaba este endpoint con un ForeignKeyViolation al borrar el User viejo más abajo.
    db.query(PrintLog).filter(
        PrintLog.user_id == old_id, PrintLog.tenant_id == event.tenant_id
    ).update({"user_id": new_id}, synchronize_session=False)
    db.flush()

    db.delete(user)

    signatures.rename_signatures(event.tenant_id, old_id, new_id)
    if get_storage().exists(photo_key(event.tenant_id, old_id)):
        get_storage().move(photo_key(event.tenant_id, old_id), photo_key(event.tenant_id, new_id))

    db.commit()
    return {"message": "Cédula actualizada correctamente", "new_id": new_id}


@router.delete("/users/{user_id}/logs")
def delete_user_logs(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("admin")),
):
    """Histórico (2026-09-21 en adelante) — ya NO se usa desde el frontend, quedó reemplazado por
    `DELETE /users/{id}` (borrado real, ver abajo) y `PATCH /events/{id}/users/{id}/status`
    (cambio de estado sin borrar nada). Se deja documentado, no se borra el endpoint, por si algún
    integrador externo llegó a depender de él. Ojo: este SÍ borra por tenant completo, no por
    evento — bug conocido, no replicar este patrón en código nuevo."""
    event = get_event_for_staff(event_id, db, staff)
    db.query(AccessLog).filter(AccessLog.user_id == user_id, AccessLog.tenant_id == event.tenant_id).delete()
    db.commit()
    return {"message": "Registros eliminados. Estado regresado a No Registrado."}


@router.delete("/users/{user_id}")
def delete_user_from_event(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    """Borra a la persona de ESTE evento por completo (2026-09-16, pedido explícito: "Eliminar"
    debía borrar de verdad, no solo resetear el estado). Scoped al evento — no confundir con el
    viejo `.../logs` de arriba, que por bug afectaba TODO el tenant. Si tras sacarla de este
    evento la persona no queda en NINGÚN otro evento del mismo tenant (mismo User se reusa entre
    eventos, ver CLAUDE.md), se borra también el `User` y su foto física — si sigue en otro
    evento, ese `User` se conserva intacto, no se puede reventar la base de un evento ajeno."""
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    # 26-oct-2026 (A2): TODO lo de la persona en este evento, sin dejar huérfanos. Antes quedaban el historial de impresión (print_logs, con llave hacia la persona: al borrarla del todo
    # el servidor fallaba), los trabajos de impresión compartida, movimientos de áreas, entregas de inventario, envíos de enlaces y el historial de cambios. Lo legal (aceptación de la
    # persona: audit_consent_logs y web_acceptances) NO se toca: es un registro inmutable con su propia retención (app/consent.py, app/privacy.py).
    from app.models import AcceptMailLog, AreaMovement, InventoryDelivery, PersonChange, PrintJob, PrintLog
    att_ids = [a for (a,) in db.query(EventAttendee.id).filter(EventAttendee.event_id == event_id, EventAttendee.user_id == user_id)]
    if att_ids:
        db.query(PrintJob).filter(PrintJob.event_id == event_id, PrintJob.attendee_id.in_(att_ids)).delete(synchronize_session=False)
    for model in (PrintLog, AreaMovement, InventoryDelivery, AcceptMailLog, PersonChange):
        db.query(model).filter(model.event_id == event_id, model.user_id == user_id).delete(synchronize_session=False)
    db.query(EventAttendee).filter(EventAttendee.event_id == event_id, EventAttendee.user_id == user_id).delete()
    db.query(AccessLog).filter(AccessLog.event_id == event_id, AccessLog.user_id == user_id).delete()
    signatures.delete_signatures(event.tenant_id, event_id, user_id)
    db.flush()

    other_attendee = db.query(EventAttendee).filter(
        EventAttendee.user_id == user_id, EventAttendee.tenant_id == event.tenant_id
    ).first()
    other_log = db.query(AccessLog).filter(
        AccessLog.user_id == user_id, AccessLog.tenant_id == event.tenant_id
    ).first()

    fully_deleted = False
    if not other_attendee and not other_log:
        for model in (PrintLog, AreaMovement, InventoryDelivery):       # lo que tenga en otros eventos YA cerrados del cliente (sin inscripción ni ingresos) también apunta a la persona
            db.query(model).filter(model.tenant_id == event.tenant_id, model.user_id == user_id).delete(synchronize_session=False)
        get_storage().delete(photo_key(event.tenant_id, user_id))
        db.delete(user)
        fully_deleted = True

    db.commit()
    return {
        "message": "Persona eliminada de este evento" + (
            " y de la base de datos (no pertenecía a ningún otro evento de este cliente)."
            if fully_deleted else ". Sigue en la base porque pertenece a otro evento del mismo cliente."
        ),
        "fully_deleted": fully_deleted,
    }


@router.patch("/events/{event_id}/users/{user_id}/status")
def update_registration_status(
    event_id: int, user_id: str, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    """Cambia manualmente el estado de registro de una persona en este evento (2026-09-16, nuevo;
    ampliado a coordinador+ el 2026-09-17, pedido explícito — antes admin+ solamente, junto con
    DELETE /users/{id} arriba) — antes la única forma de pasar a "Registrado" era un escaneo/
    búsqueda real, y no existía forma de volver a "No registrado" salvo el viejo borrado-de-logs.
    Pensado para el caso real que describió Juan David: crear a alguien de antemano (aún no ha
    llegado) sin que quede "Registrado" de una, y poder marcarlo cuando sí llegue — o al revés,
    corregir un registro hecho por error. `data: {"status": "registrado" | "no_registrado"}`."""
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")

    new_status = data.get("status")
    if new_status not in ("registrado", "no_registrado"):
        raise HTTPException(status_code=400, detail="status debe ser 'registrado' o 'no_registrado'")
    # 2026-09-23: el digitador temporal solo puede MARCAR como registrado (al guardar una edición);
    # volver a "No registrado" sigue siendo de coordinador+.
    if new_status == "no_registrado" and max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) < ROLE_HIERARCHY["coordinador"]:
        raise HTTPException(status_code=403, detail="No tienes permiso para esta acción")

    was_registered = _already_checked_in(db, event_id, user_id)
    deleted_logs = 0
    if new_status == "registrado" and not was_registered:
        missing = person_missing_required(db, event, user)
        if missing:                                     # A3: el mismo código claro en todos los caminos
            raise HTTPException(status_code=409, detail={"code": "missing_required", "missing": missing, "message": missing_required_message(missing)})
    if new_status == "registrado":
        if not _already_checked_in(db, event_id, user_id):
            log = AccessLog(
                tenant_id=event.tenant_id, user_id=user_id, record_type="Existente",
                event_id=event_id, registered_by_staff_id=staff.id,
                registration_method="biometrico" if data.get("method") == "biometrico" else "tradicional",  # Fase 16: cambio manual de estado desde el Directorio; «biometrico» lo manda la verificación del operador tras un escaneo facial
                **regtime.measured(data.get("took_ms"), data.get("ui_flow")),
            )
            db.add(log)
            _upsert_attendee(db, event_id, user_id, event.tenant_id, touch=True)
    else:
        deleted_logs = db.query(AccessLog).filter(AccessLog.event_id == event_id, AccessLog.user_id == user_id).delete()

    if was_registered != (new_status == "registrado"):          # rastro: quién, cuándo (at), estado anterior y nuevo; al deshacer queda cuántos accesos se borraron
        db.add(PersonChange(tenant_id=event.tenant_id, event_id=event_id, user_id=user_id, staff_user_id=staff.id, kind="registration_status",
                            old_value="Registrado" if was_registered else "No registrado", new_value="Registrado" if new_status == "registrado" else "No registrado",
                            detail=f"accesos borrados: {deleted_logs}" if new_status == "no_registrado" else None))
    db.commit()
    return {"message": "Estado de registro actualizado", "status": new_status}

@router.post("/register")
def manual_register(
    event_id: int = Form(...), id: str = Form(...), first_name: str = Form(...), last_name: str = Form(...),
    role: str = Form(""), entity: str = Form(""), phone: str = Form(""),
    email: str = Form(""), opt_1: str = Form(""), extra_fields: str = Form(None), categories: str = Form(None), certificate: str = Form(None), digital_contact: str = Form(None), send_digital_now: str = Form(None),
    request: Request = None,
    field_labels: str = Form(None), file: UploadFile = File(None), force: bool = Form(False), biometric_consent: str = Form(None), birth_date: str = Form(""),
    took_ms: str = Form(""), ui_flow: str = Form(""),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador")),
):
    """file es OPCIONAL: el alta manual la puede disparar tanto el flujo facial (con foto, para
    poder reconocer a esta persona después) como el de cédula (sin foto, solo identidad).
    Si la cédula ya existe como User en el tenant (de este evento o de uno anterior — User vive
    a nivel de tenant, no de evento) no se rechaza de plano: si todavía no tiene AccessLog para
    ESTE evento, simplemente se le agrega (reutilizar a alguien de un evento pasado es válido);
    si ya lo tiene, se avisa (DUPLICADO) igual que recognize/checkin-cedula, salvo force=true.

    Campos opcionales (2026-09-22, mismo esquema que bulk_register): `extra_fields` es un JSON
    {"opcional_1": "valor", ...} armado por el frontend (kiosk_registro.html deja agregar hasta
    30 campos opcionales al formulario de alta individual, con los mismos nombres que el roster
    original si lo hay). Si alguna clave usada todavía no tiene rótulo para este evento, se
    devuelve {"result": "NEEDS_LABELS", "fields": [...]} igual que bulk_register — el frontend
    normalmente ya manda `field_labels` de una vez porque él mismo preguntó el nombre al agregar
    el campo, así que este camino solo se ejerce en casos raros/defensivos."""
    return _manual_register(**locals())          # a esta altura `locals()` son solo los parámetros del endpoint: se pasan tal cual al cuerpo (sin repetirlos a mano)


def _manual_register(event_id, id, first_name, last_name, role, entity, phone, email, opt_1, extra_fields, categories, certificate, digital_contact, send_digital_now, request, field_labels, file,
                     force, biometric_consent, birth_date, db, staff, retry: bool = False, took_ms=None, ui_flow=None):
    """Cuerpo de `POST /register`. `retry=True` solo en el ÚNICO reintento tras un choque de cédula (ver más abajo): nunca se reintenta dos veces."""
    args = {k: v for k, v in locals().items() if k != "retry"}          # los argumentos tal como llegaron (aquí `locals()` son solo los parámetros), para el único reintento
    event = get_event_for_staff(event_id, db, staff)
    require_event_in_progress(event)

    extras = _parse_extra_fields(extra_fields)
    try:
        person_categories = _clean_categories(event, json.loads(categories)) if categories else []
    except ValueError:
        person_categories = []
    try:
        contact_clean = digital_badge.normalize_contact(digital_contact) if digital_contact else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    used_optional_keys = set(extras.keys())
    missing = used_optional_keys - set(event.get_optional_labels().keys())
    if missing and not field_labels:
        return {"result": "NEEDS_LABELS", "fields": sorted(missing, key=lambda k: int(k.split("_")[1]))}
    if field_labels:
        _apply_optional_labels(event, used_optional_keys, field_labels)
        db.commit()

    if file is not None and file.filename and not _truthy(biometric_consent):      # Ley 1581: sin autorización expresa no se guarda el rostro (se evalúa primero)
        raise HTTPException(status_code=400, detail=BIOMETRIC_CONSENT_REQUIRED)
    birth = minors.parse_birth(birth_date)
    if str(birth_date or "").strip() and birth is None:
        raise HTTPException(status_code=400, detail="La fecha de nacimiento no es válida")
    minor = minors.is_minor(birth)
    has_photo = file is not None and bool(file.filename)
    if has_photo and event.biometrics_locked:
        raise HTTPException(status_code=400, detail="Este evento no usa biometría: no se guardan fotos de las personas. Regístrala sin foto.")
    if has_photo and not minor and birth is None:
        raise HTTPException(status_code=400, detail="Para guardar el rostro hace falta la fecha de nacimiento: solo se capta el rostro de mayores de 18 años")
    if privacy.is_suppressed(db, event.tenant_id, id):
        raise HTTPException(status_code=409, detail=SUPPRESSED_MSG)
    existing = db.query(User).filter(User.id == id, User.tenant_id == event.tenant_id).first()
    if existing:
        if birth is not None:
            existing.birth_date = birth
            if minor:
                existing.is_biometric_enabled = False
                privacy.purge_person(db, event.tenant_id, existing.id)      # menor de 18: sin vector ni foto
        if not force and _already_checked_in(db, event.id, existing.id):
            return _duplicate_warning(db, event.id, existing)
        log = AccessLog(
            tenant_id=event.tenant_id, user_id=existing.id, record_type="Existente",
            event_id=event.id, registered_by_staff_id=staff.id,
            registration_method="tradicional",  # Fase 16: alta manual, formulario
            **regtime.measured(took_ms, ui_flow),
        )
        db.add(log)
        _upsert_attendee(db, event.id, existing.id, event.tenant_id, person_categories if categories else None, digital_contact=contact_clean, touch=True)
        db.commit()
        reply = {"message": "Esta persona ya existía en el sistema — registrada para este evento."}
        if contact_clean and event.digital_badge_enabled:
            reply["digital"] = _send_digital(db, event, existing, request) if _send_now(send_digital_now) else {"sent": False, "detail": "Correo guardado. La escarapela NO se envió (dejaste sin marcar «Enviar ahora la escarapela»)"}
        return reply

    field_configs = parametros.field_configs_for_event(db, event)
    final_values = {"role": role, "entity": entity, "phone": phone, "email": email, "opt_1": opt_1, "certificate": certificate or "", "digital_contact": contact_clean or "", **extras}
    missing = _missing_required_fields(field_configs, final_values)
    if missing:
        raise HTTPException(status_code=400, detail=f"Faltan campos obligatorios: {', '.join(missing)}")
    bad_emails = _invalid_email_fields(field_configs, final_values)
    if bad_emails:
        raise HTTPException(status_code=400, detail="Correo no válido — " + "; ".join(bad_emails))

    face_enc_json = None
    img_array = None
    # OJO: un <input type="file"> vacío igual manda una parte multipart (con filename=""), así
    # que `file is not None` es cierto incluso sin archivo real — hay que revisar `file.filename`
    # también, si no, `file.read()` da bytes vacíos y `Image.open()` truena (500) en vez de
    # tratarlo como "no se adjuntó foto" (CEDULA-08, bug real encontrado en testing 2026-09-21).
    if has_photo and not minor:
        if not _truthy(biometric_consent):      # Ley 1581 (dato sensible): sin autorización expresa de la persona NO se guarda su rostro; puede registrarse por cédula
            raise HTTPException(status_code=400, detail=BIOMETRIC_CONSENT_REQUIRED)
        img_array = BiometricEngine.process_image_stream(file.file.read())
        if consent_mod.has_acceptance(db, event.tenant_id, id, event.id):      # REGLA A: el vector solo se calcula si la PERSONA ya aceptó (la casilla del digitador no cuenta)
            try:
                encodings = faces.extract(img_array, is_registration=True)
            except faces.Busy:
                raise HTTPException(status_code=503, detail="Hay muchos procesos faciales en cola. Intenta de nuevo en unos segundos.", headers={"Retry-After": "3"})
            if not encodings:
                return {"error": "No se detectó un rostro en la fotografía."}
            face_enc_json = json.dumps(encodings)

    user = User(
        id=id, tenant_id=event.tenant_id, first_name=first_name.strip(), last_name=last_name.strip(),
        role=role, entity=entity, phone=phone, email=email, opt_1=opt_1, face_encoding=face_enc_json,
        biometric_consent_at=utcnow() if face_enc_json else None, biometric_consent_source="kiosko" if face_enc_json else None,
        birth_date=birth, is_biometric_enabled=not minor,
        face_captured_at=utcnow() if (img_array is not None and not face_enc_json) else None,          # foto sin vector: el reloj de retención corre igual
    )
    user.set_extras(extras)
    db.add(user)
    # Mismo bug que ya se había arreglado en bulk_register (ver ese comentario) pero nunca se
    # replicó aquí: con autoflush=False, el INSERT de User quedaba pendiente sin mandarse a la
    # base todavía cuando AccessLog/EventAttendee (que dependen de él por llave foránea) se
    # intentaban insertar en el mismo flush — Postgres (y SQLite con PRAGMA foreign_keys=ON)
    # rechazan el INSERT de event_attendees con ForeignKeyViolation porque el User referenciado
    # técnicamente "no existe todavía" en ese punto. Un flush() explícito aquí garantiza que el
    # INSERT de User ya se mandó antes de crear las filas que dependen de él (reproducido y
    # confirmado con un test end-to-end vía FastAPI TestClient + SQLite con FK activas, 2026-09-23).
    try:
        db.flush()
    except IntegrityError:
        # Otra petición creó a esta misma cédula entre la consulta de arriba y este INSERT (otro quiosco o una carga «solo agregar», app/roster_append.py): antes era un 500 para quien registraba.
        # UN solo reintento y solo si la persona AHORA existe: se atiende como persona que ya existía (la rama de arriba, que no toca la foto ni el consentimiento). Si no existe (el error es de
        # OTRA restricción) o ya era el reintento, se propaga el error original: nunca hay bucle.
        db.rollback()
        if retry or not db.query(User.id).filter(User.id == id, User.tenant_id == event.tenant_id).first():
            raise
        return _manual_register(**args, retry=True)

    log = AccessLog(
        tenant_id=event.tenant_id, user_id=id, record_type="Nuevo",
        event_id=event.id, registered_by_staff_id=staff.id,
        registration_method="tradicional",  # Fase 16: alta manual, formulario
        **regtime.measured(took_ms, ui_flow),
    )
    db.add(log)
    _upsert_attendee(db, event.id, id, event.tenant_id, person_categories, certificate=_truthy(certificate) if certificate else None, digital_contact=contact_clean, touch=True)
    db.commit()

    if img_array is not None:
        crypto.save_image(Image.fromarray(img_array), photo_key(event.tenant_id, id))      # cifrada en reposo si hay llave

    reply = {"message": "Usuario registrado exitosamente como Nuevo."}
    if img_array is not None and not face_enc_json:
        reply["face_pending"] = "La foto quedó guardada; el reconocimiento facial se activa cuando la persona acepte en la pantalla de autorización."
    if minor:
        reply["minor"] = "Es menor de 18 años: se registró SIN rostro (no se capta ni se guarda). Ingresa por cédula o QR."
    if contact_clean and event.digital_badge_enabled:
        reply["digital"] = _send_digital(db, event, user, request) if _send_now(send_digital_now) else {"sent": False, "detail": "Correo guardado. La escarapela NO se envió (dejaste sin marcar «Enviar ahora la escarapela»)"}
    return reply

def _carry_source_events(db: Session, event: Event, source_event_ids: list, staff: StaffUser):
    """Igual que `_carry_source_event` pero con uno o VARIOS eventos de origen (2026-09-23): une a las
    personas de todos. Devuelve ({ids}, "Evento A, Evento B")."""
    ids, names = set(), []
    for source_id in dict.fromkeys(source_event_ids):  # sin repetir, conservando el orden
        got, name = _carry_source_event(db, event, source_id, staff)
        ids |= got
        names.append(name)
    return ids, ", ".join(names)


def _carry_source_event(db: Session, event: Event, source_event_id: int, staff: StaffUser):
    """Ítem 18: agrega al evento `event` a TODAS las personas de otro evento del MISMO cliente (su
    directorio: EventAttendee ∪ AccessLog), como asistentes esperados — sin AccessLog, o sea "No
    registrado". Las personas viven a nivel de cliente (User), así que no se copian datos: ya son
    las mismas filas, y por eso prevalece el dato del evento viejo frente a un Excel con el mismo ID.
    También trae los rótulos de campos opcionales del evento viejo que este todavía no tenga, para
    que sus valores (opcional_N) sigan teniendo nombre. Devuelve ({ids}, nombre_del_evento_origen)."""
    source = get_event_for_staff(source_event_id, db, staff)
    if source.id == event.id:
        raise HTTPException(status_code=400, detail="Elige un evento distinto a este")
    if source.tenant_id != event.tenant_id:
        raise HTTPException(status_code=400, detail="Solo se pueden traer personas de eventos del mismo cliente")
    ids = {a.user_id for a in db.query(EventAttendee).filter(EventAttendee.event_id == source.id)}
    ids |= {l.user_id for l in db.query(AccessLog).filter(AccessLog.event_id == source.id, AccessLog.record_type != "Actualizado")}
    for user_id in ids:
        _upsert_attendee(db, event.id, user_id, event.tenant_id)
    labels = event.get_optional_labels()
    for key, label in source.get_optional_labels().items():
        labels.setdefault(key, label)
    event.set_optional_labels(labels)
    db.flush()
    return ids, source.name


@router.post("/bulk_roster")
def bulk_roster(
    event_id: int = Form(...), roster_file: UploadFile = File(None), field_labels: str = Form(None), source_event_id: List[int] = Form(None), background: bool = Form(True),
    roster_upload: str = Form(None), overwrite_birth: str = Form(None), append_only: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Carga de SOLO la base (Excel/CSV, sin fotos). Es la misma carga que `bulk_register`, pero esta ruta la sirve el servicio WEB (sin dlib): `bulk_register` vive en el servicio de BIOMETRÍA (ver
    app/appmode.py), que se apaga cuando no se usa y al arrancar carga el modelo facial: ese arranque en frío (~15 s) lo pagaba hasta una carga de una sola persona."""
    return bulk_register(event_id=event_id, roster_file=roster_file, zip_file=None, field_labels=field_labels, source_event_id=source_event_id, background=background, photos_authorized=None,
                         roster_upload=roster_upload, zip_upload=None, overwrite_birth=overwrite_birth, append_only=append_only, db=db, staff=staff)


@router.post("/bulk_roster/preview")
def bulk_roster_preview(
    event_id: int = Form(...), roster_file: UploadFile = File(None), roster_upload: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Vista previa de «solo agregar personas nuevas» (app/roster_append.py): lee y valida la hoja y cuenta qué pasaría, SIN escribir nada. Mismos permisos que la carga. No borra el archivo subido:
    la carga real lo vuelve a usar."""
    event = get_event_for_staff(event_id, db, staff)
    if blocked := event_rules.roster_block_reason(event, append_only=True):
        raise HTTPException(status_code=400, detail=blocked)
    roster_up = uploads.fetch(roster_upload, "bulk_roster", {"e": event_id})
    content = roster_up.content if roster_up else (roster_file.file.read() if (roster_file is not None and roster_file.filename) else None)
    if content is None:
        raise HTTPException(status_code=400, detail=roster_append.NEEDS_FILE)
    name = roster_up.filename if roster_up else roster_file.filename
    res = _bulk_register_impl(db, staff, event_id=event_id, roster_filename=name, content=content, zip_bytes=None, field_labels=None, source_event_id=None, step={"phase": "prepare"}, append_only=True)
    db.rollback()          # nada se escribe; si algo quedó abierto, se descarta
    return roster_append.preview(db, event, res["prepared"])


@router.post("/bulk_register")
def bulk_register(
    event_id: int = Form(...), roster_file: UploadFile = File(None), zip_file: UploadFile = File(None),
    field_labels: str = Form(None), source_event_id: List[int] = Form(None), background: bool = Form(False), photos_authorized: str = Form(None),
    roster_upload: str = Form(None), zip_upload: str = Form(None), overwrite_birth: str = Form(None), append_only: str = Form(None),
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Carga masiva de la base del evento (ver `_bulk_register_impl` para las reglas). Con `background=true`
    (lo que usa la pantalla "Adjuntar Base de Datos", Sprint 5) responde de inmediato con `{job_id}` y el trabajo
    corre en un hilo, con avance consultable en `GET /api/bulk_jobs/{job_id}`; sin `background` procesa dentro de
    la petición y devuelve el resultado, como siempre."""
    event = get_event_for_staff(event_id, db, staff)  # 403/404 de acceso, de inmediato
    append = _truthy(append_only)          # «solo agregar personas nuevas» (app/roster_append.py): se valida ANTES de leer nada
    if append and (zip_upload or (zip_file is not None and bool(zip_file.filename))):
        raise HTTPException(status_code=400, detail=roster_append.ZIP_REJECTED)
    if append and source_event_id:
        raise HTTPException(status_code=400, detail=roster_append.SOURCE_REJECTED)
    if append and not (roster_upload or (roster_file is not None and bool(roster_file.filename))):
        raise HTTPException(status_code=400, detail=roster_append.NEEDS_FILE)
    if append and not background:
        raise HTTPException(status_code=400, detail="«Solo agregar personas nuevas» se ejecuta por pasos (background=true).")
    has_zip = bool(zip_upload) or (zip_file is not None and bool(zip_file.filename))
    zip_ignored = bool(event.biometrics_locked and has_zip)
    if zip_ignored:          # candado «sin biometría»: las fotos NO se leen, no se guardan y no encienden el rostro (el aviso sale en el resultado)
        zip_file, zip_upload, has_zip = None, None, False
    if has_zip and not (event.facial_enabled and event.client_photos_before):
        # Fuente de verdad única (Fase 0): el uso del rostro y el origen de la foto se eligen SOLO en Parámetros (paso guiado). Las fotos del cliente (zip) solo caben en el origen A.
        raise HTTPException(status_code=400, detail="Las fotos (zip) solo se cargan si el evento usa reconocimiento facial con fotos entregadas por el cliente (origen A). Cámbialo en Parámetros → Reconocimiento facial: paso guiado.")
    if has_zip and not _truthy(photos_authorized):      # el organizador declara que tiene la autorización de cada titular
        raise HTTPException(status_code=400, detail="Para cargar fotos debes declarar que cuentas con la autorización expresa de cada persona para tratar su dato biométrico (marca la casilla de autorización).")
    has_roster = bool(roster_upload) or (roster_file is not None and bool(roster_file.filename))
    use_steps, why = bulk_steps.decide(event, has_zip, has_roster)
    if append and not use_steps:
        raise HTTPException(status_code=400, detail=f"«Solo agregar personas nuevas» no está disponible en este servidor ({why}).")
    if append and (blocked := event_rules.roster_block_reason(event, append_only=True)):
        raise HTTPException(status_code=400, detail=blocked)
    if background:      # por qué camino va CADA carga (sin datos personales): así se ve en el log si una carga solo de Excel cae al Job y por qué
        log.info("carga masiva: camino=%s motivo=%s backend=%s evento=%s", "pasos" if use_steps else ("job" if bulk_jobs.uses_cloud_run() else "hilo"), why,
                 os.getenv("BULK_BACKEND", "thread"), event.id)
    if background and bulk_jobs.uses_cloud_run() and not use_steps:      # el Job de Cloud Run: cargas con fotos; la base sola va por pasos (app/bulk_steps.py)
        return _launch_bulk_cloud_run(db, event, staff, roster_file, zip_file, roster_upload, zip_upload, field_labels, source_event_id, zip_ignored, _truthy(overwrite_birth))
    # Archivos grandes: llegan ya subidos al almacenamiento (`*_upload`, ver app/uploads.py); los chicos pueden seguir viniendo en la petición.
    roster_up = uploads.fetch(roster_upload, "bulk_roster", {"e": event_id})
    zip_up = uploads.fetch(zip_upload, "bulk_zip", {"e": event_id})
    content = roster_up.content if roster_up else (roster_file.file.read() if (roster_file is not None and roster_file.filename) else None)
    roster_filename = roster_up.filename if roster_up else (roster_file.filename if content is not None else None)
    zip_bytes = zip_up.content if zip_up else (zip_file.file.read() if (zip_file is not None and zip_file.filename) else None)
    args = dict(event_id=event_id, roster_filename=roster_filename,
                content=content, zip_bytes=zip_bytes, field_labels=field_labels, source_event_id=source_event_id, zip_ignored=zip_ignored, overwrite_birth=_truthy(overwrite_birth), append_only=append)

    def cleanup(result):
        # NEEDS_LABELS: el navegador reenvía la MISMA carga con los nombres de las columnas; los archivos temporales tienen que seguir ahí.
        if not (isinstance(result, dict) and result.get("result") == "NEEDS_LABELS"):
            uploads.discard(roster_up, zip_up)
        return result

    if not background:
        return cleanup(_bulk_register_impl(db, staff, **args))

    if bulk_steps.eligible(event, zip_bytes, content):          # sin fotos: carga POR PASOS, cada paso dentro de su petición (en Cloud Run un hilo casi no recibe CPU; ver app/bulk_steps.py)
        return {"background": True, **bulk_steps.start(db, event, staff, args, cleanup)}

    if bulk_jobs.active_job(db, event_id):
        raise HTTPException(status_code=409, detail="Ya hay una carga en curso para este evento — espera a que termine.")
    job_id = bulk_jobs.create_job(db, event_id, staff.id)
    staff_id = staff.id

    def work(job_db, reporter):
        worker_staff = job_db.query(StaffUser).filter(StaffUser.id == staff_id).first()
        return cleanup(_bulk_register_impl(job_db, worker_staff, progress=reporter, **args))

    bulk_jobs.start(job_id, work)
    return {"background": True, "job_id": job_id, "mode": "thread", "reason": why}


def _launch_bulk_cloud_run(db, event, staff, roster_file, zip_file, roster_upload, zip_upload, field_labels, source_event_id, zip_ignored=False, overwrite_birth=False) -> dict:
    """BULK_BACKEND=cloudrun: la carga la ejecuta un Cloud Run Job. Aquí NO se descargan los archivos (un ZIP de 2 GB no cabe en el
    servicio web): solo se guardan sus tokens; los que vinieron en la petición se dejan antes en el almacenamiento (`uploads.stash`)."""
    scope = {"e": event.id}

    def token(upload_token, file, purpose):
        if upload_token:
            uploads.read_token(upload_token)                 # firma y vigencia de una vez; propósito y alcance los revisa el Job
            return upload_token
        if file is not None and file.filename:
            return uploads.stash(purpose, scope, event.tenant_id, file.filename, file.file.read(), file.content_type or "application/octet-stream")
        return None

    spec = {"roster": token(roster_upload, roster_file, "bulk_roster"), "zip": token(zip_upload, zip_file, "bulk_zip"),
            "field_labels": field_labels, "source_event_id": source_event_id, "zip_ignored": zip_ignored, "overwrite_birth": overwrite_birth}
    if bulk_jobs.active_job(db, event.id):
        raise HTTPException(status_code=409, detail="Ya hay una carga en curso para este evento — espera a que termine.")
    job_id = bulk_jobs.create_job(db, event.id, staff.id, spec)
    try:
        bulk_jobs.launch_cloud_run(job_id)
    except Exception:  # noqa: BLE001 — la tarea queda marcada con el error y el navegador lo muestra
        log.error("no se pudo lanzar el Job de la carga %s", job_id, exc_info=True)
        bulk_jobs._finish(job_id, error_status=503, error_detail="No se pudo iniciar el procesamiento de la carga. Intenta de nuevo en unos minutos.")
        raise HTTPException(status_code=503, detail="No se pudo iniciar el procesamiento de la carga. Intenta de nuevo en unos minutos.")
    return {"background": True, "job_id": job_id, "mode": "job"}


def run_bulk_spec(db: Session, job, progress) -> dict:
    """Lo que ejecuta el Cloud Run Job (`app/bulk_runner.py`) con lo que dejó `_launch_bulk_cloud_run`."""
    spec, event_id = json.loads(job.spec_json), job.event_id
    staff = db.query(StaffUser).filter(StaffUser.id == job.staff_user_id).first()
    roster_up = uploads.fetch(spec.get("roster"), "bulk_roster", {"e": event_id})
    zip_up = uploads.fetch(spec.get("zip"), "bulk_zip", {"e": event_id})
    result = _bulk_register_impl(
        db, staff, event_id=event_id, roster_filename=roster_up.filename if roster_up else None, content=roster_up.content if roster_up else None,
        zip_bytes=zip_up.content if zip_up else None, field_labels=spec.get("field_labels"), source_event_id=spec.get("source_event_id"), progress=progress,
        zip_ignored=bool(spec.get("zip_ignored")), overwrite_birth=bool(spec.get("overwrite_birth")))
    if not (isinstance(result, dict) and result.get("result") == "NEEDS_LABELS"):     # NEEDS_LABELS: la misma carga vuelve con los nombres
        uploads.discard(roster_up, zip_up)
    return result


_TIMING_KEYS = ("prep_client_ms", "sign_ms", "put_ms", "post_ms", "first_step_ms", "steps_ms", "total_ms", "rows", "steps", "bytes")


@router.post("/bulk_timing")
def bulk_timing(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    """Tiempos de una carga medidos EN EL NAVEGADOR (preparación, firma de la subida, subida, POST, primer paso, pasos, total): solo números y el tipo de camino, a la bitácora, para ver en qué fase se va el
    tiempo junto con las líneas «carga masiva: fases» del servidor. Sin datos personales."""
    out = {k: round(float(data[k]), 1) for k in _TIMING_KEYS if isinstance(data.get(k), (int, float)) and not isinstance(data.get(k), bool)}
    out["mode"] = str(data.get("mode") or "")[:12]
    out["job"] = str(data.get("job_id") or "")[:8]
    log.info("carga masiva: tiempos del navegador " + json.dumps(out))
    return {"ok": True}


@router.get("/bulk_steps/active")       # OJO: NO bajo /api/bulk_jobs/*: Firebase manda esa ruta (un segmento) al servicio de biometría, que no la sirve (ver app/appmode.py)
def bulk_job_active(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """La carga por pasos de esta persona que quedó a medias en este evento (para retomarla tras cerrar la página)."""
    get_event_for_staff(event_id, db, staff)
    return {"job": bulk_steps.active_for(db, event_id, staff)}


@router.post("/bulk_jobs/{job_id}/step")
def bulk_job_step(
    job_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Procesa el siguiente grupo de filas de una carga por pasos (idempotente; ver app/bulk_steps.py) y devuelve el estado."""
    return bulk_steps.run_step(db, job_id, staff)


@router.get("/bulk_jobs/{job_id}")
def bulk_job_status(
    job_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Avance de una carga en segundo plano: estado, etapa, `done`/`total` (unidades ponderadas) y, al terminar,
    el resultado (o el error) que antes devolvía la petición."""
    job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Carga no encontrada")
    get_event_for_staff(job.event_id, db, staff)
    if bulk_steps._is_steps(job):
        return bulk_steps.serialize_job(job)
    return bulk_jobs.serialize(job, db)


def _bulk_register_impl(
    db: Session, staff: StaffUser, event_id: int, roster_filename, content, zip_bytes, field_labels, source_event_id, progress=None, zip_ignored: bool = False, overwrite_birth: bool = False, step: Optional[dict] = None, append_only: bool = False,
):
    """Carga la base de asistentes esperados para el evento — sirve para CUALQUIER método de
    registro (cédula, facial, QR futuro), no es exclusiva de facial. roster_file acepta .csv o
    .xlsx (Historia 1.1: el negocio manda Excel). zip_file es OPCIONAL: solo hace falta si además
    quieres que estas personas se puedan reconocer por cara (las fotos del zip, nombradas
    <cédula>.jpg, se procesan a encoding biométrico). Sin zip, solo se cargan datos de identidad +
    se asocian al evento (EventAttendee) — suficiente para acreditar por cédula. Los errores de
    fila no abortan la carga completa, se reportan al final. No se permite cargar sobre un evento
    ya 'finalizado' (sí sobre 'creado' o 'en_proceso' — es preparación previa al evento).

    Campos dinámicos "opcional_1".."opcional_30" (2026-09-20): además de las columnas fijas
    (id, nombres, apellidos, cargo, entidad, telefono, correo, "tipo de asistente"), el roster
    puede traer hasta 30 columnas "opcional_N" — se interpretan las que de verdad vengan usadas
    (con al menos un valor no vacío en alguna fila), el resto se ignoran. Si el archivo trae
    columnas opcionales que este evento todavía no tiene rotuladas (Event.optional_field_labels),
    se devuelve {"result": "NEEDS_LABELS", "fields": [...]} SIN procesar nada — el frontend debe
    preguntarle al operador a qué corresponde cada una y reenviar la misma petición con
    field_labels (JSON, ej. {"opcional_1": "Talla de camisa"}) para que se guarden y se continúe
    con la carga."""
    # Carga POR PASOS (24-oct-2026, app/bulk_steps.py): `step={"phase": "prepare"}` hace todo lo previo a las filas y devuelve lo preparado; `step={"phase": "rows", ...}` procesa SOLO el siguiente grupo
    # de filas (cada paso dentro de su propia petición, reanudable e idempotente). Sin `step`, una carga completa como siempre.
    resume = bool(step and step.get("phase") == "rows")
    phases = _Phases()
    event = get_event_for_staff(event_id, db, staff)
    # Una sola regla (app/event_rules.py `roster_block_reason`), la misma que usa la pantalla para avisar ANTES: finalizado nunca; en proceso solo si todavía no tuvo una carga exitosa
    # (volver a cargar pisaría o duplicaría registros hechos en vivo, 2026-09-22). En los pasos siguientes al primero no se repite: el primero ya la aplicó.
    blocked = None if resume else event_rules.roster_block_reason(event, append_only=append_only)
    if blocked:
        raise HTTPException(status_code=400, detail=blocked)

    if zip_bytes and not resume:            # B3 (0C): topes de entradas / tamaño descomprimido / razón de compresión, antes de abrir nada
        try:
            safe_limits.open_checked_zip(zip_bytes).close()
        except safe_limits.LimitError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message)
    if append_only and not resume:          # «solo agregar» (app/roster_append.py): solo por pasos, solo con el archivo de la base, sin fotos ni eventos de origen, sin crear campos
        if zip_bytes:
            raise HTTPException(status_code=400, detail=roster_append.ZIP_REJECTED)
        if source_event_id:
            raise HTTPException(status_code=400, detail=roster_append.SOURCE_REJECTED)
        if content is None or not step or step.get("phase") != "prepare":
            raise HTTPException(status_code=400, detail=roster_append.NEEDS_FILE)
        field_labels = None
    if not resume:
        # Ítem 18 (reunión 2026-09-21): además de (o en vez de) un Excel nuevo, se puede traer a todas las
        # personas de OTRO evento del MISMO cliente. Quedan como "No registrado" en este evento.
        has_excel = content is not None
        if not has_excel and not source_event_id:
            raise HTTPException(status_code=400, detail="Sube un archivo de base o elige un evento anterior del que traer a las personas")
        carried_ids = set()
        if not has_excel:
            carried_ids, source_name = _carry_source_events(db, event, source_event_id, staff)
            event.roster_uploaded = True
            db.commit()
            return {
                "message": f"Se agregaron {len(carried_ids)} personas de: {source_name} (quedan como No registrado).",
                "count": 0, "carried": len(carried_ids), "errors": [], "optional_labels": event.get_optional_labels(),
            }

        header_columns, rows = _read_roster_rows(roster_filename, content)
        phases.mark("leer_archivo")
        if len(rows) > ROSTER_MAX_ROWS:
            raise HTTPException(status_code=400, detail=f"El archivo tiene {len(rows):,} filas y el máximo es {ROSTER_MAX_ROWS:,} por carga. Divídelo en varios archivos y cárgalos uno tras otro.".replace(",", "."))
        # Columnas por TÍTULO: conocidas → su campo; con título propio → campo opcional nuevo (o el existente del mismo nombre); ninguna se ignora en silencio (informe `columns`).
        header_columns, rows, columns_report, auto_labels = roster_columns.canonicalize(header_columns, rows, event.get_optional_labels(), create_fields=not append_only)
        phases.mark("columnas")
        # La fecha de nacimiento solo sirve para el control de menores del reconocimiento facial: sin rostro (y sin fotos que lo vayan a encender) la columna se ignora, con aviso.
        birth_used = bool(event.facial_enabled)          # una sola fuente de verdad: el paso guiado de Parámetros (la carga ya no enciende ni apaga el rostro)
        birth_ignored_rows = 0
        if not birth_used:
            birth_ignored_rows = sum(1 for r in rows if str(r.get("fecha de nacimiento") or "").strip())      # filas que traían fecha y no se guardarán: se avisa en el resumen
            roster_columns.drop_column(header_columns, rows, columns_report, "fecha de nacimiento", "no se usa en este evento (no tiene reconocimiento facial)")

        # 2026-09-16, pedido explícito: antes, un archivo con columnas completamente distintas a la
        # plantilla se procesaba igual — cada fila terminaba reportada como "❌ sin ID/cédula" (porque
        # ninguna columna reconocida traía nada), pero la carga "completaba" con 0 perfiles sin dejar
        # claro que el problema real era el FORMATO del archivo, no los datos. Ahora se valida de una
        # que las columnas mínimas de la plantilla estén presentes antes de procesar ninguna fila.
        has_id_col = any(k in header_columns for k in _ID_KEYS)
        has_nombres_col = any(k in header_columns for k in ('nombres', 'nombre'))
        has_apellidos_col = any(k in header_columns for k in ('apellidos', 'apellido'))
        if not rows or not (has_id_col and has_nombres_col and has_apellidos_col):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Este archivo no tiene el formato esperado — deben venir al menos las columnas "
                    "'id' (o 'cédula'), 'nombres' y 'apellidos'. Descarga y usa la plantilla oficial "
                    "de carga de asistentes en vez de un archivo con otras columnas."
                ),
            )

        used_optional_keys = set()
        for row in rows:
            for raw_key, value in row.items():
                norm = _normalize_optional_key(raw_key)
                if norm and (value or "").strip():
                    used_optional_keys.add(norm)

        missing = used_optional_keys - set(event.get_optional_labels().keys()) - set(auto_labels)          # los de título propio ya traen su nombre: no se pregunta
        if missing and not field_labels:
            # 2026-09-16, pedido explícito: hasta 2 valores de ejemplo por campo (tal como vienen en
            # el archivo) para que el operador identifique a qué corresponde sin tener que abrir el
            # Excel — ej. si "opcional_1" trae "Talla M"/"Talla L", eso mismo se muestra al preguntar.
            examples = _optional_field_examples(rows, missing)
            return {
                "result": "NEEDS_LABELS",
                "fields": sorted(missing, key=lambda k: int(k.split("_")[1])),
                "examples": examples,
            }

        labels_to_apply = {}
        if field_labels:
            try:
                labels_to_apply = dict(json.loads(field_labels) or {})
            except (json.JSONDecodeError, TypeError, ValueError):
                labels_to_apply = {}
        for slot, title in auto_labels.items():
            labels_to_apply.setdefault(slot, title)
        if labels_to_apply:
            _apply_optional_labels(event, used_optional_keys, json.dumps(labels_to_apply))
            db.commit()

        source_name = ""
        if source_event_id:
            carried_ids, source_name = _carry_source_events(db, event, source_event_id, staff)

        # Se declara acá (antes solo existía más abajo, en el pre-escaneo) para que el bloque del zip
        # de abajo pueda reportar en la misma lista — mismo criterio de prefijos (❌/⚠️/ℹ️) que el
        # resto del archivo, sin inventar un campo nuevo que el frontend no sepa mostrar.
        errors = []
        if zip_ignored:
            errors.append("⚠️ Este evento no usa biometría (bloqueado): el zip de fotos se ignoró, no se guardó ninguna foto y el reconocimiento facial no se activó.")
        # identificador -> encoding ya calculada al leer el zip (2026-09-22): antes se calculaba acá
        # Y OTRA VEZ más abajo (al releer la misma foto del disco) — el costo real de una carga masiva
        # es el encoding facial (num_jitters=25, ver CLAUDE.md), así que calcularlo dos veces por foto
        # duplicaba sin necesidad el tiempo de procesamiento de cada lote.
        zip_encodings = {}
        zip_photos = set()
        # REGLA A (2026-10-06): NINGÚN flujo calcula el vector de alguien que aún no aceptó. Solo se pre-calcula en un evento de un tercero con el pre-cálculo autorizado (anexo firmado, solo super_admin);
        # en todo lo demás las fotos se guardan cifradas y el vector se calcula DESPUÉS de que la persona acepte (app/enroll.py).
        precalc = event.controller_mode == "tercero" and bool(event.precalculo_autorizado)

        progress = progress or (lambda *a, **k: None)
        photo_entries = []
        if zip_bytes:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as counting_zip:
                photo_entries = [
                    n for n in counting_zip.namelist()
                    if not (n.startswith('__MACOSX') or n.startswith('.') or n.endswith('/')) and os.path.basename(n)
                ]
        total_units = len(photo_entries) * bulk_jobs.PHOTO_WEIGHT + len(rows) * bulk_jobs.ROW_WEIGHT
        done_units = 0
        progress("Leyendo el archivo", 0, total_units, force=True)

        if zip_bytes:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
                for photo_i, filename in enumerate(photo_entries, start=1):
                    progress(f"Procesando fotos ({photo_i} de {len(photo_entries)})", done_units, total_units)
                    done_units += bulk_jobs.PHOTO_WEIGHT
                    basename = os.path.basename(filename)
                    with contextlib.nullcontext():      # la lectura con tope va en safe_limits.read_entry (B3)
                        try:
                            img_array = BiometricEngine.process_image_stream(safe_limits.read_entry(zip_ref, filename))
                        except safe_limits.LimitError as exc:
                            errors.append(f"⚠️ La foto '{basename}' del zip se omitió: {exc.message}")
                            continue
                        except Exception:
                            errors.append(f"⚠️ La foto '{basename}' del zip no se pudo leer (formato no soportado o archivo dañado) — no quedó asociada a nadie.")
                            continue
                        # Misma validación que ya hace /api/register (manual_register) para altas
                        # individuales: una foto sin rostro detectable no debe quedar guardada como si
                        # fuera una foto biométrica válida — antes se guardaba igual en silencio (bug
                        # real, QA local 2026-09-15: el coordinador nunca se enteraba de que esa
                        # persona quedó sin reconocimiento facial funcional).
                        if precalc:
                            encodings = faces.extract(img_array, jitters=BiometricEngine.BULK_JITTERS, max_side=BiometricEngine.BULK_MAX_SIDE)
                            if not encodings:
                                errors.append(f"⚠️ La foto '{basename}' del zip no tiene un rostro detectable — no se asoció como foto biométrica de esa persona.")
                                continue
                            zip_encodings[os.path.splitext(basename)[0]] = encodings
                        zip_photos.add(os.path.splitext(basename)[0])
                        crypto.save_image(Image.fromarray(img_array), photo_key(event.tenant_id, os.path.splitext(basename)[0]))      # la clave lleva la cédula SIN extensión (antes quedaba «<cédula>.jpg.jpg»: la foto no se encontraba ni la borraba la purga)

            if photo_entries and not precalc:
                errors.append("ℹ️ Las fotos se guardaron cifradas, pero su vector facial NO se calcula todavía: se calcula cuando cada persona acepta el reconocimiento facial (en la puerta o desde el celular).")

            # (Fase 0, 2026-10-17) La carga ya NO enciende el reconocimiento facial: llegar aquí con fotos exige que el paso guiado ya diga «usa rostro» con origen A.

        # --- Pre-escaneo: identificar cédulas (con corrección del "Excel las volvió número"),
        # detectar cédulas repetidas dentro del mismo archivo, ANTES de tocar la base de datos.
        # Esto es lo que le permite al operador ver de una vez, con celda exacta, qué está mal en su
        # archivo en vez de enterarse fila por fila o con un error genérico. ---
        row_infos = []
        seen_rows_by_id = {}
        for row_num, clean_row in enumerate(rows, start=2):  # fila 1 es el encabezado
            identificador, id_cell, id_note = _extract_identificador(clean_row, header_columns, row_num)
            notes = [id_note] if id_note else []
            row_infos.append({
                "row_num": row_num, "clean_row": clean_row,
                "identificador": identificador, "id_cell": id_cell, "notes": notes,
            })
            if identificador:
                seen_rows_by_id.setdefault(identificador, []).append(row_num)

        id_col = next((header_columns[k] for k in _ID_KEYS if k in header_columns), None)
        for id_val, row_nums in seen_rows_by_id.items():
            if len(row_nums) > 1 and not append_only:
                cells = ", ".join(f"{id_col}{n}" if id_col else f"fila {n}" for n in row_nums)
                errors.append(
                    f"⚠️ La cédula '{id_val}' aparece repetida en {len(row_nums)} filas ({cells}) — "
                    f"se combinaron los datos y quedó lo de la última fila."
                )


        if step and step.get("phase") == "prepare":      # solo la preparación: se devuelve lo que los pasos necesitan (la persistencia la hace app/bulk_steps.py)
            phases.mark("prescan")
            phases.emit(len(rows))
            return {"prepared": {"header_columns": header_columns, "rows": rows, "columns_report": columns_report, "birth_used": birth_used, "birth_ignored_rows": birth_ignored_rows,
                                 **({"dup_rows": roster_append.duplicate_rows(row_infos)} if append_only else {})},
                    "state": {**({"append_only": True, "append": roster_append.new_state()} if append_only else {}), "pos": 0, "errors": errors, "count": 0, "birth_bad_rows": [], "birth_kept_rows": [], "birth_completed": 0, "birth_replaced": 0,
                              "carried_ids": sorted(carried_ids), "source_name": source_name, "overwrite_birth": bool(overwrite_birth)}}
    else:
        # Reanudación: lo preparado y el avance vienen del paso anterior (guardados cifrados); aquí solo se arman las filas de ESTE paso.
        prepared, state = step["prepared"], step["state"]
        header_columns, rows, columns_report = prepared["header_columns"], prepared["rows"], prepared["columns_report"]
        birth_used, birth_ignored_rows = prepared["birth_used"], prepared["birth_ignored_rows"]
        errors, carried_ids, source_name = state["errors"], set(state["carried_ids"]), state["source_name"]
        append_only = bool(state.get("append_only"))
        zip_encodings, zip_photos, precalc = {}, set(), False        # los pasos solo atienden cargas SIN fotos ni pre-cálculo (el resto va por el camino de siempre)
        progress = progress or (lambda *a, **k: None)
        total_units, done_units = len(rows), state["pos"]
        step_pos = state["pos"]
        step_end = min(len(rows), step_pos + int(step.get("limit") or len(rows)))
        row_infos = []
        for row_num, clean_row in enumerate(rows[step_pos:step_end], start=step_pos + 2):
            identificador, id_cell, id_note = _extract_identificador(clean_row, header_columns, row_num)
            row_infos.append({"row_num": row_num, "clean_row": clean_row, "identificador": identificador, "id_cell": id_cell, "notes": [id_note] if id_note else []})
        phases.mark("armar_filas")
    if append_only:          # el resto de esta función es la carga normal (pisa a los existentes); «solo agregar» tiene su propio recorrido de filas
        return roster_append.run_step(db, event, staff, step, row_infos, header_columns, columns_report, birth_used, prepared, state, step_pos, step_end, len(rows), progress)
    if not resume:
        count = 0
        birth_bad_rows, birth_kept_rows, birth_completed, birth_replaced = [], [], 0, 0
    else:
        count, birth_bad_rows, birth_kept_rows = state["count"], list(state["birth_bad_rows"]), list(state["birth_kept_rows"])
        birth_completed, birth_replaced = state["birth_completed"], state["birth_replaced"]
        overwrite_birth = bool(state.get("overwrite_birth"))
    row_total = len(rows)
    row_offset = step_pos if resume else 0
    form_registered_ids = []          # columna «Registrado en formulario» = sí: esas cédulas quedan como YA INSCRITAS en los formularios del evento (no ocupan cupo; ver formsvc.mark_preregistered)

    # --- Rendimiento (23-oct-2026): antes cada persona costaba 9 viajes a la base (≈120 ms con Neon a 12 ms por viaje). Ahora se consulta TODO lo que ya existe de una vez (supresiones,
    # personas, inscripciones del evento: una consulta por cada 2.000 cédulas) y las filas nuevas se escriben por lotes (un INSERT múltiple por tabla y lote). Las reglas por fila no cambian. ---
    file_ids = list({i["identificador"] for i in row_infos if i["identificador"]})
    suppressed_ids, users_by_id, attendees_by_user = set(), {}, {}
    if file_ids:
        from app.models import SuppressedPerson
        hash_by_id = {i: consent_mod.cedula_hash(i) for i in file_ids}
        id_by_hash = {}
        for i, h in hash_by_id.items():
            id_by_hash.setdefault(h, []).append(i)
        for part in _chunks(list(id_by_hash), _LOOKUP_CHUNK):
            for (h,) in db.query(SuppressedPerson.cedula_hash).filter(SuppressedPerson.tenant_id == event.tenant_id, SuppressedPerson.cedula_hash.in_(part)):
                suppressed_ids.update(id_by_hash.get(h, []))
        for part in _chunks(file_ids, _LOOKUP_CHUNK):
            for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(part)):
                users_by_id[u.id] = u
            for att in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part)):
                attendees_by_user[att.user_id] = att
    new_users, new_attendees = [], []

    phases.mark("consultas_en_bloque")
    photo_state = {"calls": 0, "keys": None}

    def photo_exists(ident, known_user) -> bool:
        """¿Hay una foto guardada de esta persona? Solo importa para quien YA existe en la base (una persona nueva no tiene foto) y solo cuando cambia algo: en un evento con rostro (se borra la foto
        de un menor o sin fecha) o si todavía no tiene `face_captured_at` (arranca el reloj de retención). Las primeras consultas van una por una; si son muchas, se lista la carpeta de fotos del
        cliente UNA vez (en la nube cada `exists` era una petición a Cloud Storage por persona: 8.000 personas = minutos)."""
        if known_user is None or not (event.facial_enabled or known_user.face_captured_at is None):
            return False
        key = photo_key(event.tenant_id, f"{ident}")
        photo_state["calls"] += 1
        if photo_state["keys"] is None and photo_state["calls"] > _PHOTO_LISTING_AFTER:
            photo_state["keys"] = set(get_storage().list(photo_key(event.tenant_id, "x").rsplit("/", 1)[0]))
        if photo_state["keys"] is not None:
            return key in photo_state["keys"]
        return get_storage().exists(key)

    for chunk_start in range(0, len(row_infos), _BULK_CHUNK):
        chunk = list(enumerate(row_infos[chunk_start:chunk_start + _BULK_CHUNK], start=row_offset + chunk_start + 1))
        for isolate in (False, True):
            # Primero se intenta el lote entero en UNA transacción interna; si la base rechaza algo, se deshace SOLO ese lote y se repite fila por fila con un SAVEPOINT cada una
            # (como siempre): una fila mala se reporta y no arrastra a las demás.
            snap = (len(errors), count, len(birth_bad_rows), len(birth_kept_rows), birth_completed, birth_replaced, done_units)
            new_users.clear()
            new_attendees.clear()
            try:
                with (contextlib.nullcontext() if isolate else db.begin_nested()):
                    for row_i, info in chunk:
                        done_units += bulk_jobs.ROW_WEIGHT
                        if row_i % 50 == 0 or row_i == row_total:          # el avance se informa cada 50 filas (y el que lo escribe, como mucho una vez por segundo): nunca por fila
                            progress(f"Guardando personas ({row_i} de {row_total})", done_units, total_units)
                        row_num, clean_row, identificador = info["row_num"], info["clean_row"], info["identificador"]
                        errors.extend(info["notes"])

                        if not identificador:
                            where = info["id_cell"] or f"fila {row_num}"
                            errors.append(f"❌ Fila {row_num} ({where}): sin ID/cédula, se omitió esta fila.")
                            continue

                        if identificador in suppressed_ids:
                            errors.append(f"⚠️ Fila {row_num}: esta persona solicitó la supresión de sus datos — se omitió (no se volvió a crear).")
                            continue

                        if identificador in carried_ids:
                            # Ítem 18: un ID repetido entre el evento anterior y el Excel queda como UN solo registro,
                            # y prevalece el dato del evento anterior — no se toca a la persona que ya existe.
                            errors.append(f"ℹ️ Fila {row_num}: la cédula '{identificador}' ya venía del evento anterior — se conservaron sus datos del evento anterior (no se duplicó).")
                            continue

                        # Validaciones de calidad de dato — no bloquean la fila (se guarda igual), solo avisan
                        # exactamente en qué celda está el problema para que el operador lo revise si quiere.
                        nombres, nombres_cell = _field_lookup(clean_row, header_columns, row_num, 'nombres', 'nombre')
                        if not nombres:
                            errors.append(f"⚠️ Fila {row_num} ({nombres_cell or 'sin columna de nombres'}): falta el nombre.")
                        apellidos, apellidos_cell = _field_lookup(clean_row, header_columns, row_num, 'apellidos', 'apellido')
                        if not apellidos:
                            errors.append(f"⚠️ Fila {row_num} ({apellidos_cell or 'sin columna de apellidos'}): falta el apellido.")
                        correo, correo_cell = _field_lookup(clean_row, header_columns, row_num, 'correo', 'e-mail corporativo')
                        if correo and not _EMAIL_RE.match(correo):
                            errors.append(f"⚠️ Fila {row_num} ({correo_cell}): el correo '{correo}' no parece válido — se guardó igual, revísalo.")
                        telefono, telefono_cell = _field_lookup(clean_row, header_columns, row_num, 'telefono', 'tel. celular')
                        if telefono and not _PHONE_RE.match(telefono):
                            errors.append(f"⚠️ Fila {row_num} ({telefono_cell}): el teléfono '{telefono}' tiene caracteres raros — se guardó igual, revísalo.")

                        try:
                            face_enc_json = None
                            if str(identificador) in zip_encodings:
                                face_enc_json = json.dumps(zip_encodings[str(identificador)])
                            elif precalc:
                                img_key = photo_key(event.tenant_id, f"{identificador}")
                                if get_storage().exists(img_key):
                                    stored = crypto.read_array(img_key)          # la foto guardada puede estar cifrada
                                    enc = faces.extract(stored, jitters=BiometricEngine.BULK_JITTERS, max_side=BiometricEngine.BULK_MAX_SIDE) if stored is not None else None
                                    if enc:
                                        face_enc_json = json.dumps(enc)
                            # Menores (L3): la fecha de nacimiento (columna opcional «fecha de nacimiento») decide. Menor de 18 → sin vector ni foto y sin biometría; sin fecha, el rostro no se conserva.
                            birth_raw = next((clean_row[k] for k in _BIRTH_KEYS if clean_row.get(k)), "") if birth_used else ""
                            birth = minors.parse_birth(birth_raw)
                            if birth_raw and birth is None:
                                errors.append(f"⚠️ Fila {row_num}: la fecha de nacimiento '{birth_raw}' no es válida (usa AAAA-MM-DD, DD/MM/AAAA o una fecha de Excel).")
                                birth_bad_rows.append(row_num)
                            # Una persona que ya tenía una fecha válida distinta NO la pierde por una recarga (salvo que el coordinador marque «reemplazar»): manda la guardada. Quien no tenía fecha, la completa.
                            known_user = users_by_id.get(identificador)
                            stored_birth = known_user.birth_date if known_user is not None else None
                            birth_action = ""
                            if birth is not None and stored_birth is not None and stored_birth != birth:
                                if overwrite_birth:
                                    birth_action = "replaced"
                                else:
                                    birth_action = "kept"
                                    birth_kept_rows.append(row_num)
                                    errors.append(f"⚠️ Fila {row_num}: ya tenía una fecha de nacimiento guardada distinta a la del archivo; no se cambió (marca «{OVERWRITE_BIRTH_LABEL}» si quieres cambiarla).")
                                    birth = stored_birth
                            elif birth is not None and stored_birth is None:
                                birth_action = "completed"
                            row_minor = minors.is_minor(birth)
                            has_photo = str(identificador) in zip_photos or photo_exists(identificador, known_user)
                            if birth_used and (face_enc_json or has_photo) and (row_minor or birth is None):
                                face_enc_json = None
                                has_photo = False
                                get_storage().delete(photo_key(event.tenant_id, f"{identificador}"))
                                errors.append(f"⚠️ Fila {row_num}: " + ("es menor de 18 años: no se guardó su rostro (solo cédula o QR)." if row_minor else "tiene foto pero no fecha de nacimiento: no se guardó su rostro (solo se capta el rostro de mayores de 18 años)."))

                            # SAVEPOINT por fila (no solo un try/except de Python): con autoflush=False, una sola
                            # fila con un problema real de base de datos (ej. una violación de llave) dejaba la
                            # transacción completa "abortada" para Postgres, y el error solo aparecía hasta el
                            # db.commit() final — tumbando TODA la carga con un 500, incluidas las filas que sí
                            # habían "funcionado" en Python pero nunca llegaron a guardarse. Con begin_nested(),
                            # si esta fila falla se revierte solo su savepoint (la transacción de afuera sigue
                            # sana) y el flush() intermedio asegura que el INSERT de User ya se mandó a Postgres
                            # antes del de EventAttendee (que depende de él por llave foránea).
                            with (db.begin_nested() if isolate else contextlib.nullcontext()):
                                user = users_by_id.get(identificador)
                                if not user:
                                    user = User(id=identificador, tenant_id=event.tenant_id)
                                    db.add(user)
                                    users_by_id[identificador] = user
                                    new_users.append(identificador)

                                user.first_name = nombres
                                user.last_name = apellidos
                                user.role = clean_row.get('cargo', '')
                                user.entity = clean_row.get('entidad', '') or clean_row.get('empresa', '')  # 'empresa' = columna del nombre viejo, sigue aceptándose en Excels ya armados
                                user.phone = telefono
                                user.email = correo
                                user.opt_1 = clean_row.get('tipo de asistente', '') or clean_row.get('tipo_asistente', '')
                                if birth is not None and birth_action != "kept":
                                    if birth_action == "replaced":
                                        db.add(PersonChange(tenant_id=event.tenant_id, event_id=event.id, user_id=user.id, staff_user_id=staff.id if staff else None, kind="birth_date",
                                                            old_value=stored_birth.isoformat(), new_value=birth.isoformat(), detail="reemplazada por una recarga de la base"))
                                        birth_replaced += 1
                                    elif birth_action == "completed":
                                        birth_completed += 1
                                    user.birth_date = birth
                                    user.is_biometric_enabled = not row_minor
                                    if row_minor:
                                        user.face_encoding = None
                                if has_photo and not face_enc_json and user.face_captured_at is None:
                                    user.face_captured_at = utcnow()          # foto guardada sin vector: el reloj de retención (7 días / tope de 180) corre igual

                                extras = {}
                                for raw_key, value in clean_row.items():
                                    norm = _normalize_optional_key(raw_key)
                                    val = (value or "").strip()
                                    if norm and val:
                                        extras[norm] = val
                                user.set_extras(extras)

                                if face_enc_json:
                                    user.face_encoding = face_enc_json
                                    user.biometric_consent_at, user.biometric_consent_source = utcnow(), "carga_masiva"

                                if isolate:
                                    db.flush()           # el User ya existe en la base antes que su inscripción (lo que antes hacía cada fila; por lotes se hace al cerrar el lote)
                                # Categorías (ítem 14): columna "categoria"/"categorias" (con o sin tilde), varias
                                # separadas por coma/;/|. Las que el evento no conocía se agregan solas.
                                raw_categories = next((clean_row[k] for k in ("categoria", "categorias", "categoría", "categorías") if clean_row.get(k)), None)
                                raw_certificate = clean_row.get('certificado')
                                _upsert_attendee_cached(
                                    db, event.id, identificador, event.tenant_id, attendees_by_user, new_attendees,
                                    _clean_categories(event, raw_categories, auto_add=True) if raw_categories else None,
                                    certificate=_truthy(raw_certificate) if raw_certificate else None,
                                )
                                if _truthy(clean_row.get('registrado en formulario') or ''):
                                    form_registered_ids.append(identificador)
                                if isolate:
                                    db.flush()

                            count += 1
                        except Exception as e:
                            if not isolate:                 # sin SAVEPOINT por fila no se puede deshacer SOLO esta fila: se deshace el lote y se repite fila por fila
                                raise _RetryRowByRow() from e
                            where = info["id_cell"] or f"fila {row_num}"
                            errors.append(f"❌ Fila {row_num} ({where}): no se pudo guardar — {e}")

                    if not isolate:
                        db.flush()
                break
            except SQLAlchemyError:
                if isolate:
                    raise
                for uid in new_users:
                    users_by_id.pop(uid, None)
                for uid in new_attendees:
                    attendees_by_user.pop(uid, None)
                del errors[snap[0]:]
                del birth_bad_rows[snap[2]:]
                del birth_kept_rows[snap[3]:]
                count, birth_completed, birth_replaced, done_units = snap[1], snap[4], snap[5], snap[6]
                log.warning("carga masiva: un lote fue rechazado por la base; se repite fila por fila")
        phases.lap()

    if form_registered_ids:
        try:
            with db.begin_nested():
                formsvc.mark_preregistered(db, event, form_registered_ids)
        except SQLAlchemyError:
            log.warning("carga masiva: no se pudo marcar «registrado en formulario»", exc_info=True)
            errors.append("⚠️ No se pudo marcar a las personas «Registrado en formulario»: vuelve a cargar el mismo archivo.")
    if resume and step_end < row_total:             # paso intermedio: se devuelve el avance; la persistencia y el commit los hace app/bulk_steps.py
        phases.emit(len(row_infos))
        return {"done": False, "state": {"pos": step_end, "errors": errors, "count": count, "birth_bad_rows": birth_bad_rows, "birth_kept_rows": birth_kept_rows,
                                          "birth_completed": birth_completed, "birth_replaced": birth_replaced, "carried_ids": sorted(carried_ids), "source_name": source_name,
                                          "overwrite_birth": bool(overwrite_birth)}}

    if (count > 0 or carried_ids) and not event.roster_uploaded:
        event.roster_uploaded = True

    # Resumen de las fechas de nacimiento (avisa lo que no se pudo guardar y por qué)
    if birth_ignored_rows:
        errors.insert(0, f"⚠️ {birth_ignored_rows} fila(s) traían fecha de nacimiento y NO se guardaron porque este evento no tiene el reconocimiento facial activo. Actívalo y vuelve a cargar el mismo archivo: se completarán las fechas.")
    if birth_bad_rows:
        shown = ", ".join(str(n) for n in birth_bad_rows[:30]) + ("…" if len(birth_bad_rows) > 30 else "")
        errors.insert(0, f"⚠️ {len(birth_bad_rows)} fila(s) con fecha de nacimiento que no se pudo entender: fila(s) {shown}. Usa DD/MM/AAAA, AAAA-MM-DD o una fecha de Excel.")
    birth_summary = {"completed": birth_completed, "replaced": birth_replaced, "kept_rows": birth_kept_rows, "unreadable_rows": birth_bad_rows, "ignored_rows": birth_ignored_rows}
    db.commit()
    message = f"Carga completa: {count} perfiles cargados."
    if carried_ids:
        message += f" Además, {len(carried_ids)} personas traídas de: {source_name}."
    if errors:
        message += f" {len(errors)} observación(es) — revisa el detalle."
    message += " " + roster_columns.summary(columns_report)
    phases.mark("resumen")
    phases.emit(row_total)
    return {"message": message, "count": count, "errors": errors, "optional_labels": event.get_optional_labels(), "columns": columns_report, "birth": birth_summary}

@router.get("/report")
def download_report(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
    # 2026-09-17 (pedido explícito): 'cliente' ve Estadísticas (gráficos, vía
    # require_role_or_client en stats.py) pero YA NO puede exportar la base — antes usaba el mismo
    # require_role_or_client que las gráficas, ahora exige coordinador+ como cualquier otra
    # acción operativa, sin la excepción de cliente.
):
    event = get_event_for_staff(event_id, db, staff)
    return heavy.excel_response(lambda path: ReportManager.generate_excel_report(db, event.id, event.tenant_id, path), heavy.event_report_filename(event, "Reporte final"))


@router.get("/events/{event_id}/incomplete-registrations")
def incomplete_registrations(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """A3: personas YA registradas en este evento a las que les falta un obligatorio (se acreditaron sin conexión, o el campo se volvió obligatorio después). La pantalla las lista
    como «falta completar» para abrir «Editar persona» en el campo vacío. Sin columnas nuevas: se calcula con los datos de hoy."""
    event = get_event_for_staff(event_id, db, staff)
    field_configs = [c for c in parametros.field_configs_for_event(db, event) if c["field_type"] not in SKIP_REQUIRED_TYPES and not c.get("locked")]
    if not any(c["required"] for c in field_configs):
        return {"count": 0, "people": []}
    ids = {u for (u,) in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado").distinct()}
    if not ids:
        return {"count": 0, "people": []}
    attendees = {a.user_id: a for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(ids))}
    people = []
    for user in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids)):
        att = attendees.get(user.id)
        values = {"role": user.role, "entity": user.entity, "phone": user.phone, "email": user.email, "opt_1": user.opt_1, **user.get_extras(),
                  "birth_date": user.birth_date.isoformat() if getattr(user, "birth_date", None) else "",
                  "certificate": "true" if (att and att.certificate) else "", "digital_contact": (att.digital_contact if att else "") or ""}
        labels = set(_missing_required_fields(field_configs, values))
        if labels:
            people.append({"id": user.id, "first_name": user.first_name, "last_name": user.last_name,
                           "missing": [{"key": c["key"], "label": c["label"]} for c in field_configs if c["required"] and c["label"] in labels]})
    people.sort(key=lambda p: (p["last_name"] or "", p["first_name"] or ""))
    return {"count": len(people), "people": people[:200]}
