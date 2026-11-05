"""Formulario de PERSONA diseñado por el admin (Fase 1A, pieza 5; docs/15 «Plan 4»).

Reutiliza el motor de los formularios web SIN su parte pública ni los pagos: la misma forma de diseño (`rows` con hasta 4 campos uno al lado del otro, `sheets` = grupos, `show_if` por
campo, validado con `app/formlib.py`) pero sobre los campos que el evento YA tiene (`parametros.field_configs_for_event`: identidad, fijos y `opcional_N`, sin tope). Se usa al CREAR
(«Registrar nuevo») y al EDITAR personas en el quiosco, y viaja VERSIONADA a la copia local sin red (`form_version`).

Diseño guardado (JSON en `app_settings`, clave `person_form:<evento>`, SIN columna nueva ni migración):
  {"enabled": bool, "form_version": int,
   "sheets": [{"id", "title", "open"}],                       # grupos; uno que lleva un obligatorio queda SIEMPRE abierto (a la vista)
   "rows":   [{"sheet": id, "items": [clave, ...hasta 4]}],    # una fila = campos uno al lado del otro (columnas)
   "fields": {clave: {"required": bool, "text_case": ""|"upper"|"lower", "show_if": {...}?}}}
Lo OBLIGATORIO no se guarda dos veces: al guardar el diseño se escribe en `event_field_configs.required` (la única fuente que ya validan manual_register, update_user, la bandeja y la
acreditación). «Texto al escribir» (`text_case`) solo vale para texto: nombres, apellidos, cargo, entidad y opcionales de texto; NUNCA cédula, teléfono ni fecha; el correo SIEMPRE va en minúsculas.

Interruptores: `PERSON_FORM_ENABLED` (entorno, APAGADO por defecto: con él apagado nada de esto se ve ni se aplica) y `enabled` dentro del diseño de CADA evento (también apagado por defecto)."""
import hashlib
import json
import os
import re
from typing import Optional

from app import formlib, roster_text
from app.models import AppSetting, EventFieldConfig
from app.timeutil import utcnow

ENV_FLAG = "PERSON_FORM_ENABLED"
MAX_FIELDS, MAX_SHEETS, MAX_ROW_ITEMS = 700, 12, 4
TEXT_FIELD_TYPES = ("text_short", "text_long")
FIXED_TEXT_KEYS = ("first_name", "last_name", "role", "entity", "opt_1")       # fijos que admiten mayúsculas/minúsculas (si su tipo es texto)
ALWAYS_REQUIRED = ("id", "first_name")           # cédula y nombres: siempre obligatorios
NEVER_REQUIRED = ("last_name", "categories", "birth_date")      # el apellido puede ir vacío (viene junto con los nombres, como en la carga flexible)
CASE_MODES = ("", roster_text.UPPER, roster_text.LOWER)
DEFAULT_OPEN_SHEET, DEFAULT_MORE_SHEET, DEFAULT_OTHER_SHEET = "datos", "mas", "otros"
MORE_COUNT = 7        # cuántos campos van en «Más datos»; el resto, en «Otros datos»


def env_enabled() -> bool:
    return os.getenv(ENV_FLAG, "0").strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def setting_key(event_id: int) -> str:
    return f"person_form:{event_id}"           # app_settings.key mide 64: cabe de sobra


# ------------------------------------------------------------------ qué admite cada campo
def case_capable(cfg: dict) -> bool:
    """¿Admite «Texto al escribir»? Solo campos de TEXTO del evento (nunca cédula, teléfono, correo, fecha, listas ni casillas)."""
    key = str(cfg.get("key") or "")
    if cfg.get("field_type") not in TEXT_FIELD_TYPES:
        return False
    return key in FIXED_TEXT_KEYS or bool(re.fullmatch(r"opcional_\d+", key))


def required_editable(cfg: dict) -> bool:
    return cfg.get("key") not in ALWAYS_REQUIRED and cfg.get("key") not in NEVER_REQUIRED


def _signature(configs: list) -> str:
    """Huella de lo que el evento define para cada campo (clave, nombre, tipo, obligatorio, opciones): si cambia en Parámetros, un dispositivo con la copia anterior lo sabe."""
    raw = json.dumps([[c["key"], c.get("label"), c.get("field_type"), bool(c.get("required")), c.get("options") or []] for c in configs], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:10]  # huella de versión, no de seguridad


