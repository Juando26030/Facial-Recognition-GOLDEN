"""Parámetros del Evento (Sprint 2.2, 2026-09-16, pedido explícito) — coordinador+ define, por
evento, cómo debe comportarse cada campo del alta manual/edición: si es obligatorio, qué tipo de
control usar (texto corto/largo, lista desplegable con sus propias opciones, booleano), y si debe
generar estadística sola al entrar a Estadísticas (y con qué gráfico) sin tener que pedirla a
mano cada vez — ver stats.py: list_stats_variables, que lee estos mismos configs.

Decisión de alcance (avisada a Juan David al entregar): lo "obligatorio" se valida en
manual_register y update_user (routers/api.py) — NO en bulk_register, que sigue con su
comportamiento tolerante de siempre; forzar esto ahí arriesgaba romper cargas reales con datos
incompletos que hoy funcionan.
"""
import io
from datetime import date
import json
import os
import re
import uuid
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app import (
    audit_actions,
    event_history,
    biometric_setup,
    brandcolor,
    digital_fields,
    idle,
    lastname,
    publicurl,
    registro_gear,
)
from app.roster_columns import MAX_OPTIONAL_FIELDS
from app.auth import get_current_staff, get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import CHART_TYPES, Event, EventFieldConfig, FIELD_TYPES, StaffUser
from app.storage import get_storage, key_of

router = APIRouter()

# Identidad (reunión 2026-09-21, ítems 3a y 4): siempre texto corto obligatorio — NO se puede
# cambiar su tipo/obligatoriedad ni generar estadística, pero SÍ su etiqueta y su posición en el
# formulario (`locked=True` en la serialización).
IDENTITY_FIELDS = [
    ("first_name", "Nombres"),
    ("last_name", "Apellidos"),
    ("id", "Cédula"),
]
IDENTITY_KEYS = {k for k, _ in IDENTITY_FIELDS}
# Campos de los que solo se cambia nombre y posición: identidad + "Categoría" (ítem 14: sus opciones
# salen de las categorías del evento, no de una lista propia, y se guarda por evento).
LOCKED_KEYS = IDENTITY_KEYS | {"categories", "certificate", "digital_contact", "birth_date", "code"}      # birth_date: base del control de menores; solo etiqueta y posición

# Campos fijos configurables (además de los opcional_N ya rotulados del evento, ver
# Event.optional_field_labels). "status" no es un campo de formulario (ver stats.py).
DELETED_TYPE = "deleted"          # B2: un campo FIJO borrado en este evento queda marcado así en event_field_configs (sin migración)
DELETABLE_FIXED = ("role", "entity", "phone", "email", "opt_1")      # cédula/ID, nombres y apellidos nunca; categoría, certificado, correo de escarapela y fecha se apagan en su módulo
CONFIGURABLE_FIXED_FIELDS = [
    ("role", "Cargo"),
    ("entity", "Entidad"),
    ("phone", "Teléfono"),
    ("email", "Correo Electrónico"),
    ("opt_1", "Tipo de Asistente"),
    ("birth_date", "Fecha de nacimiento"),
]


def _configurable_fields(event: Event):
    """(key, label por defecto) de todo lo configurable para este evento, en el orden POR DEFECTO
    (la identidad primero, igual que el formulario de siempre)."""
    fields = list(IDENTITY_FIELDS) + [f for f in CONFIGURABLE_FIXED_FIELDS if f[0] != "birth_date" or event.facial_enabled]      # la fecha de nacimiento solo existe con rostro (control de menores)
    if event.code_enabled:
        fields.insert(len(IDENTITY_FIELDS), ("code", "Código de la persona (QR)"))          # 17-nov-2026: solo existe con el interruptor «Código de la persona» activo (Parámetros › Campos); obligatorio según ese mismo interruptor
    if event.get_categories():
        fields.append(("categories", "Categoría"))
    if event.certificates_enabled:
        fields.append(("certificate", "Certificado"))
    if event.digital_badge_enabled:
        fields.append(("digital_contact", "Correo corporativo para la escarapela digital"))
    optional_labels = event.get_optional_labels()
    for key, label in sorted(optional_labels.items(), key=lambda kv: int(kv[0].split("_")[1])):
        fields.append((key, label))
    return fields


# Hotfix 23-nov-2026 (sin migración, para no chocar con la numeración de staging): el alcance por defecto de la estadística de un campo
# (toda la base / solo registrados / solo no registrados) viaja en la misma columna `default_chart_type` como «<gráfico>@<alcance>».
# «all» se guarda sin sufijo, así que las filas viejas quedan igual. Leer y escribir SOLO con estas dos funciones.
STAT_SCOPES = ("all", "registered", "unregistered")


def split_chart_scope(raw) -> tuple:
    """`'bar@registered'` → `('bar', 'registered')`; `'pie'` → `('pie', 'all')`; vacío → `(None, 'all')`."""
    if not raw:
        return None, "all"
    chart, _, scope = str(raw).partition("@")
    return (chart or None), (scope if scope in STAT_SCOPES else "all")


def join_chart_scope(chart, scope) -> "str | None":
    if not chart:
        return None
    return chart if scope in (None, "", "all") else f"{chart}@{scope}"


CARD_DEFAULT_KEYS = ("id", "first_name", "last_name")          # 21-nov-2026: lo que la tarjeta de Registro muestra de fábrica (la entidad ya no)


