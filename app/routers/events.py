import re
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, field_validator

from app.inputcheck import check_text, check_username, text_validator
from app.tenant_scope import assert_same_tenant
from sqlalchemy.orm import Session

from sqlalchemy import func, or_

import logging

from app import audit_actions, event_only, jobs, security, staff_credentials, status_changes, temp_client, warmup
from app.timeutil import utcnow
from app.database import get_db
from app import event_archive, event_rules, formsvc, inventory_svc
from app import event_codes, event_contacts, event_duplicate, event_transfer as et
from app.crm import platform_link as crm_link
from app import event_history, event_lease, public_slug, person_history
from app import event_template as event_tpl
from app import event_template_svc
from app import pledge, testperson, workday
from app.models import EventChangeLog, EventStatusChange, SystemEvent, AccessLog, BadgeTemplate, BulkJob, WebForm, RouletteConfig, RouletteDraw, EVENT_STATUSES, Event, EventAttendee, EventFieldConfig, EventState, EventStaffAuthorization, PrintDevice, PrintLog, PrintRoute, SavedColor, StaffUser, SuperEvent, Tenant
from app.routers import event_types as event_types_router
from app.routers.event_docs import delete_event_files
from app.routers.forms import delete_form_rows
from app import queue_svc
from app.routers.areas_inventory import delete_event_modules
from app.auth import assert_event_scope, assert_event_tenant, effective_roles, is_inventory_only, scope_events_query, get_current_staff, get_event_for_staff, hash_password, require_role
from app.cities_data import COUNTRY_CITIES

router = APIRouter()
log = logging.getLogger("golden.events")


@router.get("/cities")
def list_cities(country: str, staff: StaffUser = Depends(require_role("coordinador"))):
    """Sugerencias de ciudad para el país dado (dataset GeoNames, ver app/cities_data.py),
    ordenadas por población — se recorta a las primeras 300 para no mandar un <datalist> gigante
    al navegador en países con miles de ciudades. El campo de ciudad siempre acepta texto libre
    también, por si la ciudad buscada no queda entre esas 300."""
    return COUNTRY_CITIES.get(country, [])[:300]


class EventStaffIn(BaseModel):
    username: Optional[str] = None  # cédula, para digitador; vacío si `client` (el servidor genera el usuario)
    temp_coordinator: bool = False  # 16-nov-2026: coordinador temporal (app/event_only.py): permisos de coordinador SOLO sobre este evento; usuario `ct-…` y contraseña aleatoria, sin correo. Lo crea una comercial, un admin o el super admin
    client: bool = False  # 12-nov-2026: cliente temporal (app/temp_client.py): mismos permisos que el digitador, usuario y contraseña aleatorios, sin autorización del coordinador
    password: Optional[str] = None      # 6-nov-2026: el digitador temporal entra con su cédula como usuario Y contraseña; solo se manda una si alguien quiere otra distinta (esa sí pasa la política estricta)
    full_name: Optional[str] = None
    role: str = "digitador"  # "digitador" (coordinador+, no comercial) o "cliente" (comercial+)
    phone: Optional[str] = None  # Sprint 2.4: notificaciones por WhatsApp más adelante
    email: Optional[str] = None  # Fase 4: correo donde recibe los datos de ingreso y del evento (opcional)

    _u = field_validator("username")(classmethod(lambda cls, v: None if v in (None, "") else check_username(v)))
    _t = text_validator("full_name")


class AssignExistingIn(BaseModel):
    staff_id: int


def _serialize_staff(s: StaffUser) -> dict:
    return {"id": s.id, "username": s.username, "full_name": s.full_name, "role": s.role, "is_active": s.is_active, "has_email": bool((s.email or "").strip()), "client_temp": bool(getattr(s, "client_temp", False)), "event_only": bool(getattr(s, "event_only", False))}


# Código del evento (orden del 21-oct-2026). Va en direcciones públicas: /aceptar/<código>, el QR del cartel y los enlaces personales ya enviados por correo.
EVENT_CODE_RE = re.compile(r"[A-Za-z0-9._-]+")          # solo para eventos NUEVOS; los códigos solo numéricos siguen permitidos
EVENT_CODE_HELP = ("El código del evento solo puede tener letras sin tilde, números, punto (.), guion (-) y guion bajo (_), sin espacios. "
                   "Ejemplo: FERIA-2026.")
EVENT_CODE_LOCKED = ("El código del evento no se puede cambiar una vez creado: los QR y los enlaces de aceptación ya emitidos dependen de él. "
                     "Si necesitas otro código, crea un evento nuevo.")


class EventIn(BaseModel):
    _t = text_validator("name", "location", "address", "country", "city")
    """Qué es obligatorio lo decide la PLANTILLA DE EVENTO (Configuración › Diseñar plantilla para eventos, app/event_template.py), no este modelo: la plantilla de fábrica pide lo mismo que antes
    (todo menos observaciones, pañoleta y superevento). Solo `tenant_id`, `event_code` y `name` son obligatorios siempre. Los interruptores (nombre de su columna) y `extra` (campos
    personalizados de la plantilla, claves `c_…`) son opcionales."""
    tenant_id: str
    event_code: str = ""          # vacío = el servidor pone el siguiente número libre (app/event_codes.py)
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    setup_date: Optional[date] = None
    event_time_start: Optional[str] = None
    event_time_end: Optional[str] = None
    setup_time_start: Optional[str] = None
    setup_time_end: Optional[str] = None
    coordinator_staff_id: Optional[int] = None
    commercial_staff_id: Optional[int] = None  # Sprint 2.4 Fase 5: si no viene, se resuelve en create_event (self si el creador es comercial; si la plantilla lo exige, obligatorio elegir si es admin+)
    bandana_color: Optional[str] = None  # Sprint 2.4 Fase 12: "Color de pañoleta", hex #rrggbb
    bandana_color_name: Optional[str] = None  # nombre libre para ese color (ej. "Rojo Golden")
    super_event_id: Optional[int] = None  # superevento al que pertenece (2026-09-23: también se elige al CREAR el evento)
    event_type_id: Optional[int] = None  # Fase 10 (C): «Categoría (tipo de evento)» (app/routers/event_types.py); sin valor = «Sin categoría»
    notes: Optional[str] = None
    # Interruptores: la MISMA columna que cambia «Parámetros del evento» (una sola fuente de datos). Sin valor = no se toca (queda apagado, como siempre).
    facial_enabled: Optional[bool] = None
    aceptar_enabled: Optional[bool] = None
    face_door_enabled: Optional[bool] = None
    inventory_enabled: Optional[bool] = None
    areas_enabled: Optional[bool] = None
    certificates_enabled: Optional[bool] = None
    digital_badge_enabled: Optional[bool] = None
    review_detail: Optional[bool] = None
    auto_print_badge: Optional[bool] = None
    auto_register: Optional[bool] = None
    shared_print_enabled: Optional[bool] = None
    extra: Optional[Dict[str, Any]] = None      # campos personalizados de la plantilla {clave: valor}
    contacts: Optional[List[Dict[str, Any]]] = None      # 16-nov-2026: contactos del cliente en el evento (app/event_contacts.py); sin este campo, entra el contacto principal de la cuenta del CRM


class EventUpdate(BaseModel):
    _t = text_validator("name", "location", "address", "country", "city")
    event_code: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    setup_date: Optional[date] = None
    event_time_start: Optional[str] = None
    event_time_end: Optional[str] = None
    setup_time_start: Optional[str] = None
    setup_time_end: Optional[str] = None
    coordinator_staff_id: Optional[int] = None
    commercial_staff_id: Optional[int] = None
    bandana_color: Optional[str] = None
    bandana_color_name: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    state_id: Optional[int] = None          # estado configurable (docs/18); al elegirlo, `status` pasa a su estado base
    review_detail: Optional[bool] = None          # 0143: «Revisar el detalle»
    auto_print_badge: Optional[bool] = None
    auto_register: Optional[bool] = None
    super_event_id: Optional[int] = None  # ítem 19; null explícito = sacarlo de su superevento
    event_type_id: Optional[int] = None  # Fase 10 (C): null explícito = dejarlo «Sin categoría»
    extra: Optional[Dict[str, Any]] = None      # Fase 2: valores de campos personalizados de la plantilla que se cambian (un valor null borra ese valor); los demás no se tocan