# ------------------------------------------------------------------ diseño por defecto
def _pack(keys: list, sheet: str, rows: list) -> None:
    for i in range(0, len(keys), 2):
        rows.append({"sheet": sheet, "items": keys[i:i + 2]})


def default_design(configs: list) -> dict:
    """~10 campos a la vista: cédula, nombres y apellidos arriba + los que el evento marcó obligatorios; el resto, en grupos que se despliegan."""
    keys = [c["key"] for c in configs]
    top = [k for k in ("id", "first_name", "last_name") if k in keys]
    top += [c["key"] for c in configs if c.get("required") and c["key"] not in top]
    rest = [k for k in keys if k not in top]
    sheets, rows = [{"id": DEFAULT_OPEN_SHEET, "title": "Datos principales", "open": True}], []
    if "id" in top:
        rows.append({"sheet": DEFAULT_OPEN_SHEET, "items": ["id"]})
    names = [k for k in ("first_name", "last_name") if k in top]
    if names:
        rows.append({"sheet": DEFAULT_OPEN_SHEET, "items": names})
    _pack([k for k in top if k not in ("id", "first_name", "last_name")], DEFAULT_OPEN_SHEET, rows)
    if rest[:MORE_COUNT]:
        sheets.append({"id": DEFAULT_MORE_SHEET, "title": "Más datos", "open": False})
        _pack(rest[:MORE_COUNT], DEFAULT_MORE_SHEET, rows)
    if rest[MORE_COUNT:]:
        sheets.append({"id": DEFAULT_OTHER_SHEET, "title": "Otros datos", "open": False})
        _pack(rest[MORE_COUNT:], DEFAULT_OTHER_SHEET, rows)
    return {"enabled": False, "form_version": 1, "sheets": sheets, "rows": rows, "fields": {}}


# ------------------------------------------------------------------ sanear lo que manda el diseñador
def _required_now(key: str, cfg: dict, field_in: dict) -> bool:
    if key in ALWAYS_REQUIRED:
        return True
    if key in NEVER_REQUIRED:
        return False
    return bool(field_in["required"]) if "required" in field_in else bool(cfg.get("required"))


