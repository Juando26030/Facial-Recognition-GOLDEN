"""Plantilla de evento (Fase 2, entrega 2): lógica PURA (sin base de datos ni FastAPI, se prueba sola).

Qué es: la definición, hecha por un administrador, de los campos que tiene un evento, cuáles pide «Nuevo evento» (y en qué orden y pasos) y cuáles salen en la tarjeta del calendario.
Dónde se guarda cada VALOR:
  * campos base (código, nombre, país, ciudad, fechas, coordinador, comercial, pañoleta…)  -> las columnas de `events` de siempre. NADA cambia para el resto del sistema.
  * interruptores del evento (rostro, inventario, áreas, certificados…)                     -> las columnas booleanas de `events` que ya usa «Parámetros del evento» (UNA sola fuente de datos).
  * campos personalizados (clave `c_…`)                                                     -> `events.extra_json` {clave: valor}.
Quitar un campo personalizado de la plantilla NUNCA borra lo guardado en los eventos: el campo queda «retirado» (sigue en la lista con `retired`, sus valores siguen en `extra_json`).

Contratos para el resto de la Fase 2: docs/FASE_2_ALCANCE.md, sección «Plantilla de evento: modelo y contratos». El espejo en el navegador es static/js/event-field-render.js."""
import copy
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app import event_inventory

SCOPE_GLOBAL = "global"


class TemplateError(ValueError):
    """Plantilla o valor inválido; el mensaje va en español, listo para mostrar tal cual."""


# ------------------------------------------------------------------------------------------------------------------------------------ límites (topes razonables)
MAX_ACTIVE_FIELDS = 80            # campos no retirados (los base y los interruptores ya son ~30)
MAX_TOTAL_FIELDS = 160            # con los retirados
MAX_TITLE = 60
MAX_HELP = 200
MAX_OPTIONS = 50
MAX_OPTION_LEN = 60
MAX_SECTIONS = 6
MAX_SECTION_TITLE = 40
MAX_ZONE_ITEMS = 12
MAX_INVENTORY_TYPES = 20
MAX_INVENTORY_REFS = 30
MAX_INVENTORY_LINES = event_inventory.MAX_LINES
MAX_INVENTORY_QTY = event_inventory.MAX_QTY
MAX_COLORS = 8
MAX_EXTRA_BYTES = 20_000          # tope del JSON de valores personalizados de UN evento
MAX_PAYLOAD_BYTES = 400_000       # tope del cuerpo de PUT (lo revisa el router)
MAX_SHORT = 200
MAX_LONG = 2000
MONEY_MAX = Decimal("9999999999999")      # ~10 billones: sobra para pesos
NUMBER_ABS_MAX = Decimal("999999999999")

KEY_RE = re.compile(r"^c_[a-z0-9]{1,24}$")                   # claves de campos personalizados
SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
INV_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_BAD_TEXT = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_LONG = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]")        # el texto largo acepta saltos de línea (\n \r \t) pero no marcas HTML

# ------------------------------------------------------------------------------------------------------------------------------------ tipos de campo
# creatable: el administrador puede crear campos nuevos de este tipo. Los demás solo existen como campos base/ligados.
TYPES = {
    "text_short": {"label": "Texto corto", "creatable": True},
    "text_long": {"label": "Texto largo", "creatable": True},
    "select": {"label": "Lista desplegable", "creatable": True},
    "money": {"label": "Dinero", "creatable": True},
    "number": {"label": "Número", "creatable": True},
    "commercial": {"label": "Comercial", "creatable": True},
    "coordinator": {"label": "Coordinador", "creatable": True},
    "date": {"label": "Fecha", "creatable": True},
    "time": {"label": "Hora", "creatable": True},
    "datetime": {"label": "Fecha y hora", "creatable": True},
    "country": {"label": "País", "creatable": True},
    "city": {"label": "Ciudad", "creatable": True},
    "address_map": {"label": "Dirección con mapa", "creatable": True},
    "contact": {"label": "Contacto del evento", "creatable": True},
    "bandana_colors": {"label": "Colores de pañoletas", "creatable": True},
    "inventory": {"label": "Inventario (anterior)", "creatable": False},          # Fase 5: ya no se crea; vive el catálogo (app/inventory_unify.py). Un campo viejo sobrevive solo «retirado»
    "workday": {"label": "Jornada (calculada)", "creatable": False},
    "switch": {"label": "Interruptor", "creatable": False},
    "client": {"label": "Cliente", "creatable": False},
    "super_event": {"label": "Superevento", "creatable": False},
    "event_type": {"label": "Categoría (tipo de evento)", "creatable": False},          # Fase 10 (C): lista que administra el super_admin (app/routers/event_types.py)
}
CREATABLE_TYPES = tuple(t for t, m in TYPES.items() if m["creatable"])
CURRENCIES = ("COP", "USD", "EUR")