def _serialize(e: Event) -> dict:
    return {
        "id": e.id, "tenant_id": e.tenant_id, "tenant_name": e.tenant.name if e.tenant else None,
        "event_code": e.event_code, "name": e.name, "location": e.location, "address": e.address,
        "country": e.country, "city": e.city, "status": e.status,
        "state_id": e.state_id, "state_name": e.state.name if e.state else None, "state_color": e.state.color if e.state else None,
        "billed": e.billed_at is not None, "billed_at": e.billed_at.isoformat() if e.billed_at else None,
        "billed_by_name": (e.billed_by.full_name or e.billed_by.username) if e.billed_by else None,
        "final_db_uploaded": bool(e.final_db_key), "final_db_name": e.final_db_name, "final_db_uploaded_at": e.final_db_uploaded_at.isoformat() if e.final_db_uploaded_at else None,
        "final_db_uploaded_by_name": (e.final_db_uploaded_by.full_name or e.final_db_uploaded_by.username) if e.final_db_uploaded_by else None,
        "start_date": e.start_date.isoformat() if e.start_date else None,
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "setup_date": e.setup_date.isoformat() if e.setup_date else None,
        "event_time_start": e.event_time_start, "event_time_end": e.event_time_end,
        "setup_time_start": e.setup_time_start, "setup_time_end": e.setup_time_end,
        **workday.serialize(e),          # Fase 5: jornada calculada (solo lectura): workday_key / workday_label / workday_hours
        "notes": e.notes,
        "coordinator_staff_id": e.coordinator_staff_id,
        "coordinator_name": (e.coordinator.full_name or e.coordinator.username) if e.coordinator else None,
        "commercial_staff_id": e.commercial_staff_id,
        "commercial_name": (e.commercial.full_name or e.commercial.username) if e.commercial else None,
        "bandana_color": e.bandana_color,
        "bandana_color_name": e.bandana_color_name,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "data_archived": e.data_archived_at is not None, "data_archived_at": e.data_archived_at.isoformat() if e.data_archived_at else None, "archived": e.archived_at is not None, "archived_at": e.archived_at.isoformat() if e.archived_at else None, "archived_auto": e.archived_at is not None and e.archived_by_id is None,
        "local": event_lease.serialize(e),          # Fase 6: «en servidor local» (solo lectura en la nube) y última subida
        "facial_enabled": e.facial_enabled,
        "auto_print_badge": e.auto_print_badge,
        "auto_register": e.auto_register,
        "review_detail": bool(e.review_detail),
        "event_type_id": e.event_type_id, "event_type_name": e.event_type.name if e.event_type else None, "event_type_color": (e.event_type.color or None) if e.event_type else None,
        "super_event_id": e.super_event_id,
        "super_event_name": e.super_event.name if e.super_event else None,
        "extra": e.get_extra(),      # Fase 2: valores de los campos personalizados de la plantilla (los retirados también); {} en los eventos anteriores
        "switches": {k: bool(getattr(e, k, False)) for k in event_tpl.SWITCH_KEYS},      # Fase 2: los interruptores de la plantilla (mismas columnas que Parámetros)
        "bandana_colors": [{"name": e.bandana_color_name or "", "hex": e.bandana_color}] if e.bandana_color else [],
        "report_uploaded": bool(e.report_pdf_path),  # ítem 6: bombillo verde/naranja
        "report_uploaded_at": e.report_uploaded_at.isoformat() if e.report_uploaded_at else None,
    }


