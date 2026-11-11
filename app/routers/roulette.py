"""Ruleta / sorteos por evento (Sprint 5).

Dos configuraciones separadas: COMPORTAMIENTO (de dónde salen los candidatos y cómo se elige al ganador) y VISUAL
(cómo se ve la ruleta en la pantalla que ve la gente). La ejecución la dispara un coordinador+ desde su pantalla; la
pantalla de visualización (`/r/<token>`, sin login, para un proyector) consulta por sondeo y anima la ruleta
cuando aparece un sorteo nuevo. El resultado que se revela SIEMPRE es el ya determinado por el modo elegido:
predeterminado a mano en los modos 1-3 y 5a, realmente aleatorio (servidor, `SystemRandom`) solo en 5b y en "todos".

Modos (candidatos = siempre la base ya cargada del evento):
  single_fixed   1. un ganador elegido de antemano
  ordered        2. N ganadores en el orden exacto elegido
  shuffled       3. los mismos N elegidos, en orden aleatorio en cada ejecución
  all            4. todos los asistentes: cada ejecución saca a `batch_size` personas al azar entre quienes aún no
                 han salido en esta ronda (sin repetir) hasta agotarlos; "Reiniciar ronda" empieza de nuevo
  filter_manual  5a. el filtro solo acota la lista visible; el operador elige a mano (como 1-3)
  filter_random  5b. sorteo real: el sistema elige `count` al azar entre quienes cumplen el filtro

Auditoría (decisión: no estaba especificada, pero sin ella el módulo pierde valor): cada ejecución guarda un
`RouletteDraw` con nombre del sorteo, modo, si fue aleatorio real, filtro, ganadores, quién lo ejecutó y cuándo;
se consulta en pantalla y se descarga en Excel.
"""
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from app.timeutil import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.orm import Session

from app import heavy, publicurl, security
from app.auth import get_event_for_staff, require_role
from app import event_archive
from app.database import get_db
from app import testperson
from app.models import AccessLog, Event, EventAttendee, RouletteConfig, RouletteDraw, StaffUser, User
from app.routers.badges import ALLOWED_IMAGE_EXT
from app.storage import badge_asset_key, get_storage
from app.timeutil import to_local, _TZ

router = APIRouter()         # bajo /api (coordinador+)
public_router = APIRouter()  # /r/<token> (sin login)

MODES = ("single_fixed", "ordered", "shuffled", "all", "filter_manual", "filter_random")
_RNG = secrets.SystemRandom()
POOL_SIZE = 300  # nombres que se mandan a la pantalla (la ruleta circular usa hasta 24; el estilo «casino» los recorre todos)
AUTH_MAX_AGE = timedelta(minutes=30)   # una autorización de giro que nadie usa caduca

ALLOWED_FONTS = [
    "Roboto", "Open Sans", "Lato", "Montserrat", "Oswald", "Raleway", "Poppins", "Playfair Display", "Inter",
    "Bebas Neue", "Anton", "Archivo Black", "Pacifico", "Lobster", "Dancing Script", "Merriweather", "Nunito",
    "Ubuntu", "Rubik", "Comfortaa", "Space Grotesk", "Manrope", "Zilla Slab",
]
DEFAULT_STYLE = {
    "title": "¡Sorteo!", "title_font": "Bebas Neue", "title_color": "#FFFFFF",
    "font_family": "Montserrat", "text_color": "#FFFFFF",
    "colors": ["#D4AF37", "#0A0E2E", "#B8941F", "#1B2456", "#E8C766", "#141B47"],
    "background_color": "#0A0E2E", "background_image": "", "logo": "", "pointer_color": "#FF4D6D",
    "winner_bg": "#D4AF37", "winner_color": "#0A0E2E", "spin_seconds": 6,
    "wheel_style": "circular",   # circular | jackpot (columna vertical estilo casino: para muchos nombres)
    # Fase 10 (C), todo dentro de style_json (sin migración):
    "winner_fields": ["entity"],   # datos que salen bajo el nombre del ganador (el nombre siempre sale); ver winner_field_choices()
    "top_images_cfg": [],          # un {height, align} por cada logo/banner de top_images (mismo orden): alto en % del alto de la pantalla y alineación
    "name_scale": 100,             # tamaño del nombre del ganador (% del tamaño base)
    "fields_scale": 150,           # tamaño de los DEMÁS datos (empresa, correo…) (% del tamaño base; antes se veían muy pequeños en el proyector)
    "top_images": [],              # logos/banners arriba de la pantalla (hasta MAX_TOP_IMAGES), ruta "<cliente>/<archivo>" como el logo
    "spin_mode": "fixed",          # fixed = dura `spin_seconds` · manual = giro libre: un clic en «Girar» lo inicia y otro en «Detener» lo frena
}
MAX_TOP_IMAGES = 4
MAX_WINNER_FIELDS = 8
SPIN_MODES = ("fixed", "manual")
FIXED_WINNER_FIELDS = (("entity", "Empresa"), ("email", "Correo"), ("role", "Cargo"), ("opt_1", "Tipo de asistente"))     # la ciudad y demás datos propios del evento salen de sus campos opcionales con nombre
MAX_QUEUE_STEPS = 20           # sorteos en fila (11-nov-2026): cuántos se pueden dejar preparados con una sola autorización
DEFAULT_BEHAVIOR = {"queue": [], "mode": "single_fixed", "winners": [], "count": 1, "batch_size": 1,
                    "filter": {"conditions": []}, "exclude_previous_winners": True, "all_reset_at": None}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# ------------------------------------------------------------------ utilidades
