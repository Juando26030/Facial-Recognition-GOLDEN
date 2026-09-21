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
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_staff, get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import CHART_TYPES, Event, EventFieldConfig, FIELD_TYPES, StaffUser

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
LOCKED_KEYS = IDENTITY_KEYS | {"categories"}

# Campos fijos configurables (además de los opcional_N ya rotulados del evento, ver
# Event.optional_field_labels). "status" no es un campo de formulario (ver stats.py).
CONFIGURABLE_FIXED_FIELDS = [
    ("role", "Cargo"),
    ("entity", "Entidad"),
    ("phone", "Teléfono"),
    ("email", "Correo Electrónico"),
    ("opt_1", "Tipo de Asistente"),
]


def _configurable_fields(event: Event):
    """(key, label por defecto) de todo lo configurable para este evento, en el orden POR DEFECTO
    (la identidad primero, igual que el formulario de siempre)."""
    fields = list(IDENTITY_FIELDS) + list(CONFIGURABLE_FIXED_FIELDS)
    if event.get_categories():
        fields.append(("categories", "Categoría"))
    optional_labels = event.get_optional_labels()
    for key, label in sorted(optional_labels.items(), key=lambda kv: int(kv[0].split("_")[1])):
        fields.append((key, label))
    return fields


def _serialize(key: str, default_label: str, row: Optional[EventFieldConfig], categories: Optional[list] = None) -> dict:
    """`label` = lo que se muestra en este evento (el propio si lo personalizaron, si no el de por
    defecto); `default_label` se conserva para poder mostrarlo como sugerencia en Parámetros."""
    locked = key in LOCKED_KEYS
    label = (row.label if row and row.label else default_label)
    if row is None or locked:
        return {
            "key": key, "label": label, "default_label": default_label, "locked": locked,
            "required": False, "field_type": "categories" if key == "categories" else "text_short",
            "options": categories or [], "help_text": "",
            "default_stat_enabled": False, "default_chart_type": None,
        }
    return {
        "key": key, "label": label, "default_label": default_label, "locked": False,
        "required": row.required, "field_type": row.field_type,
        "options": row.get_options(), "help_text": row.help_text or "",
        "default_stat_enabled": row.default_stat_enabled,
        "default_chart_type": row.default_chart_type,
    }


def field_configs_for_event(db: Session, event: Event) -> list:
    """Lista completa de campos configurables de este evento, cada uno con su config real si
    existe o los valores por defecto si todavía no se guardó nada — así quien consuma esto
    (frontend, o la validación de manual_register/update_user) siempre ve la lista completa sin
    filas 'faltantes'. Usado también por stats.py para saber qué gráficos generar solos.

    Viene ORDENADA (ítem 4): por `sort_order` si alguien reordenó; los campos sin posición guardada
    (ej. un opcional agregado después de reordenar) van al final, en su orden por defecto."""
    rows = {r.field_key: r for r in db.query(EventFieldConfig).filter(EventFieldConfig.event_id == event.id)}
    ordered = []
    for idx, (key, label) in enumerate(_configurable_fields(event)):
        row = rows.get(key)
        position = row.sort_order if row and row.sort_order is not None else 1000 + idx
        ordered.append((position, _serialize(key, label, row, event.get_categories())))
    return [cfg for _, cfg in sorted(ordered, key=lambda pair: pair[0])]


def field_labels_for_event(db: Session, event: Event) -> dict:
    """{field_key: etiqueta efectiva} — atajo para reportes/estadísticas/plantillas que solo
    necesitan el nombre a mostrar."""
    return {cfg["key"]: cfg["label"] for cfg in field_configs_for_event(db, event)}


LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
LOGO_MODES = ("default", "hidden", "custom")


