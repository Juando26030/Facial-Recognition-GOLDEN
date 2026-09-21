import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import BadgeTemplate, SavedBadgeTemplate, StaffUser, User, PrintLog
from app.auth import get_current_staff, get_event_for_staff, require_role_excluding

router = APIRouter()

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _badge_assets_dir(tenant_id: str) -> str:
    path = os.path.join('data', tenant_id, 'badge_assets')
    os.makedirs(path, exist_ok=True)
    return path


def _serialize_template(t) -> dict:
    return {
        "id": t.id, "name": t.name, "width_mm": t.width_mm, "height_mm": t.height_mm,
        "orientation": t.orientation, "background_type": t.background_type,
        "background_value": t.background_value, "elements": t.get_elements(),
    }


class BadgeTemplateIn(BaseModel):
    name: str = "Escarapela"
    width_mm: float
    height_mm: float
    orientation: str = "vertical"
    background_type: str = "color"
    background_value: Optional[str] = None
    elements: list = []


class SaveAsIn(BaseModel):
    name: str


DEFAULT_ELEMENTS = [
    {"id": "el_nombre", "type": "text_variable", "variable": "first_name", "x": 5, "y": 10, "width": 52, "height": 8,
     "rotation": 0, "z_index": 1, "font_family": "Roboto", "font_size": 14, "font_color": "#0A0E2E",
     "font_weight": "bold", "align": "center"},
    {"id": "el_apellido", "type": "text_variable", "variable": "last_name", "x": 5, "y": 19, "width": 52, "height": 8,
     "rotation": 0, "z_index": 2, "font_family": "Roboto", "font_size": 14, "font_color": "#0A0E2E",
     "font_weight": "bold", "align": "center"},
    {"id": "el_entidad", "type": "text_variable", "variable": "entity", "x": 5, "y": 30, "width": 52, "height": 6,
     "rotation": 0, "z_index": 3, "font_family": "Roboto", "font_size": 10, "font_color": "#555555",
     "font_weight": "normal", "align": "center"},
]


def _get_or_create_template(event, db: Session) -> BadgeTemplate:
    tpl = db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id).first()
    if not tpl:
        tpl = BadgeTemplate(
            tenant_id=event.tenant_id, event_id=event.id, name=f"Escarapela {event.name}",
            width_mm=62.0, height_mm=100.0, orientation="vertical",
            background_type="color", background_value="#FFFFFF",
        )
        tpl.set_elements(DEFAULT_ELEMENTS)
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
    return tpl


@router.get("/events/{event_id}/badge-template")
async def get_badge_template(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",)))
):
    """La plantilla ACTIVA del evento — se crea sola con un diseño mínimo por defecto (nombre +
    apellido + entidad) la primera vez que se pide, así el editor nunca arranca en blanco del
    todo. Mínimo `digitador`+ (bug real, QA local 2026-09-15): este GET también lo usa
    badge_print.html para cargar la plantilla antes de imprimir, y un digitador (el rol que más
    imprime el día del evento) recibía 403 — la escritura (`PUT` abajo) sigue exigiendo
    `coordinador`+, solo se separó el gate de lectura."""
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db)
    return _serialize_template(tpl)


@router.put("/events/{event_id}/badge-template")
async def update_badge_template(
    event_id: int, data: BadgeTemplateIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db)
    tpl.name = data.name
    tpl.width_mm = data.width_mm
    tpl.height_mm = data.height_mm
    tpl.orientation = data.orientation
    tpl.background_type = data.background_type
    tpl.background_value = data.background_value
    tpl.set_elements(data.elements)
    db.commit()
    return _serialize_template(tpl)


@router.get("/events/{event_id}/saved-badge-templates")
async def list_saved_badge_templates(
    event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))
):
    """Librería reusable — GLOBAL para toda la app (2026-09-16, pedido explícito: antes era por
    tenant, ahora una plantilla guardada desde CUALQUIER evento de CUALQUIER cliente aparece acá
    y se puede importar en cualquier otro, sin importar el cliente). `tenant_id` se sigue
    guardando en la fila (trazabilidad de quién la creó) pero ya no filtra qué se lista."""
    event = get_event_for_staff(event_id, db, staff)  # valida acceso al evento, no se usa para filtrar
    saved = db.query(SavedBadgeTemplate).order_by(SavedBadgeTemplate.name).all()
    return [{
        "id": s.id, "name": s.name, "width_mm": s.width_mm, "height_mm": s.height_mm,
        "orientation": s.orientation,
    } for s in saved]


@router.post("/events/{event_id}/badge-template/save-as")
async def save_badge_template_as(
    event_id: int, data: SaveAsIn, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """'Guardar como plantilla': copia el diseño actual del evento a una fila nueva de la
    librería reusable. Es una COPIA — editar el evento después no toca esta fila."""
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db)
    saved = SavedBadgeTemplate(
        tenant_id=event.tenant_id, name=data.name.strip() or tpl.name,
        width_mm=tpl.width_mm, height_mm=tpl.height_mm, orientation=tpl.orientation,
        background_type=tpl.background_type, background_value=tpl.background_value,
    )
    saved.set_elements(tpl.get_elements())
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return {"id": saved.id, "name": saved.name}