def sanitize(raw: dict, configs: list) -> dict:
    """Valida el diseño del editor contra los campos REALES del evento; lanza ValueError con un mensaje legible. Lo desconocido se ignora (un campo borrado del evento no rompe el diseño)."""
    if not isinstance(raw, dict):
        raise ValueError("El diseño del formulario de persona no es válido")
    by_key = {c["key"]: c for c in configs}
    if len(by_key) > MAX_FIELDS:
        raise ValueError("Demasiados campos")
    sheets_in = raw.get("sheets") if isinstance(raw.get("sheets"), list) else []
    sheets, seen = [], set()
    for s in sheets_in[:MAX_SHEETS]:
        sid = str((s or {}).get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", sid) or sid in seen:
            raise ValueError("Grupo con identificador inválido o repetido")
        seen.add(sid)
        sheets.append({"id": sid, "title": formlib._text((s or {}).get("title"), 60) or "Grupo", "open": bool((s or {}).get("open", True))})
    if not sheets:
        sheets = [{"id": DEFAULT_OPEN_SHEET, "title": "Datos principales", "open": True}]
    sheet_ids = [s["id"] for s in sheets]
    fields_in = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    fields = {}
    for key, f in fields_in.items():
        if key not in by_key:
            continue
        f = f if isinstance(f, dict) else {}
        out = {}
        if "required" in f and key not in ALWAYS_REQUIRED and key not in NEVER_REQUIRED:
            out["required"] = bool(f["required"])
        mode = roster_text.parse_mode(f.get("text_case"))
        if mode is None:
            raise ValueError(f"«{by_key[key]['label']}»: «Texto al escribir» no es válido")
        if mode:
            if not case_capable(by_key[key]):
                raise ValueError(f"«{by_key[key]['label']}»: «Texto al escribir» solo aplica a campos de texto (no a cédula, teléfono, correo, fecha ni listas)")
            out["text_case"] = mode
        fields[key] = out
    placeholders = {k: {} for k in by_key}
    for key, f in fields_in.items():
        if key not in by_key or not isinstance(f, dict) or not f.get("show_if"):
            continue
        cond = formlib._sanitize_condition(f["show_if"], placeholders, key)
        if cond:
            if _required_now(key, by_key[key], fields[key]):
                raise ValueError(f"«{by_key[key]['label']}»: un campo obligatorio no puede aparecer solo según otro campo. Quita la condición o el «obligatorio»")
            fields[key]["show_if"] = cond
    formlib._check_condition_cycles({k: {"show_if": fields.get(k, {}).get("show_if")} for k in by_key})
    rows, placed = [], set()
    for row in raw.get("rows") if isinstance(raw.get("rows"), list) else []:
        items = [i for i in ((row or {}).get("items") or []) if i in by_key and i not in placed]
        if not items:
            continue
        if len(items) > MAX_ROW_ITEMS:
            raise ValueError(f"Una fila admite hasta {MAX_ROW_ITEMS} campos uno al lado del otro")
        placed.update(items)
        sid = (row or {}).get("sheet")
        rows.append({"sheet": sid if sid in sheet_ids else sheet_ids[0], "items": items})
    missing = [c["key"] for c in configs if c["key"] not in placed]        # un campo del evento que el diseño no menciona va al final, en el último grupo
    _pack(missing, sheet_ids[-1], rows)
    for sheet in sheets:                                                   # un grupo con un obligatorio queda abierto: lo obligatorio siempre está a la vista
        if any(_required_now(k, by_key[k], fields.get(k, {})) for r in rows if r["sheet"] == sheet["id"] for k in r["items"]):
            sheet["open"] = True
    return {"enabled": bool(raw.get("enabled")), "sheets": sheets, "rows": rows, "fields": fields}


# ------------------------------------------------------------------ guardado
def _row(db, event_id: int) -> Optional[AppSetting]:
    return db.query(AppSetting).filter(AppSetting.key == setting_key(event_id)).first()


def load_raw(db, event) -> Optional[dict]:
    row = _row(db, event.id)
    if not row or not row.value:
        return None
    try:
        data = json.loads(row.value)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _core(d: dict) -> str:
    return json.dumps({k: d.get(k) for k in ("enabled", "sheets", "rows", "fields")}, ensure_ascii=False, sort_keys=True)


def save(db, event, raw: dict, configs: list) -> dict:
    """Guarda el diseño (versión +1 SOLO si cambió algo) y escribe lo obligatorio en los parámetros del evento. Devuelve el diseño efectivo. El `commit` lo hace quien llama."""
    clean = sanitize(raw, configs)
    prev = load_raw(db, event)
    version = int((prev or {}).get("form_version") or 0)
    if prev is None or _core(prev) != _core(clean):
        version += 1
    clean["form_version"] = max(version, 1)
    row = _row(db, event.id)
    if row is None:
        row = AppSetting(key=setting_key(event.id))
        db.add(row)
    row.value = json.dumps(clean, ensure_ascii=False)
    row.updated_at = utcnow()
    by_key = {c["key"]: c for c in configs}
    for key, f in clean["fields"].items():
        if "required" not in f or not required_editable(by_key[key]):
            continue
        cfg_row = db.query(EventFieldConfig).filter_by(event_id=event.id, field_key=key).first()
        if cfg_row is None:
            if not f["required"]:
                continue
            cfg_row = EventFieldConfig(event_id=event.id, field_key=key, required=True, field_type="text_short")
            db.add(cfg_row)
        cfg_row.required = bool(f["required"])
    db.flush()
    return clean


# ------------------------------------------------------------------ diseño efectivo (lo que ven el servidor y el quiosco)
def effective(stored: Optional[dict], configs: list) -> dict:
    """El diseño guardado completado con la realidad del evento HOY: sin campos borrados, con los nuevos al final, lo obligatorio y los textos tal como están en Parámetros."""
    base = stored if stored else default_design(configs)
    by_cfg = {c["key"]: c for c in configs}
    cleaned = {}       # lo obligatorio manda lo que dicen los parámetros del evento (no lo guardado); un obligatorio no puede depender de otro campo
    for key, f in (base.get("fields") or {}).items():
        f = {k: v for k, v in (f or {}).items() if k != "required"}
        if key in by_cfg and (by_cfg[key].get("required") or key in ALWAYS_REQUIRED):
            f.pop("show_if", None)
        cleaned[key] = f
    base = {**base, "fields": cleaned}
    try:
        clean = sanitize(base, configs)
    except ValueError:                      # un diseño viejo que ya no cuadra (p. ej. cambió el tipo de un campo): vuelve al de por defecto, sin romper el quiosco
        clean = sanitize({**default_design(configs), "enabled": base.get("enabled")}, configs)
    by_key = by_cfg
    fields = {}
    for key, cfg in by_key.items():
        f = dict(clean["fields"].get(key, {}))
        fields[key] = {"required": bool(cfg.get("required")) or key in ALWAYS_REQUIRED, "text_case": f.get("text_case", "") if case_capable(cfg) else ""}
        if f.get("show_if"):
            fields[key]["show_if"] = f["show_if"]
    for sheet in clean["sheets"]:
        if any(fields[k]["required"] for r in clean["rows"] if r["sheet"] == sheet["id"] for k in r["items"]):
            sheet["open"] = True
    return {"enabled": clean["enabled"], "form_version": int((stored or {}).get("form_version") or 1), "form_sig": _signature(configs), "sheets": clean["sheets"], "rows": clean["rows"], "fields": fields}


def active(db, event, configs: Optional[list] = None) -> Optional[dict]:
    """El diseño efectivo si el interruptor del entorno Y el del evento están prendidos; si no, None (todo se ve y funciona como siempre). Con el entorno apagado no toca la base."""
    if not env_enabled():
        return None
    stored = load_raw(db, event)
    if not stored or not stored.get("enabled"):
        return None
    if configs is None:
        from app.routers import parametros
        configs = parametros.field_configs_for_event(db, event)
    return effective(stored, configs)


def view(db, event, configs: list) -> dict:
    """Lo que devuelve GET /person-form (también para el diseñador, que necesita ver el diseño aunque el evento aún no lo use)."""
    if not env_enabled():
        return {"env_enabled": False, "enabled": False, "definition": None}
    stored = load_raw(db, event)
    definition = effective(stored, configs)
    return {"env_enabled": True, "enabled": bool(stored and stored.get("enabled")), "definition": definition}


# ------------------------------------------------------------------ texto al escribir / correo (se aplica al guardar, en el servidor)
def case_rules(definition: Optional[dict]) -> dict:
    if not definition:
        return {}
    return {k: f["text_case"] for k, f in definition["fields"].items() if f.get("text_case")}


def apply_case(data: dict, definition: Optional[dict]) -> list:
    """Convierte EN EL LUGAR los textos de `data` (nombres, apellidos, cargo, entidad, tipo, `extra_fields` opcionales) según el diseño y deja el correo en minúsculas. Devuelve las claves que cambiaron.
    Sin diseño activo no toca nada."""
    if not definition:
        return []
    rules, changed = case_rules(definition), []
    for key, mode in rules.items():
        if key.startswith("opcional_"):
            continue
        v = data.get(key)
        if isinstance(v, str) and v:
            new = roster_text.convert(v, mode)
            if new != v:
                data[key], changed = new, changed + [key]
    extras = data.get("extra_fields")
    if isinstance(extras, dict):
        for key, v in list(extras.items()):
            mode = rules.get(key)
            if mode and isinstance(v, str) and v:
                new = roster_text.convert(v, mode)
                if new != v:
                    extras[key], changed = new, changed + [key]
    email = data.get("email")
    if isinstance(email, str) and email and email != email.strip().lower():
        data["email"] = email.strip().lower()
        changed.append("email")
    return changed


def is_stale(definition: dict, op_version, op_sig=None) -> bool:
    """¿La operación de la bandeja se hizo con una copia ANTERIOR del formulario? SOLO si trae una versión entera válida y MENOR que la vigente. Ausente, ilegible, 0, negativa o mayor
    NO cuenta como vieja: la validación queda estricta (el cliente no puede debilitarla omitiendo la versión). `op_sig` se conserva por compatibilidad y no decide nada."""
    if isinstance(op_version, bool) or not isinstance(op_version, (int, str)):
        return False
    try:
        v = int(op_version)
    except ValueError:
        return False
    return 1 <= v < int(definition.get("form_version") or 1)
