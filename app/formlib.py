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

from app import richtext

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
IDENTITY_KEYS = ("id", "first_name", "last_name", "role", "entity", "phone", "email", "opt_1", "birth_date")      # birth_date (L3): un campo «fecha» del formulario con esta clave decide si la persona puede tener captura biométrica
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
    "identify": {"title": "", "text": "", "image": "", "button": ""},   # paso «Identifícate» (cédula): vacío = los textos de siempre (title «Identifícate», text según sea obligatorio o no, button «Continuar»)
    "refunds": {"days": None, "note": ""},                           # condiciones de reembolso de ESTE formulario: plazo para pedirlo (días) y una nota (ej. quién asume la comisión)
    "quotas": {"rules": []},                                         # cupos: [{id, label, match: all|any, conds: [{field, op, value}], limit}]
    "feed": "manual",                                                # realtime | on_close | manual
    "max_mb": 10,
    "language": "es",                                                # idioma en que está escrito (<html lang>): el navegador ofrece traducir desde ahí
    "translate": True,                                               # mostrar el botón «Translate» para quien no habla ese idioma
    "send_digital_badge": False,                                     # enviar la escarapela virtual al correo del inscrito cuando entra a la base del evento
    "block_repeats": {"enabled": False, "field": ""},                # «Ya inscrito»: bloquear inscripciones repetidas; `field` = id del campo identificador ("" = el campo vinculado a la cédula)
}
REPEAT_FIELD_TYPES = ("text_short", "email", "phone", "number")      # campos que pueden servir de identificador para detectar una inscripción repetida


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


WIDTH_MIN, WIDTH_MAX = 480, 1100       # px; en pantallas más angostas la tarjeta siempre ocupa el 100 %


def _card_width(value):
    """«full» (completo), un entero de WIDTH_MIN a WIDTH_MAX px, o None (no se guarda: queda el ancho de siempre)."""
    if value == "full":
        return "full"
    if isinstance(value, bool):
        return None
    try:
        px = int(float(value))
    except (TypeError, ValueError):
        return None
    return px if WIDTH_MIN <= px <= WIDTH_MAX else None


