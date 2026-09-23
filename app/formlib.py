"""Lógica pura de los Formularios Web (Sprint 5): diseño, condiciones, validación de respuestas, estados y calendario.
Sin base de datos ni HTTP — así se prueba a fondo y la usan igual el servidor (que valida SIEMPRE, sin fiarse del
navegador) y las pruebas. El navegador (`static/js/form-render.js`) implementa la misma regla de condiciones para
mostrar/ocultar en vivo, pero la del servidor manda.

Diseño (JSON):
  {"theme": {...colores, fuente, imágenes, textos},
   "rows":   [{"align": "left|center|right", "items": ["f1", "f2"]}, ...],      # una fila = campos uno al lado del otro
   "fields": {"f1": {"id","type","key","label","required","stats","readonly_when_prefilled","placeholder","help",
                     "options","accept","max_mb","show_if","content","src","sync"}}}
  `key`: si el campo alimenta la base del evento — una clave de identidad (id, first_name, ...) o `opcional_N`.
  `show_if`: {"field": id, "op": "equals|not_equals|contains|in|filled", "value": ...} — mostrar solo si se cumple.
"""
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Callable, Optional

INPUT_TYPES = ("text_short", "text_long", "email", "phone", "number", "date", "checkbox", "select", "radio", "multiselect", "file")
STATIC_TYPES = ("heading", "paragraph", "image")
ALL_TYPES = INPUT_TYPES + STATIC_TYPES
IDENTITY_KEYS = ("id", "first_name", "last_name", "role", "entity", "phone", "email", "opt_1")
STATUSES = ("pruebas", "activo", "cerrado", "finalizado")
CONDITION_OPS = ("equals", "not_equals", "contains", "in", "filled")
FILE_EXTENSIONS = ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "txt", "png", "jpg", "jpeg", "webp", "gif")
FONTS = (
    "Roboto", "Open Sans", "Lato", "Montserrat", "Oswald", "Raleway", "Poppins", "Playfair Display", "Inter", "Bebas Neue",
    "Merriweather", "Nunito", "Ubuntu", "Rubik", "Comfortaa", "Space Grotesk", "Manrope", "Zilla Slab",
)
MAX_FIELDS, MAX_OPTIONS = 80, 200
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PHONE = re.compile(r"^[+\d][\d\s().-]{5,19}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

DEFAULT_THEME = {
    "title": "Inscripción", "subtitle": "", "logo": "", "bg_image": "", "bg_color": "#F4F5F9", "card_color": "#FFFFFF",
    "text_color": "#0A0E2E", "accent": "#D4AF37", "button_text": "Enviar inscripción", "font": "Montserrat",
}
DEFAULT_SETTINGS = {
    "security": {"enabled": False, "type": "code", "code": ""},
    "prefill": {"mode": "none", "source": "event"},                  # mode: none | cedula | invite ; source: event | event:<id> | upload
    "closed_template": {"title": "Este formulario ya cerró", "text": "Lo sentimos, ya no estamos recibiendo inscripciones.", "image": ""},
    "thanks": {"mode": "template", "title": "¡Gracias por inscribirte!", "text": "Recibimos tus datos correctamente.", "image": "", "url": ""},
    "feed": "manual",                                                # realtime | on_close | manual
    "max_mb": 10,
}


def new_id(prefix="f") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60] or "formulario"


def default_design(name: str = "Inscripción") -> dict:
    """Punto de partida: cédula, nombres, apellidos y correo, ya vinculados a los campos del evento."""
    fields = {}
    rows = []
    for key, label, kind in (("id", "Cédula", "text_short"), ("first_name", "Nombres", "text_short"), ("last_name", "Apellidos", "text_short"), ("email", "Correo electrónico", "email")):
        fid = new_id()
        fields[fid] = {"id": fid, "type": kind, "key": key, "label": label, "required": True, "stats": False}
        rows.append({"align": "left", "items": [fid]})
    return {"theme": {**DEFAULT_THEME, "title": name}, "rows": rows, "fields": fields}


# ------------------------------------------------------------------ sanitizar (lo que llega del editor)
def _text(value, limit=300) -> str:
    return str(value if value is not None else "").strip()[:limit]