# ------------------------------------------------------------------------------------------------------------------------------------ interruptores (UNA fuente: las columnas de `events` de Parámetros)
# key = nombre de la opción; column = columna de events donde vive (la misma que cambia «Parámetros del evento»); requires = otra opción que debe estar activa.
SWITCHES = [
    {"key": "facial_enabled", "title": "Reconocimiento facial", "help": "El evento usa el rostro en la puerta. Se puede cambiar después en Parámetros del evento.", "requires": None},
    {"key": "aceptar_enabled", "title": "Aceptación desde el celular", "help": "Las personas aceptan y dan la selfie desde el celular antes del evento. Necesita el reconocimiento facial.", "requires": "facial_enabled"},
    {"key": "face_door_enabled", "title": "Entrada con rostro sin ayuda", "help": "Pantalla de autoservicio «Entrar con mi rostro». Necesita el reconocimiento facial.", "requires": "facial_enabled"},
    {"key": "inventory_enabled", "title": "Control de inventario", "help": "Reparto de insumos a las personas del evento.", "requires": None},
    {"key": "areas_enabled", "title": "Control de áreas", "help": "Entrada y salida por zonas.", "requires": None},
    {"key": "certificates_enabled", "title": "Certificados", "help": "Certificados descargables para los asistentes.", "requires": None},
    {"key": "digital_badge_enabled", "title": "Escarapela digital", "help": "Escarapela enviada por correo.", "requires": None},
    {"key": "auto_print_badge", "title": "Imprimir la escarapela sola", "help": "Al registrar a alguien se imprime la escarapela sin tocar el botón.", "requires": None},
    {"key": "auto_register", "title": "Modo autoregistro", "help": "Un acierto en la puerta acredita a la persona de una vez, sin confirmar.", "requires": None},
    {"key": "shared_print_enabled", "title": "Impresión compartida", "help": "Varias personas imprimen en una misma impresora.", "requires": None},
]
SWITCH_KEYS = tuple(s["key"] for s in SWITCHES)
SWITCH_BY_KEY = {s["key"]: s for s in SWITCHES}
# Nota: la «Ruleta» no tiene interruptor en Parámetros del evento (siempre está disponible), así que no se ofrece aquí para no inventar una segunda fuente de datos.


# Títulos anteriores de campos de fábrica que se renombraron (2026-11-07: «Impresión compartida y por USB» → «Impresión compartida»).
LEGACY_TITLES = {"sw_shared_print_enabled": ("Impresión compartida y por USB",)}


def default_title_for(field_key: str) -> str:
    for s in SWITCHES:
        if switch_field_key(s["key"]) == field_key:
            return s["title"]
    return field_key


def switch_field_key(switch: str) -> str:
    return "sw_" + switch


# ------------------------------------------------------------------------------------------------------------------------------------ campos base
# key = nombre de la columna de events (o «bandana» = bandana_color + bandana_color_name; «client» = tenant_id).
# locked: siempre obligatorio y no se puede quitar de la vista de creación. section/cal: dónde va de fábrica.
def _b(key, type_, title, required, section=None, **extra):
    d = {"key": key, "type": type_, "title": title, "required": required, "section": section}
    d.update(extra)
    return d


BASE_FIELDS = [
    _b("client", "client", "Cliente", True, "datos", locked=True),
    _b("event_code", "text_short", "Código interno", True, "datos", locked=True, help="Va en los enlaces y QR del evento y no se puede cambiar después. Solo letras sin tilde, números, punto, guion o guion bajo (ej. FERIA-2026)."),
    _b("name", "text_short", "Nombre del evento", True, "datos", locked=True),
    _b("event_type_id", "event_type", "Categoría (tipo de evento)", False, "datos", help="Opcional: el tipo de evento (Feria, Congreso…). Con él el calendario filtra por categoría."),
    _b("country", "country", "País", True, "datos"),
    _b("city", "city", "Ciudad", True, "datos", config={"country_key": "country"}),
    _b("location", "text_short", "Lugar", True, "datos"),
    _b("address", "text_short", "Dirección", True, "datos"),
    _b("start_date", "date", "Fecha inicio", True, "fechas"),
    _b("end_date", "date", "Fecha fin", True, "fechas"),
    _b("event_time_start", "time", "Hora inicio evento", True, "fechas"),
    _b("event_time_end", "time", "Hora fin evento", True, "fechas"),
    _b("setup_date", "date", "Fecha montaje", True, "fechas"),
    _b("setup_time_start", "time", "Hora inicio montaje", True, "fechas"),
    _b("setup_time_end", "time", "Hora fin montaje", True, "fechas"),
    # Fase 5: campo INFORMATIVO calculado (app/workday.py). No es una columna ni un valor guardado: se deduce de event_time_start/event_time_end. De fábrica no está en ninguna vista;
    # el administrador decide si lo agrega a «Nuevo evento»/«Editar evento» y si sale en la tarjeta del calendario (colocándolo en una zona).
    _b("workday", "workday", "Jornada", False, None, help="Se calcula sola con la hora de inicio y la de fin del evento. No se edita."),
    _b("coordinator_staff_id", "coordinator", "Coordinador asignado", True, "responsables"),
    _b("commercial_staff_id", "commercial", "Comercial asignada", True, "responsables"),
    _b("super_event_id", "super_event", "Superevento", False, "responsables", help="Opcional: agrupa eventos hermanos de este cliente."),
    _b("bandana", "bandana_colors", "Color de pañoleta", False, "revisa", config={"max": 1}),
    _b("notes", "text_long", "Observaciones", False, "revisa"),
]
BASE_BY_KEY = {f["key"]: f for f in BASE_FIELDS}
LOCKED_KEYS = tuple(f["key"] for f in BASE_FIELDS if f.get("locked"))
BASE_KEYS = tuple(f["key"] for f in BASE_FIELDS)
SWITCH_FIELD_KEYS = tuple(switch_field_key(k) for k in SWITCH_KEYS)
BOUND_KEYS = BASE_KEYS + SWITCH_FIELD_KEYS            # los que NO viven en extra_json