@router.post("/events/{event_id}/badge-template/import/{saved_id}")
async def import_saved_badge_template(
    event_id: int, saved_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """'Importar plantilla': copia el diseño de una SavedBadgeTemplate al BadgeTemplate de ESTE
    evento (sobrescribe lo que tuviera) — punto de partida editable, no una referencia compartida.
    La librería es global (2026-09-16): se puede importar cualquier plantilla guardada, sin
    importar en qué cliente/evento se haya guardado originalmente."""
    event = get_event_for_staff(event_id, db, staff)
    saved = db.query(SavedBadgeTemplate).filter(SavedBadgeTemplate.id == saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Plantilla guardada no encontrada")

    tpl = _get_or_create_template(event, db)
    tpl.width_mm = saved.width_mm
    tpl.height_mm = saved.height_mm
    tpl.orientation = saved.orientation
    tpl.background_type = saved.background_type
    tpl.background_value = saved.background_value
    tpl.set_elements(saved.get_elements())
    tpl.imported_from_saved_template_id = saved.id
    db.commit()
    return _serialize_template(tpl)


@router.delete("/saved-badge-templates/{saved_id}")
async def delete_saved_badge_template(
    saved_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))
):
    saved = db.query(SavedBadgeTemplate).filter(SavedBadgeTemplate.id == saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Plantilla guardada no encontrada")
    # coordinador+ sin alcance de tenant fijo puede borrar de cualquier tenant (igual que el resto
    # de acciones coordinador+ en este proyecto); no se exige event_id acá porque la librería no
    # es de un evento puntual.
    # imported_from_saved_template_id es SOLO trazabilidad ("de dónde vino este diseño"), no un
    # vínculo vivo — hay que soltarlo antes de borrar, si no, cualquier BadgeTemplate que haya
    # importado esta plantilla (aunque ya la haya editado después) deja la fila huérfana y el
    # DELETE truena con ForeignKeyViolation (bug real, encontrado con un test end-to-end antes de
    # llegar a producción, 2026-09-15 — mismo patrón que Event/AccessLog en routers/events.py).
    db.query(BadgeTemplate).filter(
        BadgeTemplate.imported_from_saved_template_id == saved_id
    ).update({"imported_from_saved_template_id": None})
    db.delete(saved)
    db.commit()
    return {"message": "Plantilla eliminada de la librería"}


@router.post("/events/{event_id}/badge-template/upload-image")
async def upload_badge_image(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Sube una imagen (fondo, o un image_static suelto como un logo) y devuelve el storage_path
    para usar en background_value o en el campo storage_path de un elemento image_static."""
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"Formato no soportado ({ext or 'sin extensión'}) — usa PNG, JPG, WEBP o GIF")

    filename = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _badge_assets_dir(event.tenant_id)
    dest_path = os.path.join(dest_dir, filename)
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    return {"storage_path": f"{event.tenant_id}/{filename}"}


@router.get("/badge-assets/{tenant_id}/{filename}")
async def get_badge_asset(
    tenant_id: str, filename: str, staff: StaffUser = Depends(get_current_staff)
):
    """Sirve una imagen subida para escarapelas — cualquier staff autenticado puede verla (es
    una imagen de fondo/logo, no un dato sensible; el login ya es la barrera real, igual que con
    el resto de la app)."""
    safe_filename = os.path.basename(filename)  # nunca confiar en el path que manda el cliente
    path = os.path.join('data', tenant_id, 'badge_assets', safe_filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path)


@router.get("/users/{user_id}/badge-print-data")
async def get_badge_print_data(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Datos completos de UNA persona para imprimir su escarapela — incluye extra_fields (los
    campos opcionales) y si tiene foto, que /api/users normal (el Directorio) no manda."""
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    has_photo = os.path.isfile(os.path.join('data', event.tenant_id, 'known_people', f"{user.id}.jpg"))
    return {
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "entity": user.entity, "phone": user.phone, "email": user.email,
        "opt_1": user.opt_1, "extra_fields": user.get_extras(),
        "optional_field_labels": event.get_optional_labels(),
        "has_photo": has_photo,
    }


@router.get("/users/{user_id}/photo")
async def get_user_photo(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """La foto biométrica de la persona (si existe) — para el elemento image_variable
    (source: "photo") de la escarapela."""
    event = get_event_for_staff(event_id, db, staff)
    path = os.path.join('data', event.tenant_id, 'known_people', f"{user_id}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Esta persona no tiene foto registrada")
    return FileResponse(path)


@router.get("/users/{user_id}/print-count")
async def get_print_count(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Cuántas veces se ha impreso la escarapela de esta persona en ESTE evento — para avisar
    antes de repetir (Sprint 2.4 Fase 3, pedido explícito)."""
    event = get_event_for_staff(event_id, db, staff)
    count = db.query(PrintLog).filter(
        PrintLog.event_id == event.id, PrintLog.user_id == user_id, PrintLog.tenant_id == event.tenant_id
    ).count()
    return {"times_printed": count}


@router.post("/users/{user_id}/print-log")
async def log_print(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Registra una impresión de escarapela — se llama justo antes de abrir la ventana de
    impresión, tras cualquier confirmación necesaria."""
    event = get_event_for_staff(event_id, db, staff)
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    db.add(PrintLog(
        tenant_id=event.tenant_id, user_id=user_id, event_id=event.id, printed_by_staff_id=staff.id,
    ))
    db.commit()
    return {"ok": True}
