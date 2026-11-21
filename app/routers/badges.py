import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app import audit_actions, contacts, crypto, form_client, person_code, publicurl, reprint
from app.timeutil import utcnow
from app.eventpeople import require_person_of_event
from app.storage import badge_asset_key, get_storage, photo_key
from app import event_archive
from app.database import get_db
from app import testperson
from app.inputcheck import text_validator
from app.models import BadgeTemplate, EventAttendee, SavedBadgeTemplate, StaffUser, User, PrintLog
from app.auth import ROLE_HIERARCHY, assert_tenant_id, effective_roles, get_current_staff, get_event_for_staff, require_role, require_role_excluding

router = APIRouter()

ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _serialize_template(t) -> dict:
    return {
        "id": t.id, "name": t.name, "width_mm": t.width_mm, "height_mm": t.height_mm,
        "orientation": t.orientation, "background_type": t.background_type,
        "background_value": t.background_value, "elements": t.get_elements(),
        "updated_at": t.updated_at.isoformat() + "Z" if t.updated_at else None,          # versión: quien imprime sabe con qué plantilla dibujó
    }


@router.put("/events/{event_id}/badge-mode")
def set_badge_mode(
    event_id: int, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Ítem 14: `per_category` False = una plantilla para todas las categorías; True = una distinta
    por categoría (las que no tengan plantilla propia siguen usando la general)."""
    event = get_event_for_staff(event_id, db, staff)
    per_category = bool(data.get("per_category"))
    if per_category and not event.get_categories():
        raise HTTPException(status_code=400, detail="Este evento no tiene categorías — créalas primero en Parámetros del Evento")
    event.badge_per_category = per_category
    db.commit()
    return {"badge_per_category": event.badge_per_category, "categories": event.get_categories()}


class BadgeTemplateIn(BaseModel):
    name: str = "Escarapela"
    width_mm: float
    height_mm: float
    orientation: str = "vertical"
    background_type: str = "color"
    background_value: Optional[str] = None
    elements: list = []


class SaveAsIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    _t = text_validator("name")      # C2: sin «<» ni «>»


def _default_certificate_elements(event) -> list:
    """Diseño inicial del certificado (A4 horizontal, 297x210 mm): título, 'se otorga a', nombre y
    apellido de la persona y el nombre del evento — el coordinador lo edita a su gusto."""
    base = {"rotation": 0, "font_family": "Playfair Display", "font_color": "#0A0E2E", "align": "center", "x": 20, "width": 257}
    return [
        {**base, "id": "cert_titulo", "type": "text_static", "content": "CERTIFICADO DE PARTICIPACIÓN", "y": 30, "height": 16, "z_index": 1, "font_size": 30, "font_weight": "bold"},
        {**base, "id": "cert_otorga", "type": "text_static", "content": "Se otorga el presente certificado a", "y": 65, "height": 10, "z_index": 2, "font_size": 16, "font_weight": "normal"},
        {**base, "id": "cert_nombre", "type": "text_variable", "variable": "first_name", "y": 82, "height": 16, "z_index": 3, "font_size": 32, "font_weight": "bold"},
        {**base, "id": "cert_apellido", "type": "text_variable", "variable": "last_name", "y": 100, "height": 16, "z_index": 4, "font_size": 32, "font_weight": "bold"},
        {**base, "id": "cert_evento", "type": "text_static", "content": f"por su participación en {event.name}", "y": 132, "height": 12, "z_index": 5, "font_size": 18, "font_weight": "normal"},
    ]


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


def _get_or_create_template(event, db: Session, category: Optional[str] = None, kind: str = "badge") -> BadgeTemplate:
    """Plantilla del evento (`category=None` = la general, para todas las categorías). Con una
    categoría (ítem 14, reunión 2026-09-21): la de esa categoría; si todavía no tiene, se crea como
    COPIA de la general — punto de partida editable, no un vínculo vivo."""
    if kind not in ("badge", "certificate"):
        raise HTTPException(status_code=400, detail="kind debe ser badge o certificate")
    if category is not None and category not in event.get_categories():
        raise HTTPException(status_code=400, detail="Esa categoría no existe en este evento")
    tpl = db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id, BadgeTemplate.category == category, BadgeTemplate.kind == kind).first()
    if not tpl and kind == "certificate":
        # Ítem 5: el certificado es UNA plantilla por evento (A4 horizontal, sin categorías).
        tpl = BadgeTemplate(
            tenant_id=event.tenant_id, event_id=event.id, category=None, kind="certificate",
            name=f"Certificado {event.name}", width_mm=297.0, height_mm=210.0, orientation="horizontal",
            background_type="color", background_value="#FFFFFF",
        )
        tpl.set_elements(_default_certificate_elements(event))
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
        return tpl
    if not tpl:
        base = _get_or_create_template(event, db) if category is not None else None
        tpl = BadgeTemplate(
            tenant_id=event.tenant_id, event_id=event.id, category=category, kind="badge",
            name=f"Escarapela {event.name}" + (f" — {category}" if category else ""),
            width_mm=base.width_mm if base else 62.0, height_mm=base.height_mm if base else 100.0,
            orientation=base.orientation if base else "vertical",
            background_type=base.background_type if base else "color",
            background_value=base.background_value if base else "#FFFFFF",
        )
        tpl.set_elements(base.get_elements() if base else DEFAULT_ELEMENTS)
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
    return tpl


def template_category_for_user(event, db: Session, user_id: str) -> Optional[str]:
    """Categoría cuya plantilla se debe usar para imprimir a esta persona: con "una plantilla por
    categoría" activo, la primera de sus categorías que tenga plantilla propia; si no, la general."""
    if not event.badge_per_category:
        return None
    attendee = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user_id).first()
    for category in (attendee.get_categories() if attendee else []):
        if db.query(BadgeTemplate).filter(BadgeTemplate.event_id == event.id, BadgeTemplate.category == category, BadgeTemplate.kind == "badge").first():
            return category
    return None


