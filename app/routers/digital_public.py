"""Escarapela digital PÚBLICA (reunión 2026-09-21, ítem 17): la persona abre el enlace secreto que recibió
(/b/<token>) — sin iniciar sesión — y ve su escarapela con una animación y un reloj en vivo (para
evitar que se rote una captura de pantalla entre asistentes). El token es la única credencial: es largo,
aleatorio y por persona/evento; solo sirve para ver esa escarapela (nunca datos de otras personas)."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, EventAttendee, User
from app.routers.badges import ALLOWED_IMAGE_EXT, _get_or_create_template, _serialize_template, template_category_for_user

router = APIRouter()


def _resolve(db: Session, token: str):
    att = db.query(EventAttendee).filter(EventAttendee.digital_token == token).first()
    event = db.query(Event).filter(Event.id == att.event_id).first() if att else None
    if not att or not event or not event.digital_badge_enabled:
        raise HTTPException(status_code=404, detail="Escarapela no encontrada")
    user = db.query(User).filter(User.id == att.user_id, User.tenant_id == att.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Escarapela no encontrada")
    return att, event, user


@router.get("/b/{token}", response_class=HTMLResponse)
async def digital_badge_page(token: str, request: Request, db: Session = Depends(get_db)):
    from app.main import templates  # import tardío: main.py importa este módulo
    try:
        _resolve(db, token)
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Escarapela no disponible</h3>", status_code=404)
    return templates.TemplateResponse(request=request, name="digital_badge.html", context={"token": token})


@router.get("/b/{token}/data")
async def digital_badge_data(token: str, db: Session = Depends(get_db)):
    att, event, user = _resolve(db, token)
    category = template_category_for_user(event, db, user.id)
    template = _serialize_template(_get_or_create_template(event, db, category))
    has_photo = os.path.isfile(os.path.join("data", event.tenant_id, "known_people", f"{user.id}.jpg"))
    return {
        "event": {"name": event.name, "code": event.event_code},
        "template": template,
        "person": {
            "id": user.id, "first_name": user.first_name, "last_name": user.last_name, "role": user.role,
            "entity": user.entity, "phone": user.phone, "email": user.email, "opt_1": user.opt_1,
            "extra_fields": user.get_extras(), "has_photo": has_photo, "categories": ", ".join(att.get_categories()),
        },
    }


@router.get("/b/{token}/asset/{tenant_id}/{filename}")
async def digital_badge_asset(token: str, tenant_id: str, filename: str, db: Session = Depends(get_db)):
    """Imágenes de la plantilla (fondo/logos) — solo del cliente de esta escarapela."""
    _, event, _ = _resolve(db, token)
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = os.path.join("data", tenant_id, "badge_assets", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path)


@router.get("/b/{token}/photo")
async def digital_badge_photo(token: str, db: Session = Depends(get_db)):
    _, event, user = _resolve(db, token)
    path = os.path.join("data", event.tenant_id, "known_people", f"{user.id}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Sin foto")
    return FileResponse(path)