def sanitize_design(design: dict, optional_keys: set) -> dict:
    """Valida y limpia el diseño que manda el editor; lanza ValueError con un mensaje legible si algo no cuadra.
    Solo se conservan las propiedades conocidas."""
    if not isinstance(design, dict):
        raise ValueError("El diseño del formulario no es válido")
    theme_in = design.get("theme") or {}
    theme = {**DEFAULT_THEME}
    for key in ("title", "subtitle", "button_text"):
        if key in theme_in:
            theme[key] = _text(theme_in[key], 160)
    for key in ("bg_color", "card_color", "text_color", "accent"):
        if key in theme_in:
            if not _HEX.match(str(theme_in[key])):
                raise ValueError(f"«{key}» debe ser un color como #D4AF37")
            theme[key] = theme_in[key]
    if "font" in theme_in:
        if theme_in["font"] not in FONTS:
            raise ValueError("Fuente no disponible")
        theme["font"] = theme_in["font"]
    for key in ("logo", "bg_image"):
        theme[key] = _text(theme_in.get(key), 200)

    fields_in = design.get("fields") or {}
    if not isinstance(fields_in, dict) or len(fields_in) > MAX_FIELDS:
        raise ValueError(f"Un formulario admite hasta {MAX_FIELDS} elementos")
    allowed_keys = set(IDENTITY_KEYS) | set(optional_keys)
    fields, used_keys = {}, set()
    for fid, f in fields_in.items():
        if not isinstance(f, dict) or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(fid)):
            raise ValueError("Elemento con identificador inválido")
        kind = f.get("type")
        if kind not in ALL_TYPES:
            raise ValueError(f"Tipo de campo no válido: {kind}")
        clean = {"id": fid, "type": kind, "label": _text(f.get("label"), 200), "help": _text(f.get("help"), 300)}
        if kind in INPUT_TYPES:
            if not clean["label"]:
                raise ValueError("Todos los campos necesitan un nombre (etiqueta)")
            key = f.get("key") or None
            if key:
                if key not in allowed_keys:
                    raise ValueError(f"«{clean['label']}»: el campo del evento «{key}» no existe")
                if key in used_keys:
                    raise ValueError(f"El campo del evento «{key}» está en el formulario dos veces")
                used_keys.add(key)
            clean.update({
                "key": key, "required": bool(f.get("required")), "stats": bool(f.get("stats")),
                "readonly_when_prefilled": bool(f.get("readonly_when_prefilled")), "placeholder": _text(f.get("placeholder"), 120),
                "sync": bool(f.get("sync")) and not key,      # pedir que se cree también en Parámetros del Evento
            })
            if kind in ("select", "radio", "multiselect"):
                options = [_text(o, 120) for o in (f.get("options") or []) if _text(o, 120)]
                if not options:
                    raise ValueError(f"«{clean['label']}»: agrega al menos una opción")
                if len(options) > MAX_OPTIONS or len(set(options)) != len(options):
                    raise ValueError(f"«{clean['label']}»: las opciones no pueden repetirse (máximo {MAX_OPTIONS})")
                clean["options"] = options
            if kind == "file":
                accept = [str(a).lower().lstrip(".") for a in (f.get("accept") or [])]
                bad = [a for a in accept if a not in FILE_EXTENSIONS]
                if bad:
                    raise ValueError(f"«{clean['label']}»: formato no permitido ({', '.join(bad)})")
                clean["accept"] = accept or list(FILE_EXTENSIONS)
                try:
                    clean["max_mb"] = max(1, min(20, int(f.get("max_mb") or 10)))
                except (TypeError, ValueError):
                    raise ValueError(f"«{clean['label']}»: el tamaño máximo debe ser un número de MB")
        elif kind in ("heading", "paragraph"):
            clean["content"] = _text(f.get("content"), 2000)
        else:  # image
            clean["src"] = _text(f.get("src"), 200)
        clean["show_if"] = _sanitize_condition(f.get("show_if"), fields_in, fid)
        fields[fid] = clean

    rows, placed = [], set()
    for row in design.get("rows") or []:
        items = [i for i in (row.get("items") or []) if i in fields and i not in placed]
        if not items:
            continue
        if len(items) > 4:
            raise ValueError("Una fila admite hasta 4 elementos uno al lado del otro")
        placed.update(items)
        rows.append({"align": row.get("align") if row.get("align") in ("left", "center", "right") else "left", "items": items})
    for fid in fields:                       # cualquier elemento que no quedó en una fila va al final, en su propia fila
        if fid not in placed:
            rows.append({"align": "left", "items": [fid]})
    _check_condition_cycles(fields)
    return {"theme": theme, "rows": rows, "fields": fields}