@router.get("/events/{event_id}/badge-template")
def get_badge_template(
    response: Response, event_id: int, category: Optional[str] = None, kind: str = "badge", db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """La plantilla ACTIVA del evento — se crea sola con un diseño mínimo por defecto (nombre +
    apellido + entidad) la primera vez que se pide, así el editor nunca arranca en blanco del
    todo. Mínimo `digitador`+ (bug real, QA local 2026-09-15): este GET también lo usa
    badge_print.html para cargar la plantilla antes de imprimir, y un digitador (el rol que más
    imprime el día del evento) recibía 403 — la escritura (`PUT` abajo) sigue exigiendo
    `coordinador`+, solo se separó el gate de lectura."""
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db, category, kind)
    response.headers["Cache-Control"] = "no-store"          # 25-oct-2026: nadie (navegador, Firebase Hosting, un proxy) guarda la plantilla: cada impresión usa la vigente
    return _serialize_template(tpl)


@router.put("/events/{event_id}/badge-template")
def update_badge_template(
    event_id: int, data: BadgeTemplateIn, category: Optional[str] = None, kind: str = "badge", db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db, category, kind)
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
def list_saved_badge_templates(
    event_id: int, include_archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",)))
):
    """Librería reusable — GLOBAL para toda la app (2026-09-16, pedido explícito: antes era por
    tenant, ahora una plantilla guardada desde CUALQUIER evento de CUALQUIER cliente aparece acá
    y se puede importar en cualquier otro, sin importar el cliente). `tenant_id` se sigue
    guardando en la fila (trazabilidad de quién la creó) pero ya no filtra qué se lista."""
    get_event_for_staff(event_id, db, staff)  # valida acceso al evento, no se usa para filtrar
    query = db.query(SavedBadgeTemplate)
    if include_archived:
        if staff.role not in ("coordinador", "comercial", "admin", "super_admin"):
            raise HTTPException(status_code=403, detail="No tienes permiso para ver las plantillas archivadas")
    else:
        query = query.filter(SavedBadgeTemplate.archived_at.is_(None))
    return [{
        "id": s.id, "name": s.name, "width_mm": s.width_mm, "height_mm": s.height_mm,
        "orientation": s.orientation, "archived": s.archived_at is not None,
    } for s in query.order_by(SavedBadgeTemplate.name).all()]