# columnas de events que escribe cada campo base (para armar el Event al crear)
BASE_COLUMNS = {"client": ("tenant_id",), "bandana": ("bandana_color", "bandana_color_name")}
for _f in BASE_FIELDS:
    if _f["type"] != "workday":          # la jornada no tiene columna: se calcula
        BASE_COLUMNS.setdefault(_f["key"], (_f["key"],))
for _s in SWITCH_KEYS:
    BASE_COLUMNS[switch_field_key(_s)] = (_s,)

DEFAULT_SECTIONS = [
    ("datos", "Datos del evento"),
    ("fechas", "Fechas y horas"),
    ("responsables", "Responsables"),
    ("revisa", "Revisa y crea"),
]
DEFAULT_CALENDAR = {
    "top": [("name", False), ("event_code", False)],
    "left": [("city", False), ("start_date", True), ("end_date", True)],
    "right": [("event_time_start", True), ("event_time_end", True), ("coordinator_staff_id", True)],
    "bottom": [("location", False), ("commercial_staff_id", True)],
}
ZONES = ("top", "left", "right", "bottom")
ZONE_LABELS = {"top": "Arriba (encabezado)", "left": "Izquierda", "right": "Derecha", "bottom": "Abajo"}


def default_template() -> dict:
    """La plantilla de fábrica: reproduce EXACTAMENTE lo que «Nuevo evento» pedía antes de existir la plantilla (mismos campos, pasos y obligatoriedad)."""
    fields = []
    for b in BASE_FIELDS:
        f = {"key": b["key"], "type": b["type"], "title": b["title"], "required": b["required"], "options": [], "config": clean_config(b["type"], b.get("config") or {}), "help": b.get("help", ""), "retired": False}
        fields.append(f)
    for s in SWITCHES:
        fields.append({"key": switch_field_key(s["key"]), "type": "switch", "title": s["title"], "required": False, "options": [], "config": {"switch": s["key"]}, "help": s["help"], "retired": False})
    sections = [{"id": sid, "title": title, "keys": [b["key"] for b in BASE_FIELDS if b["section"] == sid]} for sid, title in DEFAULT_SECTIONS]
    cal = {z: [{"key": k, "label": lab} for k, lab in DEFAULT_CALENDAR[z]] for z in ZONES}
    return {"fields": fields, "creation_layout": {"sections": sections}, "calendar_layout": {"zones": cal}}