def _percent(value, default: int) -> int:
    """Porcentaje 10–100 (o 0 = automático cuando `default` es 0); lo demás cae al valor por defecto."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if 10 <= n <= 100 else default


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
    theme["logo_width"] = _percent(theme_in.get("logo_width"), 0)      # % del ancho de la tarjeta; 0 = automático (como antes)
    theme["logo_full"] = bool(theme_in.get("logo_full"))               # el logo/banner ocupa la tarjeta de lado a lado, sin márgenes
    width = _card_width(theme_in.get("width"))                          # ancho máximo de la tarjeta; sin llave = 760 px como siempre
    if width is not None:
        theme["width"] = width

    fields_in = design.get("fields") or {}
    if not isinstance(fields_in, dict) or len(fields_in) > MAX_FIELDS:
        raise ValueError(f"Un formulario admite hasta {MAX_FIELDS} elementos")
    allowed_keys = set(IDENTITY_KEYS) | set(optional_keys)
    fields, used_keys, total_variants = {}, set(), 0
    for fid, f in fields_in.items():
        if not isinstance(f, dict) or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(fid)):
            raise ValueError("Elemento con identificador inválido")
        kind = f.get("type")
        if kind not in ALL_TYPES:
            raise ValueError(f"Tipo de campo no válido: {kind}")
        clean = {"id": fid, "type": kind, "label": _text(f.get("label"), 200), "help": richtext.clean_text(f.get("help"), 300)}      # la etiqueta (label) es texto plano: es el nombre de la columna en reportes. La ayuda y el nombre de presentación admiten formato completo
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
                if f.get("capture") == "signature":      # firma dibujada en un lienzo (compromiso digital): es un PNG pequeño que el navegador entrega como si fuera un archivo
                    clean.update({"capture": "signature", "accept": ["png"], "max_mb": 1})
            if f.get("sensitive"):      # dato sensible (Ley 1581): el servidor lo guarda CIFRADO aparte de data_json y lo borra por retención (formsvc.split_sensitive / purge_sensitive)
                clean["sensitive"] = True
        elif kind in ("heading", "paragraph"):
            clean["content"] = richtext.clean_text(f.get("content"), 2000)
        elif kind == PAYMENT_TYPE:
            clean["label"] = clean["label"] or "Pago"
            clean["pay"] = sanitize_payment(f.get("pay"), fields_in, fid)
        elif kind == COMPANIONS_TYPE:
            clean.update(_sanitize_companions(f))
        else:  # image
            clean["src"] = _text(f.get("src"), 200)
            clean["width"] = _percent(f.get("width"), 100)             # % del ancho disponible
            clean["alt"] = _text(f.get("alt"), 200)                    # texto alternativo (accesibilidad); vacío = imagen decorativa
        internal = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(f.get("internal_name") or "")).split())[:60]
        if internal:                        # «Nombre interno» (P11b): solo para el diseñador (listas, lienzo, encabezados del Excel); texto plano y nunca llega a la página pública
            clean["internal_name"] = internal
        if kind not in STATIC_TYPES:        # nombre de PRESENTACIÓN con formato: solo se pinta en el formulario público y la vista previa; todo lo demás usa `label`
            shown = richtext.clean_text(f.get("display_label"), 300)
            if shown:                       # sin llave si está vacío: los formularios existentes no cambian
                clean["display_label"] = shown
        variants, n_variants = _sanitize_variants(f.get("variants"), fields_in, fid, kind)
        if variants:                        # solo si el elemento las usa: los formularios existentes no ganan ninguna llave nueva
            clean["variants"] = variants
            total_variants += n_variants
        clean["show_if"] = _sanitize_condition(f.get("show_if"), fields_in, fid)
        fields[fid] = clean

    if total_variants > MAX_VARIANTS_PER_FORM:
        raise ValueError(f"El formulario admite hasta {MAX_VARIANTS_PER_FORM} variantes en total")
    if sum(1 for f in fields.values() if f["type"] == PAYMENT_TYPE) > 1:
        raise ValueError("Un formulario admite un solo campo de pago")
    if sum(1 for f in fields.values() if f["type"] == COMPANIONS_TYPE) > 1:
        raise ValueError("Un formulario admite un solo campo de acompañantes")
    for f in fields.values():
        if f["type"] == PAYMENT_TYPE and f["pay"].get("companions_charge") and not any(x["type"] == COMPANIONS_TYPE for x in fields.values()):
            raise ValueError("Para cobrar por los acompañantes agrega también el campo «Acompañantes»")
    sheets = _sanitize_sheets(design.get("sheets"), fields_in)
    sheet_ids = [s["id"] for s in sheets]
    rows, placed = [], set()
    for row in design.get("rows") or []:
        items = [i for i in (row.get("items") or []) if i in fields and i not in placed]
        if not items:
            continue
        if len(items) > 4:
            raise ValueError("Una fila admite hasta 4 elementos uno al lado del otro")
        placed.update(items)
        clean_row = {"align": row.get("align") if row.get("align") in ("left", "center", "right") else "left", "items": items}
        if sheets:
            clean_row["sheet"] = row.get("sheet") if row.get("sheet") in sheet_ids else sheet_ids[0]       # sin hoja (o inexistente) = la primera
        rows.append(clean_row)
    for fid in fields:                       # cualquier elemento que no quedó en una fila va al final (en la última hoja), en su propia fila
        if fid not in placed:
            rows.append({"align": "left", "items": [fid], **({"sheet": sheet_ids[-1]} if sheets else {})})
    if sheets:
        rows.sort(key=lambda r: sheet_ids.index(r["sheet"]))              # estable: dentro de cada hoja se conserva el orden
        _check_sheets(sheets, rows, fields)
    _check_condition_cycles(fields)
    out = {"theme": theme, "rows": rows, "fields": fields}
    if sheets:
        out["sheets"] = sheets
    return out


# ------------------------------------------------------------------ hojas (P12)
MAX_SHEETS = 20


def _sanitize_sheets(sheets_in, fields_in: dict) -> list:
    """Hojas del formulario [{id, title, description, show_if?}]. Con menos de 2 no hay hojas: es el formulario de una sola hoja de siempre (sin llave `sheets`).
    La primera y la última hoja son siempre visibles (no admiten `show_if`)."""
    if not isinstance(sheets_in, list) or len(sheets_in) < 2:
        return []
    if len(sheets_in) > MAX_SHEETS:
        raise ValueError(f"Un formulario admite hasta {MAX_SHEETS} hojas")
    sheets, seen = [], set()
    for i, s in enumerate(sheets_in):
        if not isinstance(s, dict) or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(s.get("id") or "")) or s["id"] in seen:
            raise ValueError("Hoja con identificador inválido o repetido")
        seen.add(s["id"])
        sheet = {"id": s["id"], "title": richtext.clean_text(s.get("title"), 120, basic=True), "description": richtext.clean_text(s.get("description"), 600)}
        cond = _sanitize_condition(s.get("show_if"), fields_in, "") if 0 < i < len(sheets_in) - 1 else None
        if cond:
            sheet["show_if"] = cond
        sheets.append(sheet)
    return sheets


def sheet_of_field(design: dict) -> dict:
    """{id del campo: id de su hoja}; vacío si el formulario es de una sola hoja."""
    return {fid: row["sheet"] for row in design.get("rows") or [] if row.get("sheet") for fid in row["items"]}


def _check_sheets(sheets: list, rows: list, fields: dict) -> None:
    index = {s["id"]: i for i, s in enumerate(sheets)}
    at = {fid: index[row["sheet"]] for row in rows for fid in row["items"]}
    last = len(sheets) - 1
    for fid, f in fields.items():
        if f["type"] in (PAYMENT_TYPE, COMPANIONS_TYPE) and at[fid] != last:
            raise ValueError("El pago y los acompañantes van en la última hoja")
        trees = [f.get("show_if")] + [it["when"] for v in variants_of(f).values() for it in v.get("items") or []]
        for tree in trees:                                                  # reglas y variantes: campos de la misma hoja o de una anterior
            if any(at[leaf["field"]] > at[fid] for leaf in cond_leaves(tree)):
                raise ValueError(f"«{f.get('label') or fid}»: una regla usa un campo de una hoja posterior")
    for i, s in enumerate(sheets):                                          # la condición de una hoja, solo con campos de hojas anteriores
        if any(at[leaf["field"]] >= i for leaf in cond_leaves(s.get("show_if"))):
            raise ValueError(f"La condición de la hoja «{_sheet_name(s)}» solo puede usar campos de hojas anteriores")


def _sheet_name(sheet: dict) -> str:       
    return richtext.to_plain(sheet.get("title") or "") or f"Hoja {sheet['id']}"


def first_error_sheet(design: dict, errors: dict) -> Optional[str]:
    """Id de la primera hoja (en su orden) que tiene un campo con error, para que el navegador salte a ella; None si el formulario es de una sola hoja."""
    at = sheet_of_field(design)
    order = [s["id"] for s in design.get("sheets") or []]
    hits = {at[fid.split("__")[0]] for fid in errors if fid.split("__")[0] in at}
    return next((sid for sid in order if sid in hits), None)


def _sanitize_rule(cond, fields_in: dict, own_id: str) -> dict:
    if not isinstance(cond, dict) or cond.get("field") not in fields_in or cond.get("field") == own_id:
        raise ValueError("Una regla condicional apunta a un campo que no existe")
    op = cond.get("op", "equals")
    if op not in CONDITION_OPS:
        raise ValueError("Operador de regla no válido")
    value = cond.get("value")
    return {"field": cond["field"], "op": op, "value": [str(v) for v in value] if isinstance(value, list) else _text(value, 200)}


# ------------------------------------------------------------------ condiciones en árbol y variantes por propiedad (P9)
# Condición = una HOJA {field, op, value} o un GRUPO {match: all|any, rules: [hojas o grupos], name?}. Las dos formas antiguas de `show_if`
# ({field,op,value} y {match,rules[]} de un nivel) son casos particulares: valen tal cual, sin migración.
MAX_COND_DEPTH = 3             # niveles de grupos (el grupo raíz cuenta como 1)
MAX_COND_LEAVES = 30           # hojas (reglas sueltas) por árbol
MAX_GROUP_RULES = 12           # hijos directos de un grupo
MAX_VARIANTS_PER_PROP = 200    # variantes de una propiedad de un elemento
MAX_VARIANTS_PER_FORM = 3000   # variantes en todo el formulario (P11 las genera desde una tabla)
# Propiedades con variantes por tipo de elemento. Sin variante que aplique: content y src → el elemento no ocupa espacio; las demás → su valor propio.
VARIANT_TARGETS = {"heading": ("content",), "paragraph": ("content",), "image": ("src",), PAYMENT_TYPE: ("display_label", "help"), COMPANIONS_TYPE: ("display_label", "help")}
INPUT_VARIANT_TARGETS = ("display_label", "help", "placeholder")
HIDEABLE_PROPS = ("content", "src")
# Ruta de una imagen subida desde el editor: «cliente/archivo.ext» (nada de URLs, «..» ni otras extensiones).
IMAGE_PATH_RE = re.compile(r"[A-Za-z0-9_-][\w.-]*/[A-Za-z0-9_-][\w.-]*\.(?:png|jpe?g|webp|gif)")


def _variant_targets(kind: str) -> tuple:
    return VARIANT_TARGETS.get(kind) or (INPUT_VARIANT_TARGETS if kind in INPUT_TYPES else ())


def variants_of(field: dict) -> dict:
    """{propiedad: {"items": [{"when", "value", "name"?}], "default"?}} del elemento. Normaliza el formato de P2 ({by, items:[{rule, content}], default}; nunca llegó a
    producción, este normalizador se quita en una versión posterior): era solo `content` y se reescribe al formato nuevo en el siguiente guardado."""
    v = field.get("variants")
    if not isinstance(v, dict):
        return {}
    if "items" in v:
        out = {"items": [{"when": it.get("rule"), "value": it.get("content", "")} for it in (v.get("items") or []) if isinstance(it, dict)]}
        if v.get("default"):
            out["default"] = v["default"]
        return {"content": out}
    return {k: x for k, x in v.items() if isinstance(x, dict)}


def _variant_value(prop: str, raw) -> str:
    if prop == "content":
        return richtext.clean_text(raw, 2000)
    if prop in ("display_label", "help"):
        return richtext.clean_text(raw, 300)
    if prop == "placeholder":
        return _text(raw, 120)
    text = _text(raw, 200)                                    # src: una ruta que no sea de una imagen subida NO es válida (None); vacío = «no mostrar imagen»
    return text if not text or IMAGE_PATH_RE.fullmatch(text) else None


def _sanitize_variants(v, fields_in: dict, own_id: str, kind: str):
    """Variantes de un elemento: {propiedad: {"items": [{"when": condición, "value", "name"?}], "default"?}}. Gana la primera cuya condición se cumple;
    si ninguna, `default`; si no hay (o es vacío): content/src no ocupan espacio y las demás propiedades usan su valor propio."""
    given = variants_of({"variants": v})
    out, total = {}, 0
    for prop in _variant_targets(kind):
        data = given.get(prop)
        if not data:
            continue
        raw_items = [it for it in (data.get("items") or []) if isinstance(it, dict)]
        if len(raw_items) > MAX_VARIANTS_PER_PROP:
            raise ValueError(f"Una propiedad admite hasta {MAX_VARIANTS_PER_PROP} variantes")
        items = []
        for it in raw_items:
            when = _sanitize_condition(it.get("when"), fields_in, own_id)
            if not when:
                continue                                      # una variante sin condición nunca se aplicaría
            value = _variant_value(prop, it.get("value"))
            if value is None:
                continue                                      # imagen con una ruta inválida: la variante se descarta
            item = {"when": when, "value": value}
            for extra in ("name", "group"):                # nombre de la variante y grupo (P10: el editor agrupa y pliega; no cambia qué se muestra)
                label = _text(it.get(extra), 40)
                if label:
                    item[extra] = label
            items.append(item)
        default = _variant_value(prop, data.get("default")) or ""
        if items or default:
            out[prop] = {"items": items, **({"default": default} if default else {})}
            total += len(items)
    return out or None, total


def pick_variant(field: dict, prop: str, values: dict, visible: Optional[set] = None) -> Optional[str]:
    """Valor que se muestra de `prop`: sin variantes, el propio; con variantes, el de la primera cuya condición se cumple, o el `default`. `visible`: ids de los campos
    visibles (una hoja sobre un campo oculto no cuenta; None = todos). Sin variante que aplique: None si la propiedad es ocultable (content, src), si no su valor propio.
    Igual que `pickVariant` de static/js/form-render.js."""
    v = variants_of(field).get(prop)
    if not v:
        return field.get(prop) or ""
    for it in v["items"]:
        if cond_tree_met(it["when"], values, lambda f: visible is None or f in visible):
            return it["value"] or (None if prop in HIDEABLE_PROPS else field.get(prop) or "")
    if v.get("default"):
        return v["default"]
    return None if prop in HIDEABLE_PROPS else field.get(prop) or ""


def image_refs(design: dict):
    """(dueño, clave) de cada ruta de imagen del diseño: la de los elementos imagen y las de sus variantes. Exportar/importar las lleva en el zip y cualquier barrido
    de archivos sin uso debe contarlas como referencias vivas."""
    for f in design["fields"].values():
        if f.get("type") == "image":
            yield f, "src"
        for prop, data in variants_of(f).items():
            if prop == "src":
                for it in data.get("items") or []:
                    yield it, "value"
                if data.get("default"):
                    yield data, "default"


def _sanitize_cond_node(node, fields_in: dict, own_id: str, depth: int, leaves: list):
    if isinstance(node, dict) and "rules" in node:
        if depth > MAX_COND_DEPTH:
            raise ValueError(f"Las condiciones admiten hasta {MAX_COND_DEPTH} niveles de grupos")
        kids = [k for k in (_sanitize_cond_node(r, fields_in, own_id, depth + 1, leaves) for r in (node.get("rules") or [])[:MAX_GROUP_RULES]) if k]
        if not kids:
            return None
        name = _text(node.get("name"), 40)
        if len(kids) == 1 and not name:
            return kids[0]
        out = {"match": "any" if node.get("match") == "any" else "all", "rules": kids}
        if name:
            out["name"] = name
        return out
    leaves[0] += 1
    if leaves[0] > MAX_COND_LEAVES:
        raise ValueError(f"Una condición admite hasta {MAX_COND_LEAVES} reglas")
    return _sanitize_rule(node, fields_in, own_id)


def _sanitize_condition(cond, fields_in: dict, own_id: str):
    """Condición (regla de visibilidad o de una variante): hoja o árbol de grupos Y/O, ver arriba."""
    if not cond:
        return None
    return _sanitize_cond_node(cond, fields_in, own_id, 1, [0])


def cond_leaves(cond) -> list:
    """Todas las hojas {field, op, value} de una condición, en cualquier nivel."""
    if not cond:
        return []
    if "rules" in cond:
        return [leaf for r in cond["rules"] for leaf in cond_leaves(r)]
    return [cond]


def cond_tree_met(node: dict, values: dict, is_visible: Callable) -> bool:
    """¿Se cumple la condición? Una hoja cuenta solo si su campo está visible (`is_visible(id)`) y se cumple con la normalización de P6; un grupo «all» pide todas, «any» alguna."""
    if "rules" in node:
        met = [cond_tree_met(r, values, is_visible) for r in node["rules"]]
        return any(met) if node.get("match") == "any" else bool(met) and all(met)
    return bool(is_visible(node["field"])) and condition_met(node, values)


def _check_condition_cycles(fields: dict) -> None:
    state = {}

    def walk(fid):
        if state.get(fid) == 1:
            raise ValueError("Las reglas condicionales se apuntan en círculo")
        if state.get(fid) == 2:
            return
        state[fid] = 1
        for r in cond_leaves(fields[fid].get("show_if")):
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
        f.pop("internal_name", None)                       # el nombre interno es del diseñador: no se publica
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


def _sanitize_quota_rules(q_in) -> list:
    """Cupos por combinación de variables: cada regla = condiciones sobre campos del formulario (todas o alguna) + un máximo de inscripciones.
    Acepta también el formato anterior {field, limits: {opción: máximo}} (un cupo por opción de un campo) y lo convierte."""
    q_in = q_in if isinstance(q_in, dict) else {}
    rules_in = q_in.get("rules")
    if rules_in is None and q_in.get("limits"):
        rules_in = [{"label": str(o), "limit": n, "conds": [{"field": q_in.get("field"), "op": "equals", "value": o}]} for o, n in (q_in.get("limits") or {}).items()]
    out, used = [], set()
    for r in (rules_in or []):
        if not isinstance(r, dict):
            continue
        try:
            limit = int(r.get("limit"))
        except (TypeError, ValueError):
            continue
        conds = []
        for c in (r.get("conds") or [])[:6]:
            if isinstance(c, dict) and c.get("field") and c.get("op", "equals") in CONDITION_OPS:
                v = c.get("value")
                conds.append({"field": _text(c["field"], 40), "op": c.get("op", "equals"), "value": [str(x) for x in v] if isinstance(v, list) else _text(v, 200)})
        if not (0 <= limit <= 1_000_000) or not conds:     # 0 = «cerrado temporalmente»: se guarda y nadie puede elegirlo
            continue
        rid = str(r.get("id") or "")
        while not re.fullmatch(r"[a-z0-9]{4,12}", rid) or rid in used:
            rid = secrets.token_hex(3)
        used.add(rid)
        label = _text(r.get("label"), 120) or f"Cupo {len(out) + 1}"
        try:
            sched = parse_schedule([i for i in (r.get("schedule") or []) if isinstance(i, dict)][:20])      # calendario propio del cupo (mismos tramos que el del formulario)
        except ValueError:
            sched = []
        item = {"id": rid, "label": label, "match": "any" if r.get("match") == "any" else "all", "conds": conds, "limit": limit, "message": richtext.clean_text(r.get("message"), QUOTA_MESSAGE_MAX, basic=True)}
        if r.get("status") in STATUSES and r.get("status") != "activo":
            item["status"] = r["status"]          # estado manual del cupo (como el del formulario); sin él = activo
        try:
            ca = r.get("closes_at")
            if ca:
                datetime.fromisoformat(str(ca))
                item["closes_at"] = str(ca)[:16]              # fecha de cierre del cupo; con `closes_enforce` cierra de verdad, sin él es solo un aviso (se muestra, no cierra)
                if r.get("closes_enforce") is True:
                    item["closes_enforce"] = True
        except ValueError:
            pass
        if sched:
            item["schedule"] = sched
            if r.get("use_schedule") is True:
                item["use_schedule"] = True
        out.append(item)   # admite negrilla, cursiva, subrayado y color como los demás mensajes
    return out


QUOTA_MESSAGE_MAX = 300
QUOTA_DEFAULT_MESSAGE = "Ya se llenaron los cupos de {cupo}. Elige otra opción para poder inscribirte."
QUOTA_DEFAULT_MESSAGE_SERVER = "Ya se llenaron los cupos de {cupo}. Elige otra opción o escribe a los organizadores."


QUOTA_CLOSED_MESSAGE = "Por ahora no estamos recibiendo inscripciones de {cupo}. Elige otra opción."


def quota_full_message(message, label, server: bool = False, closed: bool = False) -> str:
    """Texto que ve la persona cuando su elección cae en un cupo lleno: el mensaje de la regla (o el de siempre si está vacío) con «{cupo}» → nombre del cupo. Con `closed` (máximo 0) el texto por defecto es el de CERRADO.
    Espejo en JS: `quotaFullMessage` de static/js/form-render.js."""
    default = QUOTA_CLOSED_MESSAGE if closed else (QUOTA_DEFAULT_MESSAGE_SERVER if server else QUOTA_DEFAULT_MESSAGE)   # `closed`: el máximo del cupo es 0
    text = (richtext.to_plain(message) if server else str(message or "").strip()) or default       # el mensaje puede traer formato: en la respuesta del servidor (texto plano) se muestra sin etiquetas
    return text.replace("{cupo}", str(label or ""))


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
    for key in ("closed_template", "thanks", "identify"):
        base = out[key]
        given = s_in.get(key) if isinstance(s_in.get(key), dict) else {}
        for k in base:
            if k in given:
                base[k] = richtext.clean_text(given[k], 600) if k == "text" else _text(given[k], 200)      # el texto admite formato; el título sigue siendo texto plano
    if not IMAGE_PATH_RE.fullmatch(out["identify"]["image"]):      # la imagen del paso de cédula es SIEMPRE una ruta «cliente/archivo.ext» de las que sube el editor
        out["identify"]["image"] = ""
    if out["thanks"]["mode"] not in ("template", "redirect"):
        out["thanks"]["mode"] = "template"
    if out["thanks"]["mode"] == "redirect" and not re.match(r"^https?://[^\s]+$", out["thanks"]["url"] or ""):
        raise ValueError("La dirección a la que se redirige debe empezar con http:// o https://")
    out["quotas"] = {"rules": _sanitize_quota_rules(s_in.get("quotas"))}
    r_in = s_in.get("refunds") or {}
    try:
        r_days = int(r_in.get("days")) if r_in.get("days") not in (None, "") else None
    except (TypeError, ValueError):
        r_days = None
    out["refunds"] = {"days": r_days if r_days and 1 <= r_days <= 365 else None, "note": _text(r_in.get("note"), 600)}
    out["feed"] = s_in.get("feed") if s_in.get("feed") in ("realtime", "on_close", "manual") else "manual"
    try:
        out["max_mb"] = max(1, min(20, int(s_in.get("max_mb") or 10)))
    except (TypeError, ValueError):
        out["max_mb"] = 10
    out["language"] = s_in.get("language") if s_in.get("language") in LANGUAGES else "es"
    out["translate"] = bool(s_in.get("translate", True))
    out["send_digital_badge"] = bool(s_in.get("send_digital_badge", False))
    br = s_in.get("block_repeats") if isinstance(s_in.get("block_repeats"), dict) else {}
    out["block_repeats"] = {"enabled": bool(br.get("enabled")), "field": _text(br.get("field"), 40)}
    return out


def normalize_identifier(value, ftype: str = "text_short") -> str:
    """Valor de un campo identificador listo para comparar «ya inscrito»: teléfono = solo dígitos; los demás (correo, documento, otro) = minúsculas y sin espacios, puntos ni guiones.
    Debe coincidir con la expresión SQL de `formsvc.repeat_by_value`."""
    text = str(value if value is not None else "")
    if ftype == "phone":
        return re.sub(r"\D", "", text)
    if ftype == "email":
        return re.sub(r"\s", "", text.lower())          # el punto y el guion SÍ cuentan en un correo
    return re.sub(r"[\s.\-]", "", text.lower())


# ------------------------------------------------------------------ condiciones y visibilidad
def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None or value == "":
        return []
    return [str(value)]


def norm_value(x) -> str:
    """Valor de una regla listo para comparar: sin tildes, sin mayúsculas y con los espacios colapsados («Bogota» = « bogotá »).
    Debe coincidir con `norm` de static/js/form-render.js y static/js/form-sync.js."""
    text = unicodedata.normalize("NFD", str(x))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split()).lower()


def condition_met(cond: Optional[dict], values: dict) -> bool:
    if not cond:
        return True
    current = values.get(cond["field"])
    have = _as_list(current)
    want = cond.get("value")
    op = cond.get("op", "equals")
    norm = norm_value
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
    memo, sheet_memo = {}, {}
    sheet_at = sheet_of_field(design)
    sheet_cond = {s["id"]: s.get("show_if") for s in design.get("sheets") or []}

    def sheet_visible(sid):             # una hoja oculta por su condición oculta todos sus campos
        if sid not in sheet_memo:
            cond = sheet_cond.get(sid)
            sheet_memo[sid] = True if not cond else cond_tree_met(cond, values, lambda f: f in fields and visible(f))
        return sheet_memo[sid]

    def visible(fid):
        if fid in memo:
            return memo[fid]
        cond = fields[fid].get("show_if")
        result = sheet_visible(sheet_at[fid]) if fid in sheet_at else True
        if result and cond:
            result = cond_tree_met(cond, values, lambda f: f in fields and visible(f))
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


# ------------------------------------------------------------------ estado y calendario propios de un cupo
def rule_state_now(rule: dict, now_local: datetime) -> str:
    """Estado vigente del cupo, con la MISMA lógica del formulario: su estado manual (activo si no tiene) o, con «programar por fechas», el del tramo en curso (fuera de todo tramo =
    cerrado). El estado del formulario general SIEMPRE prima: si el formulario está cerrado o finalizado nadie entra y esto ni se consulta; un cupo cerrado no cierra el formulario."""
    st = effective_status(rule.get("status") or "activo", bool(rule.get("use_schedule")), rule.get("schedule") or [], now_local)
    if st == "activo" and rule.get("closes_enforce") and rule.get("closes_at") and now_local >= datetime.fromisoformat(rule["closes_at"]):
        return "cerrado"                       # llegó su fecha de cierre y se pidió que cierre de verdad
    return st


def rule_open_now(rule: dict, now_local: datetime) -> bool:
    return rule_state_now(rule, now_local) == "activo"      # pruebas y finalizado tampoco reciben inscripciones del público


def rule_limit_now(rule: dict, now_local: datetime) -> int:
    """Máximo vigente: el del cupo, o 0 («cerrado») si su estado/calendario no lo tiene activo ahora."""
    return rule["limit"] if rule_open_now(rule, now_local) else 0


def rule_schedule_info(rule: dict, now_local: datetime) -> Optional[dict]:
    """None si el cupo no tiene estado ni calendario propios (sigue al formulario). Si no: {state: 'abierto'|'cerrado'|'finalizado'|'pruebas', closes, opens} con `closes` = fin del tramo
    activo en curso y `opens` = inicio del próximo tramo activo (solo con calendario)."""
    sched, use = rule.get("schedule") or [], bool(rule.get("use_schedule"))
    if not use and (rule.get("status") or "activo") == "activo" and not rule.get("closes_at"):
        return None
    st = rule_state_now(rule, now_local)
    info = {"state": "abierto" if st == "activo" else st, "closes": None, "opens": None, "enforced": bool(rule.get("closes_enforce"))}
    if rule.get("closes_at") and st == "activo":
        info["closes"] = rule["closes_at"]       # aviso «Cierra el…» (también cuando no cierra por sí sola)
    elif rule.get("closes_at") and st == "cerrado" and rule.get("closes_enforce"):
        info["closes"] = rule["closes_at"]       # ya cerró por su fecha: se sigue mostrando (en rojo)
    if use:
        act = [t for t in sched if t.get("status") == "activo"]
        for t in act:
            if datetime.fromisoformat(t["from"]) <= now_local < datetime.fromisoformat(t["to"]):
                info["closes"] = min(filter(None, [t["to"], info["closes"]]))
        if st != "activo":
            nxt = [t for t in act if datetime.fromisoformat(t["from"]) > now_local]
            info["opens"] = nxt[0]["from"] if nxt else None
    if info["closes"]:
        info["days_left"] = round((datetime.fromisoformat(info["closes"]) - now_local).total_seconds() / 86400, 2)      # negativo = la fecha ya pasó
    return info


# ------------------------------------------------------------------ tabla de respuestas: paginación y búsqueda (pura, sin base)
ANSWERS_PAGE_SIZES = (20, 50, 100)
ANSWERS_DEFAULT_PAGE_SIZE = 20
ANSWERS_MAX_QUERY = 80


def answers_page_size(raw) -> int:
    """Tamaño de página de la tabla de respuestas: 20, 50 o 100. Un valor no válido (o ausente) usa 50; uno mayor a 100 se acota a 100."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return ANSWERS_DEFAULT_PAGE_SIZE
    if n in ANSWERS_PAGE_SIZES:
        return n
    return ANSWERS_PAGE_SIZES[-1] if n > ANSWERS_PAGE_SIZES[-1] else ANSWERS_DEFAULT_PAGE_SIZE