def _sanitize_condition(cond, fields_in: dict, own_id: str):
    if not cond:
        return None
    if not isinstance(cond, dict) or cond.get("field") not in fields_in or cond.get("field") == own_id:
        raise ValueError("Una regla condicional apunta a un campo que no existe")
    op = cond.get("op", "equals")
    if op not in CONDITION_OPS:
        raise ValueError("Operador de regla no válido")
    value = cond.get("value")
    return {"field": cond["field"], "op": op, "value": [str(v) for v in value] if isinstance(value, list) else _text(value, 200)}


def _check_condition_cycles(fields: dict) -> None:
    for start in fields:
        seen, cur = set(), start
        while cur:
            if cur in seen:
                raise ValueError("Las reglas condicionales se apuntan en círculo")
            seen.add(cur)
            cond = fields[cur].get("show_if")
            cur = cond["field"] if cond else None


def sanitize_settings(settings: dict) -> dict:
    s_in = settings or {}
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_SETTINGS.items()}
    sec = s_in.get("security") or {}
    out["security"] = {"enabled": bool(sec.get("enabled")), "type": sec.get("type") if sec.get("type") in ("code", "cedula") else "code", "code": _text(sec.get("code"), 60)}
    if out["security"]["enabled"] and out["security"]["type"] == "code" and not out["security"]["code"]:
        raise ValueError("Define la palabra o código de acceso del formulario")
    pre = s_in.get("prefill") or {}
    mode = pre.get("mode") if pre.get("mode") in ("none", "cedula", "invite") else "none"
    source = _text(pre.get("source") or "event", 30)
    if source not in ("event", "upload") and not re.fullmatch(r"event:\d+", source):
        raise ValueError("Fuente de datos para el pre-llenado no válida")
    out["prefill"] = {"mode": mode, "source": source}
    for key in ("closed_template", "thanks"):
        base = out[key]
        given = s_in.get(key) or {}
        for k in base:
            if k in given:
                base[k] = _text(given[k], 600 if k == "text" else 200)
    if out["thanks"]["mode"] not in ("template", "redirect"):
        out["thanks"]["mode"] = "template"
    if out["thanks"]["mode"] == "redirect" and not re.match(r"^https?://[^\s]+$", out["thanks"]["url"] or ""):
        raise ValueError("La dirección a la que se redirige debe empezar con http:// o https://")
    out["feed"] = s_in.get("feed") if s_in.get("feed") in ("realtime", "on_close", "manual") else "manual"
    try:
        out["max_mb"] = max(1, min(20, int(s_in.get("max_mb") or 10)))
    except (TypeError, ValueError):
        out["max_mb"] = 10
    return out


# ------------------------------------------------------------------ condiciones y visibilidad
def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None or value == "":
        return []
    return [str(value)]


def condition_met(cond: Optional[dict], values: dict) -> bool:
    if not cond:
        return True
    current = values.get(cond["field"])
    have = _as_list(current)
    want = cond.get("value")
    op = cond.get("op", "equals")
    norm = lambda x: str(x).strip().lower()
    if op == "filled":
        return bool(have) and (current is not False)
    if op == "equals":
        return any(norm(h) == norm(want) for h in have)
    if op == "not_equals":
        return not any(norm(h) == norm(want) for h in have)
    if op == "contains":
        return any(norm(want) in norm(h) for h in have)
    if op == "in":
        wanted = {norm(w) for w in _as_list(want)}
        return any(norm(h) in wanted for h in have)
    return False


def visible_ids(design: dict, values: dict) -> set:
    """Elementos que se muestran según las reglas. Un elemento cuyo «padre» está oculto también queda oculto."""
    fields = design["fields"]
    memo = {}

    def visible(fid):
        if fid in memo:
            return memo[fid]
        cond = fields[fid].get("show_if")
        result = True
        if cond:
            parent = cond["field"]
            result = parent in fields and visible(parent) and condition_met(cond, values)
        memo[fid] = result
        return result

    return {fid for fid in fields if visible(fid)}