# ------------------------------------------------------------------------------------------------------------------------------------ utilidades
def _text(value, what: str, max_len: int, allow_empty: bool = False, long: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise TemplateError(f"{what} debe ser texto")
    v = value.strip()
    if (_BAD_LONG if long else _BAD_TEXT).search(v):
        raise TemplateError(f"{what} no puede incluir «<», «>» ni caracteres de control")
    if not v and not allow_empty:
        raise TemplateError(f"{what} no puede quedar vacío")
    if len(v) > max_len:
        raise TemplateError(f"{what} admite hasta {max_len} caracteres")
    return v


def _int(value, what: str, lo: int, hi: int) -> int:
    if isinstance(value, bool):
        raise TemplateError(f"{what} debe ser un número entero")
    try:
        n = int(str(value).strip()) if not isinstance(value, int) else value
    except (TypeError, ValueError):
        raise TemplateError(f"{what} debe ser un número entero")
    if n < lo or n > hi:
        raise TemplateError(f"{what} debe estar entre {lo} y {hi}")
    return n


def _decimal(value, what: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise TemplateError(f"{what} debe ser un número")
    if isinstance(value, (int, float)):
        d = Decimal(str(value))
    else:
        raw = str(value).strip().replace(" ", "")
        if raw.count(",") and not raw.count("."):
            raw = raw.replace(",", ".") if raw.count(",") == 1 else raw.replace(",", "")
        elif raw.count(",") and raw.count("."):
            raw = raw.replace(",", "")
        try:
            d = Decimal(raw)
        except InvalidOperation:
            raise TemplateError(f"{what} debe ser un número")
    if not d.is_finite():
        raise TemplateError(f"{what} debe ser un número")
    return d


def _num_out(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def is_empty(value) -> bool:
    """¿Sin valor? (un interruptor en «no» NO está vacío)."""
    if value is None or value is False:
        return value is None
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, dict):
        return all(is_empty(v) for v in value.values())
    return False


# ------------------------------------------------------------------------------------------------------------------------------------ configuración por tipo
def clean_config(type_: str, config, fields_so_far=None, key: str = "") -> dict:
    """Deja solo la configuración que el tipo entiende, validada. Lo desconocido se descarta."""
    c = config if isinstance(config, dict) else {}
    out = {}
    if type_ == "text_short":
        out["max_len"] = _int(c.get("max_len", MAX_SHORT), "El largo máximo", 1, MAX_SHORT)
    elif type_ == "text_long":
        out["max_len"] = _int(c.get("max_len", MAX_LONG), "El largo máximo", 1, MAX_LONG)
    elif type_ == "money":
        cur = c.get("currency", "COP")
        if cur not in CURRENCIES:
            raise TemplateError("La moneda debe ser una de: " + ", ".join(CURRENCIES))
        out["currency"] = cur
    elif type_ == "number":
        lo = _decimal(c["min"], "El mínimo") if c.get("min") not in (None, "") else None
        hi = _decimal(c["max"], "El máximo") if c.get("max") not in (None, "") else None
        if lo is not None and hi is not None and lo > hi:
            raise TemplateError("El mínimo no puede ser mayor que el máximo")
        for what, v in (("El mínimo", lo), ("El máximo", hi)):
            if v is not None and abs(v) > NUMBER_ABS_MAX:
                raise TemplateError(f"{what} es demasiado grande")
        out["min"] = _num_out(lo) if lo is not None else None
        out["max"] = _num_out(hi) if hi is not None else None
        out["decimals"] = _int(c.get("decimals", 0), "Los decimales", 0, 4)
    elif type_ == "city":
        ck = c.get("country_key")
        out["country_key"] = ck if isinstance(ck, str) and ck else None
    elif type_ == "bandana_colors":
        out["max"] = _int(c.get("max", 1), "La cantidad máxima de colores", 1, MAX_COLORS)
    elif type_ == "inventory":
        out["inventory_types"] = _clean_inventory_types(c.get("inventory_types"))
    elif type_ == "switch":
        sw = c.get("switch")
        if sw not in SWITCH_BY_KEY:
            raise TemplateError("Interruptor desconocido")
        out["switch"] = sw
    return out


def _clean_inventory_types(raw) -> list:
    if not isinstance(raw, list) or not raw:
        raise TemplateError("El inventario necesita al menos un tipo (por ejemplo «Pañoletas»)")
    if len(raw) > MAX_INVENTORY_TYPES:
        raise TemplateError(f"El inventario admite hasta {MAX_INVENTORY_TYPES} tipos")
    out, seen, seen_labels = [], set(), set()
    for t in raw:
        if not isinstance(t, dict):
            raise TemplateError("Tipo de inventario inválido")
        label = _text(t.get("label"), "El nombre del tipo de inventario", MAX_TITLE)
        key = t.get("key")
        if not isinstance(key, str) or not INV_KEY_RE.match(key):
            raise TemplateError("Clave de tipo de inventario inválida")
        if key in seen:
            raise TemplateError("Hay dos tipos de inventario con la misma clave")
        seen.add(key)
        if label.lower() in seen_labels:
            raise TemplateError(f"Hay dos tipos de inventario llamados «{label}»")
        seen_labels.add(label.lower())
        refs = _clean_options(t.get("refs") or [], "Las referencias", MAX_INVENTORY_REFS, allow_empty_list=True)
        out.append({"key": key, "label": label, "refs": refs})
    return out


def _clean_options(raw, what: str, max_items: int, allow_empty_list: bool = False) -> list:
    if not isinstance(raw, list):
        raise TemplateError(f"{what} deben ser una lista")
    if not raw and not allow_empty_list:
        raise TemplateError(f"{what}: agrega al menos una opción")
    if len(raw) > max_items:
        raise TemplateError(f"{what} admiten hasta {max_items} opciones")
    out, seen = [], set()
    for o in raw:
        v = _text(o, "Una opción", MAX_OPTION_LEN)
        if v.lower() in seen:
            raise TemplateError(f"{what}: «{v}» está repetida")
        seen.add(v.lower())
        out.append(v)
    return out


# ------------------------------------------------------------------------------------------------------------------------------------ validación de la plantilla
def merge_missing_base(tpl: dict) -> dict:
    """Plantilla guardada + los campos base/interruptores que el código haya agregado después (quedan fuera de las vistas hasta que el administrador los ponga)."""
    out = copy.deepcopy(tpl)
    for f in out["fields"]:      # renombres de fábrica: una plantilla guardada con el título anterior toma el nuevo (el administrador sigue pudiendo cambiarlo a otro)
        if f.get("title") in LEGACY_TITLES.get(f.get("key"), ()):
            f["title"] = default_title_for(f["key"])
    have = {f["key"] for f in out["fields"]}
    for f in default_template()["fields"]:
        if f["key"] not in have:
            out["fields"].append(f)
    if "event_type_id" not in have:          # Fase 10 (C): la categoría aparece SOLA en «Nuevo evento» (Datos del evento) de las plantillas guardadas antes; el administrador puede quitarla al guardar la plantilla
        for sec in out.get("creation_layout", {}).get("sections", []):
            if sec.get("id") == "datos" and "event_type_id" not in sec.get("keys", []):
                keys = sec.setdefault("keys", [])
                keys.insert(keys.index("name") + 1 if "name" in keys else len(keys), "event_type_id")
                break
    return out


def validate_template(payload, previous: dict = None) -> dict:
    """Valida y normaliza el cuerpo de PUT. `previous` = plantilla vigente (para retirar, sin borrar, los campos personalizados que ya no vengan).
    Devuelve {"fields", "creation_layout", "calendar_layout"} listo para guardar; lanza TemplateError con un mensaje claro."""
    if not isinstance(payload, dict):
        raise TemplateError("La plantilla debe ser un objeto")
    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise TemplateError("Falta la lista de campos")
    if len(raw_fields) > MAX_TOTAL_FIELDS:
        raise TemplateError(f"La plantilla admite hasta {MAX_TOTAL_FIELDS} campos")

    fields, seen = [], set()
    for rf in raw_fields:
        f = _clean_field(rf)
        if f["key"] in seen:
            raise TemplateError(f"El campo «{f['title']}» está repetido")
        seen.add(f["key"])
        fields.append(f)

    for key in BOUND_KEYS:
        if key not in seen:
            raise TemplateError(f"Falta el campo base «{key}»: recarga la pantalla")

    # los personalizados que existían y ya no vienen quedan RETIRADOS (sus valores guardados no se tocan)
    if previous:
        for pf in previous.get("fields", []):
            if pf["key"] not in seen and pf["key"] not in BOUND_KEYS:
                gone = copy.deepcopy(pf)
                gone["retired"] = True
                fields.append(gone)
                seen.add(pf["key"])

    by_key = {f["key"]: f for f in fields}
    active = [f for f in fields if not f["retired"]]
    if len(active) > MAX_ACTIVE_FIELDS:
        raise TemplateError(f"La plantilla admite hasta {MAX_ACTIVE_FIELDS} campos activos: retira alguno")
    if len(fields) > MAX_TOTAL_FIELDS:
        raise TemplateError(f"La plantilla admite hasta {MAX_TOTAL_FIELDS} campos en total, contando los retirados")

    # configuraciones que dependen de otros campos
    for f in fields:
        if f["type"] == "city":
            ck = f["config"].get("country_key")
            if ck is not None and (ck not in by_key or by_key[ck]["type"] != "country" or by_key[ck]["retired"]):
                f["config"]["country_key"] = None
    for f in fields:                                      # un campo retirado de nuevo en uso no puede quedar roto
        if f["retired"] and (f["key"] in BOUND_KEYS):
            raise TemplateError(f"El campo «{f['title']}» es parte del sistema y no se puede retirar")

    creation = _clean_creation(payload.get("creation_layout"), by_key)
    calendar = _clean_calendar(payload.get("calendar_layout"), by_key)

    placed = {k for s in creation["sections"] for k in s["keys"]}
    for k in LOCKED_KEYS:
        if k not in placed:
            raise TemplateError(f"«{by_key[k]['title']}» no se puede quitar de la vista de creación")
    for f in fields:
        if f["required"] and not f["retired"] and f["key"] not in placed:
            raise TemplateError(f"«{f['title']}» es obligatorio, así que tiene que estar en la vista de creación")
    return {"fields": fields, "creation_layout": creation, "calendar_layout": calendar}


def _clean_field(rf) -> dict:
    if not isinstance(rf, dict):
        raise TemplateError("Campo inválido")
    key = rf.get("key")
    if not isinstance(key, str):
        raise TemplateError("Un campo no tiene clave")
    title = _text(rf.get("title"), "El título del campo", MAX_TITLE)
    helptext = _text(rf.get("help"), "La ayuda del campo", MAX_HELP, allow_empty=True)
    retired = bool(rf.get("retired"))
    if key in BOUND_KEYS:
        base = BASE_BY_KEY.get(key)
        if base:
            type_ = base["type"]
            config = clean_config(type_, {**(base.get("config") or {}), **{k: v for k, v in (rf.get("config") or {}).items() if k in ("max_len",)}})
            if type_ == "city":
                config = {"country_key": "country"}
            if type_ == "bandana_colors":
                config = {"max": 1}
        else:                                              # interruptor ligado
            sw = key[3:]
            type_, config = "switch", {"switch": sw}
        locked = key in LOCKED_KEYS
        required = True if locked else bool(rf.get("required")) and type_ != "switch"
        if type_ in ("switch", "workday"):          # el interruptor y la jornada (calculada) nunca son obligatorios
            required = False
        return {"key": key, "type": type_, "title": title, "required": required, "options": [], "config": config, "help": helptext, "retired": False}
    if not KEY_RE.match(key):
        raise TemplateError("Clave de campo inválida")
    type_ = rf.get("type")
    if type_ == "inventory":
        if not retired:          # Fase 5 (9-nov-2026): el inventario es UNO solo, el catálogo (app/inventory_unify.py). El campo viejo solo sobrevive «retirado».
            raise TemplateError(f"«{title}»: el inventario ahora se maneja con el catálogo (Configuración → Inventario); este tipo de campo ya no se puede usar")
    elif type_ not in CREATABLE_TYPES:
        raise TemplateError(f"Tipo de campo no permitido en «{title}»")
    options = _clean_options(rf.get("options"), f"«{title}»: las opciones", MAX_OPTIONS) if type_ == "select" else []
    config = clean_config(type_, rf.get("config"), key=key)
    return {"key": key, "type": type_, "title": title, "required": bool(rf.get("required")), "options": options, "config": config, "help": helptext, "retired": retired}


def _clean_creation(raw, by_key: dict) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list) or not raw["sections"]:
        raise TemplateError("La vista de creación necesita al menos un paso")
    if len(raw["sections"]) > MAX_SECTIONS:
        raise TemplateError(f"La vista de creación admite hasta {MAX_SECTIONS} pasos")
    sections, sids, used = [], set(), set()
    for s in raw["sections"]:
        if not isinstance(s, dict):
            raise TemplateError("Paso inválido")
        sid = s.get("id")
        if not isinstance(sid, str) or not SECTION_ID_RE.match(sid) or sid in sids:
            raise TemplateError("Identificador de paso inválido o repetido")
        sids.add(sid)
        title = _text(s.get("title"), "El título del paso", MAX_SECTION_TITLE)
        keys = s.get("keys")
        if not isinstance(keys, list) or not keys:
            raise TemplateError(f"El paso «{title}» está vacío: pon al menos un campo o quítalo")
        clean_keys = []
        for k in keys:
            if k in used:
                raise TemplateError("Un campo no puede estar dos veces en la vista de creación")
            f = by_key.get(k)
            if f is None or f["retired"]:
                raise TemplateError("La vista de creación usa un campo que no existe o fue retirado")
            used.add(k)
            clean_keys.append(k)
        sections.append({"id": sid, "title": title, "keys": clean_keys})
    return {"sections": sections}


def _clean_calendar(raw, by_key: dict) -> dict:
    zones_in = raw.get("zones") if isinstance(raw, dict) else None
    if not isinstance(zones_in, dict):
        raise TemplateError("Falta la vista del calendario")
    if set(zones_in) - set(ZONES):
        raise TemplateError("Zona del calendario desconocida")
    zones, used = {}, set()
    for z in ZONES:
        items = zones_in.get(z) or []
        if not isinstance(items, list) or len(items) > MAX_ZONE_ITEMS:
            raise TemplateError(f"La zona «{ZONE_LABELS[z]}» admite hasta {MAX_ZONE_ITEMS} campos")
        out = []
        for it in items:
            if not isinstance(it, dict):
                raise TemplateError("Elemento del calendario inválido")
            k = it.get("key")
            f = by_key.get(k)
            if f is None or f["retired"]:
                raise TemplateError("El calendario usa un campo que no existe o fue retirado")
            if k in used:
                raise TemplateError("Un campo no puede salir dos veces en la tarjeta del calendario")
            used.add(k)
            out.append({"key": k, "label": bool(it.get("label"))})
        zones[z] = out
    return {"zones": zones}


# ------------------------------------------------------------------------------------------------------------------------------------ valores
def clean_value(field: dict, raw):
    """Normaliza el valor de UN campo según su tipo. Lanza TemplateError (mensaje con el título del campo). Un valor vacío devuelve None."""
    t, title = field["type"], field["title"]
    cfg = field.get("config") or {}
    if t == "switch":
        if raw is None:
            return None
        if not isinstance(raw, bool):
            raise TemplateError(f"«{title}» debe ser sí o no")
        return raw
    if t == "workday":          # calculado: nunca se recibe ni se guarda un valor
        return None
    if is_empty(raw):
        return None
    w = f"«{title}»"
    if t == "text_short":
        return _text(raw, w, int(cfg.get("max_len") or MAX_SHORT))
    if t == "text_long":
        return _text(raw, w, int(cfg.get("max_len") or MAX_LONG), long=True)
    if t == "select":
        v = _text(raw, w, MAX_OPTION_LEN)
        if v not in (field.get("options") or []):
            raise TemplateError(f"{w}: elige una de las opciones de la lista")
        return v
    if t == "money":
        d = _decimal(raw, w)
        if d < 0 or d > MONEY_MAX or d != d.quantize(Decimal("0.01")):
            raise TemplateError(f"{w} debe ser un valor en dinero válido, de 0 en adelante y con máximo 2 decimales")
        return _num_out(d)
    if t == "number":
        d = _decimal(raw, w)
        if abs(d) > NUMBER_ABS_MAX:
            raise TemplateError(f"{w} es demasiado grande")
        dec = int(cfg.get("decimals") or 0)
        if d != d.quantize(Decimal(1).scaleb(-dec)):
            raise TemplateError(f"{w} admite hasta {dec} decimales")
        if cfg.get("min") is not None and d < Decimal(str(cfg["min"])):
            raise TemplateError(f"{w} no puede ser menor que {cfg['min']}")
        if cfg.get("max") is not None and d > Decimal(str(cfg["max"])):
            raise TemplateError(f"{w} no puede ser mayor que {cfg['max']}")
        return _num_out(d)
    if t in ("commercial", "coordinator", "super_event", "event_type"):
        return _int(raw, w, 1, 2_147_483_647)
    if t == "date":
        return _date(raw, w)
    if t == "time":
        return _time(raw, w)
    if t == "datetime":
        s = _text(raw, w, 32)
        m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{1,2}:\d{2})$", s)
        if not m:
            raise TemplateError(f"{w} debe tener fecha y hora")
        return _date(m.group(1), w) + "T" + _time(m.group(2), w)
    if t == "country":
        return _text(raw, w, 80)
    if t == "city":
        return _text(raw, w, 100)
    if t == "client":
        return _text(raw, w, 64)
    if t == "address_map":
        if not isinstance(raw, dict):
            raise TemplateError(f"{w} debe ser una dirección")
        text = _text(raw.get("text"), w, MAX_SHORT, allow_empty=True)
        lat, lng = raw.get("lat"), raw.get("lng")
        if (lat is None) != (lng is None):
            raise TemplateError(f"{w}: la ubicación del mapa necesita latitud y longitud")
        if lat is not None:
            lat_d, lng_d = _decimal(lat, w), _decimal(lng, w)
            if not (-90 <= lat_d <= 90 and -180 <= lng_d <= 180):
                raise TemplateError(f"{w}: la ubicación del mapa está fuera de rango")
            lat, lng = round(float(lat_d), 6), round(float(lng_d), 6)
        if not text and lat is None:
            return None
        return {"text": text, "lat": lat, "lng": lng}
    if t == "contact":
        if not isinstance(raw, dict):
            raise TemplateError(f"{w} debe tener nombre y teléfono")
        name = _text(raw.get("name"), w, 100, allow_empty=True)
        phone = _text(raw.get("phone"), w, 30, allow_empty=True)
        if phone:
            digits = re.sub(r"\D", "", phone)
            if not (7 <= len(digits) <= 15) or re.search(r"[^\d+\-\s().]", phone):
                raise TemplateError(f"{w}: el teléfono celular debe tener entre 7 y 15 dígitos")
            phone = ("+" if phone.startswith("+") else "") + digits
        if not name and not phone:
            return None
        return {"name": name, "phone": phone}
    if t == "bandana_colors":
        if not isinstance(raw, list):
            raise TemplateError(f"{w} debe ser una lista de colores")
        if len(raw) > int(cfg.get("max") or 1):
            raise TemplateError(f"{w} admite hasta {int(cfg.get('max') or 1)} color(es)")
        out = []
        for c in raw:
            if not isinstance(c, dict) or not HEX_RE.match(str(c.get("hex") or "")):
                raise TemplateError(f"{w}: cada color debe ser un hex como #C0392B")
            out.append({"name": _text(c.get("name"), w, 60, allow_empty=True), "hex": str(c["hex"]).lower()})
        return out or None
    if t == "inventory":
        try:
            return event_inventory.clean_lines(raw, cfg.get("inventory_types") or [], w)
        except event_inventory.InventoryError as exc:
            raise TemplateError(str(exc))
    raise TemplateError(f"{w}: tipo de campo no soportado")


