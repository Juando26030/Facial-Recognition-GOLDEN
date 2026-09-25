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
  `show_if`: {"field": id, "op": "equals|not_equals|contains|in|filled", "value": ...} — mostrar solo si se cumple; o un grupo
  {"match": "all|any", "rules": [ ...hasta 6 reglas como la anterior ]} — todas (y) o alguna (o).
"""
import json
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime
from typing import Callable, Optional

INPUT_TYPES = ("text_short", "text_long", "email", "phone", "number", "date", "checkbox", "select", "radio", "multiselect", "file")
STATIC_TYPES = ("heading", "paragraph", "image")
PAYMENT_TYPE = "payment"      # «Pago» (Wompi): máximo uno por formulario; no guarda un valor, cobra un monto
COMPANIONS_TYPE = "companions"   # «Acompañantes»: la persona elige cuántos (0…N) y por cada uno se despliega un mini-formulario; puede cobrarse por cada uno
COMPANION_FIELD_TYPES = ("text_short", "email", "phone", "number")
ALL_TYPES = INPUT_TYPES + STATIC_TYPES + (PAYMENT_TYPE, COMPANIONS_TYPE)
DATE_FIELD = "@date"          # en una condición de precio: la fecha de HOY (hora local) en vez de un campo
DATE_OPS = ("before", "on_or_after")
TAX_RATE = 19      # IVA en Colombia (%)
MIN_PAYMENT_COP, MAX_PAYMENT_COP = 1500, 10_000_000   # Wompi: mínimo por transacción y tope por transacción (persona jurídica)
IDENTITY_KEYS = ("id", "first_name", "last_name", "role", "entity", "phone", "email", "opt_1")
STATUSES = ("pruebas", "activo", "cerrado", "finalizado")
CONDITION_OPS = ("equals", "not_equals", "contains", "in", "filled")
FILE_EXTENSIONS = ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "txt", "png", "jpg", "jpeg", "webp", "gif")
FONTS = (
    "Roboto", "Open Sans", "Lato", "Montserrat", "Oswald", "Raleway", "Poppins", "Playfair Display", "Inter", "Bebas Neue",
    "Merriweather", "Nunito", "Ubuntu", "Rubik", "Comfortaa", "Space Grotesk", "Manrope", "Zilla Slab",
)
MAX_FIELDS, MAX_OPTIONS = 80, 200
LANGUAGES = ("es", "en", "pt")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PHONE = re.compile(r"^[+\d][\d\s().-]{5,19}$")
_NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")
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
    "quotas": {"field": "", "limits": {}},                           # cupo por categoría: {campo (lista/opción única), limits: {opción: máximo}}
    "feed": "manual",                                                # realtime | on_close | manual
    "max_mb": 10,
    "language": "es",                                                # idioma en que está escrito (<html lang>): el navegador ofrece traducir desde ahí
    "translate": True,                                               # mostrar el botón «Translate» para quien no habla ese idioma
    "send_digital_badge": False,                                     # enviar la escarapela virtual al correo del inscrito cuando entra a la base del evento
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


# ------------------------------------------------------------------ documentos de identidad (Colombia y los más frecuentes en el mundo)
def _nit_ok(v: str) -> bool:
    if "-" not in v:
        return True                                    # sin dígito de verificación: solo se comprueba el formato
    num, dv = v.split("-")
    weights = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
    total = sum(int(d) * w for d, w in zip(reversed(num), weights))
    r = total % 11
    return int(dv) == (r if r < 2 else 11 - r)


def _rut_ok(v: str) -> bool:
    num, dv = v.split("-")
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(num)))
    r = 11 - total % 11
    return dv == ("0" if r == 11 else "K" if r == 10 else str(r))


def _cpf_ok(v: str) -> bool:
    if len(set(v)) == 1:
        return False
    for n in (9, 10):
        total = sum(int(v[i]) * (n + 1 - i) for i in range(n))
        if int(v[n]) != (total * 10 % 11) % 10:
            return False
    return True


def _nie_ok(v: str) -> bool:
    n = int(str("XYZ".index(v[0])) + v[1:8])
    return v[8] == "TRWAGMYFPDXBNJZSQVHLCKE"[n % 23]


# mode: cómo se normaliza lo escrito ANTES de comprobar el patrón (digits: solo números, sin puntos/espacios/guiones; alnum: mayúsculas sin separadores).
ID_DOCS = [
    {"code": "CC", "label": "Cédula de ciudadanía (Colombia)", "mode": "digits", "pattern": r"\d{6,10}", "hint": "solo números, de 6 a 10 dígitos"},
    {"code": "TI", "label": "Tarjeta de identidad (Colombia)", "mode": "digits", "pattern": r"\d{10,11}", "hint": "solo números, 10 u 11 dígitos"},
    {"code": "CE", "label": "Cédula de extranjería (Colombia)", "mode": "digits", "pattern": r"\d{6,10}", "hint": "solo números, de 6 a 10 dígitos"},
    {"code": "RC", "label": "Registro civil (Colombia)", "mode": "digits", "pattern": r"\d{6,12}", "hint": "solo números, de 6 a 12 dígitos"},
    {"code": "PPT", "label": "Permiso por Protección Temporal — PPT (Colombia)", "mode": "digits", "pattern": r"\d{5,10}", "hint": "solo números, de 5 a 10 dígitos"},
    {"code": "PEP", "label": "Permiso Especial de Permanencia — PEP (Colombia)", "mode": "digits", "pattern": r"\d{8,15}", "hint": "solo números, de 8 a 15 dígitos"},
    {"code": "NIT", "label": "NIT (Colombia)", "mode": "nit", "pattern": r"\d{8,10}(-\d)?", "hint": "8 a 10 dígitos, con o sin guion y dígito de verificación (ej. 900123456-8)", "check": _nit_ok},
    {"code": "PA", "label": "Pasaporte", "mode": "alnum", "pattern": r"[A-Z0-9]{5,15}", "hint": "letras y números, de 5 a 15 caracteres, sin espacios"},
    {"code": "DNI", "label": "DNI / documento nacional (España, Perú, Argentina…)", "mode": "alnum", "pattern": r"[A-Z0-9]{6,12}", "hint": "letras y números, de 6 a 12 caracteres"},
    {"code": "NIE", "label": "NIE (España)", "mode": "alnum", "pattern": r"[XYZ]\d{7}[A-Z]", "hint": "X, Y o Z + 7 números + letra (ej. X1234567L)", "check": _nie_ok},
    {"code": "CPF", "label": "CPF (Brasil)", "mode": "digits", "pattern": r"\d{11}", "hint": "11 números (con o sin puntos y guion)", "check": _cpf_ok},
    {"code": "RUT", "label": "RUT (Chile)", "mode": "rut", "pattern": r"\d{7,8}-[\dK]", "hint": "7 u 8 números y dígito verificador (ej. 12345678-5)", "check": _rut_ok},
    {"code": "CI_EC", "label": "Cédula de identidad (Ecuador)", "mode": "digits", "pattern": r"\d{10}", "hint": "10 números"},
    {"code": "CI_VE", "label": "Cédula de identidad (Venezuela)", "mode": "alnum", "pattern": r"[VE]\d{6,9}", "hint": "V o E + de 6 a 9 números (ej. V12345678)"},
    {"code": "CURP", "label": "CURP (México)", "mode": "alnum", "pattern": r"[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d", "hint": "18 caracteres (ej. GOMC800101HDFRRL09)"},
    {"code": "OTRO", "label": "Otro documento", "mode": "alnum", "pattern": r"[A-Z0-9]{4,20}", "hint": "letras y números, de 4 a 20 caracteres"},
]
ID_DOC_BY_CODE = {d["code"]: d for d in ID_DOCS}


def id_docs_public() -> list:
    """Lo que el navegador necesita (sin las funciones de verificación, que solo corren en el servidor)."""
    return [{k: v for k, v in d.items() if k != "check"} for d in ID_DOCS]


def id_doc_normalize(mode: str, raw: str) -> str:
    text = str(raw or "").strip().upper()
    if mode == "digits":
        return re.sub(r"[\s.\-]", "", text)
    if mode == "alnum":
        return re.sub(r"[\s.\-]", "", text)
    if mode == "nit":
        return re.sub(r"[\s.]", "", text)
    if mode == "rut":
        text = re.sub(r"[\s.]", "", text)
        return text if "-" in text or len(text) < 2 else f"{text[:-1]}-{text[-1]}"
    return text


def validate_id_doc(code: str, raw: str):
    """(ok, número normalizado, mensaje). El servidor es quien manda: el navegador solo avisa antes."""
    spec = ID_DOC_BY_CODE.get(code)
    if not spec:
        return False, "", "tipo de documento no válido"
    value = id_doc_normalize(spec["mode"], raw)
    if not re.fullmatch(spec["pattern"], value):
        return False, value, f"{spec['label']}: {spec['hint']}"
    if spec.get("check") and not spec["check"](value):
        return False, value, f"{spec['label']}: el número no es válido (revisa los dígitos)"
    return True, value, ""


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
            if kind == "text_short" and f.get("doc_types"):      # el campo es un documento de identidad: tipos permitidos (validación por tipo)
                types = list(dict.fromkeys(str(c) for c in (f.get("doc_types") or []) if str(c) in ID_DOC_BY_CODE))
                if types:
                    clean["doc_types"] = types
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
        elif kind == PAYMENT_TYPE:
            clean["label"] = clean["label"] or "Pago"
            clean["pay"] = sanitize_payment(f.get("pay"), fields_in, fid)
        elif kind == COMPANIONS_TYPE:
            clean.update(_sanitize_companions(f))
        else:  # image
            clean["src"] = _text(f.get("src"), 200)
        clean["show_if"] = _sanitize_condition(f.get("show_if"), fields_in, fid)
        fields[fid] = clean

    if sum(1 for f in fields.values() if f["type"] == PAYMENT_TYPE) > 1:
        raise ValueError("Un formulario admite un solo campo de pago")
    if sum(1 for f in fields.values() if f["type"] == COMPANIONS_TYPE) > 1:
        raise ValueError("Un formulario admite un solo campo de acompañantes")
    for f in fields.values():
        if f["type"] == PAYMENT_TYPE and f["pay"].get("companions_charge") and not any(x["type"] == COMPANIONS_TYPE for x in fields.values()):
            raise ValueError("Para cobrar por los acompañantes agrega también el campo «Acompañantes»")
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


def _sanitize_rule(cond, fields_in: dict, own_id: str) -> dict:
    if not isinstance(cond, dict) or cond.get("field") not in fields_in or cond.get("field") == own_id:
        raise ValueError("Una regla condicional apunta a un campo que no existe")
    op = cond.get("op", "equals")
    if op not in CONDITION_OPS:
        raise ValueError("Operador de regla no válido")
    value = cond.get("value")
    return {"field": cond["field"], "op": op, "value": [str(v) for v in value] if isinstance(value, list) else _text(value, 200)}


def _sanitize_condition(cond, fields_in: dict, own_id: str):
    """Regla de visibilidad: una sola regla {field, op, value} o un GRUPO {match: all|any, rules: [...]} (hasta 6 reglas; «all» = todas, «any» = alguna)."""
    if not cond:
        return None
    if isinstance(cond, dict) and "rules" in cond:
        rules = [_sanitize_rule(r, fields_in, own_id) for r in (cond.get("rules") or [])[:6]]
        if not rules:
            return None
        return rules[0] if len(rules) == 1 else {"match": "any" if cond.get("match") == "any" else "all", "rules": rules}
    return _sanitize_rule(cond, fields_in, own_id)


def cond_rules(cond) -> list:
    return [] if not cond else (cond["rules"] if "rules" in cond else [cond])


def _check_condition_cycles(fields: dict) -> None:
    state = {}

    def walk(fid):
        if state.get(fid) == 1:
            raise ValueError("Las reglas condicionales se apuntan en círculo")
        if state.get(fid) == 2:
            return
        state[fid] = 1
        for r in cond_rules(fields[fid].get("show_if")):
            walk(r["field"])
        state[fid] = 2

    for fid in fields:
        walk(fid)


# ------------------------------------------------------------------ campo de pago: monto, reglas y descuentos
def _pesos(n: int) -> str:
    return "$" + f"{n:,}".replace(",", ".")


def _money(value, what: str) -> int:
    try:
        n = int(round(float(str(value).replace(",", ".")))) if value not in (None, "") else 0
    except (TypeError, ValueError):
        raise ValueError(f"{what}: escribe un monto en pesos (número)")
    if n < 0 or n > MAX_PAYMENT_COP:
        raise ValueError(f"{what}: el monto debe estar entre 0 y {_pesos(MAX_PAYMENT_COP)} COP (tope de Wompi por transacción)")
    if 0 < n < MIN_PAYMENT_COP:
        raise ValueError(f"{what}: el monto mínimo por transacción es {_pesos(MIN_PAYMENT_COP)} COP")
    return n


def _sanitize_price_conditions(conds, fields_in: dict, own_id: str) -> list:
    out = []
    for c in (conds or [])[:5]:
        if not isinstance(c, dict):
            raise ValueError("Una condición de precio no es válida")
        op, value = c.get("op", "equals"), c.get("value")
        if c.get("field") == DATE_FIELD:
            if op not in DATE_OPS:
                raise ValueError("Una condición de fecha debe ser «antes de» o «desde»")
            try:
                datetime.strptime(str(value), "%Y-%m-%d")
            except ValueError:
                raise ValueError("Una condición de fecha necesita una fecha válida")
            out.append({"field": DATE_FIELD, "op": op, "value": str(value)})
            continue
        ref = fields_in.get(c.get("field"))
        if not ref or c.get("field") == own_id or ref.get("type") not in INPUT_TYPES:
            raise ValueError("Una regla de precio apunta a un campo que no existe (o no guarda respuestas)")
        if op not in CONDITION_OPS:
            raise ValueError("Operador de regla de precio no válido")
        out.append({"field": c["field"], "op": op, "value": [str(v) for v in value] if isinstance(value, list) else _text(value, 200)})
    return out


def _sanitize_companions(f: dict) -> dict:
    """Configuración del campo «Acompañantes»: cuántos como máximo/mínimo y qué se pide de CADA acompañante."""
    try:
        mx = max(1, min(20, int(f.get("max") or 5)))
        mn = max(0, min(mx, int(f.get("min") or 0)))
    except (TypeError, ValueError):
        raise ValueError("«Acompañantes»: el máximo y el mínimo deben ser números")
    people, seen = [], set()
    for p in (f.get("person_fields") or [])[:6]:
        pid = str(p.get("id") or "")
        ptype = p.get("type") if p.get("type") in COMPANION_FIELD_TYPES else "text_short"
        label = _text(p.get("label"), 80)
        if not label or not re.fullmatch(r"[A-Za-z0-9_]{1,20}", pid) or pid in seen:
            raise ValueError("«Acompañantes»: cada dato que se pide necesita un nombre y no puede repetirse")
        seen.add(pid)
        people.append({"id": pid, "label": label, "type": ptype, "required": bool(p.get("required"))})
    if not people:
        people = [{"id": "nombre", "label": "Nombre completo", "type": "text_short", "required": True}]
    return {"max": mx, "min": mn, "person_fields": people}


def companions_count(design: dict, values: dict) -> int:
    """Cuántos acompañantes trae esta respuesta (0 si no hay campo, si está oculto por una regla o si vino vacío)."""
    for fid, f in design["fields"].items():
        if f["type"] == COMPANIONS_TYPE:
            if fid not in visible_ids(design, values):
                return 0
            v = values.get(fid)
            return max(0, min(len(v) if isinstance(v, list) else 0, f["max"]))
    return 0


def _price_meta(item: dict, allowed: tuple, used: set) -> dict:
    """Identidad y «cómo se aplica» de una regla de precio o descuento: `category` (por lo que la persona responde: variable + contenido),
    `link` (solo quien entra por el enlace propio de ese precio/descuento, `?d=<link_key>`) o `code` (solo quien escribe un código válido)."""
    how = item.get("how") if item.get("how") in allowed else "category"
    pid = str(item.get("id") or "")
    while not re.fullmatch(r"[a-z0-9]{4,12}", pid) or pid in used:
        pid = secrets.token_hex(3)
    used.add(pid)
    meta = {"id": pid, "how": how}
    if how == "link":
        key = str(item.get("link_key") or "")
        meta["link_key"] = key if re.fullmatch(r"[A-Za-z0-9]{6,24}", key) else secrets.token_hex(5)
    return meta


def public_design(design: dict) -> dict:
    """El diseño que ve el público: sin las claves de los enlaces de descuento (si no, cualquiera las leería) y con `pay.codes`
    para que se muestre la casilla del código."""
    out = json.loads(json.dumps(design))
    for f in out["fields"].values():
        if f.get("type") == PAYMENT_TYPE and isinstance(f.get("pay"), dict):
            f["pay"]["codes"] = any(d.get("how") == "code" for d in f["pay"].get("discounts", []))
            for item in f["pay"].get("rules", []) + f["pay"].get("discounts", []):
                item.pop("link_key", None)
    return out


def sanitize_payment(pay, fields_in: dict, own_id: str) -> dict:
    """Configuración del campo «Pago»: `mode` fixed (un monto) o rules (el monto depende de otras respuestas: la primera
    regla que se cumple manda; si ninguna, el monto base) y `discounts` (todos los que se cumplen se aplican en orden;
    porcentaje sobre el monto vigente, o valor fijo). Un monto final de 0 = no hay nada que cobrar."""
    pay = pay if isinstance(pay, dict) else {}
    mode = pay.get("mode") if pay.get("mode") in ("fixed", "rules") else "fixed"
    out = {"currency": "COP", "mode": mode, "description": _text(pay.get("description"), 120), "amount": _money(pay.get("amount"), "Monto del pago"), "rules": [], "discounts": [],
           "companions_charge": bool(pay.get("companions_charge")),
           "tax": pay.get("tax") if pay.get("tax") in ("add", "none") else ""}      # IVA: "add" = se suma el 19 % y se aclara «con IVA»; "none" = «precio sin IVA» (no se suma); "" = no se menciona      # cobrar el mismo valor por cada acompañante (tú + N)
    if not out["amount"] and mode == "fixed":
        raise ValueError("El campo de pago necesita un monto")
    used_ids: set = set()
    if mode == "rules":
        for r in (pay.get("rules") or [])[:20]:
            out["rules"].append({"label": _text(r.get("label"), 80), "when": _sanitize_price_conditions(r.get("when"), fields_in, own_id), "amount": _money(r.get("amount"), "Monto de una regla"),
                                 **_price_meta(r, ("category", "link"), used_ids)})
    for d in (pay.get("discounts") or [])[:20]:
        kind = d.get("kind") if d.get("kind") in ("percent", "amount") else "percent"
        try:
            value = float(str(d.get("value")).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError("Un descuento necesita un valor numérico")
        if kind == "percent" and not (0 < value <= 100):
            raise ValueError("Un descuento en porcentaje debe estar entre 0 y 100")
        if kind == "amount" and not (0 < value <= MAX_PAYMENT_COP):
            raise ValueError("Un descuento en pesos debe ser mayor que 0")
        out["discounts"].append({"label": _text(d.get("label"), 80) or "Descuento", "kind": kind, "value": round(value, 2) if kind == "percent" else int(round(value)),
                                 "when": _sanitize_price_conditions(d.get("when"), fields_in, own_id), **_price_meta(d, ("category", "link", "code"), used_ids)})
    return out


def payment_field(design: dict, values: Optional[dict] = None) -> Optional[dict]:
    """El campo de pago del formulario (con `values`, solo si está visible según las reglas), o None."""
    for fid, f in design["fields"].items():
        if f["type"] == PAYMENT_TYPE:
            return f if values is None or fid in visible_ids(design, values) else None
    return None


def _price_cond_met(c: dict, values: dict, today: date) -> bool:
    if c["field"] == DATE_FIELD:
        limit = datetime.strptime(c["value"], "%Y-%m-%d").date()
        return today < limit if c["op"] == "before" else today >= limit
    return condition_met(c, values)


def _applies(item: dict, values: dict, today: date, ctx: dict) -> bool:
    """¿Esta regla/descuento cuenta ahora? `ctx`: {"links": claves de enlace con las que entró la persona, "codes": ids de descuento
    cuyo código escribió y es válido}. Además de eso, siempre se piden sus condiciones (si tiene)."""
    how = item.get("how", "category")
    if how == "link" and item.get("link_key") not in ctx["links"]:
        return False
    if how == "code" and item.get("id") not in ctx["codes"]:
        return False
    return all(_price_cond_met(c, values, today) for c in item["when"])


def compute_amount(pay: dict, values: dict, today: date, people: int = 1, ctx: Optional[dict] = None) -> dict:
    """Monto en pesos según las respuestas (`values`: solo campos VISIBLES, ver `priced_values`) y la fecha de hoy.
    Devuelve {"amount", "unit", "people", "base", "applied": [{"label", "kind": "rule|discount|people", "effect"}]}: `applied` explica el total.
    Con `pay.companions_charge`, el precio por persona (con reglas y descuentos ya aplicados) se multiplica por `people` (quien se inscribe + sus acompañantes)."""
    ctx = ctx or {"links": set(), "codes": set()}
    amount, applied = pay["amount"], []
    # Entre las reglas de precio que se cumplen manda la MÁS ESPECÍFICA (la que pide más condiciones; un enlace propio cuenta como una más y gana
    # los empates); si empatan del todo, la primera de la lista. Así «categoría X = 100.000» y «categoría X + respondió Y = 150.000» conviven sin
    # que la primera tape a la segunda.
    met = [(len(r["when"]) + (1 if r.get("how") == "link" else 0), r.get("how") == "link", -i, r) for i, r in enumerate(pay.get("rules", [])) if _applies(r, values, today, ctx)]
    if met:
        r = max(met, key=lambda m: m[:3])[3]
        amount = r["amount"]
        applied.append({"label": r["label"] or "Regla de precio", "kind": "rule", "effect": f"monto {_pesos(amount)}", "id": r.get("id")})
    base = amount
    for d in pay.get("discounts", []):
        if _applies(d, values, today, ctx):
            cut = amount * d["value"] / 100 if d["kind"] == "percent" else d["value"]
            amount = max(0, int(amount - cut + 0.5))
            applied.append({"label": d["label"], "kind": "discount", "effect": f"-{d['value']:g}%" if d["kind"] == "percent" else f"-{_pesos(d['value'])}", "id": d.get("id")})
    n = max(1, int(people or 1)) if pay.get("companions_charge") else 1
    if n > 1:
        applied.append({"label": f"{n} personas (tú + {n - 1} acompañante{'s' if n > 2 else ''})", "kind": "people", "effect": f"× {n}"})
    total = amount * n
    tax = int(total * TAX_RATE / 100 + 0.5) if pay.get("tax") == "add" and total > 0 else 0
    if tax:
        applied.append({"label": f"IVA {TAX_RATE}%", "kind": "tax", "effect": f"+{_pesos(tax)}"})
    return {"amount": total + tax, "subtotal": total, "tax": tax, "unit": amount, "people": n, "base": base, "applied": applied}


def priced_values(design: dict, values: dict) -> dict:
    """Solo las respuestas de campos visibles: un campo oculto por una regla no puede cambiar el precio."""
    shown = visible_ids(design, values)
    return {k: v for k, v in values.items() if k in shown}


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
    q_in = s_in.get("quotas") or {}
    limits = {}
    for opt, n in list((q_in.get("limits") or {}).items())[:50]:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if 0 < n <= 1_000_000 and str(opt).strip():
            limits[_text(opt, 120)] = n
    out["quotas"] = {"field": _text(q_in.get("field"), 40) if limits else "", "limits": limits}
    out["feed"] = s_in.get("feed") if s_in.get("feed") in ("realtime", "on_close", "manual") else "manual"
    try:
        out["max_mb"] = max(1, min(20, int(s_in.get("max_mb") or 10)))
    except (TypeError, ValueError):
        out["max_mb"] = 10
    out["language"] = s_in.get("language") if s_in.get("language") in LANGUAGES else "es"
    out["translate"] = bool(s_in.get("translate", True))
    out["send_digital_badge"] = bool(s_in.get("send_digital_badge", False))
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
            met = [r["field"] in fields and visible(r["field"]) and condition_met(r, values) for r in cond_rules(cond)]
            result = any(met) if cond.get("match") == "any" else all(met)
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
        if kind == COMPANIONS_TYPE:
            _validate_companions(f, fid, values.get(fid), clean, errors, email_checker)
            continue
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
        if f.get("doc_types"):
            chosen = str(values.get(fid + "__tipo") or "") or f["doc_types"][0]
            if chosen not in f["doc_types"]:
                errors[fid] = f"«{label}»: elige un tipo de documento válido"
            else:
                ok, number, message = validate_id_doc(chosen, text)
                if ok:
                    clean[fid], clean[fid + "__tipo"] = number, chosen
                else:
                    errors[fid] = f"«{label}»: {message}"
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
            if not _NUMBER.match(text):
                errors[fid] = f"«{label}»: debe ser un número (solo dígitos, con punto o coma decimal si hace falta)"
        elif kind == "date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                errors[fid] = f"«{label}»: escribe una fecha válida"
        if fid not in errors and fid not in clean:
            clean[fid] = text
    return clean, errors


def _validate_companions(f: dict, fid: str, raw, clean: dict, errors: dict, email_checker=None) -> None:
    items = raw if isinstance(raw, list) else []
    if len(items) > f["max"]:
        errors[fid] = f"«{f['label']}»: máximo {f['max']}"
        return
    if len(items) < f["min"]:
        errors[fid] = f"«{f['label']}»: agrega al menos {f['min']}"
        return
    out = []
    for i, item in enumerate(items, start=1):
        item = item if isinstance(item, dict) else {}
        row = {}
        for pf in f["person_fields"]:
            text = str(item.get(pf["id"]) if item.get(pf["id"]) is not None else "").strip()[:200]
            who = f"Acompañante {i}: «{pf['label']}»"
            if not text:
                if pf["required"]:
                    errors[fid] = f"{who} es obligatorio"
                    return
                continue
            if pf["type"] == "email":
                if not _EMAIL.match(text):
                    errors[fid] = f"{who}: escribe un correo con formato válido"
                    return
                text = text.lower()
            elif pf["type"] == "phone" and not _PHONE.match(text):
                errors[fid] = f"{who}: escribe un teléfono válido"
                return
            elif pf["type"] == "number":
                if not _NUMBER.match(text):
                    errors[fid] = f"{who}: debe ser un número"
                    return
            row[pf["id"]] = text
        out.append(row)
    clean[fid] = out


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