@router.get("/my-events")
def my_events(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    """Para el dashboard: eventos a los que este staff puede entrar directo. digitador/cliente ->
    solo eventos en_proceso con autorización explícita. coordinador+ -> todos los en_proceso.

    `has_any_authorization` (2026-09-16, ronda 2 — QA reportó que un `cliente` recién asignado
    veía "No tienes eventos autorizados todavía. Pide a un coordinador que te asigne", un mensaje
    que sonaba a que la asignación no existía, cuando en realidad sí existía pero el evento
    todavía no estaba "En Proceso" — el mensaje no distinguía los dos casos. No se logró
    reproducir un bug real en la asignación en sí (`EventStaffAuthorization` se crea igual para
    digitador y cliente, ver create_event_staff) probando el mismo flujo real con TestClient; lo
    más probable es justamente ese mensaje ambiguo. Este campo nuevo deja que el frontend
    distinga "no tienes ninguna asignación" de "tienes asignación(es) pero ningún evento está en
    proceso todavía" sin cambiar la forma de `events` (sigue siendo la lista de siempre)."""
    if is_inventory_only(staff):          # F5-9 D (D1): almacén/contabilidad solos no entran a eventos (su pantalla es /inventario)
        return {"events": [], "has_any_authorization": False}
    query = event_archive.active_only(db.query(Event).filter(Event.status == "en_proceso"))
    has_any_authorization = True
    if staff.role in ("digitador", "cliente"):
        has_any_authorization = db.query(EventStaffAuthorization).filter(
            EventStaffAuthorization.staff_user_id == staff.id
        ).first() is not None
        query = query.join(
            EventStaffAuthorization, EventStaffAuthorization.event_id == Event.id
        ).filter(EventStaffAuthorization.staff_user_id == staff.id)
    else:
        query = scope_events_query(query, staff)
    events = query.order_by(Event.created_at.desc()).all()
    return {"events": [_serialize(e) for e in events], "has_any_authorization": has_any_authorization}


def _strip_accents(text: str) -> str:
    """NFD + descarta las marcas diacríticas (categoría Unicode 'Mn') — 'María'/'Compañía' quedan
    como 'Maria'/'Compania' para poder buscar sin tildes/ñ (2026-09-15, Sprint 2 Fix 1: la
    búsqueda era insensible a mayúsculas pero NO a tildes, ver CLAUDE.md)."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _words(text: Optional[str]) -> list:
    return re.findall(r"\w+", _strip_accents(text or "").lower())


def _edit_distance(a: str, b: str) -> int:
    """Distancia de edición con transposición de letras adyacentes contada como 1 (Damerau/OSA):
    "jaun" vs "juan" = 1, "yuliana" vs "juliana" = 1. Mismo algoritmo que `editDistance` en
    static/js/directory.js (se mantienen iguales a propósito, como el resto de la búsqueda)."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[len(b)]


def _typo_match(a: str, b: str) -> bool:
    """Tolera errores de tipeo (reunión 2026-09-21, ítem 2): palabras de 4+ letras con hasta 1
    error (4-6 letras) o 2 (7+), comparando contra la palabra entera Y contra su inicio del mismo
    largo (así "julia" también encuentra "yuliana" mientras se sigue escribiendo). Palabras de
    3 letras o menos no se toleran: "ana"/"ani" no deben confundirse."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 4:
        return False
    limit = 1 if len(short) <= 6 else 2
    return _edit_distance(short, long_) <= limit or _edit_distance(short, long_[:len(short)]) <= limit


def _matches_by_word_prefix(haystack: str, query: str) -> bool:
    """True si CADA palabra de `query` es prefijo de ALGUNA palabra de `haystack`
    (ej. 'c' o 'cor' matchean 'Corferias', pero 'ferias' no) — como cualquier buscador
    "empieza por", no una coincidencia de substring en cualquier posición."""
    query_words = _words(query)
    if not query_words:
        return False
    haystack_words = _words(haystack)
    return all(any(hw.startswith(qw) for hw in haystack_words) for qw in query_words)


def _archive_filter(query, staff: StaffUser, include_archived: bool):
    """Fase 3: por defecto SOLO los eventos activos (los archivados no salen en listas, calendario ni selectores). `include_archived=true` es de admin+ («Ver archivados»)."""
    if not include_archived:
        return event_archive.active_only(query)
    if staff.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Solo un administrador puede ver los eventos archivados")
    return query


@router.get("/events/search")
def search_events(
    q: str = "", status: Optional[str] = None,
    commercial_staff_id: Optional[int] = None, coordinator_staff_id: Optional[int] = None, include_archived: bool = False,
    db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Búsqueda libre entre todos los clientes/eventos: por código, nombre, país o ciudad del
    evento, o por nombre del cliente (tenant). Filtrado en Python (no SQL LIKE) para que la
    coincidencia sea por inicio de palabra y no por substring en medio de una palabra.
    `status` (2026-09-16, para /eventos del menú lateral): filtro adicional por estado
    (creado/en_proceso/finalizado), combinable con `q`. `q` pasa a ser opcional — con solo
    `status` puesto (sin texto de búsqueda) igual debe listar, filtrando nada más por estado.
    `commercial_staff_id`/`coordinator_staff_id` (Sprint 2.4 Fase 5, pedido explícito): filtro por
    pertenencia — una comercial usa `commercial_staff_id=<su propio id>` para "Mis eventos"
    (omitiéndolo ve "Todos"); admin+ los usa para filtrar por cualquier comercial o coordinador
    asignado, ambos combinables entre sí y con `q`/`status`."""
    all_events = _archive_filter(scope_events_query(db.query(Event), staff), staff, include_archived).order_by(Event.created_at.desc()).all()
    matches = []
    for e in all_events:
        if status and e.status != status:
            continue
        if commercial_staff_id is not None and e.commercial_staff_id != commercial_staff_id:
            continue
        if coordinator_staff_id is not None and e.coordinator_staff_id != coordinator_staff_id:
            continue
        if q:
            haystack = " ".join(filter(None, [
                e.name, e.event_code, e.country, e.city, e.tenant.name if e.tenant else None,
            ]))
            if not _matches_by_word_prefix(haystack, q):
                continue
        matches.append(e)
    return [_serialize(e) for e in matches]


@router.get("/events")
def list_events(
    tenant_id: Optional[str] = None, include_archived: bool = False, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    query = _archive_filter(scope_events_query(db.query(Event), staff), staff, include_archived)
    if tenant_id:
        query = query.filter(Event.tenant_id == tenant_id)
    return [_serialize(e) for e in query.order_by(Event.created_at.desc()).all()]


def _validate_event_dates(start_date, end_date, setup_date):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="La fecha de inicio no puede ser después de la fecha de fin")
    if setup_date and start_date and setup_date > start_date:
        raise HTTPException(status_code=400, detail="La fecha de montaje debe ser el día del inicio o antes")


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@router.get("/colors")
def list_saved_colors(include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Librería de colores de pañoleta (se define una vez y se elige en cualquier evento). Por defecto sin los archivados; `include_archived=true` es de coordinador+."""
    query = db.query(SavedColor)
    if include_archived:
        if staff.role not in ("coordinador", "comercial", "admin", "super_admin"):
            raise HTTPException(status_code=403, detail="No tienes permiso para ver los colores archivados")
    else:
        query = query.filter(SavedColor.archived_at.is_(None))
    return [{"id": c.id, "name": c.name, "hex": c.hex, "archived": c.archived_at is not None} for c in query.order_by(SavedColor.name)]


@router.post("/colors")
def save_color(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Crea un color. Si ya existe uno con ese nombre (la librería es compartida por toda la organización), solo admin+ puede cambiarle el tono: un coordinador que manda el
    mismo nombre con otro tono recibe 409 (con el mismo tono es idempotente). Así "Rojo Golden" es siempre uno solo y nadie lo pisa sin permiso (cierre de seguridad, Fase 3)."""
    name = str(data.get("name") or "").strip()[:60]
    hex_value = str(data.get("hex") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Ponle un nombre al color para guardarlo (ej. Rojo Golden)")
    try:
        check_text(name, "El nombre del color")      # C1: sin «<» ni «>» (el panel además lo escapa al pintar)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not _HEX_RE.match(hex_value):
        raise HTTPException(status_code=400, detail="El color debe ser un hex como #C0392B")
    color = db.query(SavedColor).filter(func.lower(SavedColor.name) == name.lower()).first()
    if color:
        if color.archived_at is not None:
            raise HTTPException(status_code=400, detail="Ese color está archivado: restáuralo para usarlo")
        if color.hex.lower() != hex_value.lower():
            if staff.role not in ("admin", "super_admin"):
                raise HTTPException(status_code=409, detail=f"Ya existe un color llamado «{color.name}» con otro tono. Elígelo de la lista o ponle otro nombre; solo un administrador puede cambiarlo")
            audit_actions.record(db, staff, "update", "saved_color", color.id, color.name, f"{color.hex} -> {hex_value.lower()}")
            color.hex = hex_value.lower()
    else:
        color = SavedColor(name=name, hex=hex_value.lower(), created_by_id=staff.id)
        db.add(color)
    db.commit()
    return {"id": color.id, "name": color.name, "hex": color.hex}


def _color_or_404(db: Session, color_id: int) -> SavedColor:
    color = db.query(SavedColor).filter(SavedColor.id == color_id).first()
    if not color:
        raise HTTPException(status_code=404, detail="Color no encontrado")
    return color


@router.post("/colors/{color_id}/archive")
def archive_saved_color(color_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Archivar = quitarlo de la lista de colores guardados. Los eventos que ya lo usan guardan su propia copia: no cambian. Un coordinador o superior lo restaura."""
    color = _color_or_404(db, color_id)
    if color.archived_at is not None:
        raise HTTPException(status_code=400, detail="El color ya está archivado")
    color.archived_at, color.archived_by_id = utcnow(), staff.id
    audit_actions.record(db, staff, "archive", "saved_color", color.id, color.name)
    db.commit()
    return {"id": color.id, "name": color.name, "hex": color.hex, "archived": True}


@router.post("/colors/{color_id}/restore")
def restore_saved_color(color_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    color = _color_or_404(db, color_id)
    if color.archived_at is None:
        raise HTTPException(status_code=400, detail="El color no está archivado")
    color.archived_at, color.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "saved_color", color.id, color.name)
    db.commit()
    return {"id": color.id, "name": color.name, "hex": color.hex, "archived": False}


@router.delete("/colors/{color_id}")
def delete_saved_color(color_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """Borrado DEFINITIVO: solo super_admin y de un color ya archivado (no hay otras dependencias: los eventos guardan su copia)."""
    color = _color_or_404(db, color_id)
    if color.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el color; el borrado definitivo solo aplica a colores archivados")
    audit_actions.record(db, staff, "delete", "saved_color", color.id, color.name)
    db.delete(color)
    db.commit()
    return {"message": "Color eliminado de la librería"}


@router.post("/events")
def create_event(
    data: EventIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """Crear eventos: coordinador+. Historia: antes del 16-sep-2026 era coordinador+; ese día pasó a
    comercial+; el 4-nov-2026 Juan David (dueño) decidió que los COORDINADORES vuelven a poder crear.
    Un coordinador «puro» (sin rol comercial ni admin) solo puede crear eventos donde él es el
    coordinador (si manda otro id, 403: no puede crear un evento y quedarse sin verlo); la comercial
    es opcional para él (la columna admite NULL). Comercial, doble rol y admin+ siguen igual."""
    tenant_row = db.query(Tenant).filter(Tenant.id == data.tenant_id).first()
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Cliente (tenant) no encontrado")
    if tenant_row.archived_at is not None:
        raise HTTPException(status_code=400, detail="El cliente está archivado: restáuralo para crearle eventos")
    assert_same_tenant(staff, data.tenant_id, "Cliente (tenant) no encontrado")          # P5: limitado a su cliente, solo crea eventos de su cliente
    pure_coordinator = not ({"comercial", "admin", "super_admin"} & effective_roles(staff))
    if pure_coordinator and data.coordinator_staff_id is None:
        data.coordinator_staff_id = staff.id          # el coordinador «puro» siempre queda como coordinador de lo que crea (aunque la plantilla no le muestre ese campo)
    if pure_coordinator and data.coordinator_staff_id != staff.id:
        raise HTTPException(status_code=403, detail="Un coordinador solo puede crear eventos asignados a sí mismo")
    data.event_code = (data.event_code or "").strip() or event_codes.next_code(db)
    if db.query(Event).filter(Event.event_code == data.event_code).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un evento con el código '{data.event_code}'")
    # Solo eventos NUEVOS (orden del 21-oct-2026): el código va en direcciones públicas (/aceptar/<código>, QR y enlaces personales). Los existentes no se tocan.
    if not EVENT_CODE_RE.fullmatch(data.event_code or ""):
        raise HTTPException(status_code=400, detail=EVENT_CODE_HELP)
    if db.query(Event.id).filter(func.lower(func.btrim(Event.event_code)) == data.event_code.lower()).first():
        raise HTTPException(status_code=400, detail=f"Ya existe un evento con el código «{data.event_code}» escrito con otras mayúsculas o minúsculas: elige otro código.")
    _validate_event_dates(data.start_date, data.end_date, data.setup_date)

    # Fase 2: lo obligatorio y los campos extra los decide la PLANTILLA DE EVENTO (la de fábrica pide lo mismo que antes). La comercial que crea se asigna a sí misma y el coordinador «puro» queda
    # como coordinador: esas dos reglas del servidor no se exigen en el formulario.
    waive = set()
    if pure_coordinator or "comercial" in effective_roles(staff):
        waive.add("commercial_staff_id")
    prepared = event_template_svc.prepare_creation(db, data.dict(), data.extra, waive=waive)
    commercial_required = any(f["key"] == "commercial_staff_id" and f["required"] and any(f["key"] in sec["keys"] for sec in prepared["template"]["creation_layout"]["sections"])
                              for f in prepared["template"]["fields"])

    # Sprint 2.4 Fase 5 (2026-09-16, pedido explícito): "por defecto se asigne una comercial que
    # es quien crea el evento, a menos de que... lo puede cambiar a otras comerciales... o los
    # administradores eligen una comercial". Si quien crea es comercial y no manda un id, se
    # asigna a sí misma; si es admin+ (no es comercial), tiene que elegir explícitamente.
    commercial_id = data.commercial_staff_id
    if commercial_id is None:
        if "comercial" in effective_roles(staff):
            commercial_id = staff.id
        elif pure_coordinator or not commercial_required:
            commercial_id = None          # coordinador puro, o la plantilla no la exige: la comercial es opcional (columna nullable)
        else:
            raise HTTPException(status_code=400, detail="Debes asignar una comercial para este evento")
    else:
        if pure_coordinator:
            raise HTTPException(status_code=403, detail="Un coordinador no asigna la comercial: la define un comercial o un administrador")
        commercial = db.query(StaffUser).filter(
            StaffUser.id == commercial_id,
            or_(StaffUser.role == "comercial", StaffUser.secondary_role == "comercial"),
            StaffUser.is_active == True,
        ).first()
        if not commercial:
            raise HTTPException(status_code=400, detail="La comercial asignada no es válida")

    if data.coordinator_staff_id is not None:      # 0C (N3): debe ser un coordinador activo (igual que en la creación)
        coord = db.query(StaffUser).filter(
            StaffUser.id == data.coordinator_staff_id,
            or_(StaffUser.role == "coordinador", StaffUser.secondary_role == "coordinador"),
            StaffUser.is_active == True,
        ).first()
        if not coord:
            raise HTTPException(status_code=400, detail="El coordinador asignado no es válido")

    event_types_router.check_assignable(db, data.event_type_id)
    if data.super_event_id is not None:
        sup = db.query(SuperEvent).filter(SuperEvent.id == data.super_event_id).first()
        if not sup or sup.tenant_id != data.tenant_id:
            raise HTTPException(status_code=400, detail="El superevento debe existir y ser del mismo cliente que el evento")
        if sup.archived_at is not None:
            raise HTTPException(status_code=400, detail="El superevento está archivado: restáuralo para asignarle eventos")

    event_data = data.dict(exclude={"extra", "contacts", *event_tpl.SWITCH_KEYS})
    event_data["commercial_staff_id"] = commercial_id
    event_data.setdefault("accept_no_birth_mode", "require_personal_link")      # D5: los eventos nuevos exigen el enlace personal si la base no trae fecha de nacimiento (los existentes quedan en 'any'; se cambia en Parámetros)
    event_data["pledge_enabled"] = True          # Fase 4: todo evento nuevo EXIGE el compromiso digital de sus digitadores (se puede apagar en «Usuarios temporales»); los existentes no cambian
    event_data.update(prepared["columns"])          # pañoleta normalizada e interruptores: las MISMAS columnas que cambia «Parámetros del evento»
    initial = event_rules.default_state(db, event_data.get("status") or "creado")
    if initial is not None:
        event_data["state_id"] = initial.id
    event = Event(**event_data, created_by_id=staff.id)
    if prepared["extra"]:
        event.set_extra(prepared["extra"])
    db.add(event)
    db.flush()
    public_slug.ensure(db, event)          # D2.5k: nombre del enlace limpio de inscripciones («nombre + año», único)
    event_template_svc.after_create(db, event)
    testperson.ensure_for_event(db, event)          # toda evento nuevo trae su persona de prueba (no cuenta en reportes ni estadísticas)
    if pledge.text_available():
        pledge.create_or_regenerate(db, event, staff)          # el enlace del compromiso queda listo desde el primer día (sin texto aprobado no se publica: ver pledge.missing_for_login)
    try:
        if data.contacts is None:
            event_contacts.replace(db, event, event_contacts.default_from_crm(db, event.tenant_id))          # por defecto: el contacto principal de la cuenta en el CRM
        else:
            event_contacts.replace(db, event, data.contacts)
    except event_contacts.ContactError as e:
        raise HTTPException(status_code=400, detail=str(e))
    crm_link.link_new_event(db, staff, event)          # CRM: el evento nace con su oportunidad ganada (y su cuenta, si faltaba); un fallo del CRM no impide crear el evento
    db.commit()
    db.refresh(event)
    return _serialize(event)


def _auto_send_survey(db: Session, event: Event, staff: StaffUser, request_base: str) -> dict:
    """16-nov-2026 (pedido de Juan David): al pasar a «Facturado» la encuesta se envía sola al contacto PRINCIPAL del evento (misma cola y mismo enlace que el envío manual). Nunca lanza ni deshace el cambio de estado:
    si falta algo (correo, base final, dirección pública) lo dice y la comercial la envía a mano desde Editar evento."""
    from app import delivery, publicurl
    try:
        db.refresh(event)
        if not delivery.is_billed(event) or delivery.final_db(event) is None:
            return {"sent": False, "detail": "No se envió la encuesta: el evento no está listo para la entrega al cliente."}
        contact = delivery.client_contact(db, event)
        if contact is None:
            return {"sent": False, "detail": "No se envió la encuesta: el evento no tiene un contacto principal con correo. Agrégalo y envíala desde Editar evento."}
        base = publicurl.base(request_base)
        if not base:
            return {"sent": False, "detail": "No se envió la encuesta: falta la dirección pública (PUBLIC_BASE_URL)."}
        link = delivery.ensure_link(db, event, staff)
        if delivery.mail_sent_recently(db, link.id):
            return {"sent": False, "detail": "La encuesta ya se había enviado hace menos de una hora."}
        delivery.enqueue_mail(db, event, link, base, staff)
        db.commit()
        jobs.kick()
        return {"sent": True, "recipient": contact["email"], "detail": f"La encuesta va en camino a {contact['email']}."}
    except Exception:                                   # el estado ya quedó guardado: un fallo aquí no puede devolver error al usuario
        db.rollback()
        log.exception("No se pudo encolar la encuesta automática del evento %s", getattr(event, "id", "?"))
        return {"sent": False, "detail": "No se pudo enviar la encuesta sola; envíala desde Editar evento."}


@router.patch("/events/{event_id}")
def update_event(
    event_id: int, data: EventUpdate, request: Request, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="El evento está archivado: restáuralo para editarlo")
    event_lease.assert_editable(event)          # Fase 6: en un servidor local es de solo lectura aquí
    new_state = None
    if data.state_id is not None:            # estado configurable (docs/18): el evento pasa al estado base de ese estado
        new_state = db.get(EventState, data.state_id)
        if not new_state or not new_state.is_active:
            raise HTTPException(status_code=400, detail="El estado elegido no existe o está desactivado")
        data.status = new_state.base_status
    if data.status is not None and data.status not in EVENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado inválido (debe ser uno de: {', '.join(EVENT_STATUSES)})")
    if new_state is None and data.status is not None and data.status != event.status:
        new_state = event_rules.default_state(db, data.status)          # cambió solo el estado base: se usa el primer estado activo de ese tipo
    status_changed = data.status is not None and data.status != event.status
    if status_changed and data.status == "en_proceso":
        inventory_svc.assert_can_enter_in_progress(db, event)          # Fase 5: regla de cuadre del inventario (app/inventory.py); sin líneas de inventario no estorba
    # 2026-09-16, pedido explícito: si el evento ya tiene gente cargada (roster y/o registros en
    # vivo), no se puede "devolver" a 'creado' — 'creado' es preparación previa al evento, y
    # volver a ese estado con datos reales adentro presta a confusión (¿el evento no ha empezado,
    # o ya tiene gente?). No aplica a pasar a 'finalizado', solo a la vuelta específica hacia atrás.
    if data.status == "creado" and event.status != "creado":
        tiene_asistentes = db.query(EventAttendee).filter(EventAttendee.event_id == event_id, EventAttendee.user_id != testperson.TEST_ID).first() is not None
        if tiene_asistentes:
            raise HTTPException(
                status_code=400,
                detail=("Este evento ya tiene personas cargadas/registradas — no se puede devolver a 'Creado' desde aquí. Un administrador puede hacerlo con «Devolver a Creado» (queda registrado quién y cuándo; "
                        "no se borra nada). Si necesitas pausarlo, usa 'Finalizado', o crea un evento nuevo si de verdad necesitas empezar de cero."),
            )
    entering_billing = leaving_billing = False
    if new_state is not None and new_state.id != event.state_id:          # Fase 5: «Facturado» (estado con la regla client_delivery) lo pone o quita SOLO una comercial (también con doble rol) o un administrador
        entering_billing, leaving_billing = event_rules.is_billing_state(new_state), event_rules.is_billing_state(event.state)
        if (entering_billing or leaving_billing) and not ({"comercial", "admin", "super_admin"} & effective_roles(staff)):
            raise HTTPException(status_code=403, detail="Solo una comercial o un administrador puede poner el evento en «Facturado» o sacarlo de ese estado")
        if entering_billing and event.status != "finalizado":
            raise HTTPException(status_code=400, detail="Solo un evento «Finalizado» se puede pasar a «Facturado»")
        if entering_billing and not event.final_db_key:          # decisión de Juan David (9-nov-2026): sin la base final adjunta no se factura
            raise HTTPException(status_code=400, detail="Para pasar el evento a «Facturado» primero hay que adjuntar la base de datos final (Editar evento → Base de datos final)")
        if leaving_billing and entering_billing:
            leaving_billing = False          # de un estado de facturación a otro: se conserva quién y cuándo lo facturó
            entering_billing = False
    if data.event_code is not None and data.event_code != event.event_code:          # el código es fijo una vez creado (orden del 21-oct-2026)
        raise HTTPException(status_code=400, detail=EVENT_CODE_LOCKED)
    if data.coordinator_staff_id is not None and data.coordinator_staff_id != event.coordinator_staff_id:      # P8: misma validación que al crear (0C, N3)
        coord = db.query(StaffUser).filter(
            StaffUser.id == data.coordinator_staff_id,
            or_(StaffUser.role == "coordinador", StaffUser.secondary_role == "coordinador"),
            StaffUser.is_active == True,
        ).first()
        if not coord:
            raise HTTPException(status_code=400, detail="El coordinador asignado no es válido")
    if data.commercial_staff_id is not None:
        # Reasignar la comercial es decisión de comercial+ — un coordinador "puro" puede editar el
        # resto del evento (fechas, estado, etc.) pero no a quién pertenece comercialmente. Un
        # coordinador+comercial (Fase 15) SÍ puede, porque también es comercial de verdad.
        if not ({"comercial", "admin", "super_admin"} & effective_roles(staff)):
            raise HTTPException(status_code=403, detail="Solo una comercial o Admin puede reasignar la comercial del evento")
        commercial = db.query(StaffUser).filter(
            StaffUser.id == data.commercial_staff_id,
            or_(StaffUser.role == "comercial", StaffUser.secondary_role == "comercial"),
            StaffUser.is_active == True,
        ).first()
        if not commercial:
            raise HTTPException(status_code=400, detail="La comercial asignada no es válida")

    event_types_router.check_assignable(db, data.event_type_id, event.event_type_id)
    if data.super_event_id is not None:
        sup = db.query(SuperEvent).filter(SuperEvent.id == data.super_event_id).first()
        if not sup or sup.tenant_id != event.tenant_id:
            raise HTTPException(status_code=400, detail="El superevento debe existir y ser del mismo cliente que el evento")
        if sup.archived_at is not None and sup.id != event.super_event_id:          # conservar el que ya tiene (archivado) no estorba; asignar uno archivado nuevo, sí
            raise HTTPException(status_code=400, detail="El superevento está archivado: restáuralo para asignarle eventos")

    effective_start = data.start_date if data.start_date is not None else event.start_date
    effective_end = data.end_date if data.end_date is not None else event.end_date
    effective_setup = data.setup_date if data.setup_date is not None else event.setup_date
    _validate_event_dates(effective_start, effective_end, effective_setup)

    extra_patch = event_template_svc.merge_extra(db, event.get_extra(), data.extra) if data.extra is not None else None      # valida ANTES de tocar nada
    history_before = event_history.snapshot(db, event)          # Fase 5: historial por campo (se compara con lo que quede abajo, en el mismo commit)
    for field, value in data.dict(exclude_unset=True, exclude={"extra"}).items():
        setattr(event, field, value)
    if extra_patch is not None:
        event.set_extra(extra_patch)
    if new_state is not None:
        event.state_id = new_state.id
    if entering_billing:
        event.billed_at, event.billed_by_id = utcnow(), staff.id
        audit_actions.record(db, staff, "billed", "event", event.id, event.name, f"estado «{new_state.name}»")
    elif leaving_billing:
        event.billed_at = event.billed_by_id = None          # el historial (quién y cuándo lo facturó) queda en audit_actions
        audit_actions.record(db, staff, "unbilled", "event", event.id, event.name, f"pasó a «{new_state.name}»")
    changed_rows = event_history.record(db, event, history_before, staff, "edit")
    db.commit()
    if changed_rows:
        jobs.kick()                  # despierta el envío del aviso de campos clave (si se encoló alguno)
    if status_changed:
        warmup.kick()                  # entra o sale de «en proceso»: precalentar / soltar instancias YA, sin esperar la hora
    out = _serialize(event)
    if entering_billing:
        out["survey_email"] = _auto_send_survey(db, event, staff, str(request.base_url))
    return out


@router.get("/events/{event_id:int}")          # «:int»: sin él esta ruta (incluida ANTES que calendar) se tragaba GET /events/calendar y el calendario respondía 422
def get_event(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Un evento (mismo formato de la lista), para abrir su edición desde un enlace: /eventos?editar=<id> (correo del aviso de la base final, Fase 5)."""
    return _serialize(get_event_for_staff(event_id, db, staff))


@router.get("/events/{event_id}/staff-users")
def list_event_staff(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))
):
    """digitador + cliente autorizados para ESTE evento."""
    get_event_for_staff(event_id, db, staff)          # 0C (N2/A7): el evento debe existir y ser accesible (tenant y pertenencia) para quien lista
    staff_list = (
        db.query(StaffUser)
        .join(EventStaffAuthorization, EventStaffAuthorization.staff_user_id == StaffUser.id)
        .filter(EventStaffAuthorization.event_id == event_id, or_(StaffUser.role.in_(("digitador", "cliente")), StaffUser.event_only.is_(True)))
        .all()
    )
    return [_serialize_staff(s) for s in staff_list]


@router.get("/events/next-code")
def next_event_code(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Código que se propone (en gris) al crear un evento: el siguiente al más alto solo numérico."""
    return {"event_code": event_codes.next_code(db)}


@router.get("/event-contacts/options")
def event_contact_options(tenant_id: str, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Contactos de la cuenta del CRM de un cliente, para elegirlos como contactos del evento (el principal de la cuenta, primero). Vacío si el cliente no tiene cuenta en el CRM."""
    if not db.query(Tenant.id).filter(Tenant.id == tenant_id).first():
        raise HTTPException(status_code=404, detail="Cliente (tenant) no encontrado")
    return {"contacts": event_contacts.crm_options(db, tenant_id)}


@router.get("/events/{event_id}/contacts")
def get_event_contacts(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return {"contacts": event_contacts.list_for(db, event.id), "crm_options": event_contacts.crm_options(db, event.tenant_id)}


@router.put("/events/{event_id}/contacts")
def put_event_contacts(event_id: int, data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Deja la lista de contactos del evento (reemplaza la anterior). Uno principal: recibe el informe final y la encuesta. Queda en `audit_actions` (cantidad; nunca nombres, teléfonos ni correos)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    try:
        rows = event_contacts.replace(db, event, data.get("contacts"))
    except event_contacts.ContactError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit_actions.record(db, staff, "update", "event_contacts", event.id, None, f"evento {event.id}: {len(rows)} contacto(s)")
    db.commit()
    return {"contacts": rows}


@router.get("/events/{event_id}/duplicate-suggestion")
def duplicate_suggestion(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Código y nombre libres para «Duplicar evento» (el usuario puede cambiarlos antes de confirmar)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return event_duplicate.suggest(db, event)


@router.post("/events/{event_id}/duplicate")
def duplicate_event(event_id: int, data: dict = Body(default={}), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Duplica el evento (app/event_duplicate.py): nuevo código y nombre «… (copia)», todo lo configurado y las personas, sin la historia. Coordinador+ (igual que crear eventos).
    Queda en `audit_actions` (ids de evento; nunca nombres de personas)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    try:
        new = event_duplicate.duplicate(db, event, staff, event_code=str(data.get("event_code") or "").strip() or None, name=str(data.get("name") or "").strip() or None)
        event_contacts.copy_to(db, event.id, new.id)                 # los mismos contactos del cliente (con su principal)
        crm_link.link_new_event(db, staff, new)                      # como al crear un evento a mano: queda su oportunidad ganada en el CRM (si el CRM está encendido)
        audit_actions.record(db, staff, "create", "event", new.id, None, f"duplicado del evento {event.id}")
        db.commit()
    except et.TransferError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": new.id, "event_code": new.event_code, "name": new.name, "message": f"Evento duplicado: «{new.name}» ({new.event_code})."}


def can_manage_event_only(staff: StaffUser) -> bool:
    """Crear y quitar coordinadores temporales: comercial, admin o super admin (un coordinador, ni siquiera uno temporal, no crea otros coordinadores)."""
    return bool(effective_roles(staff) & {"comercial", "admin", "super_admin"})


def _create_temp_coordinator(event_id: int, data: EventStaffIn, db: Session, staff: StaffUser) -> dict:
    """Coordinador temporal (16-nov-2026, app/event_only.py): rol `coordinador` con `event_only`, autorizado SOLO para este evento. Usuario y contraseña los genera el servidor y se entregan UNA vez en esta
    respuesta (la contraseña no se guarda en claro ni va por correo). Queda en `audit_actions` (ids; nunca el usuario)."""
    if not can_manage_event_only(staff):
        raise HTTPException(status_code=403, detail="Solo una comercial, un administrador o el super administrador crea coordinadores temporales")
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    if event.status == "finalizado" or event.archived_at is not None:
        raise HTTPException(status_code=400, detail="Este evento ya finalizó o está archivado: no se le pueden agregar coordinadores temporales")
    if not (data.full_name or "").strip():
        raise HTTPException(status_code=400, detail="Escribe el nombre de la persona")
    username = temp_client.new_username(lambda n: db.query(StaffUser.id).filter(StaffUser.username == n).first() is not None, prefix=event_only.USER_PREFIX)
    password = temp_client.new_password(username)
    new_user = StaffUser(username=username, password_hash=hash_password(password), full_name=data.full_name.strip(), role="coordinador", event_only=True,
                         tenant_id=event.tenant_id, created_by_id=staff.id, must_change_password=False)
    db.add(new_user)
    db.flush()
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=new_user.id, authorized_by_id=staff.id))
    audit_actions.record(db, staff, "create", "event_only_coordinator", new_user.id, None, f"evento {event.id}: coordinador temporal creado")
    db.commit()
    return {**_serialize_staff(new_user), "credentials": {"username": username, "password": password}, "credentials_mail": "disabled"}


@router.post("/events/{event_id}/staff-users")
def create_event_staff(
    event_id: int, data: EventStaffIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    """Crea una cuenta digitador o cliente y la autoriza para ESTE evento en un solo paso — no
    queda visible en /admin/staff como cuenta 'suelta' sin asociar.

    Sprint 2.4 (2026-09-16, pedido explícito): las dos excepciones que NO siguen la jerarquía
    simple de STAFF_ROLES (ver models.py) se codifican a mano acá:
    - 'cliente' exige comercial+ (antes admin+ solamente — comercial ahora también puede).
    - 'digitador' excluye explícitamente a 'comercial', aunque en la jerarquía quede "por encima"
      de coordinador — comercial gestiona clientes/eventos, no cuentas temporales de operación.
    Fase 15 (doble rol coordinador+comercial): ambas excepciones se evalúan sobre effective_roles,
    no sobre `staff.role` a secas — alguien coordinador+comercial SÍ puede crear digitador (porque
    también es coordinador de verdad), la exclusión es solo para quien es comercial pura."""
    from app import localmode
    if localmode.is_local_server():          # F5-9 A-12 (regla de Juan David, 9-nov-2026): el servidor local NUNCA crea cuentas; se crean en la nube antes de llevar el evento
        raise HTTPException(status_code=403, detail=localmode.ACCOUNTS_ONLY_CLOUD)
    if data.temp_coordinator:
        return _create_temp_coordinator(event_id, data, db, staff)
    if data.role == "cliente":
        # 2026-11-05 (pedido de Juan David): ya no se crean cuentas «cliente» temporales de evento; para compartir estadísticas están los enlaces con vencimiento (/ver/e/{token}, stats_links.py). Las cuentas cliente existentes y el cliente de FORMULARIO (/mi-formulario) no se tocan.
        raise HTTPException(status_code=400, detail="Ya no se crean cuentas de cliente para el evento. Para compartir las estadísticas usa un enlace con vencimiento.")
    if data.role != "digitador":
        raise HTTPException(status_code=400, detail="Rol inválido (debe ser 'digitador')")
    if data.role == "digitador" and effective_roles(staff).issubset({"comercial"}):
        raise HTTPException(status_code=403, detail="Un comercial no puede crear cuentas digitador")

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    if data.client:          # 12-nov-2026: cliente temporal = digitador (mismos permisos) con usuario y contraseña aleatorios; se entregan UNA vez en esta respuesta y no llevan correo
        if not (data.full_name or "").strip():
            raise HTTPException(status_code=400, detail="Escribe el nombre de la persona del cliente")
        username = temp_client.new_username(lambda n: db.query(StaffUser.id).filter(StaffUser.username == n).first() is not None)
        password = temp_client.new_password(username)
        new_user = StaffUser(username=username, password_hash=hash_password(password), full_name=data.full_name.strip(), role="digitador", client_temp=True,
                             tenant_id=event.tenant_id, created_by_id=staff.id, must_change_password=False)
        db.add(new_user)
        db.flush()
        db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=new_user.id, authorized_by_id=staff.id))
        db.commit()
        return {**_serialize_staff(new_user), "credentials": {"username": username, "password": password}, "credentials_mail": "disabled"}
    if not data.username:
        raise HTTPException(status_code=400, detail="Escribe el usuario (la cédula)")
    if db.query(StaffUser).filter(StaffUser.username == data.username).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese usuario")
    password = (data.password or "").strip() or data.username        # decisión de Juan David (6-nov-2026): la cuenta temporal de digitador usa su cédula como contraseña; no aplica la política de contraseña segura
    if password != data.username:
        problem = security.password_problem(password, data.username, strict=True)         # 0C (C11): una contraseña DISTINTA de la cédula, puesta por un administrador, sí cumple la política estricta
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    # 'digitador'/'cliente' son las dos excepciones del teléfono obligatorio+único (Sprint 2.4
    # Fase 4) — acá sigue siendo opcional, pero si se manda uno, igual debe ser único.
    phone = (data.phone or "").strip() or None
    if phone and db.query(StaffUser).filter(StaffUser.phone == phone).first():
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese teléfono")

    raw_email = (data.email or "").strip()
    if raw_email and not staff_credentials.valid_email(raw_email):
        raise HTTPException(status_code=400, detail="Correo con formato inválido")
    new_user = StaffUser(
        username=data.username, password_hash=hash_password(password),
        full_name=data.full_name, role=data.role, tenant_id=event.tenant_id, created_by_id=staff.id,
        phone=phone, email=staff_credentials.valid_email(raw_email) or None,
        must_change_password=security.must_change_on_set_by_other(data.role),       # Fase 4: el cliente de evento cambia la contraseña inicial; el digitador temporal no
    )
    db.add(new_user)
    db.flush()  # para obtener new_user.id antes de commitear
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=new_user.id, authorized_by_id=staff.id))
    mail_queued = staff_credentials.enqueue_for_event(db, new_user, "created", event)          # Fase 4: un correo (sin contraseña) con el evento y el enlace de ingreso; respeta el interruptor del evento
    db.commit()
    if mail_queued:
        jobs.kick()
    return {**_serialize_staff(new_user), "credentials_mail": "queued" if mail_queued else ("disabled" if not event.staff_mail_enabled else "no_email")}


@router.post("/events/{event_id}/staff-users/assign-existing")
def assign_existing_staff(
    event_id: int, data: AssignExistingIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("comercial")),
):
    """Autoriza una cuenta YA existente para ESTE evento. Digitadores: admin+. Coordinadores temporales
    (los que quedaron «creados» al terminar su evento): comercial+, buscándolos. Para una cuenta nueva usar POST .../staff-users."""
    get_event_for_staff(event_id, db, staff)          # 0C (N2): el evento debe existir y ser accesible para quien asigna
    target = db.query(StaffUser).filter(
        StaffUser.id == data.staff_id, or_(StaffUser.role.in_(("digitador", "cliente")), StaffUser.event_only.is_(True))
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.event_only:
        if not can_manage_event_only(staff):
            raise HTTPException(status_code=403, detail="No tienes permiso para asignar coordinadores temporales")
        if not target.is_active or target.archived_at is not None:
            raise HTTPException(status_code=400, detail="Esta cuenta está inactiva o archivada")
        ev = db.get(Event, event_id)
        if ev.status == "finalizado" or ev.archived_at is not None:
            raise HTTPException(status_code=400, detail="No se puede asignar a un evento finalizado o archivado")
    else:
        if not effective_roles(staff) & {"admin", "super_admin"}:
            raise HTTPException(status_code=403, detail="Solo un administrador asigna cuentas digitador existentes")
        if target.role == "cliente":
            raise HTTPException(status_code=400, detail="Ya no se asignan cuentas de cliente a un evento. Para compartir las estadísticas usa un enlace con vencimiento.")
    assert_same_tenant(staff, target.tenant_id, "Usuario no encontrado")          # P5: limitado a su cliente, solo asigna cuentas de su cliente
    existing = db.query(EventStaffAuthorization).filter_by(staff_user_id=target.id, event_id=event_id).first()
    if existing:
        return {"message": "Ya estaba autorizado para este evento"}
    db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=target.id, authorized_by_id=staff.id))
    event = db.get(Event, event_id)
    mail_queued = False if target.event_only else staff_credentials.enqueue_for_event(db, target, "assigned", event)          # Fase 4: aviso (una sola vez por persona y evento); a los coordinadores temporales nunca por correo
    db.commit()
    if mail_queued:
        jobs.kick()
    return {**_serialize_staff(target), "credentials_mail": "queued" if mail_queued else ("disabled" if not event.staff_mail_enabled else "no_email")}