def _date(raw, what: str) -> str:
    try:
        if isinstance(raw, datetime):
            return raw.date().isoformat()
        if isinstance(raw, date):
            return raw.isoformat()
        return date.fromisoformat(str(raw).strip()).isoformat()
    except ValueError:
        raise TemplateError(f"{what} debe ser una fecha válida (AAAA-MM-DD)")


def _time(raw, what: str) -> str:
    m = TIME_RE.match(str(raw).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise TemplateError(f"{what} debe ser una hora válida (HH:MM)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


# ------------------------------------------------------------------------------------------------------------------------------------ crear un evento con la plantilla
def raw_values_from_payload(payload: dict, extra: dict) -> dict:
    """Pone en una sola forma {clave de campo: valor} lo que manda «Nuevo evento»: las columnas de siempre (nivel superior), los interruptores (por el nombre de su columna) y `extra` (personalizados)."""
    raw = {}
    for key in BASE_KEYS:
        if key == "workday":
            continue
        if key == "bandana":
            if payload.get("bandana_color") or payload.get("bandana_color_name"):
                raw[key] = [{"name": payload.get("bandana_color_name") or "", "hex": payload.get("bandana_color") or ""}] if payload.get("bandana_color") else None
            continue
        cols = BASE_COLUMNS[key]
        if cols[0] in payload and payload[cols[0]] is not None:
            raw[key] = payload[cols[0]]
    for sw in SWITCH_KEYS:
        if payload.get(sw) is not None:
            raw[switch_field_key(sw)] = payload[sw]
    for k, v in (extra or {}).items():
        raw[k] = v
    return raw


def evaluate_creation(tpl: dict, raw: dict, waive=(), extra_keys=()) -> dict:
    """Valida lo que manda «Nuevo evento» contra la plantilla vigente.
    `waive`: claves cuya obligatoriedad no se exige (el servidor las resuelve por regla: p. ej. la comercial que crea se asigna a sí misma).
    `extra_keys`: claves recibidas dentro de `extra` (para rechazar las desconocidas o retiradas).
    Devuelve {"clean": {clave: valor}, "errors": [mensajes]} (errors vacío = válido)."""
    by_key = {f["key"]: f for f in tpl["fields"]}
    placed = {k for s in tpl["creation_layout"]["sections"] for k in s["keys"]}
    errors, clean, missing = [], {}, []
    for k in extra_keys:
        f = by_key.get(k)
        if f is None or k in BOUND_KEYS:
            errors.append(f"El campo «{k}» no existe en la plantilla")
        elif f["retired"]:
            errors.append(f"El campo «{f['title']}» fue retirado de la plantilla")
        elif k not in placed:
            errors.append(f"El campo «{f['title']}» no está en la vista de creación")
    for f in tpl["fields"]:
        if f["retired"]:
            continue
        k = f["key"]
        try:
            v = clean_value(f, raw.get(k)) if k in raw else None
        except TemplateError as exc:
            errors.append(str(exc))
            continue
        if v is None:
            if k in placed and f["required"] and f["type"] != "switch" and k not in waive:
                missing.append(f["title"])
            continue
        clean[k] = v
    if missing:
        errors.insert(0, "Falta completar: " + ", ".join(missing))
    errors.extend(switch_errors(clean))
    return {"clean": clean, "errors": errors}


def switch_errors(clean: dict) -> list:
    out = []
    for s in SWITCHES:
        k = switch_field_key(s["key"])
        if clean.get(k) and s["requires"] and not clean.get(switch_field_key(s["requires"])):
            out.append(f"«{s['title']}» necesita «{SWITCH_BY_KEY[s['requires']]['title']}» activo")
    return out


def split_clean(clean: dict) -> tuple:
    """(columnas de events, extra_json) a partir de los valores ya limpios. Los campos base van a sus columnas, los interruptores a sus columnas, el resto a `extra`."""
    cols, extra = {}, {}
    for k, v in clean.items():
        if k == "bandana":
            cols["bandana_color"] = v[0]["hex"]
            cols["bandana_color_name"] = v[0]["name"] or None
        elif k == "client":
            continue
        elif k in BASE_KEYS:
            cols[k] = v
        elif k in SWITCH_FIELD_KEYS:
            cols[k[3:]] = bool(v)
        else:
            extra[k] = v
    return cols, extra


def extra_size_ok(extra: dict) -> bool:
    import json
    return len(json.dumps(extra, ensure_ascii=False)) <= MAX_EXTRA_BYTES


def catalog() -> dict:
    """Lo que la pantalla de diseño necesita saber del servidor (tipos, interruptores, límites): una sola fuente."""
    return {
        "types": [{"type": t, "label": m["label"], "creatable": m["creatable"]} for t, m in TYPES.items()],
        "switches": [{"key": s["key"], "field_key": switch_field_key(s["key"]), "title": s["title"], "help": s["help"], "requires": s["requires"]} for s in SWITCHES],
        "locked": list(LOCKED_KEYS), "base": list(BASE_KEYS), "currencies": list(CURRENCIES),
        "zones": [{"zone": z, "label": ZONE_LABELS[z]} for z in ZONES],
        "limits": {"title": MAX_TITLE, "help": MAX_HELP, "options": MAX_OPTIONS, "option": MAX_OPTION_LEN, "sections": MAX_SECTIONS, "section_title": MAX_SECTION_TITLE,
                   "zone_items": MAX_ZONE_ITEMS, "active_fields": MAX_ACTIVE_FIELDS, "inventory_types": MAX_INVENTORY_TYPES, "inventory_refs": MAX_INVENTORY_REFS,
                   "colors": MAX_COLORS, "short": MAX_SHORT, "long": MAX_LONG},
    }
