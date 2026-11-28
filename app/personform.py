"""Formulario de PERSONA diseñado por el admin (Fase 1A, pieza 5; docs/15 «Plan 4»).

Reutiliza el motor de los formularios web SIN su parte pública ni los pagos: la misma forma de diseño (`rows` con hasta 4 campos uno al lado del otro, `sheets` = grupos, `show_if` por
campo, validado con `app/formlib.py`) pero sobre los campos que el evento YA tiene (`parametros.field_configs_for_event`: identidad, fijos y `opcional_N`, sin tope). Se usa al CREAR
(«Registrar nuevo») y al EDITAR personas en el quiosco, y viaja VERSIONADA a la copia local sin red (`form_version`).

Diseño guardado (JSON en `app_settings`, clave `person_form:<evento>`, SIN columna nueva ni migración):
  {"enabled": bool, "form_version": int,
   "sheets": [{"id", "title", "open"}],                       # grupos; uno que lleva un obligatorio queda SIEMPRE abierto (a la vista)
   "rows":   [{"sheet": id, "items": [clave, ...hasta 4]}],    # una fila = campos uno al lado del otro (columnas)
   "text_case": ""|"upper"|"lower"|"title",                    # «Texto al escribir» GENERAL del evento: vale para el formulario predeterminado y el a la medida (lo de cada campo manda sobre esto)
   "fields": {clave: {"required": bool, "text_case": ""|"upper"|"lower"|"title", "show_if": {...}?}}}
Lo OBLIGATORIO no se guarda dos veces: al guardar el diseño se escribe en `event_field_configs.required` (la única fuente que ya validan manual_register, update_user, la bandeja y la
acreditación). «Texto al escribir» (`text_case`) solo vale para texto: nombres, apellidos, cargo, entidad y opcionales de texto; NUNCA cédula, teléfono ni fecha; el correo SIEMPRE va en minúsculas.

Interruptores: `PERSON_FORM_ENABLED` (entorno, APAGADO por defecto: con él apagado nada de esto se ve ni se aplica) y `enabled` dentro del diseño de CADA evento (también apagado por defecto)."""
import hashlib
import json
import os
import re
from typing import Optional

from app import formlib, roster_text
from app.models import AppSetting, EventAttendee, EventFieldConfig
from app.timeutil import utcnow

ENV_FLAG = "PERSON_FORM_ENABLED"
MAX_FIELDS, MAX_SHEETS, MAX_ROW_ITEMS = 700, 12, 4
TEXT_FIELD_TYPES = ("text_short", "text_long")
FIXED_TEXT_KEYS = ("first_name", "last_name", "role", "entity", "opt_1")       # fijos que admiten mayúsculas/minúsculas (si su tipo es texto)
ALWAYS_REQUIRED = ("id", "first_name")           # cédula y nombres: siempre obligatorios
NEVER_REQUIRED = ("categories", "birth_date")
NEVER_HIDDEN = ("id", "first_name", "categories")          # en un formulario por categoría estos campos siempre se ven (la cédula y el nombre identifican; la categoría elige el formulario)
EVENT_DECIDES = ("last_name", "code")      # el apellido es obligatorio según la base cargada o lo elegido en Parámetros (app/lastname.py) y el código de la persona según su interruptor (Parámetros › Campos); llega ya resuelto en `cfg["required"]`, el diseño no lo cambia
CASE_MODES = ("", roster_text.UPPER, roster_text.LOWER, roster_text.TITLE)
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
    return cfg.get("key") not in ALWAYS_REQUIRED and cfg.get("key") not in NEVER_REQUIRED and cfg.get("key") not in EVENT_DECIDES


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
    if field_in.get("hidden"):
        return False                       # un campo oculto en esta categoría nunca se exige
    if key in ALWAYS_REQUIRED:
        return True
    if key in NEVER_REQUIRED:
        return False
    if key in EVENT_DECIDES:
        return bool(cfg.get("required"))
    return bool(field_in["required"]) if "required" in field_in else bool(cfg.get("required"))


def sanitize(raw: dict, configs: list, allow_hidden: bool = False) -> dict:
    """Valida el diseño del editor contra los campos REALES del evento; lanza ValueError con un mensaje legible. Lo desconocido se ignora (un campo borrado del evento no rompe el diseño).
    `allow_hidden` (solo los formularios por categoría): un campo puede quedar OCULTO para esa categoría (no se ve ni se exige); cédula, nombres y categoría nunca."""
    if not isinstance(raw, dict):
        raise ValueError("El diseño del formulario de persona no es válido")
    by_key = {c["key"]: c for c in configs}
    if len(by_key) > MAX_FIELDS:
        raise ValueError("Demasiados campos")
    general_case = roster_text.parse_mode(raw.get("text_case"))
    if general_case is None:
        raise ValueError("«Texto al escribir» no es válido")
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
        if allow_hidden and f.get("hidden") and key not in NEVER_HIDDEN:
            out["hidden"] = True
        if "required" in f and key not in ALWAYS_REQUIRED and key not in NEVER_REQUIRED and key not in EVENT_DECIDES:
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
        if key not in by_key or not isinstance(f, dict) or not f.get("show_if") or fields.get(key, {}).get("hidden"):
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
    return {"enabled": bool(raw.get("enabled")), "text_case": general_case, "sheets": sheets, "rows": rows, "fields": fields}