def _norm(text) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "").lower()) if unicodedata.category(c) != "Mn").strip()


def _full_name(u) -> str:
    return f"{u.first_name or ''} {u.last_name or ''}".strip()


def _get_config(db: Session, event: Event, create=True) -> Optional[RouletteConfig]:
    cfg = db.query(RouletteConfig).filter_by(event_id=event.id).first()
    if not cfg and create:
        cfg = RouletteConfig(event_id=event.id, behavior_json=json.dumps(DEFAULT_BEHAVIOR), style_json=json.dumps(DEFAULT_STYLE))
        db.add(cfg)
        db.commit()
    return cfg


def _behavior(cfg) -> dict:
    return {**DEFAULT_BEHAVIOR, **(json.loads(cfg.behavior_json) if cfg.behavior_json else {})}


def _style(cfg) -> dict:
    return {**DEFAULT_STYLE, **(json.loads(cfg.style_json) if cfg.style_json else {})}


def candidates(db: Session, event: Event) -> list:
    """La base del evento (EventAttendee ∪ quienes ya tienen un registro real), con lo necesario para filtrar."""
    att = {a.user_id: a for a in db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.user_id != testperson.TEST_ID)}
    logs = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.record_type != "Actualizado", AccessLog.user_id != testperson.TEST_ID).order_by(AccessLog.timestamp).all()
    first_log = {}
    for lg in logs:
        first_log.setdefault(lg.user_id, lg.timestamp)
    ids = set(att) | set(first_log)
    if not ids:
        return []
    out = []
    for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(ids)).order_by(User.last_name, User.first_name):
        a = att.get(u.id)
        out.append({
            "id": u.id, "name": _full_name(u), "entity": u.entity or "", "role": u.role or "", "opt_1": u.opt_1 or "",
            "email": u.email or "",
            "extras": u.get_extras(), "categories": a.get_categories() if a else [],
            "registered_at": first_log.get(u.id), "status": "registrado" if u.id in first_log else "no_registrado",
        })
    return out