# ---------------------------------------------------------------- Usuarios temporales: Excel y borrado en bloque (6-nov-2026)
STAFF_IMPORT_MAX_ROWS = 200          # D5/I5: con bcrypt de 10 rondas (~60-80 ms en Cloud Run) caben de sobra en los 60 s de una petición
STAFF_IMPORT_MAX_BYTES = 2 * 1024 * 1024
STAFF_IMPORT_MAX_COLS = 30           # solo se leen las primeras 30 columnas (la plantilla trae 3)
STAFF_IMPORT_BCRYPT_ROUNDS = 10      # estas cuentas usan la cédula como contraseña (decisión de Juan David): más rondas no las protegen y sí agotan la petición
STAFF_NAME_MAX = 120


def _temp_password_hash(ident: str) -> str:
    import bcrypt
    return bcrypt.hashpw(ident.encode(), bcrypt.gensalt(rounds=STAFF_IMPORT_BCRYPT_ROUNDS)).decode()


def _can_manage_temp(staff: StaffUser) -> None:
    if effective_roles(staff).issubset({"comercial"}):
        raise HTTPException(status_code=403, detail="Un comercial no puede administrar cuentas digitador")


def _assert_can_manage_target(staff: StaffUser, target: StaffUser) -> None:
    """Quién puede quitar o eliminar una cuenta temporal del evento: los digitadores, como siempre (`_can_manage_temp`); un coordinador temporal, solo una comercial, un admin o el super admin."""
    if target.event_only:
        if not can_manage_event_only(staff):
            raise HTTPException(status_code=403, detail="Solo una comercial, un administrador o el super administrador administra coordinadores temporales")
        return
    _can_manage_temp(staff)