@router.post("/events/{event_id}/badge-template/save-as")
def save_badge_template_as(
    event_id: int, data: SaveAsIn, category: Optional[str] = None, kind: str = "badge", db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """'Guardar como plantilla': copia el diseño actual del evento a una fila nueva de la
    librería reusable. Es una COPIA — editar el evento después no toca esta fila."""
    event = get_event_for_staff(event_id, db, staff)
    tpl = _get_or_create_template(event, db, category, kind)
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
def import_saved_badge_template(
    event_id: int, saved_id: int, category: Optional[str] = None, kind: str = "badge", db: Session = Depends(get_db),
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
    if saved.archived_at is not None:
        raise HTTPException(status_code=400, detail="La plantilla está archivada: restáurala para importarla")

    tpl = _get_or_create_template(event, db, category, kind)
    tpl.width_mm = saved.width_mm
    tpl.height_mm = saved.height_mm
    tpl.orientation = saved.orientation
    tpl.background_type = saved.background_type
    tpl.background_value = saved.background_value
    tpl.set_elements(saved.get_elements())
    tpl.imported_from_saved_template_id = saved.id
    db.commit()
    return _serialize_template(tpl)


def _saved_or_404(db: Session, saved_id: int) -> SavedBadgeTemplate:
    saved = db.query(SavedBadgeTemplate).filter(SavedBadgeTemplate.id == saved_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Plantilla guardada no encontrada")
    return saved


@router.post("/saved-badge-templates/{saved_id}/archive")
def archive_saved_badge_template(saved_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """Archivar = sacarla de la librería (ya no se ofrece para importar). Los eventos que la importaron conservan su diseño; un coordinador o superior la restaura."""
    saved = _saved_or_404(db, saved_id)
    if saved.archived_at is not None:
        raise HTTPException(status_code=400, detail="La plantilla ya está archivada")
    saved.archived_at, saved.archived_by_id = utcnow(), staff.id
    audit_actions.record(db, staff, "archive", "saved_badge_template", saved.id, saved.name)
    db.commit()
    return {"id": saved.id, "name": saved.name, "archived": True}


@router.post("/saved-badge-templates/{saved_id}/restore")
def restore_saved_badge_template(saved_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    saved = _saved_or_404(db, saved_id)
    if saved.archived_at is None:
        raise HTTPException(status_code=400, detail="La plantilla no está archivada")
    saved.archived_at, saved.archived_by_id = None, None
    audit_actions.record(db, staff, "restore", "saved_badge_template", saved.id, saved.name)
    db.commit()
    return {"id": saved.id, "name": saved.name, "archived": False}


@router.delete("/saved-badge-templates/{saved_id}")
def delete_saved_badge_template(
    saved_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("super_admin"))
):
    """Borrado DEFINITIVO: solo super_admin y de una plantilla ya archivada."""
    saved = _saved_or_404(db, saved_id)
    if saved.archived_at is None:
        raise HTTPException(status_code=400, detail="Primero archiva la plantilla; el borrado definitivo solo aplica a plantillas archivadas")
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
    audit_actions.record(db, staff, "delete", "saved_badge_template", saved.id, saved.name)
    db.delete(saved)
    db.commit()
    return {"message": "Plantilla eliminada de la librería"}


@router.post("/events/{event_id}/badge-template/upload-image")
def upload_badge_image(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Sube una imagen (fondo, o un image_static suelto como un logo) y devuelve el storage_path
    para usar en background_value o en el campo storage_path de un elemento image_static."""
    event = get_event_for_staff(event_id, db, staff)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail=f"Formato no soportado ({ext or 'sin extensión'}) — usa PNG, JPG, WEBP o GIF")

    content = file.file.read(8_000_001)
    from app import safe_limits
    try:
        safe_limits.check_design_image(content, ext)      # I6: tamaño, píxeles y formato real (no solo la extensión)
    except safe_limits.LimitError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    filename = f"{uuid.uuid4().hex}{ext}"
    get_storage().put(badge_asset_key(event.tenant_id, filename), content)

    return {"storage_path": f"{event.tenant_id}/{filename}"}


@router.get("/badge-assets/{tenant_id}/{filename}")
def get_badge_asset(
    tenant_id: str, filename: str, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)
):
    """Sirve una imagen subida para escarapelas — cualquier staff autenticado puede verla (es
    una imagen de fondo/logo, no un dato sensible; el login ya es la barrera real, igual que con
    el resto de la app)."""
    assert_tenant_id(tenant_id, staff)                                          # B12: con ENFORCE_STAFF_TENANT=1 solo los del propio cliente
    if form_client.is_form_client(db, staff):                                  # B12: la cuenta de cliente de formulario solo ve estadísticas, no imágenes de escarapela
        raise HTTPException(status_code=404, detail="No encontrado")
    try:
        key = badge_asset_key(tenant_id, filename)         # nunca se confía en la ruta que manda el cliente
    except ValueError:                                     # «..» en el cliente: no existe, no es un error del servidor (R3-08)
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return get_storage().response(key)


def _may_preprint(staff) -> bool:
    """Preimpresiones (18-nov-2026): solo coordinador o superior (no la comercial pura) puede imprimir escarapelas con el evento en «creado» desde el módulo Preimpresiones."""
    roles = effective_roles(staff)
    return not roles.issubset({"comercial"}) and max(ROLE_HIERARCHY[r] for r in roles) >= ROLE_HIERARCHY["coordinador"]


def _require_printable(db: Session, event, user_id: str, preprint: bool = False, staff=None, certificate: bool = False) -> None:
    """5-nov-2026: con el evento en «creado» no se imprime la escarapela de nadie (igual que no se registra); la persona de prueba es la única excepción, para ensayar la impresión.
    Excepción 18-nov-2026: la ventana de PREIMPRESIÓN (`?preprint=1`, módulo Preimpresiones) sí imprime en «creado», pero solo si quien la abre es coordinador o superior.
    19-nov-2026: fuera de la preimpresión, SOLO se imprime a quien ya está REGISTRADO (acreditado) en este evento; la regla es la misma del Directorio y de la impresión compartida.
    Los certificados (`certificate=True`) no son la escarapela: conservan solo la regla del estado del evento."""
    if testperson.bypasses_gate(event, user_id):
        return
    if preprint and staff is not None and _may_preprint(staff):
        return
    if event.status == "creado":
        raise HTTPException(status_code=403, detail="El evento está en modo «creado»: la escarapela se imprime cuando el evento esté en proceso.")
    if certificate or (testperson.is_test(user_id) and event.status == "en_proceso"):          # la persona de prueba sigue sirviendo para ensayar la impresión con el evento en proceso
        return
    from app.routers.shared_print import _registered, _not_registered_msg
    if not _registered(db, event.id, user_id):
        raise HTTPException(status_code=403, detail=_not_registered_msg(db, event.tenant_id, user_id))


@router.get("/users/{user_id}/badge-print-data")
def get_badge_print_data(
    user_id: str, event_id: int, request: Request, preprint: int = 0, certificate: int = 0, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Datos completos de UNA persona para imprimir su escarapela — incluye extra_fields (los
    campos opcionales) y si tiene foto, que /api/users normal (el Directorio) no manda."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    user = require_person_of_event(db, event, user_id)          # primero si es de ESTE evento (404 igual que si no existiera); después si se le puede imprimir
    _require_printable(db, event, user_id, bool(preprint), staff, bool(certificate))
    has_photo = bool(event.badge_bio_photo_allowed) and get_storage().exists(photo_key(event.tenant_id, user.id))      # interruptor de seguridad (A1): apagado = sin foto biométrica
    attendee = db.query(EventAttendee).filter_by(event_id=event.id, user_id=user.id).first()
    card_url = ""                                                  # 18-nov-2026: enlace público de la tarjeta de la persona (modo «enlace» del QR); vacío si no hay URL pública configurada
    base = publicurl.base(str(request.base_url))
    if base:
        card_url = f"{base}/tarjeta/{contacts.person_card(db, event, user.id).share_token}"
        db.commit()
    return {
        "card_url": card_url,
        "id": user.id, "first_name": user.first_name, "last_name": user.last_name,
        "role": user.role, "entity": user.entity, "phone": user.phone, "email": user.email,
        "opt_1": user.opt_1, "extra_fields": user.get_extras(),
        "optional_field_labels": event.get_optional_labels(),
        "has_photo": has_photo,
        "categories": ", ".join(attendee.get_categories()) if attendee else "",
        **({"code": (attendee.code if attendee and attendee.code else "")} if event.code_enabled else {}),          # 17-nov-2026: el código de la persona (QR) como variable de la escarapela; la clave solo existe con el interruptor activo
        "template_category": template_category_for_user(event, db, user.id),  # qué plantilla usar (ítem 14)
    }


@router.get("/users/{user_id}/photo")
def get_user_photo(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """La foto biométrica de la persona (si existe) — para el elemento image_variable
    (source: "photo") de la escarapela."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    if not event.badge_bio_photo_allowed:
        raise HTTPException(status_code=404, detail="La impresión de la foto biométrica en la escarapela está desactivada en este evento")
    require_person_of_event(db, event, user_id)            # B2: solo la foto de alguien de ESTE evento
    key = photo_key(event.tenant_id, user_id)
    if not get_storage().exists(key):
        raise HTTPException(status_code=404, detail="Esta persona no tiene foto registrada")
    content = crypto.read_bytes(key)                       # la foto puede estar cifrada en reposo
    if content is None:
        raise HTTPException(status_code=404, detail="No se pudo leer la foto")
    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/users/{user_id}/print-count")
def get_print_count(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Cuántas veces se ha impreso la escarapela de esta persona en ESTE evento — para avisar
    antes de repetir (Sprint 2.4 Fase 3, pedido explícito)."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    require_person_of_event(db, event, user_id)
    count = db.query(PrintLog).filter(
        PrintLog.event_id == event.id, PrintLog.user_id == user_id, PrintLog.tenant_id == event.tenant_id
    ).count()
    state = reprint.state_for(db, event, staff, user_id)
    db.commit()                                         # deja anotado un vencimiento, si lo hubo
    blocked = ""                                        # 19-nov-2026: la pantalla avisa ANTES de abrir la ventana (el servidor igual lo exige al pedir los datos y al registrar la impresión)
    try:
        _require_printable(db, event, user_id)
    except HTTPException as exc:
        blocked = str(exc.detail)
    return {"times_printed": count, "blocked": blocked, **state}


@router.post("/users/{user_id}/print-log")
def log_print(
    user_id: str, event_id: int, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("digitador", ("comercial",))),
):
    """Registra una impresión de escarapela — se llama justo antes de abrir la ventana de
    impresión, tras cualquier confirmación necesaria."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)
    require_person_of_event(db, event, user_id)          # primero si es de ESTE evento (404 igual que si no existiera); después si se le puede imprimir
    _require_printable(db, event, user_id)
    # Fase 1B: con la reimpresión deshabilitada, registrar la impresión de alguien ya impreso exige haber gastado un permiso hace un momento (la impresión local la hace el navegador:
    # esto es lo que el servidor puede hacer cumplir; ver docs/1B_reimpresion_permisos.md «control de pantalla»).
    if reprint.is_locked_for(event, staff) and reprint.already_printed(db, event, user_id) and not reprint.recently_used(db, event, staff, user_id):
        raise HTTPException(status_code=403, detail=reprint.DENIED_DETAIL)
    db.add(PrintLog(
        tenant_id=event.tenant_id, user_id=user_id, event_id=event.id, printed_by_staff_id=staff.id,
    ))
    db.commit()
    return {"ok": True}