def _local_to_utc(value: str) -> datetime:
    """'2026-10-01T14:30' (hora local del evento) -> datetime naive en UTC."""
    local = datetime.fromisoformat(value).replace(tzinfo=_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _match(person: dict, cond: dict) -> bool:
    field, op, value = cond.get("field"), cond.get("op", "equals"), cond.get("value")
    if field == "status":
        return person["status"] == value
    if field in ("registered_after", "registered_before"):
        when = person["registered_at"]
        if not when or not value:
            return False
        limit = _local_to_utc(value)
        return when >= limit if field == "registered_after" else when <= limit
    if field == "category":
        return any(_norm(c) == _norm(value) for c in person["categories"])
    if field in ("entity", "role", "opt_1"):
        target = person[field]
    elif isinstance(field, str) and field.startswith("extra:"):
        target = person["extras"].get(field[6:], "")
    else:
        raise HTTPException(status_code=400, detail=f"Campo de filtro no válido: {field}")
    a, b = _norm(target), _norm(value)
    return (b in a) if op == "contains" else (a == b)


def apply_filter(people: list, filt: Optional[dict]) -> list:
    conds = (filt or {}).get("conditions") or []
    return [p for p in people if all(_match(p, c) for c in conds)]


def _previous_winner_ids(db: Session, event: Event, since: Optional[datetime] = None, mode: Optional[str] = None) -> set:
    q = db.query(RouletteDraw).filter(RouletteDraw.event_id == event.id)
    if mode:
        q = q.filter(RouletteDraw.mode == mode)
    if since:
        q = q.filter(RouletteDraw.created_at > since)
    ids = set()
    for d in q:
        ids |= {w["id"] for w in json.loads(d.winners_json)}
    return ids


def winner_field_choices(event: Event) -> list:
    """Datos que el coordinador puede mostrar bajo el nombre del ganador: los fijos + cada campo opcional con nombre de ESTE evento (ahí vive la ciudad, etc.). El nombre siempre sale."""
    out = [{"key": k, "label": label} for k, label in FIXED_WINNER_FIELDS]
    for key, label in sorted(event.get_optional_labels().items(), key=lambda kv: int(kv[0].split("_")[1])):
        out.append({"key": f"extra:{key}", "label": label})
    return out


TOP_ALIGNS = ("left", "center", "right")
TOP_HEIGHT_DEFAULT, TOP_HEIGHT_MIN, TOP_HEIGHT_MAX = 18, 4, 40


def _top_cfg(raw) -> dict:
    """Tamaño y alineación de UN logo/banner de arriba: alto en % del alto de la pantalla (4 a 40) y left/center/right. Lo inválido vuelve al valor por defecto."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        height = max(TOP_HEIGHT_MIN, min(TOP_HEIGHT_MAX, int(raw.get("height", TOP_HEIGHT_DEFAULT))))
    except (TypeError, ValueError):
        height = TOP_HEIGHT_DEFAULT
    align = raw.get("align") if raw.get("align") in TOP_ALIGNS else "center"
    return {"height": height, "align": align}


def _winner_fields(p: dict, keys: list, choices: list) -> list:
    """[{key, label, value}] de lo que el coordinador marcó y la persona sí tiene (lo vacío no se muestra)."""
    labels = {c["key"]: c["label"] for c in choices}
    rows = []
    for key in keys or []:
        if key not in labels:
            continue          # el campo ya no existe en el evento
        value = p["extras"].get(key[6:], "") if key.startswith("extra:") else p.get(key, "")
        value = str(value or "").strip()
        if value:
            rows.append({"key": key, "label": labels[key], "value": value})
    return rows


def _person_out(p: dict, position: int, keys: Optional[list] = None, choices: Optional[list] = None) -> dict:
    out = {"position": position, "id": p["id"], "name": p["name"], "entity": p["entity"]}
    if keys is not None:
        out["fields"] = _winner_fields(p, keys, choices or [])          # Fase 10 (C): lo que el coordinador eligió mostrar
    return out


def _serialize_draw(d: RouletteDraw, staff_names: dict) -> dict:
    return {
        "id": d.id, "label": d.label, "mode": d.mode, "is_random": d.is_random, "candidates_count": d.candidates_count,
        "filter": json.loads(d.filter_json) if d.filter_json else None, "winners": json.loads(d.winners_json),
        "created_at": to_local(d.created_at).strftime("%Y-%m-%dT%H:%M:%S"), "created_by": staff_names.get(d.created_by_id, ""),
    }


def _staff_names(db: Session, ids) -> dict:
    return {s.id: (s.full_name or s.username) for s in db.query(StaffUser).filter(StaffUser.id.in_(set(i for i in ids if i)))}


# ------------------------------------------------------------------ configuración
@router.get("/events/{event_id}/roulette")
def get_roulette(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    people = candidates(db, event)
    return {
        "behavior": _behavior(cfg), "style": _style(cfg), "fonts": ALLOWED_FONTS, "modes": MODES, "winner_field_choices": winner_field_choices(event),
        "has_display_link": bool(cfg.display_token), "candidates_total": len(people), "event_status": event.status, "authorized": bool(_authorization(cfg)),
    }


@router.get("/events/{event_id}/roulette/fields")
def filter_fields(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Campos por los que se puede filtrar: los fijos + cada campo opcional rotulado de este evento."""
    event = get_event_for_staff(event_id, db, staff)
    fields = [
        {"key": "status", "label": "Estado de registro", "type": "choice", "choices": [["registrado", "Registrado"], ["no_registrado", "No registrado"]]},
        {"key": "registered_after", "label": "Se registró desde (fecha y hora)", "type": "datetime"},
        {"key": "registered_before", "label": "Se registró hasta (fecha y hora)", "type": "datetime"},
        {"key": "category", "label": "Categoría", "type": "choice", "choices": [[c, c] for c in event.get_categories()]},
        {"key": "entity", "label": "Entidad", "type": "text"}, {"key": "role", "label": "Cargo", "type": "text"},
        {"key": "opt_1", "label": "Tipo de asistente", "type": "text"},
    ]
    for key, label in sorted(event.get_optional_labels().items(), key=lambda kv: int(kv[0].split("_")[1])):
        fields.append({"key": f"extra:{key}", "label": label, "type": "text"})
    return fields


@router.get("/events/{event_id}/roulette/candidates")
def list_candidates(
    event_id: int, filter: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador")),
):
    """Candidatos visibles (con el filtro opcional, JSON `{"conditions":[...]}`) — para elegir a mano (modos 1-3 y
    5a) y para ver cuántos cumplen el filtro (5b)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    people = candidates(db, event)
    if filter:
        try:
            people = apply_filter(people, json.loads(filter))
        except ValueError:
            raise HTTPException(status_code=400, detail="Filtro con formato inválido")
    return {"total": len(people), "people": [
        {"id": p["id"], "name": p["name"], "entity": p["entity"], "status": p["status"], "categories": p["categories"]} for p in people[:2000]
    ]}


def _validate_behavior(db: Session, event: Event, data: dict) -> dict:
    mode = data.get("mode")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"Modo inválido (uno de: {', '.join(MODES)})")
    people = candidates(db, event)
    by_id = {p["id"]: p for p in people}
    filt = data.get("filter") or {"conditions": []}
    winners = [str(w) for w in (data.get("winners") or [])]
    if len(set(winners)) != len(winners):
        raise HTTPException(status_code=400, detail="Un mismo ganador no puede repetirse en la lista")
    unknown = [w for w in winners if w not in by_id]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Estas cédulas no están en la base del evento: {', '.join(unknown)}")
    if mode in ("single_fixed", "ordered", "shuffled", "filter_manual") and not winners:
        raise HTTPException(status_code=400, detail="Elige al menos un ganador")
    if mode == "single_fixed" and len(winners) != 1:
        raise HTTPException(status_code=400, detail="Este modo tiene exactamente un ganador")
    if mode in ("ordered", "shuffled") and len(winners) < 2:
        raise HTTPException(status_code=400, detail="Elige al menos 2 ganadores (para uno solo usa «Un ganador»)")
    if mode in ("filter_manual", "filter_random") and not (filt.get("conditions") or []):
        raise HTTPException(status_code=400, detail="Define al menos una condición de filtro")
    if mode == "filter_manual":
        allowed = {p["id"] for p in apply_filter(people, filt)}
        outside = [w for w in winners if w not in allowed]
        if outside:
            raise HTTPException(status_code=400, detail="Estos ganadores no cumplen el filtro: " + ", ".join(outside))
    try:
        count = int(data.get("count") or 1)
        batch = int(data.get("batch_size") or 1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="La cantidad debe ser un número")
    if count < 1 or batch < 1 or count > 500 or batch > 500:
        raise HTTPException(status_code=400, detail="La cantidad debe estar entre 1 y 500")
    return {"mode": mode, "winners": winners, "count": count, "batch_size": batch, "filter": {"conditions": filt.get("conditions") or []},
            "exclude_previous_winners": bool(data.get("exclude_previous_winners", True)), "all_reset_at": None}


@router.put("/events/{event_id}/roulette/behavior")
def save_behavior(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    new = _validate_behavior(db, event, data)
    old = _behavior(cfg)
    new["all_reset_at"] = old.get("all_reset_at")   # cambiar la configuración no reinicia la ronda de "todos"
    new["queue"] = old.get("queue") or []            # la fila de sorteos se edita por su propio endpoint (PUT /roulette/queue)
    cfg.behavior_json = json.dumps(new)
    db.commit()
    return new


@router.put("/events/{event_id}/roulette/style")
def save_style(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    style = {**_style(cfg)}
    for key in ("title_color", "text_color", "background_color", "pointer_color", "winner_bg", "winner_color"):
        if key in data:
            if not _HEX.match(str(data[key])):
                raise HTTPException(status_code=400, detail=f"«{key}» debe ser un color como #D4AF37")
            style[key] = data[key]
    for key in ("title_font", "font_family"):
        if key in data:
            if data[key] not in ALLOWED_FONTS:
                raise HTTPException(status_code=400, detail="Fuente no disponible")
            style[key] = data[key]
    if "title" in data:
        style["title"] = str(data["title"])[:80]
    if "colors" in data:
        colors = data["colors"]
        if not isinstance(colors, list) or not (2 <= len(colors) <= 12) or not all(_HEX.match(str(c)) for c in colors):
            raise HTTPException(status_code=400, detail="Elige entre 2 y 12 colores válidos para los segmentos")
        style["colors"] = colors
    if "wheel_style" in data:
        if data["wheel_style"] not in ("circular", "jackpot"):
            raise HTTPException(status_code=400, detail="Tipo de ruleta no válido")
        style["wheel_style"] = data["wheel_style"]
    if "spin_seconds" in data:
        try:
            style["spin_seconds"] = max(2, min(20, int(data["spin_seconds"])))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="La duración debe ser un número de segundos")
    for key in ("background_image", "logo"):
        if key in data:
            value = str(data[key] or "")
            if value and not value.startswith(event.tenant_id + "/"):
                raise HTTPException(status_code=400, detail="Imagen no válida")
            style[key] = value
    if "top_images" in data:          # logos/banners de arriba de la pantalla
        imgs = data["top_images"]
        if not isinstance(imgs, list) or len(imgs) > MAX_TOP_IMAGES:
            raise HTTPException(status_code=400, detail=f"Puedes poner hasta {MAX_TOP_IMAGES} logos o banners arriba")
        raw_cfg = data.get("top_images_cfg", style.get("top_images_cfg")) or []
        if not isinstance(raw_cfg, list):
            raise HTTPException(status_code=400, detail="Tamaño de logos no válido")
        clean, cfgs = [], []
        for i, value in enumerate(imgs):
            value = str(value or "")
            if not value.startswith(event.tenant_id + "/") or os.path.splitext(value)[1].lower() not in ALLOWED_IMAGE_EXT or ".." in value:
                raise HTTPException(status_code=400, detail="Imagen no válida")
            if value in clean:
                continue
            clean.append(value)
            cfgs.append(_top_cfg(raw_cfg[i] if i < len(raw_cfg) else None))
        style["top_images"], style["top_images_cfg"] = clean, cfgs
    elif "top_images_cfg" in data:       # solo cambió el tamaño/alineación de los que ya hay
        raw_cfg = data["top_images_cfg"]
        if not isinstance(raw_cfg, list):
            raise HTTPException(status_code=400, detail="Tamaño de logos no válido")
        style["top_images_cfg"] = [_top_cfg(raw_cfg[i] if i < len(raw_cfg) else None) for i in range(len(style.get("top_images") or []))]
    for key, lo, hi, msg in (("name_scale", 50, 400, "El tamaño del nombre"), ("fields_scale", 50, 400, "El tamaño de los demás datos")):
        if key in data:
            try:
                style[key] = max(lo, min(hi, int(data[key])))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{msg} debe ser un número entre {lo} y {hi}")
    if "winner_fields" in data:       # qué datos salen bajo el nombre (el nombre siempre sale)
        keys = data["winner_fields"]
        allowed = {c["key"] for c in winner_field_choices(event)}
        if not isinstance(keys, list) or len(keys) > MAX_WINNER_FIELDS or not all(isinstance(k, str) and k in allowed for k in keys):
            raise HTTPException(status_code=400, detail="Uno de los datos elegidos para mostrar no está disponible en este evento")
        style["winner_fields"] = list(dict.fromkeys(keys))
    if "spin_mode" in data:
        if data["spin_mode"] not in SPIN_MODES:
            raise HTTPException(status_code=400, detail="Forma de girar no válida (duración fija o giro libre)")
        style["spin_mode"] = data["spin_mode"]
    cfg.style_json = json.dumps(style)
    db.commit()
    return style


@router.post("/events/{event_id}/roulette/upload-image")
def upload_image(event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="Usa una imagen PNG, JPG, WEBP o GIF")
    content = file.file.read(8_000_001)
    if len(content) > 8_000_000:
        raise HTTPException(status_code=400, detail="La imagen pesa más de 8 MB")
    from app import safe_limits
    try:
        safe_limits.check_design_image(content, ext)      # I6: tamaño, píxeles y formato real (no solo la extensión)
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    name = f"{secrets.token_hex(16)}{ext}"
    get_storage().put(badge_asset_key(event.tenant_id, name), content)
    return {"storage_path": f"{event.tenant_id}/{name}"}


@router.post("/events/{event_id}/roulette/display-link")
def display_link(event_id: int, request: Request, regenerate: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Enlace de la pantalla de visualización (para el proyector): sin login, con código secreto. Se crea la primera
    vez; con `regenerate=true` el anterior deja de funcionar."""
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    if regenerate or not cfg.display_token:
        cfg.display_token = secrets.token_urlsafe(18)
        db.commit()
    base = publicurl.base(str(request.base_url))
    return {"url": f"{base}/r/{cfg.display_token}"}


@router.get("/events/{event_id}/roulette/display-link")
def get_display_link(event_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    base = publicurl.base(str(request.base_url))
    return {"url": f"{base}/r/{cfg.display_token}" if cfg.display_token else None}


# ------------------------------------------------------------------ ejecución
def _run_draw(db: Session, event: Event, cfg: RouletteConfig, label: str, created_by_id: Optional[int], dry_run: bool = False, behavior: Optional[dict] = None) -> dict:
    """Decide el/los ganador(es) según el comportamiento guardado y (salvo `dry_run`) guarda el registro del sorteo. `dry_run` solo
    valida que el sorteo se PUEDA hacer (sin ganadores válidos, sin candidatos…) para avisar al autorizar y no al girar."""
    b = behavior or _behavior(cfg)          # `behavior`: el paso de la fila que toca (si no, el comportamiento guardado)
    mode = b["mode"]
    people = candidates(db, event)
    if not people:
        raise HTTPException(status_code=400, detail="Este evento todavía no tiene personas cargadas")
    by_id = {p["id"]: p for p in people}
    is_random, pool_people = False, people

    if mode in ("single_fixed", "ordered", "shuffled", "filter_manual"):
        chosen = [by_id[w] for w in b["winners"] if w in by_id]
        if not chosen:
            raise HTTPException(status_code=400, detail="Los ganadores elegidos ya no están en la base del evento — vuelve a elegirlos")
        if mode == "shuffled":
            _RNG.shuffle(chosen)
        if mode == "filter_manual":
            pool_people = apply_filter(people, b["filter"])
    elif mode == "all":
        since = datetime.fromisoformat(b["all_reset_at"]) if b.get("all_reset_at") else None
        drawn = _previous_winner_ids(db, event, since=since, mode="all")
        pool = [p for p in people if p["id"] not in drawn]
        if not pool:
            raise HTTPException(status_code=400, detail="Ya salieron todos los asistentes en esta ronda. Usa «Reiniciar ronda» para empezar de nuevo.")
        chosen = _RNG.sample(pool, min(b["batch_size"], len(pool)))
        is_random = True
    else:  # filter_random
        pool = apply_filter(people, b["filter"])
        pool_people = pool
        if b["exclude_previous_winners"]:
            gone = _previous_winner_ids(db, event)
            pool = [p for p in pool if p["id"] not in gone]
        if not pool:
            raise HTTPException(status_code=400, detail="Nadie cumple el filtro (o todos los que lo cumplen ya ganaron antes)")
        chosen = _RNG.sample(pool, min(b["count"], len(pool)))
        is_random = True

    keys, choices = _style(cfg).get("winner_fields") or [], winner_field_choices(event)
    winners = [_person_out(p, i, keys, choices) for i, p in enumerate(chosen, start=1)]
    if dry_run:
        return {"mode": mode, "is_random": is_random}
    draw = RouletteDraw(
        event_id=event.id, label=label, mode=mode, is_random=is_random, candidates_count=len(pool_people),
        filter_json=json.dumps(b["filter"]) if mode in ("filter_manual", "filter_random") else None,
        winners_json=json.dumps(winners), created_by_id=created_by_id,
    )
    db.add(draw)
    db.commit()
    names = [p["name"] for p in pool_people]
    _RNG.shuffle(names)
    return {"draw_id": draw.id, "mode": mode, "is_random": is_random, "winners": winners, "pool": names[:POOL_SIZE], "label": label}


@router.post("/events/{event_id}/roulette/execute")
def execute(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Ejecuta el sorteo YA (sin esperar el botón de la pantalla pública). La interfaz normal usa `authorize`: el giro lo dispara el
    botón de la pantalla de visualización. Se conserva por compatibilidad."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    return _run_draw(db, event, _get_config(db, event), str(data.get("label") or "").strip()[:120], staff.id)


def _authorization(cfg: RouletteConfig) -> Optional[dict]:
    """La autorización de giro vigente (no vencida), o None."""
    if not cfg.authorized_json:
        return None
    auth = json.loads(cfg.authorized_json)
    if utcnow() - datetime.fromisoformat(auth["at"]) > AUTH_MAX_AGE:
        return None
    return auth


def _clean_step(db: Session, event: Event, raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Un sorteo de la fila no es válido")
    behavior = _validate_behavior(db, event, raw.get("behavior") or {})
    behavior.pop("all_reset_at", None)
    start = raw.get("start") if raw.get("start") in ("click", "auto") else "click"
    spin_mode = raw.get("spin_mode") if raw.get("spin_mode") in SPIN_MODES else "fixed"
    try:
        spin_seconds = max(2, min(20, int(raw.get("spin_seconds") or 8)))
        pause = max(3, min(120, int(raw.get("pause") or 8)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Los segundos deben ser un número")
    return {"label": str(raw.get("label") or "").strip()[:120], "behavior": behavior, "start": start, "spin_mode": spin_mode,
            "spin_seconds": spin_seconds, "pause": pause}


def _queue(cfg: RouletteConfig) -> list:
    q = _behavior(cfg).get("queue")
    return q if isinstance(q, list) else []


def _step_behavior(cfg: RouletteConfig, step: dict) -> dict:
    """El comportamiento de un paso de la fila; la ronda de «todos» es la misma de siempre (se reinicia aparte)."""
    return {**DEFAULT_BEHAVIOR, **step["behavior"], "all_reset_at": _behavior(cfg).get("all_reset_at")}


@router.get("/events/{event_id}/roulette/queue")
def get_queue(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    return {"steps": _queue(_get_config(db, event)), "max": MAX_QUEUE_STEPS}


@router.put("/events/{event_id}/roulette/queue")
def save_queue(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Deja preparados varios sorteos (cada uno con su modo, sus ganadores y cómo se gira) para autorizarlos TODOS de una vez."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    raw = data.get("steps")
    if not isinstance(raw, list) or len(raw) > MAX_QUEUE_STEPS:
        raise HTTPException(status_code=400, detail=f"La fila admite de 0 a {MAX_QUEUE_STEPS} sorteos")
    steps = [_clean_step(db, event, r) for r in raw]
    cfg = _get_config(db, event)
    b = _behavior(cfg)
    b["queue"] = steps
    cfg.behavior_json = json.dumps(b)
    cfg.authorized_json = None if (_authorization(cfg) or {}).get("queue") else cfg.authorized_json     # editar la fila cancela una autorización de fila vigente
    db.commit()
    return {"steps": steps}


@router.post("/events/{event_id}/roulette/authorize")
def authorize_spin(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """El operador AUTORIZA un giro: se valida ahora (para que los errores salgan aquí y no frente al público) y se activa el botón
    «Girar» de la pantalla de visualización. El ganador se decide al girar, en el servidor."""
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    if not cfg.display_token:
        raise HTTPException(status_code=400, detail="Primero genera el enlace de la pantalla de visualización: el botón de girar vive allá")
    if data.get("queue"):
        steps = _queue(cfg)
        if not steps:
            raise HTTPException(status_code=400, detail="La fila está vacía: agrega al menos un sorteo")
        for i, step in enumerate(steps, start=1):
            try:
                _run_draw(db, event, cfg, "", staff.id, dry_run=True, behavior=_step_behavior(cfg, step))
            except HTTPException as exc:
                raise HTTPException(status_code=400, detail=f"Sorteo {i} de la fila ({step.get('label') or 'sin nombre'}): {exc.detail}")
        cfg.authorized_json = json.dumps({"label": steps[0]["label"], "by": staff.id, "at": utcnow().isoformat(), "queue": True, "step": 0})
        db.commit()
        return {"authorized": True, "label": steps[0]["label"], "queue": True, "step": 0, "total": len(steps)}
    _run_draw(db, event, cfg, "", staff.id, dry_run=True)
    label = str(data.get("label") or "").strip()[:120]
    cfg.authorized_json = json.dumps({"label": label, "by": staff.id, "at": utcnow().isoformat()})
    db.commit()
    return {"authorized": True, "label": label}


@router.delete("/events/{event_id}/roulette/authorize")
def cancel_authorization(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    cfg.authorized_json = None
    db.commit()
    return {"authorized": False}


@router.get("/events/{event_id}/roulette/authorization")
def get_authorization(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    auth = _authorization(_get_config(db, event))
    return {"authorized": bool(auth), "label": auth["label"] if auth else "", "since": auth["at"] if auth else None,
            "queue": bool(auth and auth.get("queue")), "step": (auth or {}).get("step", 0), "total": len(_queue(_get_config(db, event))) if auth and auth.get("queue") else 0}



@router.post("/events/{event_id}/roulette/reset-round")
def reset_round(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Modo «todos»: empieza una ronda nueva (vuelven a poder salir todos)."""
    event = get_event_for_staff(event_id, db, staff)
    cfg = _get_config(db, event)
    b = _behavior(cfg)
    b["all_reset_at"] = utcnow().isoformat()
    cfg.behavior_json = json.dumps(b)
    db.commit()
    return {"message": "Ronda reiniciada"}


@router.get("/events/{event_id}/roulette/round")
def round_status(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    b = _behavior(_get_config(db, event))
    since = datetime.fromisoformat(b["all_reset_at"]) if b.get("all_reset_at") else None
    drawn = _previous_winner_ids(db, event, since=since, mode="all")
    return {"drawn": len(drawn), "total": len(candidates(db, event))}


# ------------------------------------------------------------------ historial y reporte
@router.get("/events/{event_id}/roulette/draws")
def list_draws(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    draws = db.query(RouletteDraw).filter_by(event_id=event.id).order_by(RouletteDraw.id.desc()).all()
    names = _staff_names(db, [d.created_by_id for d in draws])
    return [_serialize_draw(d, names) for d in draws]


MODE_LABELS = {
    "single_fixed": "Un ganador (elegido)", "ordered": "Varios, en orden", "shuffled": "Varios, orden aleatorio",
    "all": "Todos los asistentes", "filter_manual": "Filtro + elegido a mano", "filter_random": "Filtro + sorteo real",
}


@router.get("/events/{event_id}/roulette/report")
def report(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Reporte Excel de todos los sorteos del evento (mismo estilo que el resto de reportes)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    draws = db.query(RouletteDraw).filter_by(event_id=event.id).order_by(RouletteDraw.id).all()
    names = _staff_names(db, [d.created_by_id for d in draws])
    wb = Workbook()
    ws = wb.active
    ws.title = "Sorteos"
    ws.append([f"Sorteos — {event.name} ({event.event_code})"])
    ws["A1"].font = Font(bold=True, size=13, color="0A0E2E")
    headers = ["Fecha", "Hora", "Sorteo", "Modo", "¿Aleatorio real?", "Posición", "Cédula", "Nombre", "Entidad", "Candidatos", "Filtro", "Ejecutó"]
    ws.append(headers)
    for c in ws[2]:
        c.font = Font(color="FFFFFF", bold=True)
        c.fill = PatternFill(start_color="0A0E2E", end_color="0A0E2E", fill_type="solid")
        c.alignment = Alignment(horizontal="center")
    for d in draws:
        local = to_local(d.created_at)
        filt = "; ".join(f"{c['field']} {c.get('op', 'equals')} {c.get('value')}" for c in (json.loads(d.filter_json)["conditions"] if d.filter_json else []))
        for w in json.loads(d.winners_json):
            ws.append([local.strftime("%Y-%m-%d"), local.strftime("%H:%M:%S"), d.label or "", MODE_LABELS.get(d.mode, d.mode),
                       "Sí" if d.is_random else "No (elegido de antemano)", w["position"], w["id"], (w["name"] or "").upper(),
                       (w["entity"] or "").upper(), d.candidates_count, filt, names.get(d.created_by_id, "")])
    ws.auto_filter.ref = f"A2:{chr(64 + len(headers))}{ws.max_row}"
    for col, width in zip("ABCDEFGHIJKL", (12, 10, 28, 26, 24, 9, 14, 30, 24, 11, 34, 22)):
        ws.column_dimensions[col].width = width
    return heavy.workbook_response(wb, f"Sorteos_{event.event_code}.xlsx")


# ------------------------------------------------------------------ pantalla pública (proyector)
PUBLIC_WINNER_KEYS = ("position", "name", "entity", "fields")          # B15: a la pantalla pública NO sale la cédula del ganador (la pantalla solo pinta posición, nombre y lo que el coordinador eligió mostrar: «fields», sin la clave interna)


def public_winners(winners: list) -> list:
    out = [{k: w[k] for k in PUBLIC_WINNER_KEYS if k in w} for w in winners]
    for w in out:
        if "fields" in w:
            w.pop("entity", None)          # con «fields» manda la elección del coordinador: si desmarcó la empresa, ni siquiera viaja a la pantalla pública
            w["fields"] = [{"label": f.get("label", ""), "value": f.get("value", ""), "entity": f.get("key") == "entity"} for f in w["fields"]]
    return out


def _cfg_by_token(db: Session, token: str) -> RouletteConfig:
    cfg = db.query(RouletteConfig).filter(RouletteConfig.display_token == token).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Pantalla no disponible")
    event = db.get(Event, cfg.event_id)
    if event is None or event.archived_at is not None or event.data_archived_at is not None:          # B15: el enlace público deja de servir con el evento o su base archivados
        raise HTTPException(status_code=404, detail="Pantalla no disponible")
    return cfg


@public_router.get("/r/{token}", response_class=HTMLResponse)
def display_page(token: str, request: Request, db: Session = Depends(get_db)):
    from app.main import templates  # import tardío: main.py importa este módulo
    try:
        cfg = _cfg_by_token(db, token)
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Pantalla no disponible</h3>", status_code=404)
    event = db.query(Event).filter(Event.id == cfg.event_id).first()
    return templates.TemplateResponse(request=request, name="roulette_display.html", context={"token": token, "event_name": event.name})


def _next_info(cfg: RouletteConfig, auth: Optional[dict]) -> Optional[dict]:
    """Del paso que toca en una fila autorizada: cómo arranca («click» o solo tras una pausa) y cómo gira. None si no es una fila."""
    if not auth or not auth.get("queue"):
        return None
    steps = _queue(cfg)
    i = int(auth.get("step", 0))
    if i >= len(steps):
        return None
    st = steps[i]
    return {"step": i + 1, "total": len(steps), "start": st["start"], "pause": st["pause"], "spin_mode": st["spin_mode"], "spin_seconds": st["spin_seconds"]}


@public_router.get("/r/{token}/state")
def display_state(token: str, after: Optional[int] = None, db: Session = Depends(get_db)):
    """Estilo + el `id` del último sorteo. La pantalla recuerda el `id` que ya vio y pide con `?after=<id>`: solo si hay
    uno MÁS NUEVO se arma y devuelve el sorteo (con la lista de nombres), así el sondeo de cada segundo es liviano."""
    cfg = _cfg_by_token(db, token)
    event = db.query(Event).filter(Event.id == cfg.event_id).first()
    last = db.query(RouletteDraw).filter_by(event_id=cfg.event_id).order_by(RouletteDraw.id.desc()).first()
    auth = _authorization(cfg)
    out = {"style": _style(cfg), "event_name": event.name, "latest_id": last.id if last else 0, "draw": None,
           "authorized": bool(auth), "authorized_label": auth["label"] if auth else "", "authorized_next": _next_info(cfg, auth)}
    if last and after is not None and last.id > after:
        names = [p["name"] for p in candidates(db, event)]
        _RNG.shuffle(names)
        out["draw"] = {"id": last.id, "label": last.label, "mode": last.mode, "winners": public_winners(json.loads(last.winners_json)), "pool": names[:POOL_SIZE]}
    return out


@public_router.post("/r/{token}/spin")
def spin(token: str, request: Request, db: Session = Depends(get_db)):
    """El botón «Girar» de la pantalla de visualización: solo funciona si el operador AUTORIZÓ un giro, y lo consume (una autorización =
    un giro). Con la fila bloqueada, dos pantallas que pulsen a la vez no giran dos veces. Devuelve el sorteo para animarlo al instante."""
    cfg = _cfg_by_token(db, token)
    security.enforce_public_limit(db, request, "roulette_spin", str(cfg.id), 40, timedelta(minutes=10))
    locked = db.query(RouletteConfig).filter(RouletteConfig.id == cfg.id).with_for_update().first()
    auth = _authorization(locked)
    if not auth:
        db.rollback()
        raise HTTPException(status_code=409, detail="El operador todavía no autorizó el giro")
    event = db.query(Event).filter(Event.id == locked.event_id).first()
    step, behavior, nxt_auth = None, None, None
    if auth.get("queue"):                                  # fila de sorteos: una sola autorización sirve para todos los pasos
        steps = _queue(locked)
        i = int(auth.get("step", 0))
        if i >= len(steps):
            locked.authorized_json = None
            db.commit()
            raise HTTPException(status_code=409, detail="La fila ya terminó")
        step, behavior = steps[i], _step_behavior(locked, steps[i])
        if i + 1 < len(steps):
            nxt_auth = {**auth, "step": i + 1, "label": steps[i + 1]["label"], "at": utcnow().isoformat()}
    locked.authorized_json = json.dumps(nxt_auth) if nxt_auth else None      # se consume antes de sortear: pase lo que pase no se puede repetir
    db.commit()
    try:
        res = _run_draw(db, event, locked, (step or {}).get("label") if step else auth["label"], auth["by"], behavior=behavior)
        out = {**res, "winners": public_winners(res["winners"])}          # la cédula queda en el sorteo guardado (reporte del operador), no en la pantalla pública
        if step:
            out["spin_mode"], out["spin_seconds"] = step["spin_mode"], step["spin_seconds"]
            out["queue_step"], out["queue_total"] = int(auth.get("step", 0)) + 1, len(_queue(locked))
            out["next"] = _next_info(locked, nxt_auth)
        return out
    except HTTPException:
        locked.authorized_json = json.dumps(auth)        # el sorteo no se pudo hacer: la autorización sigue vigente
        db.commit()
        raise


@public_router.get("/r/{token}/asset/{tenant_id}/{filename}")
def display_asset(token: str, tenant_id: str, filename: str, db: Session = Depends(get_db)):
    cfg = _cfg_by_token(db, token)
    event = db.query(Event).filter(Event.id == cfg.event_id).first()
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return get_storage().response(badge_asset_key(tenant_id, safe))