def answers_paging(total: int, page, page_size) -> dict:
    """{page, page_size, pages, offset}: la página pedida se acota a [1, pages] (pedir la 9 de 3 devuelve la 3); sin resultados hay 1 página vacía."""
    size = answers_page_size(page_size)
    pages = max(1, -(-max(0, int(total)) // size))
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    p = min(max(1, p), pages)
    return {"page": p, "page_size": size, "pages": pages, "offset": (p - 1) * size}


def _compact_id(value) -> str:
    """Documento comparable: minúsculas, sin espacios/puntos/guiones y, si es solo números, sin ceros a la izquierda."""
    text = re.sub(r"[\s.\-]", "", str(value if value is not None else "").lower())
    return text.lstrip("0") if text.isdigit() else text


def answers_search_fields(design: dict) -> dict:
    """Qué campos del formulario sirven para buscar: `ids` (clave de identidad `id` o campo con tipos de documento) y `names` (claves first_name y last_name).
    Si el formulario no marca ninguno de un grupo, `answers_match` busca en TODOS los valores de texto para ese grupo."""
    ids, names = [], []
    for fid, f in design.get("fields", {}).items():
        if f.get("type") not in INPUT_TYPES:
            continue
        if f.get("key") == "id" or f.get("doc_types"):
            ids.append(fid)
        elif f.get("key") in ("first_name", "last_name"):
            names.append(fid)
    return {"ids": ids, "names": names}


def answers_parse_query(q) -> Optional[dict]:
    """Prepara la búsqueda una sola vez. None = sin filtro. Regla (misma idea que el buscador del Registro, sin corrección de tipeo):
      - documento: lo escrito sin espacios/puntos/guiones (y sin ceros a la izquierda si son solo números) debe ser el INICIO del documento de la persona (exacto o prefijo);
      - nombre: cada palabra escrita (sin tildes ni mayúsculas) debe ser el INICIO de una palabra distinta del nombre o apellido, en cualquier orden (nada de «contiene»: «ma» no encuentra «Amaya»)."""
    text = str(q or "").strip()[:ANSWERS_MAX_QUERY]
    if not text:
        return None
    words = re.findall(r"[a-z0-9]+", norm_value(text))
    if not words:
        return None
    return {"doc": _compact_id(text), "words": words, "numeric": bool(re.fullmatch(r"[\d.\s\-]+", text))}


def _scalars(data: dict, fids=None) -> list:
    out = []
    for fid, v in data.items():
        if fids is not None and fid not in fids:
            continue
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
            out.append(str(v))
    return out


def answers_match(parsed: Optional[dict], data: dict, person_id, fields: dict) -> bool:
    """¿La inscripción cumple la búsqueda `parsed` (de `answers_parse_query`)? `fields` sale de `answers_search_fields`."""
    if parsed is None:
        return True
    id_vals = _scalars(data, set(fields["ids"])) if fields["ids"] else []
    if person_id:
        id_vals.append(str(person_id))
    if not fields["ids"] and not person_id:
        id_vals = _scalars(data)          # el formulario no marca documento: cualquier valor puede serlo
    if parsed["doc"] and any(_compact_id(v).startswith(parsed["doc"]) for v in id_vals):
        return True
    if parsed["numeric"]:
        return False
    name_vals = _scalars(data, set(fields["names"])) if fields["names"] else _scalars(data)
    hay = [w for v in name_vals for w in re.findall(r"[a-z0-9]+", norm_value(v))]
    for qw in parsed["words"]:
        i = next((k for k, hw in enumerate(hay) if hw.startswith(qw)), -1)
        if i < 0:
            return False
        hay.pop(i)
    return True


def answers_quota_groups(rules: list, design: dict) -> dict:
    """{id de la regla de cupo: nombre de la variable que la define} para agrupar el filtro: la etiqueta del campo si todas sus condiciones miran el mismo campo; si no, ''."""
    out = {}
    for r in rules:
        fields = {c["field"] for c in r["conds"]}
        out[r["id"]] = design.get("fields", {}).get(next(iter(fields)), {}).get("label", "") if len(fields) == 1 else ""
    return out