@router.get("/events/{event_id}/logo")
async def get_event_logo(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """Sirve el logo propio del evento (ítem 1, reunión 2026-09-21) — cualquier staff con acceso al
    evento lo necesita para dibujar el header, no solo quien lo configura."""
    event = get_event_for_staff(event_id, db, staff)
    if event.logo_mode != "custom" or not event.logo_path or not os.path.isfile(event.logo_path):
        raise HTTPException(status_code=404, detail="Este evento no tiene logo propio")
    return FileResponse(event.logo_path, headers={"Cache-Control": "no-cache"})


@router.put("/events/{event_id}/logo")
async def set_event_logo_mode(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """`mode`: 'default' (logo de Golden), 'hidden' (sin logo) o 'custom' (el propio ya subido)."""
    event = get_event_for_staff(event_id, db, staff)
    mode = data.get("mode")
    if mode not in LOGO_MODES:
        raise HTTPException(status_code=400, detail=f"mode debe ser uno de: {', '.join(LOGO_MODES)}")
    if mode == "custom" and not (event.logo_path and os.path.isfile(event.logo_path)):
        raise HTTPException(status_code=400, detail="Primero sube la imagen del logo")
    event.logo_mode = mode
    db.commit()
    return {"logo_mode": event.logo_mode}


@router.post("/events/{event_id}/logo/upload")
async def upload_event_logo(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in LOGO_EXT:
        raise HTTPException(status_code=400, detail=f"Formato no permitido — usa uno de: {', '.join(sorted(LOGO_EXT))}")
    content = await file.read()
    if not content or len(content) > 3_000_000:
        raise HTTPException(status_code=400, detail="La imagen está vacía o pesa más de 3 MB")
    folder = os.path.join("data", event.tenant_id, "event_logos")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(content)
    if event.logo_path and os.path.isfile(event.logo_path):
        os.remove(event.logo_path)
    event.logo_path, event.logo_mode = path, "custom"
    db.commit()
    return {"logo_mode": "custom"}


@router.get("/events/{event_id}/categories")
async def get_event_categories(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    event = get_event_for_staff(event_id, db, staff)
    return {"categories": event.get_categories(), "badge_per_category": event.badge_per_category}


@router.put("/events/{event_id}/categories")
async def set_event_categories(
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
async def add_optional_field(
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
    new_slot = next((n for n in range(1, 31) if n not in used_slots), None)
    if new_slot is None:
        raise HTTPException(status_code=400, detail="Ya se usaron los 30 campos opcionales disponibles para este evento")

    key = f"opcional_{new_slot}"
    labels[key] = label
    event.set_optional_labels(labels)
    db.commit()
    return {"key": key, "label": label}


@router.get("/events/{event_id}/field-configs")
async def list_field_configs(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    return field_configs_for_event(db, event)


@router.put("/events/{event_id}/field-configs/{field_key}")
async def upsert_field_config(
    event_id: int, field_key: str, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    valid_keys = {k for k, _ in _configurable_fields(event)}
    if field_key not in valid_keys:
        raise HTTPException(status_code=400, detail="Ese campo no existe o no es configurable en este evento")

    label = str(data.get("label") or "").strip()[:60] or None
    sort_order = data.get("sort_order")
    if sort_order is not None and not isinstance(sort_order, int):
        raise HTTPException(status_code=400, detail="sort_order debe ser un entero")

    row = db.query(EventFieldConfig).filter_by(event_id=event_id, field_key=field_key).first()
    if not row:
        row = EventFieldConfig(event_id=event_id, field_key=field_key)
        db.add(row)
    row.label = label
    row.sort_order = sort_order

    if field_key in LOCKED_KEYS:
        # Identidad y Categoría: solo etiqueta y posición. Tipo/obligatoriedad/estadística siguen fijos.
        row.required, row.field_type, row.default_stat_enabled, row.default_chart_type = False, "text_short", False, None
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

    row.help_text = help_text if field_type in ("consent", "signature") else None
    row.required = bool(data.get("required", False))
    row.field_type = field_type
    row.set_options(options if field_type == "select" else [])
    row.default_stat_enabled = default_stat_enabled
    row.default_chart_type = default_chart_type
    db.commit()

    return _serialize(field_key, dict(_configurable_fields(event))[field_key], row)