@router.get("/events/{event_id}/staff-users/template")
def staff_users_template(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Plantilla de Excel para asignar digitadores al evento: Identificación, Nombres y Apellidos."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from app import heavy
    _can_manage_temp(staff)
    get_event_for_staff(event_id, db, staff)
    wb = Workbook()
    ws = wb.active
    ws.title = "Usuarios"
    ws.append(["Identificación", "Nombres", "Apellidos", "Correo (opcional)"])
    for c in ws[1]:
        c.font = Font(color="FFFFFF", bold=True)
        c.fill = PatternFill(start_color="0A0E2E", end_color="0A0E2E", fill_type="solid")
        c.alignment = Alignment(horizontal="center")
    ws.append(["1012345678", "María Camila", "Pérez Gómez", "maria@ejemplo.com"])
    ws.append(["80123456", "Juan Carlos", "Rojas Díaz", ""])
    for col, w in (("A", 20), ("B", 28), ("C", 28), ("D", 32)):
        ws.column_dimensions[col].width = w
    note = wb.create_sheet("Instrucciones")
    for line in ("Una persona por fila. Borra las dos filas de ejemplo antes de subir el archivo.",
                 "Identificación: la cédula. Será el usuario y también la contraseña de la cuenta.",
                 "Correo (opcional): si lo pones, la persona recibe por correo cómo ingresar y los datos del evento (sin contraseñas).",
                 "Si la cédula ya tiene cuenta, solo se asigna a este evento. Si no, se crea y se asigna.",
                 f"Máximo {STAFF_IMPORT_MAX_ROWS} personas por archivo."):
        note.append([line])
    note.column_dimensions["A"].width = 100
    return heavy.workbook_response(wb, "Plantilla_usuarios_evento.xlsx")


@router.post("/events/{event_id}/staff-users/import")
def import_event_staff(event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Asigna digitadores a este evento desde un Excel (Identificación, Nombres, Apellidos). Cédula nueva → crea la cuenta (usuario y contraseña = cédula) y la asigna; cédula que ya tenía
    cuenta de digitador del mismo cliente → solo la asigna. Una cédula que ya es otra cosa (otro rol u otro cliente) no se toca y se informa. Devuelve cantidades y los motivos por fila (sin contraseñas)."""
    from app import localmode
    if localmode.is_local_server():          # F5-9 A-12 (regla de Juan David, 9-nov-2026): el servidor local NUNCA crea cuentas; se crean en la nube antes de llevar el evento
        raise HTTPException(status_code=403, detail=localmode.ACCOUNTS_ONLY_CLOUD)
    import re as _re
    from app import heavy, safe_limits
    from app.inputcheck import check_text
    _can_manage_temp(staff)
    event = get_event_for_staff(event_id, db, staff)
    content = file.file.read(STAFF_IMPORT_MAX_BYTES + 1)
    if len(content) > STAFF_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=400, detail="El archivo es muy grande (máximo 2 MB)")
    if not content.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo. Usa la plantilla en formato .xlsx")
    try:          # D2/I1: zip revisado, dimensión declarada ignorada, columnas y filas con tope; nunca la hoja entera en memoria
        with heavy.heavy_slot():
            rows = safe_limits.xlsx_rows(content, STAFF_IMPORT_MAX_ROWS, STAFF_IMPORT_MAX_COLS, is_blank=lambda r: all(v in (None, "") for v in r))
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=400, detail=exc.message)
    if not rows:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    def norm(v):
        return "".join(ch for ch in unicodedata.normalize("NFD", str(v or "").strip().lower()) if unicodedata.category(ch) != "Mn")
    header = [norm(c) for c in rows[0]]
    def col(*names):
        for i, h in enumerate(header):
            if h in names:
                return i
        return None
    c_id = col("identificacion", "cedula", "id", "documento", "usuario")
    c_first = col("nombres", "nombre")
    c_last = col("apellidos", "apellido")
    c_mail = col("correo", "correo (opcional)", "email", "correo electronico")
    if c_id is None:
        raise HTTPException(status_code=400, detail="Falta la columna «Identificación». Descarga la plantilla y úsala tal cual")
    data_rows = rows[1:]          # xlsx_rows ya quitó las vacías y cortó en STAFF_IMPORT_MAX_ROWS

    created, assigned_existing, already, mails, problems, seen = 0, 0, 0, 0, [], set()
    for n, r in enumerate(data_rows, start=2):
        def cell(i):
            return str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else ""
        raw_id = r[c_id] if c_id < len(r) else None
        ident = (str(int(raw_id)) if isinstance(raw_id, float) and raw_id == int(raw_id) else str(raw_id or "")).strip()
        ident = _re.sub(r"[\s.]", "", ident)
        full_name = " ".join(x for x in (cell(c_first), cell(c_last)) if x)[:STAFF_NAME_MAX].strip() or None      # D4: mismo tope y misma regla de texto que el resto de la app
        try:
            check_text(full_name, "El nombre")
        except ValueError as exc:
            problems.append({"row": n, "detail": str(exc)})
            continue
        if not ident:
            problems.append({"row": n, "detail": "Sin identificación"})
            continue
        try:
            check_username(ident)
        except ValueError:
            problems.append({"row": n, "detail": "La identificación solo admite letras, números y . _ @ - (3 a 64 caracteres)"})
            continue
        if ident in seen:
            problems.append({"row": n, "detail": "Identificación repetida en el archivo"})
            continue
        seen.add(ident)
        target = db.query(StaffUser).filter(StaffUser.username == ident).first()
        is_new = target is None
        mail_cell = cell(c_mail)
        mail_ok = staff_credentials.valid_email(mail_cell)
        if mail_cell and not mail_ok:
            problems.append({"row": n, "detail": "Correo con formato inválido (la fila no se cargó)"})
            continue
        if is_new:
            target = StaffUser(username=ident, password_hash=_temp_password_hash(ident), full_name=full_name, role="digitador", tenant_id=event.tenant_id, created_by_id=staff.id, email=mail_ok or None)
            db.add(target)
            db.flush()          # autoflush=False: hace falta el id antes de la autorización
        elif target.role != "digitador" or (target.tenant_id != event.tenant_id and not (effective_roles(staff) & {"admin", "super_admin"})):
            problems.append({"row": n, "detail": "Esa identificación ya es una cuenta que no se puede asignar aquí"})
            continue
        elif db.query(EventStaffAuthorization).filter_by(staff_user_id=target.id, event_id=event_id).first():
            already += 1
            continue
        if not is_new and not target.is_active:
            if not (effective_roles(staff) & {"admin", "super_admin"}):          # ronda de seguridad F4: un coordinador no reactiva con un Excel lo que un administrador desactivó o archivó
                problems.append({"row": n, "detail": "Esa cuenta está desactivada: solo un administrador puede reactivarla"})
                continue
            target.is_active = True          # un digitador que quedó desactivado (no se pudo borrar, D3) lo reactiva un administrador al asignarlo de nuevo
        if not is_new and mail_ok and not (target.email or "").strip():
            target.email = mail_ok          # a una cuenta que ya existía solo se le completa el correo si no tenía; nunca se reemplaza
        db.add(EventStaffAuthorization(event_id=event_id, staff_user_id=target.id, authorized_by_id=staff.id))
        if staff_credentials.enqueue_for_event(db, target, "created" if is_new else "assigned", event):
            mails += 1
        if is_new:
            created += 1
        else:
            assigned_existing += 1
    db.commit()
    if mails:
        jobs.kick()
    return {"mails_queued": mails, "created": created, "assigned_existing": assigned_existing, "already": already, "problems": problems[:100], "problems_total": len(problems)}


def _delete_event_accounts(db: Session, actor: StaffUser, event: Event, ids: list) -> dict:
    """Elimina de verdad las cuentas de digitador `ids` de este evento (lo usan «Eliminar los usuarios temporales» y «Eliminar cuenta» de una sola). A cada una se le quita el acceso a este evento
    y a sus equipos de impresión y luego se borra la cuenta soltando lo que la menciona (app/staff_refs.py). Dos excepciones, sin borrar: (1) una cuenta que además está asignada a OTRO evento solo se
    quita de este; (2) una cuenta con registros que no se pueden soltar (p. ej. una carga masiva suya) queda ARCHIVADA y desactivada. El compromiso firmado NO impide borrar: su evidencia queda en
    el evento sin la cuenta (0102). No hace commit; deja UN registro en `audit_actions` con los totales (nunca los usuarios: el del digitador es su cédula)."""
    from app import sessions, staff_refs
    deleted, kept, only_unassigned = 0, 0, 0
    for sid in ids:
        if sid == actor.id:
            continue
        elsewhere = db.query(EventStaffAuthorization).filter(EventStaffAuthorization.staff_user_id == sid, EventStaffAuthorization.event_id != event.id).count()
        db.query(EventStaffAuthorization).filter_by(event_id=event.id, staff_user_id=sid).delete()
        db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=sid).delete()
        db.query(PrintRoute).filter_by(event_id=event.id, staff_user_id=sid).delete()
        db.query(PrintRoute).filter_by(event_id=event.id, printer_staff_id=sid).update({"printer_staff_id": None})
        if elsewhere:
            only_unassigned += 1
            continue
        target = db.get(StaffUser, sid)
        if target is None:
            continue
        db.query(EventStaffAuthorization).filter(EventStaffAuthorization.authorized_by_id == sid).update({"authorized_by_id": None})
        db.query(AccessLog).filter(AccessLog.registered_by_staff_id == sid).update({"registered_by_staff_id": None})
        db.query(StaffUser).filter(StaffUser.created_by_id == sid).update({"created_by_id": None})
        sessions.revoke_all(target)
        if staff_refs.delete_or_deactivate(db, target) == "deleted":
            deleted += 1
        else:
            if target.archived_at is None:
                target.archived_at, target.archived_by_id = utcnow(), actor.id
            target.is_active = False
            kept += 1
    audit_actions.record(db, actor, "delete", "staff_user", f"evento {event.id}", None, f"evento {event.id}: {deleted} cuenta(s) de digitador eliminada(s), {kept} archivada(s) por tener registros, {only_unassigned} solo quitada(s) del evento")
    return {"deleted": deleted, "kept_archived": kept, "only_unassigned": only_unassigned}


@router.post("/events/{event_id}/staff-users/purge-temporary")
def purge_event_staff(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """«Eliminar los usuarios temporales» de este evento: BORRA de verdad las cuentas de digitador (decisión de Juan David, 8-nov-2026; antes solo se archivaban). Ver `_delete_event_accounts`."""
    _can_manage_temp(staff)
    event = get_event_for_staff(event_id, db, staff)
    ids = [r[0] for r in db.query(EventStaffAuthorization.staff_user_id).join(StaffUser, StaffUser.id == EventStaffAuthorization.staff_user_id)
           .filter(EventStaffAuthorization.event_id == event.id, StaffUser.role == "digitador")]
    out = _delete_event_accounts(db, staff, event, ids)
    db.commit()
    return out


@router.post("/events/{event_id}/staff-users/{staff_id}/delete-account")
def delete_event_staff_account(event_id: int, staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """«Eliminar cuenta» de UN digitador temporal de este evento (la misma regla que eliminar a todos). Solo digitadores asignados a este evento; el resto de roles no se borran desde aquí."""
    event = get_event_for_staff(event_id, db, staff)          # 0C (N2)
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    auth = db.query(EventStaffAuthorization).filter_by(event_id=event.id, staff_user_id=staff_id).first()
    if not target or not auth or not (target.role == "digitador" or target.event_only):
        raise HTTPException(status_code=404, detail="Esa cuenta de digitador no está en este evento")
    _assert_can_manage_target(staff, target)
    out = _delete_event_accounts(db, staff, event, [staff_id])
    db.commit()
    return out


@router.delete("/events/{event_id}/staff-users/{staff_id}")
def revoke_event_staff(
    event_id: int, staff_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("coordinador")),
):
    """Revoca el acceso de un digitador/cliente a ESTE evento y SOLO a este (E-N1, 0C). Su cuenta, su sesión y sus autorizaciones en otros eventos no se tocan (desactivar la cuenta es otra acción: /staff/{id}/deactivate).
    Se quitan además los restos por evento: su equipo de impresión registrado aquí, su ruta de impresión y las rutas de otros que imprimían en su equipo."""
    event = get_event_for_staff(event_id, db, staff)          # 0C (N2)
    target = db.query(StaffUser).filter(StaffUser.id == staff_id).first()
    auth = db.query(EventStaffAuthorization).filter_by(event_id=event.id, staff_user_id=staff_id).first()
    if not target or not auth or not (target.role in ("digitador", "cliente") or target.event_only):
        raise HTTPException(status_code=404, detail="Esa cuenta no tiene acceso a este evento")      # coordinador+ no se autoriza por evento: no hay nada que revocar aquí
    _assert_can_manage_target(staff, target)          # P7: una comercial pura no administra digitadores; los coordinadores temporales solo los administra una comercial o más
    audit_actions.record(db, staff, "revoke", "event_staff_access", auth.id, None, f"evento {event.id}: acceso de la cuenta {staff_id} revocado")          # nunca el usuario (el del digitador es su cédula)
    db.delete(auth)
    db.query(PrintDevice).filter_by(event_id=event.id, staff_user_id=staff_id).delete()
    db.query(PrintRoute).filter_by(event_id=event.id, staff_user_id=staff_id).delete()
    db.query(PrintRoute).filter_by(event_id=event.id, printer_staff_id=staff_id).update({"printer_staff_id": None})      # quien imprimía en su equipo vuelve a imprimir en el propio
    db.commit()
    remaining = db.query(EventStaffAuthorization).filter_by(staff_user_id=staff_id).count()
    return {"message": "Acceso a este evento revocado", "other_events": remaining}


@router.delete("/events/{event_id}")
def delete_event(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))
):
    """Borrado DEFINITIVO — solo super_admin y solo de un evento ya ARCHIVADO (Fase 3, 7-nov-2026: lo normal es archivar; coordinador+ avanza el estado del evento vía PATCH status,
    ver EVENT_STATUSES en models.py: creado -> en_proceso -> finalizado). Queda registrado en audit_actions (quién, cuándo, id y nombre; sin datos personales).
    Antes de borrar el Event hay que soltar lo que le apunta por FK: las EventStaffAuthorization de
    este evento no tienen sentido sin él (se borran), los AccessLog ya generados son historial
    real (se conservan, solo se les quita la referencia al evento), y los EventAttendee tampoco
    tienen sentido sin el evento — a diferencia de AccessLog, `EventAttendee.event_id` es NOT
    NULL (no se puede dejar en NULL), así que se borran directamente (bug real encontrado en
    testing 2026-09-21: EventAttendee se agregó en la migración 0008 después de escribir este
    endpoint y nunca se actualizó aquí, causaba ForeignKeyViolation/500 en cualquier evento con
    al menos una persona registrada/precargada)."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    if event.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva el evento; el borrado definitivo solo aplica a eventos archivados")
    audit_actions.record(db, staff, "delete", "event", event.id, event.name, f"cliente {event.tenant_id}")

    db.query(BulkJob).filter(BulkJob.event_id == event_id).delete()
    db.query(EventStatusChange).filter(EventStatusChange.event_id == event_id).delete()
    db.query(EventChangeLog).filter(EventChangeLog.event_id == event_id).delete()
    person_history.delete_for_event(db, event_id)          # historial de datos modificados de las personas del evento
    for _form in db.query(WebForm).filter(WebForm.event_id == event_id).all():
        delete_form_rows(db, _form)
    db.query(RouletteDraw).filter(RouletteDraw.event_id == event_id).delete()
    db.query(RouletteConfig).filter(RouletteConfig.event_id == event_id).delete()
    db.query(EventStaffAuthorization).filter(EventStaffAuthorization.event_id == event_id).delete()
    db.query(EventAttendee).filter(EventAttendee.event_id == event_id).delete()
    # Lo que se agregó después del primer arreglo de este endpoint y también apunta al evento por FK
    # (mismo tipo de bug: sin esto, borrar un evento con plantilla de escarapela, parámetros,
    # impresiones, documentos o gastos daba ForeignKeyViolation).
    db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event_id).delete()
    db.query(EventFieldConfig).filter(EventFieldConfig.event_id == event_id).delete()
    db.query(PrintLog).filter(PrintLog.event_id == event_id).delete()
    delete_event_files(db, event_id)
    delete_event_modules(db, event_id)
    queue_svc.delete_event_data(db, event_id)
    db.query(AccessLog).filter(AccessLog.event_id == event_id).update({"event_id": None})
    db.delete(event)
    db.commit()
    return {"message": "Evento eliminado permanentemente"}