FLOW_KEYS = ("facial_off", "digital_off", "autoprint_off")          # flujos que una categoría puede APAGAR (solo restringen: nunca encienden algo que el evento no tiene)


def _clean_flow(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {k: bool(raw.get(k)) for k in FLOW_KEYS if raw.get(k)}


def sanitize_variants(raw: dict, configs: list, categories: list) -> dict:
    """Formularios por CATEGORÍA (19-nov-2026): `{categoría: {sheets, rows, fields}}`. Solo de categorías que el evento tiene; cada uno se valida igual que el general (más campos ocultos).
    Lo obligatorio de una categoría vive aquí (no en `event_field_configs`, que es el del formulario general)."""
    out = {}
    variants = raw.get("variants") if isinstance(raw.get("variants"), dict) else {}
    for cat, v in variants.items():
        if cat not in categories or not isinstance(v, dict):
            continue
        clean = sanitize({**v, "enabled": True}, configs, allow_hidden=True)
        out[cat] = {k: clean[k] for k in ("sheets", "rows", "fields")}
        flow = _clean_flow(v.get("flow"))
        if flow:
            out[cat]["flow"] = flow
    return out


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
    return json.dumps({k: d.get(k) for k in ("enabled", "text_case", "sheets", "rows", "fields", "variants")}, ensure_ascii=False, sort_keys=True)


def save(db, event, raw: dict, configs: list) -> dict:
    """Guarda el diseño (versión +1 SOLO si cambió algo) y escribe lo obligatorio en los parámetros del evento. Devuelve el diseño efectivo. El `commit` lo hace quien llama."""
    clean = sanitize(raw, configs)
    clean["variants"] = sanitize_variants(raw, configs, event.get_categories())
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
        clean = sanitize({**default_design(configs), "enabled": base.get("enabled"), "text_case": base.get("text_case")}, configs)
    by_key = by_cfg
    fields = {}
    for key, cfg in by_key.items():
        f = dict(clean["fields"].get(key, {}))
        fields[key] = {"required": bool(cfg.get("required")) or key in ALWAYS_REQUIRED, "text_case": (f.get("text_case") or clean.get("text_case") or "") if case_capable(cfg) else ""}          # lo del campo manda; si no, el general del evento
        if f.get("show_if"):
            fields[key]["show_if"] = f["show_if"]
    for sheet in clean["sheets"]:
        if any(fields[k]["required"] for r in clean["rows"] if r["sheet"] == sheet["id"] for k in r["items"]):
            sheet["open"] = True
    out = {"enabled": clean["enabled"], "form_version": int((stored or {}).get("form_version") or 1), "form_sig": _signature(configs), "text_case": clean.get("text_case", ""), "sheets": clean["sheets"], "rows": clean["rows"], "fields": fields}
    variants = {}
    for cat, v in ((stored or {}).get("variants") or {}).items():
        ev = effective_variant(v, configs)
        if ev:
            variants[cat] = ev
    if variants:
        out["variants"] = variants
    return out


def effective_variant(v: dict, configs: list) -> Optional[dict]:
    """El formulario de UNA categoría tal como lo ven el servidor y el quiosco: lo obligatorio es lo que dice ESA categoría (si no dice nada, lo del evento); lo oculto no se ve ni se exige.
    None si el diseño guardado ya no cuadra con los campos del evento (entonces esa categoría usa el formulario general)."""
    try:
        clean = sanitize({**(v or {}), "enabled": True}, configs, allow_hidden=True)
    except ValueError:
        return None
    fields = {}
    for cfg in configs:
        key = cfg["key"]
        f = clean["fields"].get(key, {})
        hidden = bool(f.get("hidden"))
        if hidden:
            required = False
        elif key in ALWAYS_REQUIRED:
            required = True
        elif key in NEVER_REQUIRED:
            required = False
        elif key in EVENT_DECIDES:
            required = bool(cfg.get("required"))
        else:
            required = bool(f["required"]) if "required" in f else bool(cfg.get("required"))
        item = {"required": required, "text_case": f.get("text_case", "") if case_capable(cfg) else ""}
        if f.get("show_if") and not required and not hidden:
            item["show_if"] = f["show_if"]
        if hidden:
            item["hidden"] = True
        fields[key] = item
    for sheet in clean["sheets"]:
        if any(fields[k]["required"] for r in clean["rows"] if r["sheet"] == sheet["id"] for k in r["items"]):
            sheet["open"] = True
    out = {"sheets": clean["sheets"], "rows": clean["rows"], "fields": fields}
    flow = _clean_flow((v or {}).get("flow"))
    if flow:
        out["flow"] = flow
    return out


def for_category(definition: Optional[dict], category: Optional[str]) -> Optional[dict]:
    """El formulario que le toca a una persona de esta categoría: el propio de la categoría (con la versión y la firma del general) o, si no tiene, el general."""
    if not definition:
        return definition
    var = (definition.get("variants") or {}).get(category or "")
    if not var:
        return definition
    base_fields = definition.get("fields") or {}
    fields = {k: {**f, "text_case": (base_fields.get(k) or {}).get("text_case", "")} for k, f in (var.get("fields") or {}).items()}          # «Texto al escribir» siempre es el del general
    return {**definition, **var, "fields": fields, "variants": None, "category": category}


def person_configs(db, event, configs: list, categories: Optional[list], stored: Optional[dict] = None) -> list:
    """`configs` del evento ajustados al formulario de la categoría de la persona (una sola categoría por persona: se usa la primera). Cambia `required` (y marca `hidden`); sin formulario
    por categoría, sin diseño activo o con el entorno apagado devuelve `configs` tal cual. Todos los sitios que validan obligatorios pasan por aquí."""
    cat = (categories or [None])[0]
    if not cat or not env_enabled():
        return configs
    stored = stored if stored is not None else load_raw(db, event)
    if not stored or not stored.get("enabled") or cat not in (stored.get("variants") or {}):
        return configs
    var = effective_variant(stored["variants"][cat], configs)
    if not var:
        return configs
    out = []
    for c in configs:
        f = var["fields"].get(c["key"])
        if c["key"] in ALWAYS_REQUIRED + NEVER_REQUIRED + EVENT_DECIDES:          # cédula y nombres ya los exige la base y NO viajan en `values` (si los marcáramos obligatorios, toda edición fallaría con «Faltan Nombres, Cédula»); lo demás lo resuelve el evento
            out.append(c)
            continue
        out.append({**c, "required": f["required"], "hidden": bool(f.get("hidden"))} if f else c)
    return out


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


def case_definition(db, event, configs: Optional[list] = None) -> Optional[dict]:
    """La definición con la que se aplica «Texto al escribir» al guardar: el diseño a la medida si está activo (con el general ya mezclado) o, con el formulario PREDETERMINADO, una definición mínima con el
    «Texto al escribir» general del evento para cada campo de texto. None si no hay nada que aplicar (entonces no se toca nada, ni siquiera el correo)."""
    if not env_enabled():
        return None
    stored = load_raw(db, event)
    if not stored:
        return None
    if configs is None:
        from app.routers import parametros
        configs = parametros.field_configs_for_event(db, event)
    if stored.get("enabled"):
        return effective(stored, configs)
    mode = roster_text.parse_mode(stored.get("text_case"))
    if not mode:
        return None
    return {"text_case": mode, "fields": {c["key"]: {"text_case": mode} for c in configs if case_capable(c)}}


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


# ------------------------------------------------------------------ flujos por categoría (19-nov-2026): reconocimiento facial, escarapela digital e impresión automática
def _stored_active(db, event, stored=None) -> Optional[dict]:
    if not env_enabled():
        return None
    stored = stored if stored is not None else load_raw(db, event)
    return stored if stored and stored.get("enabled") and stored.get("variants") else None


def flow_for(db, event, categories: Optional[list], stored: Optional[dict] = None) -> dict:
    """Flujos APAGADOS para la categoría de la persona (una sola; se usa la primera): `{facial_off, digital_off, autoprint_off}`. Vacío = todo como lo decide el evento."""
    cat = (categories or [None])[0]
    st = _stored_active(db, event, stored)
    if not cat or not st:
        return {}
    return _clean_flow(((st["variants"].get(cat) or {}).get("flow")))


def user_flow(db, event, user_id: str, stored: Optional[dict] = None) -> dict:
    """Lo mismo, buscando la categoría de la persona en este evento."""
    st = _stored_active(db, event, stored)
    if not st:
        return {}
    att = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user_id).first()
    return flow_for(db, event, att.get_categories() if att else [], stored=st)


def facial_off_user_ids(db, event) -> set:
    """Personas de este evento cuya categoría NO usa reconocimiento facial (no se les ofrece la aceptación, no se les calcula el vector y no entran al índice de reconocimiento)."""
    st = _stored_active(db, event)
    if not st:
        return set()
    cats = {c for c, v in st["variants"].items() if (v or {}).get("flow", {}).get("facial_off")}
    if not cats:
        return set()
    out = set()
    for uid, raw in db.query(EventAttendee.user_id, EventAttendee.categories).filter(EventAttendee.event_id == event.id, EventAttendee.categories.isnot(None)):
        try:
            mine = json.loads(raw) if raw else []
        except ValueError:
            continue
        if mine and mine[0] in cats:
            out.add(uid)
    return out
