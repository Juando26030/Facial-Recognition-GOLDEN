"""Descarga PÚBLICA y personal del certificado (ajustes 2026-09-23): cada evento con certificados tiene un
enlace secreto (/c/<token>) que se le comparte a los asistentes. Sin iniciar sesión, la persona escribe su
cédula, ve sus datos para confirmar que es ella y descarga su propio certificado (el PDF se arma en el
navegador con la misma plantilla del editor, igual que el ZIP del coordinador).

Qué se expone: solo el nombre/entidad para confirmar y los campos que la plantilla del certificado realmente
usa — nunca la foto biométrica ni el resto de datos de la persona. El enlace es inadivinable y las consultas
por cédula tienen tope por IP (guardado en Postgres, vale con varios procesos). Solo se genera para quienes tienen Certificado = Sí, y solo con el evento Finalizado. Si la cédula es de alguien del evento sin certificado se le dice "no pidió"; si no está en la base, "no encontramos" (decisión explícita 2026-09-23: se prefirió claridad para el asistente a esconder quién está en el evento)."""
import os
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app import security
from app.auth import get_event_for_staff, require_role_excluding
from app.database import get_db
from app.models import Event, EventAttendee, StaffUser, User
from app.routers.badges import ALLOWED_IMAGE_EXT, _get_or_create_template, _serialize_template

router = APIRouter()        # público, sin prefijo (/c/<token>)
staff_router = APIRouter()  # con login, bajo /api

NOT_FOUND = "No encontramos un certificado para esa cédula en este evento. Revisa el número o consulta con los organizadores."
NOT_REQUESTED = "Usted no pidió certificado para este evento. Si crees que es un error, comunícate con los organizadores."
_MAX_LOOKUPS, _LOOKUP_WINDOW = 30, timedelta(minutes=10)


def _event_by_token(db: Session, token: str) -> Event:
    event = db.query(Event).filter(Event.certificates_token == token).first()
    if not event or not event.certificates_enabled:
        raise HTTPException(status_code=404, detail="Enlace no disponible")
    return event


def _variables_used(template: dict) -> set:
    """Nombres de variable que la plantilla usa de verdad (texto, código de barras, QR)."""
    used = set()
    for el in template.get("elements", []):
        if el.get("variable"):
            used.add(el["variable"])
        used.update(el.get("variables") or [])
    return used


@router.get("/c/{token}", response_class=HTMLResponse)
async def certificate_page(token: str, request: Request, db: Session = Depends(get_db)):
    from app.main import templates  # import tardío: main.py importa este módulo
    try:
        event = _event_by_token(db, token)
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Enlace no disponible</h3>", status_code=404)
    return templates.TemplateResponse(request=request, name="certificate_public.html", context={
        "token": token, "event_name": event.name, "finalized": event.status == "finalizado",
    })


@router.get("/c/{token}/lookup")
async def certificate_lookup(token: str, id: str, request: Request, db: Session = Depends(get_db)):
    security.enforce_public_limit(db, request, "cert_lookup", token, _MAX_LOOKUPS, _LOOKUP_WINDOW)
    event = _event_by_token(db, token)
    if event.status != "finalizado":
        raise HTTPException(status_code=409, detail="Los certificados estarán disponibles cuando el evento haya finalizado.")
    wanted = id.strip()
    candidates = [wanted, re.sub(r"[\s.,]", "", wanted)]  # tolera "1.016.100.329" o con espacios
    user = att = None
    in_event = False  # ¿la cédula pertenece a alguien de ESTE evento? (para decir "no pidió" y no "no existe")
    for candidate in dict.fromkeys(c for c in candidates if c):
        u = db.query(User).filter(User.id == candidate, User.tenant_id == event.tenant_id).first()
        if not u:
            continue
        a = db.query(EventAttendee).filter_by(event_id=event.id, user_id=candidate).first()
        if a:
            in_event = True
            if a.certificate:
                user, att = u, a
                break
    if not user:
        raise HTTPException(status_code=404, detail=NOT_REQUESTED if in_event else NOT_FOUND)

    template = _serialize_template(_get_or_create_template(event, db, None, "certificate"))
    needed = _variables_used(template)
    person = {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "has_photo": False}
    fields = {"role": user.role, "entity": user.entity, "phone": user.phone, "email": user.email, "opt_1": user.opt_1,
              "categories": ", ".join(att.get_categories())}
    person.update({k: v for k, v in fields.items() if k in needed})
    person["extra_fields"] = {k: v for k, v in user.get_extras().items() if k in needed}
    return {
        "event": {"name": event.name, "code": event.event_code},
        "template": template,
        "person": person,
        "display": {"name": f"{user.first_name or ''} {user.last_name or ''}".strip(), "entity": user.entity or ""},
    }


@router.get("/c/{token}/asset/{tenant_id}/{filename}")
async def certificate_asset(token: str, tenant_id: str, filename: str, db: Session = Depends(get_db)):
    """Imágenes de la plantilla (fondo/logos) — solo del cliente de este evento."""
    event = _event_by_token(db, token)
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = os.path.join("data", tenant_id, "badge_assets", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path)


def _public_url(request: Request, event: Event) -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
    return f"{base}/c/{event.certificates_token}"


@staff_router.get("/events/{event_id}/certificates/public-link")
async def get_public_link(
    event_id: int, request: Request, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """El enlace público del evento (o `null` si todavía no se ha generado)."""
    event = get_event_for_staff(event_id, db, staff)
    return {"url": _public_url(request, event) if event.certificates_token else None}


@staff_router.post("/events/{event_id}/certificates/public-link")
async def create_public_link(
    event_id: int, request: Request, regenerate: bool = False, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role_excluding("coordinador", ("comercial",))),
):
    """Genera el enlace público para que cada persona descargue su certificado. Si ya existe se devuelve el
    mismo; con `regenerate=true` se cambia (el enlace anterior deja de funcionar)."""
    event = get_event_for_staff(event_id, db, staff)
    if not event.certificates_enabled:
        raise HTTPException(status_code=400, detail="El módulo de certificados no está activado en este evento")
    if regenerate or not event.certificates_token:
        event.certificates_token = secrets.token_urlsafe(18)
        db.commit()
    return {"url": _public_url(request, event)}