# ------------------------------------------------------------------ archivar / restaurar (Fase 3, oleada 2)
def _event_for_admin(db: Session, staff: StaffUser, event_id: int) -> Event:
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    return event


@router.post("/events/{event_id}/archive")
def archive_event(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Archivar = ocultar de las listas y dejar el evento de solo lectura (sin registro ni formularios públicos). Solo eventos FINALIZADOS. No borra nada; un administrador lo restaura."""
    event = _event_for_admin(db, staff, event_id)
    reason = event_archive.block_reason(event)
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    event_archive.archive(db, event, staff)
    db.commit()
    formsvc.invalidate_public_cache()
    return _serialize(event)


@router.post("/events/{event_id}/restore")
def restore_event(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Restaura un evento archivado. Si lo archivó el Job a los 90 días (L7), solo lo restaura un super_admin. Los formularios públicos siguen cerrados (se reabren a mano)."""
    event = _event_for_admin(db, staff, event_id)
    if event.archived_at is None:
        raise HTTPException(status_code=400, detail="El evento no está archivado")
    if event.archived_by_id is None and staff.role != "super_admin":
        raise HTTPException(status_code=403, detail="Este evento se archivó solo a los 90 días de cerrado: solo un super administrador puede restaurarlo")
    event_archive.restore(db, event, staff)
    db.commit()
    return _serialize(event)


@router.post("/events/{event_id}/restore-data")
def restore_event_data(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))):
    """L7: desarchiva la BASE DE DATOS de un evento (la archivó el Job a los 90 días). Solo super_admin; queda en audit_actions. No reabre los formularios públicos (se hace a mano)."""
    event = _event_for_admin(db, staff, event_id)
    if event.data_archived_at is None:
        raise HTTPException(status_code=400, detail="La base de datos de este evento no está archivada")
    event_archive.restore_data(db, event, staff)
    db.commit()
    return _serialize(event)