ALWAYS_IN_CARD = CARD_DEFAULT_KEYS          # 22-nov-2026 (Juan David): cédula, nombres y apellidos SIEMPRE se ven en Registro; la casilla solo elige los demás campos


def _show_in_card(key: str, row) -> bool:
    if key in ALWAYS_IN_CARD:
        return True
    if row is not None and row.show_in_card is not None:
        return bool(row.show_in_card)
    return key in CARD_DEFAULT_KEYS


def _with_card(cfg: dict, row) -> dict:
    cfg["show_in_card"] = _show_in_card(cfg["key"], row)
    return cfg


DEPENDENTS_KEY = "dependents"          # 0161: campo «Dependientes» (cuántos y quiénes, de la base de dependientes): solo existe con esa base cargada; nombre, posición y estadística


def _serialize_base(key: str, default_label: str, row: Optional[EventFieldConfig], categories: Optional[list] = None) -> dict:
    """`label` = lo que se muestra en este evento (el propio si lo personalizaron, si no el de por
    defecto); `default_label` se conserva para poder mostrarlo como sugerencia en Parámetros."""
    if key == DEPENDENTS_KEY:
        return {"key": key, "label": (row.label if row and row.label else default_label), "default_label": default_label, "locked": False, "virtual": True,
                "required": False, "field_type": "dependents", "options": [], "help_text": "",
                "default_stat_enabled": bool(row and row.default_stat_enabled), "default_chart_type": (row.default_chart_type if row and row.default_stat_enabled else None)}
    locked = key in LOCKED_KEYS
    label = default_label if key == "certificate" else (row.label if row and row.label else default_label)
    if row is None or locked:
        return {
            "key": key, "label": label, "default_label": default_label, "locked": locked,
            "label_fixed": key == "certificate",
            "required": bool(row.required) if (row and key in ("certificate", "digital_contact")) else False,
            "field_type": {"categories": "categories", "certificate": "certificate", "digital_contact": "digital_contact", "birth_date": "date"}.get(key, "text_short"),
            "options": categories or [], "help_text": "",
            "default_stat_enabled": False, "default_chart_type": None, "default_stat_scope": "all",
        }
    return {
        "key": key, "label": label, "default_label": default_label, "locked": False,
        "required": row.required, "field_type": row.field_type,
        "options": row.get_options(), "help_text": row.help_text or "",
        "default_stat_enabled": row.default_stat_enabled,
        "default_chart_type": split_chart_scope(row.default_chart_type)[0],
        "default_stat_scope": split_chart_scope(row.default_chart_type)[1],
    }


def _fields_with_virtual(db: Session, event: Event, include_virtual: bool):
    fields = _configurable_fields(event)
    if include_virtual:
        from app import dependents
        if dependents.has_dependents(db, event.id):
            fields = fields + [(DEPENDENTS_KEY, "Dependientes")]
    return fields


def _serialize(key: str, default_label: str, row: Optional[EventFieldConfig], categories: Optional[list] = None) -> dict:
    """La configuración de un campo + `show_in_card` (0161: se ve en la tarjeta de la persona en Registro)."""
    return _with_card(_serialize_base(key, default_label, row, categories), row)


def field_configs_for_event(db: Session, event: Event, include_virtual: bool = False) -> list:
    """Lista completa de campos configurables de este evento, cada uno con su config real si
    existe o los valores por defecto si todavía no se guardó nada — así quien consuma esto
    (frontend, o la validación de manual_register/update_user) siempre ve la lista completa sin
    filas 'faltantes'. Usado también por stats.py para saber qué gráficos generar solos.

    Viene ORDENADA (ítem 4): por `sort_order` si alguien reordenó; los campos sin posición guardada
    (ej. un opcional agregado después de reordenar) van al final, en su orden por defecto.
    `include_virtual` (0161): agrega el campo «Dependientes» si el evento tiene base de dependientes. Solo lo piden Parámetros, «Editar persona» y Estadísticas: el resto
    (formularios, escarapelas, validación de lo obligatorio…) nunca lo ve, porque no es un dato que se escriba."""
    rows = {r.field_key: r for r in db.query(EventFieldConfig).filter(EventFieldConfig.event_id == event.id)}
    last_required = lastname.is_required(db, event.id)          # Fase 2: el apellido es obligatorio si la base lo usa (automático) o si se eligió a mano
    ordered = []
    for idx, (key, label) in enumerate(_fields_with_virtual(db, event, include_virtual)):
        row = rows.get(key)
        if row is not None and row.field_type == DELETED_TYPE:       # B2: campo borrado en este evento (no aparece en ningún lado)
            continue
        position = row.sort_order if row and row.sort_order is not None else 1000 + idx
        cfg = _serialize(key, label, row, event.get_categories())
        if key == "last_name":
            cfg["required"] = last_required
        elif key == "code":
            cfg["required"] = bool(event.code_required)          # lo decide el interruptor del evento, no el diseño del formulario
        ordered.append((position, cfg))
    return [cfg for _, cfg in sorted(ordered, key=lambda pair: pair[0])]


def field_labels_for_event(db: Session, event: Event) -> dict:
    """{field_key: etiqueta efectiva} — atajo para reportes/estadísticas/plantillas que solo
    necesitan el nombre a mostrar."""
    return {cfg["key"]: cfg["label"] for cfg in field_configs_for_event(db, event)}


LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}   # sin .svg: un SVG puede llevar scripts (Fase 0C, B1); los logos SVG ya guardados se sirven en «sandbox» (app/main.py)
LOGO_MODES = ("default", "hidden", "custom")


@router.get("/events/{event_id}/logo")
def get_event_logo(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """Sirve el logo propio del evento (ítem 1, reunión 2026-09-21) — cualquier staff con acceso al
    evento lo necesita para dibujar el header, no solo quien lo configura."""
    event = get_event_for_staff(event_id, db, staff)
    if event.logo_mode != "custom" or not event.logo_path or not get_storage().exists(event.logo_path):
        raise HTTPException(status_code=404, detail="Este evento no tiene logo propio")
    return get_storage().response(event.logo_path, headers={"Cache-Control": "no-cache"})


@router.put("/events/{event_id}/logo")
def set_event_logo_mode(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """`mode`: 'default' (logo de Golden), 'hidden' (sin logo) o 'custom' (el propio ya subido). Opcionales: `height` (30–80 px) y
    `fit` ('logo' = se ve completo, 'banner' = rellena el ancho del header recortando)."""
    event = get_event_for_staff(event_id, db, staff)
    if "height" in data:
        try:
            event.logo_height = max(30, min(80, int(data["height"])))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="El alto del logo debe ser un número entre 30 y 80")
    if "fit" in data:
        if data["fit"] not in ("logo", "banner"):
            raise HTTPException(status_code=400, detail="fit debe ser 'logo' o 'banner'")
        event.logo_fit = data["fit"]
    mode = data.get("mode", event.logo_mode)
    if mode not in LOGO_MODES:
        raise HTTPException(status_code=400, detail=f"mode debe ser uno de: {', '.join(LOGO_MODES)}")
    if mode == "custom" and not (event.logo_path and get_storage().exists(event.logo_path)):
        raise HTTPException(status_code=400, detail="Primero sube la imagen del logo")
    event.logo_mode = mode
    db.commit()
    return {"logo_mode": event.logo_mode, "logo_height": event.logo_height, "logo_fit": event.logo_fit}


@router.put("/events/{event_id}/brand-color")
def set_event_brand_color(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Color de marca del evento para sus páginas públicas. `color`: '#rrggbb' o null/'' (= el general de Golden). Se rechaza el que no deje leer el texto de los botones."""
    event = get_event_for_staff(event_id, db, staff)
    raw = data.get("color")
    try:
        color = brandcolor.validate(raw) if raw not in (None, "") else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if color != event.brand_color:
        audit_actions.record(db, staff, "update", "event_brand_color", event.id, event.name, f"{event.brand_color or 'general'} -> {color or 'general'}")
        event.brand_color = color
    db.commit()
    from app import formsvc          # la página pública del formulario guarda el color unos segundos en caché
    formsvc.invalidate_public_cache()
    return {"brand_color": event.brand_color}


@router.post("/events/{event_id}/logo/upload")
def upload_event_logo(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in LOGO_EXT:
        raise HTTPException(status_code=400, detail=f"Formato no permitido — usa uno de: {', '.join(sorted(LOGO_EXT))}")
    content = file.file.read(3_000_001)
    if not content or len(content) > 3_000_000:
        raise HTTPException(status_code=400, detail="La imagen está vacía o pesa más de 3 MB")
    from app import safe_limits
    try:
        safe_limits.check_design_image(content, ext, max_bytes=3_000_000)      # I6: tamaño, píxeles y formato real (no solo la extensión)
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    key = key_of(event.tenant_id, "event_logos", f"{uuid.uuid4().hex}{ext}")
    get_storage().put(key, content)
    if event.logo_path:
        get_storage().delete(event.logo_path)
    event.logo_path, event.logo_mode = key, "custom"
    db.commit()
    return {"logo_mode": "custom"}


@router.put("/events/{event_id}/digital-badge-enabled")
def set_digital_badge_enabled(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Activa/desactiva la escarapela digital (ítem 17): agrega el campo de correo corporativo y, al
    guardar a una persona con ese dato, se le envía el enlace de su escarapela. Decisión 2026-09-21:
    solo correo (se descartó WhatsApp por costo) — al activar, el campo queda `required` por defecto
    (si todavía no tenía una fila propia en event_field_configs, o sea nadie lo había tocado antes)."""
    event = get_event_for_staff(event_id, db, staff)
    was = bool(event.digital_badge_enabled)
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    event.digital_badge_enabled = bool(data.get("enabled"))
    if was != event.digital_badge_enabled:
        audit_actions.record(db, staff, "update", "event_digital_badge_enabled", event.id, event.name, f"{was} -> {event.digital_badge_enabled}")
    if not event.digital_badge_enabled:
        event.digital_badge_fields = None          # al apagar se olvida la selección: reactivar no vuelve a exponer teléfono/correo sin que alguien lo elija de nuevo
    _hr = event_history.record(db, event, _hb, staff, "switch")
    if event.digital_badge_enabled:
        row = db.query(EventFieldConfig).filter_by(event_id=event_id, field_key="digital_contact").first()
        if not row:
            db.add(EventFieldConfig(event_id=event_id, field_key="digital_contact", required=True, field_type="text_short"))
    db.commit()
    event_history.kick_after(_hr)
    return {"digital_badge_enabled": event.digital_badge_enabled}


def _digital_fields_state(db: Session, event: Event) -> dict:
    labels = field_labels_for_event(db, event)
    options = [{"key": k, "label": labels[k], "sensitive": k in digital_fields.SENSITIVE_KEYS}
               for k in digital_fields.allowed_keys(event.get_optional_labels()) if k in labels]          # solo lo que el evento tiene (los campos borrados o sin categorías no se ofrecen)
    return {"enabled": bool(event.digital_badge_enabled), "fields": options, "selected": digital_fields.parse_stored(event.digital_badge_fields),
            "warning": digital_fields.SENSITIVE_WARNING}


@router.get("/events/{event_id}/digital-badge-fields")
def get_digital_badge_fields(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    """Datos de la persona que se pueden mostrar en la escarapela digital y los elegidos (`selected` nulo = por defecto: solo lo que usa la plantilla)."""
    return _digital_fields_state(db, get_event_for_staff(event_id, db, staff))


@router.put("/events/{event_id}/digital-badge-fields")
def put_digital_badge_fields(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    """Guarda qué datos salen en la escarapela digital. `fields`: lista de claves, o nulo para volver al comportamiento por defecto. Rechaza claves desconocidas."""
    event = get_event_for_staff(event_id, db, staff)
    if not event.digital_badge_enabled:
        raise HTTPException(status_code=409, detail="Activa primero la escarapela digital")
    state = _digital_fields_state(db, event)
    offered = {f["key"] for f in state["fields"]}
    try:
        value = digital_fields.validate(data.get("fields"), event.get_optional_labels())
    except digital_fields.FieldsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if value is not None and any(k not in offered for k in value):
        raise HTTPException(status_code=400, detail="Uno de los datos ya no existe en este evento")
    event.digital_badge_fields = None if value is None else json.dumps(value)
    audit_actions.record(db, staff, "edit", "event_digital_badge_fields", event.id, event.name,
                         "por defecto" if value is None else ", ".join(value)[:400] or "ninguno")          # solo claves, nunca datos de personas
    db.commit()
    return _digital_fields_state(db, event)


DIRECTORY_PAGE_SIZES = (10, 20, 50, 100, 200)


@router.put("/events/{event_id}/directory-page-size")
def set_directory_page_size(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Filas por página de la tabla del directorio de ESTE evento (en vivo y lista local sin red): 10, 20, 50, 100 o 200. Más filas = más nodos en pantalla (en un celular o un iPad 200 filas pesan);
    la búsqueda y los contadores siempre cubren a TODAS las personas, y la paginación llega a cualquier fila."""
    event = get_event_for_staff(event_id, db, staff)
    raw = data.get("value")
    try:
        value = 0 if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()) else int(raw)         # 20.5 o true no son un tamaño
    except (TypeError, ValueError):
        value = 0
    if value not in DIRECTORY_PAGE_SIZES:
        raise HTTPException(status_code=400, detail=f"Filas por página: elige una de {', '.join(str(v) for v in DIRECTORY_PAGE_SIZES)}")
    event.directory_page_size = value
    db.commit()
    return {"directory_page_size": event.directory_page_size}


@router.get("/events/{event_id}/registro-gear-digitadores")
def get_registro_gear_digitadores(
    event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    return {"enabled": registro_gear.digitadores_enabled(db, event.id)}


@router.put("/events/{event_id}/registro-gear-digitadores")
def set_registro_gear_digitadores(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Plan 7: «Mostrar configuración del registro a digitadores». Solo decide si el digitador VE el engranaje; lo ya configurado no se pierde y los permisos de la API no cambian."""
    event = get_event_for_staff(event_id, db, staff)
    value = data.get("enabled")
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="enabled debe ser verdadero o falso")
    registro_gear.set_digitadores_enabled(db, event.id, value)
    db.commit()
    return {"enabled": value}


@router.get("/events/{event_id}/last-name-required")
def get_last_name_required(
    event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    return lastname.state(db, event.id)


@router.put("/events/{event_id}/last-name-required")
def set_last_name_required(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Fase 2: «Apellido obligatorio». `mode`: «auto» (según la base cargada), «required» u «optional» (lo manual manda sobre lo automático)."""
    event = get_event_for_staff(event_id, db, staff)
    mode = data.get("mode")
    if mode not in ("auto", "required", "optional"):
        raise HTTPException(status_code=400, detail="Elige «Automático», «Obligatorio» u «Opcional»")
    result = lastname.set_manual(db, event, {"auto": None, "required": True, "optional": False}[mode])
    db.commit()
    return result


@router.put("/events/{event_id}/idle-minutes")
def set_idle_minutes(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Minutos sin uso tras los que se cierra la sesión del personal que trabaja en ESTE evento (5 a 60), solo mientras está «en proceso». Vacío (null) = el general (SESSION_IDLE_MINUTES, 10). app/idle.py."""
    event = get_event_for_staff(event_id, db, staff)
    raw = data.get("value")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        value = None
    else:
        try:
            value = None if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()) else int(raw)
        except (TypeError, ValueError):
            value = None
        if value is None or not idle.EVENT_MIN <= value <= idle.EVENT_MAX:
            raise HTTPException(status_code=400, detail=f"Minutos sin uso: un número entero de {idle.EVENT_MIN} a {idle.EVENT_MAX}, o vacío para usar el general ({idle.general_minutes()})")
    event.idle_minutes = value
    db.commit()
    return {"idle_minutes": event.idle_minutes, "general_minutes": idle.general_minutes()}


_ANNEX_ROLES = require_role_excluding("coordinador", ("comercial",))
ANNEX_MAX = 10 * 1024 * 1024


@router.post("/events/{event_id}/facial-annex")
def upload_facial_annex(event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(_ANNEX_ROLES)):
    """Anexo firmado del cliente (PDF, Word, Excel o imagen). Sin él la cámara del evento queda bloqueada (`biometric_setup.annex_block_reason`)."""
    event = get_event_for_staff(event_id, db, staff)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(file.filename or "anexo"))[:100]
    if not name.lower().endswith(biometric_setup.ANNEX_EXTS):
        raise HTTPException(status_code=400, detail="El anexo debe ser PDF, Word, Excel o imagen")
    content = file.file.read(ANNEX_MAX + 1)
    if not content or len(content) > ANNEX_MAX:
        raise HTTPException(status_code=400, detail="El archivo está vacío o pesa más de 10 MB")
    old = biometric_setup.annex_key(event) if event.precalculo_anexo_ref else None
    event.precalculo_anexo_ref, event.precalculo_anexo_fecha, event.precalculo_garantia = name, date.today(), True
    get_storage().put(biometric_setup.annex_key(event), content)
    if old and old != biometric_setup.annex_key(event):
        get_storage().delete(old)
    biometric_setup.apply_precalc_default(event)
    db.commit()
    return {"anexo": name, "fecha": event.precalculo_anexo_fecha.isoformat(), "bloqueado": biometric_setup.annex_block_reason(event)}


@router.get("/events/{event_id}/facial-annex")
def download_facial_annex(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_ANNEX_ROLES)):
    event = get_event_for_staff(event_id, db, staff)
    if not biometric_setup.has_annex(event) or not get_storage().exists(biometric_setup.annex_key(event)):
        raise HTTPException(status_code=404, detail="Este evento no tiene anexo")
    return Response(content=get_storage().get(biometric_setup.annex_key(event)), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{event.precalculo_anexo_ref}"', "Cache-Control": "private, no-store"})


@router.put("/events/{event_id}/facial-enabled")
def set_facial_enabled(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Interruptor manual (2026-09-27, pedido explícito: "si me equivoqué y ya no quiero facial no puedo
    quitarlo o viceversa a mitad de un evento que no tenía, poder ponerlo"). Antes `facial_enabled` solo se
    encendía sola al subir el primer roster con zip de fotos (`bulk_register`) y nunca se apagaba — eso
    sigue igual (subir un zip la vuelve a encender si estaba apagada), pero ahora coordinador+ también puede
    prenderla o apagarla a mano en cualquier momento, sin depender de una carga. Apagarla NO borra ningún
    rostro/encoding ya guardado (si se vuelve a prender, la gente que ya tenía foto se sigue reconociendo);
    solo decide si `/kiosk/{id}/registro` muestra el escáner de cámara o se comporta como cédula tradicional."""
    event = get_event_for_staff(event_id, db, staff)
    if data.get("enabled") and event.biometrics_locked:
        raise HTTPException(status_code=409, detail="Este evento está bloqueado SIN biometría: quita el bloqueo en el paso guiado para activar el rostro")
    if data.get("enabled"):
        blockers = biometric_setup.facial_blockers(event)
        if blockers:
            raise HTTPException(status_code=400, detail="Para activar el reconocimiento facial en un evento de un tercero falta: " + ", ".join(blockers))
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    event.facial_enabled = bool(data.get("enabled"))
    biometric_setup.apply_precalc_default(event)          # modo de un clic por defecto si ya tiene el anexo firmado
    _hr = event_history.record(db, event, _hb, staff, "switch")
    db.commit()
    event_history.kick_after(_hr)
    return {"facial_enabled": event.facial_enabled}


@router.put("/events/{event_id}/certificates-enabled")
def set_certificates_enabled(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Activa/desactiva el módulo de certificados (ítem 5, reunión 2026-09-21). Al activarlo aparece
    el campo "Certificado" (Sí/No, default No) en Registrar/Editar y el diseñador del certificado."""
    event = get_event_for_staff(event_id, db, staff)
    _hb = event_history.snapshot(db, event)          # Fase 5: historial por campo
    event.certificates_enabled = bool(data.get("enabled"))
    _hr = event_history.record(db, event, _hb, staff, "switch")
    db.commit()
    event_history.kick_after(_hr)
    return {"certificates_enabled": event.certificates_enabled}


@router.get("/events/{event_id}/categories")
def get_event_categories(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    event = get_event_for_staff(event_id, db, staff)
    return {"categories": event.get_categories(), "badge_per_category": event.badge_per_category}


@router.put("/events/{event_id}/categories")
def set_event_categories(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Categorías del evento (ítem 14, reunión 2026-09-21): la lista de la que se eligen las de cada
    persona (Registrar/Editar/roster) y a la que se le puede asignar plantilla de escarapela."""
    event = get_event_for_staff(event_id, db, staff)
    cleaned = []
    for name in (str(x).strip() for x in (data.get("categories") or [])):
        if name and len(name) <= 40 and name.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(name)
    if len(cleaned) > 30:
        raise HTTPException(status_code=400, detail="Máximo 30 categorías por evento")
    event.set_categories(cleaned)
    if not cleaned:
        event.badge_per_category = False
    db.commit()
    return {"categories": cleaned, "badge_per_category": event.badge_per_category}


@router.post("/events/{event_id}/optional-fields")
def add_optional_field(
    event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Agrega un campo opcional nuevo directamente desde Parámetros del Evento (2026-09-16,
    pedido explícito) — sin pasar por un alta/carga de roster como hasta ahora (`NEEDS_LABELS` en
    manual_register/bulk_register, ver api.py). Busca el primer slot `opcional_N` libre (mismo
    límite de 30 que ya usa kiosk_registro.html) y lo rotula de una — queda disponible tanto en el
    formulario de alta como, una vez configurado, en el reporte (ver reports.py)."""
    event = get_event_for_staff(event_id, db, staff)
    label = str(data.get("label", "")).strip()
    if not label:
        raise HTTPException(status_code=400, detail="El campo necesita un nombre")

    labels = event.get_optional_labels()
    used_slots = {int(k.split("_")[1]) for k in labels.keys()}
    new_slot = next((n for n in range(1, MAX_OPTIONAL_FIELDS + 1) if n not in used_slots), None)
    if new_slot is None:
        raise HTTPException(status_code=400, detail=f"Se alcanzó el techo técnico de {MAX_OPTIONAL_FIELDS} campos opcionales para este evento")

    key = f"opcional_{new_slot}"
    labels[key] = label
    event.set_optional_labels(labels)
    db.commit()
    return {"key": key, "label": label}


@router.get("/events/{event_id}/field-configs")
def list_field_configs(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    return field_configs_for_event(db, event, include_virtual=True)


@router.put("/events/{event_id}/field-configs/{field_key}")
def upsert_field_config(
    event_id: int, field_key: str, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    valid_keys = {k for k, _ in _fields_with_virtual(db, event, True)}
    if field_key not in valid_keys:
        raise HTTPException(status_code=400, detail="Ese campo no existe o no es configurable en este evento")
    gone = db.query(EventFieldConfig).filter_by(event_id=event.id, field_key=field_key, field_type=DELETED_TYPE).first()
    if gone is not None:
        raise HTTPException(status_code=400, detail="Ese campo se borró de este evento")

    label = str(data.get("label") or "").strip()[:60] or None
    sort_order = data.get("sort_order")
    if sort_order is not None and not isinstance(sort_order, int):
        raise HTTPException(status_code=400, detail="sort_order debe ser un entero")

    row = db.query(EventFieldConfig).filter_by(event_id=event_id, field_key=field_key).first()
    if not row:
        row = EventFieldConfig(event_id=event_id, field_key=field_key)
        db.add(row)
    row.label = None if field_key == "certificate" else label  # "Certificado": ni nombre ni tipo editables
    row.sort_order = sort_order
    if "show_in_card" in data:          # 0161: mostrarlo en la tarjeta de la persona en Registro (cualquier campo, también los de identidad)
        if not isinstance(data["show_in_card"], bool):
            raise HTTPException(status_code=400, detail="show_in_card debe ser verdadero o falso")
        row.show_in_card = True if field_key in ALWAYS_IN_CARD else data["show_in_card"]

    if field_key == DEPENDENTS_KEY:          # 0161: nombre, posición y estadística; nunca obligatorio ni de otro tipo (no se escribe: sale de la base de dependientes)
        stat = bool(data.get("default_stat_enabled", False))
        chart = data.get("default_chart_type") if stat else None
        if stat and chart not in CHART_TYPES:
            raise HTTPException(status_code=400, detail=f"Tipo de gráfico inválido — debe ser uno de: {', '.join(CHART_TYPES)}")
        row.required, row.field_type, row.default_stat_enabled, row.default_chart_type = False, "text_short", stat, chart
        row.set_options([])
        db.commit()
        return _serialize(field_key, "Dependientes", row)

    if field_key in LOCKED_KEYS:
        # Identidad y Categoría: solo etiqueta y posición. Certificado: solo posición y obligatorio.
        row.required = bool(data.get("required", False)) if field_key in ("certificate", "digital_contact") else False
        row.field_type, row.default_stat_enabled, row.default_chart_type = "text_short", False, None
        row.set_options([])
        db.commit()
        return _serialize(field_key, dict(_configurable_fields(event))[field_key], row, event.get_categories())

    field_type = data.get("field_type", "text_short")
    if field_type not in FIELD_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de campo inválido — debe ser uno de: {', '.join(FIELD_TYPES)}")

    help_text = str(data.get("help_text") or "").strip()
    if field_type in ("consent", "signature"):
        if not field_key.startswith("opcional_"):
            raise HTTPException(status_code=400, detail="Consentimiento y firma solo se pueden usar en campos opcionales")
        if not help_text:
            raise HTTPException(status_code=400, detail="Escribe el texto de política/consentimiento que acompaña a este campo")

    options = [str(o).strip() for o in (data.get("options") or []) if str(o).strip()]
    if field_type == "select" and not options:
        raise HTTPException(status_code=400, detail="Un campo de lista desplegable necesita al menos una opción")

    default_stat_enabled = bool(data.get("default_stat_enabled", False))
    default_chart_type = data.get("default_chart_type") if default_stat_enabled else None
    if default_stat_enabled and default_chart_type not in CHART_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de gráfico inválido — debe ser uno de: {', '.join(CHART_TYPES)}")
    default_stat_scope = data.get("default_stat_scope") or "all"
    if default_stat_scope not in STAT_SCOPES:
        raise HTTPException(status_code=400, detail="Alcance de la estadística inválido: general, registrados o no registrados")

    row.help_text = help_text if field_type in ("consent", "signature") else None
    row.required = bool(data.get("required", False))
    row.field_type = field_type
    row.set_options(options if field_type == "select" else [])
    row.default_stat_enabled = default_stat_enabled
    row.default_chart_type = join_chart_scope(default_chart_type, default_stat_scope if default_stat_enabled else "all")
    db.commit()

    return _serialize(field_key, dict(_configurable_fields(event))[field_key], row)


# ------------------------------------------------------------------ correo de la escarapela virtual (editable por evento)
from app import email_template  # noqa: E402
from app.mailer import send_mail  # noqa: E402

_EMAIL_IMG = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$")
_DIGITAL_MAIL = require_role_excluding("coordinador", ("comercial",))


def _public_base(request: Request) -> str:
    return publicurl.base(str(request.base_url))


@router.get("/events/{event_id}/digital-email")
def get_digital_email(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(_DIGITAL_MAIL)):
    event = get_event_for_staff(event_id, db, staff)
    return {"subject": event.digital_email_subject or email_template.DEFAULT_SUBJECT, "body": event.digital_email_body or email_template.DEFAULT_BODY,
            "custom": bool(event.digital_email_body or event.digital_email_subject), "variables": [{"key": k, "label": l} for k, l in email_template.VARIABLES]}


@router.put("/events/{event_id}/digital-email")
def put_digital_email(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(_DIGITAL_MAIL)):
    """Guarda la plantilla (saneada). Vacía o `reset` = vuelve a la de siempre."""
    event = get_event_for_staff(event_id, db, staff)
    subject = " ".join(str(data.get("subject") or "").split())[:200]
    body = email_template.sanitize(str(data.get("body") or ""))
    if data.get("reset") or not email_template.to_text(body).strip() and "<img" not in body:
        event.digital_email_subject = event.digital_email_body = None
    else:
        if not subject:
            raise HTTPException(status_code=400, detail="Escribe el asunto del correo")
        if "{enlace}" not in body and "{boton}" not in body:
            raise HTTPException(status_code=400, detail="El correo debe incluir el enlace a la escarapela: inserta la variable «Botón» o «Enlace»")
        event.digital_email_subject, event.digital_email_body = subject, body
    db.commit()
    return {"custom": bool(event.digital_email_body)}


def _sample(event: Event, data: dict, link: str):
    return email_template.render(SimpleNamespace(name=event.name, start_date=event.start_date, location=event.location, city=event.city,
                                                 digital_email_subject=str(data.get("subject") or "")[:200] or None,
                                                 digital_email_body=email_template.sanitize(str(data.get("body") or "")) or None), "María", "Pérez", link)


@router.post("/events/{event_id}/digital-email/preview")
def preview_digital_email(event_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(_DIGITAL_MAIL)):
    event = get_event_for_staff(event_id, db, staff)
    subject, html_body, _ = _sample(event, data, f"{_public_base(request)}/b/EJEMPLO")
    return {"subject": subject, "html": html_body}


@router.post("/events/{event_id}/digital-email/test")
def test_digital_email(event_id: int, data: dict, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(_DIGITAL_MAIL)):
    """Envía el correo con datos de ejemplo a UNA dirección que escribe quien edita (para verlo como lo verá el asistente)."""
    event = get_event_for_staff(event_id, db, staff)
    to = str(data.get("to") or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
        raise HTTPException(status_code=400, detail="Escribe un correo válido para la prueba")
    subject, html_body, text = _sample(event, data, f"{_public_base(request)}/b/EJEMPLO")
    result = send_mail(to, f"[PRUEBA] {subject}", text, html=html_body)
    return {"sent": result["sent"], "detail": result["detail"]}


@router.post("/events/{event_id}/digital-email/upload-image")
def upload_email_image(event_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(_DIGITAL_MAIL)):
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise HTTPException(status_code=400, detail="La imagen debe ser PNG, JPG, GIF o WEBP")
    content = file.file.read()
    if len(content) > 3 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="La imagen pesa más de 3 MB")
    try:
        from PIL import Image
        from app import safe_limits
        safe_limits.check_image_dimensions(content)
        Image.open(io.BytesIO(content)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="Ese archivo no es una imagen válida")
    name = f"{uuid.uuid4().hex}{ext}"
    get_storage().put(key_of(event.tenant_id, "email_assets", name), content)
    return {"url": f"{_public_base(request)}/api/email-assets/{event.tenant_id}/{name}"}


@router.get("/email-assets/{tenant_id}/{filename}")
def email_asset(tenant_id: str, filename: str):
    """Imágenes de los correos: públicas a propósito (el lector de correo no tiene sesión); el nombre es un UUID no adivinable."""
    if not _EMAIL_IMG.match(filename) or "/" in tenant_id or ".." in tenant_id:
        raise HTTPException(status_code=404)
    key = key_of(tenant_id, "email_assets", filename)
    if not get_storage().exists(key):
        raise HTTPException(status_code=404)
    return get_storage().response(key, headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------------------------------------ B2: borrar un campo del evento
def _people_with_data(db: Session, event: Event, key: str) -> list:
    from app.models import EventAttendee, User
    ids = [u for (u,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)]
    if not ids:
        return []
    out = []
    for user in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids)):
        value = user.get_extras().get(key) if key.startswith("opcional_") else getattr(user, key, None)
        if value not in (None, ""):
            out.append(user)
    return out


def _field_usage(db: Session, event: Event, key: str) -> dict:
    from app.models import BadgeTemplate, WebForm
    import json as _json
    templates = [t.name or "Escarapela" for t in db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id)
                 if any(e.get("variable") == key for e in t.get_elements())]
    forms = []
    for f in db.query(WebForm).filter(WebForm.event_id == event.id):
        try:
            design = _json.loads(f.design_json or "{}")
        except ValueError:
            design = {}
        if any((fld or {}).get("key") == key for fld in (design.get("fields") or {}).values()):
            forms.append(f.name)
    return {"templates": templates, "forms": forms}


def _deletable(event: Event, key: str) -> Optional[str]:
    """None si se puede borrar; si no, el motivo."""
    if key in IDENTITY_KEYS:
        return "La cédula/ID, los nombres y los apellidos no se pueden borrar."
    if key in LOCKED_KEYS:
        return "Este campo se apaga desde su propio módulo en Parámetros, no se borra."
    if key in DELETABLE_FIXED or key in event.get_optional_labels():
        return None
    return "Ese campo no existe en este evento."


@router.get("/events/{event_id}/fields/{field_key}/usage")
def field_usage(event_id: int, field_key: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    """Lo que se pierde al borrar el campo: cuántas personas tienen dato en él y qué plantillas de escarapela y formularios lo usan (para la confirmación fuerte)."""
    event = get_event_for_staff(event_id, db, staff)
    reason = _deletable(event, field_key)
    label = next((c["label"] for c in field_configs_for_event(db, event) if c["key"] == field_key), field_key)
    return {"key": field_key, "label": label, "deletable": reason is None, "reason": reason,
            "people": len(_people_with_data(db, event, field_key)) if reason is None else 0, **(_field_usage(db, event, field_key) if reason is None else {"templates": [], "forms": []})}


@router.delete("/events/{event_id}/fields/{field_key}")
def delete_field(event_id: int, field_key: str, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))):
    """Borra un campo de ESTE evento (también uno que vino en la base original). Hay que escribir su nombre para confirmar. Desaparece de formularios, edición, directorio, reporte y
    variables de escarapela, y se borran sus datos en este evento: el dato se limpia en las personas del evento que NO están en ningún otro evento del cliente (la persona es la
    misma entre eventos; en las demás se conserva para no dañar otro evento). Queda en el historial de cambios (quién y cuándo)."""
    import json as _json
    from app.models import BadgeTemplate, PersonChange, WebForm, EventAttendee
    from app.timeutil import utcnow
    event = get_event_for_staff(event_id, db, staff)
    reason = _deletable(event, field_key)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    label = next((c["label"] for c in field_configs_for_event(db, event) if c["key"] == field_key), None)
    if label is None:
        raise HTTPException(status_code=404, detail="Ese campo ya no existe en este evento.")
    typed = str((data or {}).get("confirm") or "").strip().lower()
    if typed != label.strip().lower():
        raise HTTPException(status_code=400, detail=f"Para borrar escribe exactamente el nombre del campo: «{label}».")
    people = _people_with_data(db, event, field_key)
    usage = _field_usage(db, event, field_key)
    elsewhere = {u for (u,) in db.query(EventAttendee.user_id).filter(EventAttendee.tenant_id == event.tenant_id, EventAttendee.event_id != event.id,
                                                                      EventAttendee.user_id.in_([p.id for p in people] or [""]))}
    cleared = 0
    for user in people:
        if user.id in elsewhere:
            continue
        if field_key.startswith("opcional_"):
            extras = user.get_extras(); extras.pop(field_key, None); user.set_extras(extras)
        else:
            setattr(user, field_key, None)
        cleared += 1
    for t in db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id):              # variables de escarapela
        els = t.get_elements()
        keep = [e for e in els if e.get("variable") != field_key]
        if len(keep) != len(els):
            t.set_elements(keep)
    for f in db.query(WebForm).filter(WebForm.event_id == event.id):                          # formularios: la pregunta queda, pero ya no alimenta la base
        try:
            design = _json.loads(f.design_json or "{}")
        except ValueError:
            continue
        changed = False
        for fld in (design.get("fields") or {}).values():
            if (fld or {}).get("key") == field_key:
                fld["key"] = None; changed = True
        if changed:
            f.design_json = _json.dumps(design, ensure_ascii=False)
    row = db.query(EventFieldConfig).filter_by(event_id=event.id, field_key=field_key).first()
    if field_key.startswith("opcional_"):
        labels = event.get_optional_labels(); labels.pop(field_key, None); event.set_optional_labels(labels)
        if row is not None:
            db.delete(row)
    else:
        if row is None:
            row = EventFieldConfig(event_id=event.id, field_key=field_key)
            db.add(row)
        row.field_type, row.required, row.default_stat_enabled = DELETED_TYPE, False, False
    db.add(PersonChange(tenant_id=event.tenant_id, event_id=event.id, user_id=None, staff_user_id=staff.id, kind="field_deleted", at=utcnow(),
                        old_value=f"{field_key} ({label})", new_value=None,
                        detail=f"personas con dato: {len(people)}; datos borrados: {cleared}; plantillas: {len(usage['templates'])}; formularios: {len(usage['forms'])}"))
    db.commit()
    return {"deleted": field_key, "label": label, "people_with_data": len(people), "cleared": cleared, "kept_other_events": len(people) - cleared, **usage}