# ------------------------------------------------------------------ validar una respuesta
def validate_submission(design: dict, values: dict, uploaded: dict, email_checker: Optional[Callable] = None):
    """`values`: {field_id: valor crudo}; `uploaded`: {field_id: info} de los archivos que sí llegaron.
    Devuelve (limpios, errores). Solo se validan y se guardan los campos VISIBLES: lo que una regla dejó oculto ni
    es obligatorio ni se guarda, aunque el navegador lo haya mandado."""
    fields = design["fields"]
    visible = visible_ids(design, {**values, **{k: True for k in uploaded}})
    clean, errors = {}, {}
    for fid in visible:
        f = fields[fid]
        kind = f["type"]
        if kind not in INPUT_TYPES:
            continue
        raw = values.get(fid)
        label = f["label"]
        if kind == "file":
            if fid in uploaded:
                clean[fid] = uploaded[fid]
            elif f.get("required"):
                errors[fid] = f"«{label}»: adjunta el archivo"
            continue
        if kind == "checkbox":
            checked = str(raw).strip().lower() in ("true", "1", "on", "si", "sí", "yes")
            if f.get("required") and not checked:
                errors[fid] = f"«{label}»: debes marcar esta casilla"
            clean[fid] = checked
            continue
        if kind == "multiselect":
            chosen = _as_list(raw)
            bad = [c for c in chosen if c not in f["options"]]
            if bad:
                errors[fid] = f"«{label}»: opción no válida"
            elif f.get("required") and not chosen:
                errors[fid] = f"«{label}»: elige al menos una opción"
            else:
                clean[fid] = chosen
            continue
        text = str(raw if raw is not None else "").strip()
        if not text:
            if f.get("required"):
                errors[fid] = f"«{label}»: es obligatorio"
            continue
        limit = 5000 if kind == "text_long" else 300
        if len(text) > limit:
            errors[fid] = f"«{label}»: es demasiado largo (máximo {limit} caracteres)"
        elif kind in ("select", "radio") and text not in f["options"]:
            errors[fid] = f"«{label}»: opción no válida"
        elif kind == "email":
            if not _EMAIL.match(text):
                errors[fid] = f"«{label}»: escribe un correo con formato válido"
            elif email_checker:
                ok, reason = email_checker(text)
                if not ok:
                    errors[fid] = f"«{label}»: {reason}"
                else:
                    clean[fid] = text.lower()
            else:
                clean[fid] = text.lower()
        elif kind == "phone" and not _PHONE.match(text):
            errors[fid] = f"«{label}»: escribe un teléfono válido"
        elif kind == "number":
            try:
                float(text.replace(",", "."))
            except ValueError:
                errors[fid] = f"«{label}»: debe ser un número"
        elif kind == "date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                errors[fid] = f"«{label}»: escribe una fecha válida"
        if fid not in errors and fid not in clean:
            clean[fid] = text
    return clean, errors


# ------------------------------------------------------------------ estados y calendario
def parse_schedule(schedule: Optional[list]) -> list:
    """[{"status","from","to"}] con from/to en hora local ('2026-10-01T08:00'); valida y ordena."""
    out = []
    for item in schedule or []:
        status = item.get("status")
        if status not in STATUSES:
            raise ValueError(f"Estado no válido en el calendario: {status}")
        try:
            start, end = datetime.fromisoformat(item["from"]), datetime.fromisoformat(item["to"])
        except (KeyError, ValueError, TypeError):
            raise ValueError("Cada tramo del calendario necesita fecha y hora de inicio y de fin")
        if end <= start:
            raise ValueError("En un tramo del calendario, el fin debe ser posterior al inicio")
        out.append({"status": status, "from": item["from"], "to": item["to"], "_s": start, "_e": end})
    out.sort(key=lambda x: x["_s"])
    for a, b in zip(out, out[1:]):
        if b["_s"] < a["_e"]:
            raise ValueError("Los tramos del calendario no pueden traslaparse")
    return [{k: v for k, v in x.items() if not k.startswith("_")} for x in out]


def effective_status(manual_status: str, use_schedule: bool, schedule: list, now_local: datetime) -> str:
    """Estado vigente ahora. Con calendario: el del tramo que contiene el momento actual; FUERA de cualquier tramo
    se comporta como `cerrado` (decisión: no dejar un hueco sin definir; usa la misma plantilla de cortesía)."""
    if not use_schedule:
        return manual_status
    for item in schedule or []:
        if datetime.fromisoformat(item["from"]) <= now_local < datetime.fromisoformat(item["to"]):
            return item["status"]
    return "cerrado"