# ------------------------------------------------------------------ devolver un evento «en curso» a «creado» (pedido B, 1-nov-2026)
def _revert_counts(db: Session, event_id: int) -> dict:
    return {"attendees": db.query(func.count(EventAttendee.id)).filter(EventAttendee.event_id == event_id, EventAttendee.user_id != testperson.TEST_ID).scalar() or 0,
            "access_logs": db.query(func.count(AccessLog.id)).filter(AccessLog.event_id == event_id, AccessLog.record_type != "Actualizado", AccessLog.user_id != testperson.TEST_ID).scalar() or 0}


@router.get("/events/{event_id}/revert-to-created")
def revert_to_created_info(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Lo que la ventana de confirmación muestra ANTES de devolver el evento a «Creado»: nombre, cuántas personas e ingresos tiene y si se puede. Solo lectura."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    return {"name": event.name, "status": event.status, "allowed": event.status == "en_proceso", **_revert_counts(db, event_id),
            "sync_days": status_changes.SYNC_AFTER_REVERT.days}


class RevertIn(BaseModel):
    reason: Optional[str] = None


@router.post("/events/{event_id}/revert-to-created")
def revert_to_created(event_id: int, data: Optional[RevertIn] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Devuelve un evento «en curso» a «creado» (solo admin y super_admin). NO borra nada (ni personas, ni ingresos, ni consentimientos): solo cambia el estado y deja el rastro (quién, cuándo,
    motivo opcional y cuántas personas e ingresos tenía en `event_status_changes`). Mientras esté en «creado» el quiosco no registra ni reconoce; los quioscos sin red pueden sincronizar lo
    que registraron antes del cambio durante 7 días (`app/status_changes.py`). La cuenta de 7 días de la purga biométrica NO corre: solo cuenta desde «finalizado». Es el ÚNICO camino:
    el PATCH sigue rechazando este retroceso. De «creado» a «en curso» se vuelve con el PATCH de siempre."""
    event = db.query(Event).filter(Event.id == event_id).with_for_update().first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    if event.status != "en_proceso":
        raise HTTPException(status_code=409, detail="Solo un evento «En proceso» se puede devolver a «Creado»" + (" (los finalizados no se tocan)." if event.status == "finalizado" else "."))
    reason = ((data.reason if data else None) or "").strip()[:500] or None
    counts = _revert_counts(db, event_id)
    history_before = event_history.snapshot(db, event)
    event.status = "creado"
    new_state = event_rules.default_state(db, "creado")
    if new_state is not None:
        event.state_id = new_state.id
    db.add(EventStatusChange(event_id=event.id, tenant_id=event.tenant_id, staff_user_id=staff.id, staff_username=staff.username, from_status="en_proceso", to_status="creado", reason=reason,
                             attendees_count=counts["attendees"], access_logs_count=counts["access_logs"], at=utcnow()))
    event_history.record(db, event, history_before, staff, "state")
    db.commit()
    log.info("evento %s devuelto a «creado» por el usuario %s (%s personas, %s ingresos)", event.id, staff.id, counts["attendees"], counts["access_logs"])
    warmup.kick()                  # sale de «en proceso»: soltar las instancias precalentadas, como en cualquier cambio de estado
    return {"message": "El evento volvió a «Creado»: el quiosco no registra ni reconoce hasta que vuelva a estar en curso.", "status": "creado", **counts}


@router.get("/events/{event_id}/status-changes")
def list_status_changes(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Historial de retrocesos del evento y cuántos ingresos se sincronizaron sin hora válida (`doubtful`) para poder revisarlos. Sin datos personales."""
    event = db.query(Event).filter(Event.id == event_id).first()          # P5: mismo control de cliente y pertenencia que «Devolver a Creado»
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    assert_event_scope(event, staff, db)
    rows = db.query(EventStatusChange).filter(EventStatusChange.event_id == event_id).order_by(EventStatusChange.at.desc(), EventStatusChange.id.desc()).all()
    doubtful = db.query(func.count(AccessLog.id)).filter(AccessLog.event_id == event_id, AccessLog.doubtful_reason.isnot(None), AccessLog.user_id != testperson.TEST_ID).scalar() or 0
    flagged = db.query(SystemEvent.kind, SystemEvent.detail).filter(SystemEvent.ref == str(event_id), SystemEvent.kind.in_(list(status_changes.CONSENT_FLAGS.values()))).order_by(SystemEvent.id).all()
    consents = {"sin_hora_valida": sum(k == status_changes.CONSENT_FLAGS["no_hour"] for k, _ in flagged), "after_revert": sum(k == status_changes.CONSENT_FLAGS["after"] for k, _ in flagged),
                "entry_ids": [d for _, d in flagged][:200]}          # consentimientos guardados dentro de la ventana y marcados para revisar (UUID del dispositivo; sin datos personales)
    return {"changes": [{"at": r.at.isoformat() + "Z", "by": r.staff_username, "from": r.from_status, "to": r.to_status, "reason": r.reason, "attendees": r.attendees_count, "access_logs": r.access_logs_count}
                        for r in rows], "doubtful": doubtful, "consents": consents}
