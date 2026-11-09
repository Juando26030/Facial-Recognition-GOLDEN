"""Escarapela digital PÚBLICA (reunión 2026-09-21, ítem 17): la persona abre el enlace secreto que recibió
(/b/<token>) — sin iniciar sesión — y ve su escarapela con una animación y un reloj en vivo (para
evitar que se rote una captura de pantalla entre asistentes). El token es la única credencial: es largo,
aleatorio y por persona/evento; solo sirve para ver esa escarapela (nunca datos de otras personas)."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app import crypto, digital_fields, dynamic_qr, publicurl, wallet
from app.storage import badge_asset_key, get_storage, photo_key
from app.database import get_db
from app.models import Event, EventAttendee, User
from app.routers.certificates_public import _variables_used
from app.routers.badges import ALLOWED_IMAGE_EXT, _get_or_create_template, _serialize_template, template_category_for_user

router = APIRouter()


def _resolve(db: Session, token: str):
    att = db.query(EventAttendee).filter(EventAttendee.digital_token == token).first()
    event = db.query(Event).filter(Event.id == att.event_id).first() if att else None
    if not att or not event or not event.digital_badge_enabled or event.archived_at is not None or event.data_archived_at is not None:          # R2-2: archivar el evento o su base (L7) cierra también el enlace
        raise HTTPException(status_code=404, detail="Escarapela no encontrada")
    user = db.query(User).filter(User.id == att.user_id, User.tenant_id == att.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Escarapela no encontrada")
    return att, event, user


@router.get("/b/{token}", response_class=HTMLResponse)
def digital_badge_page(token: str, request: Request, db: Session = Depends(get_db)):
    from app.main import templates  # import tardío: main.py importa este módulo
    try:
        _resolve(db, token)
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Escarapela no disponible</h3>", status_code=404)
    return templates.TemplateResponse(request=request, name="digital_badge.html", context={"token": token})


def _extra_list(db: Session, event: Event, person: dict, keys: set) -> list:
    """Con lista elegida por el evento: los datos marcados con su rótulo, para mostrarlos bajo el nombre. Sin lista (por defecto) no hay bloque: la plantilla lo dice todo."""
    if digital_fields.parse_stored(event.digital_badge_fields) is None:
        return []
    from app.routers.parametros import field_labels_for_event  # import tardío: parametros importa mucho
    labels = field_labels_for_event(db, event)
    return digital_fields.display_list(keys, person, labels, digital_fields.allowed_keys(event.get_optional_labels()))


@router.get("/b/{token}/contact")
def digital_badge_contact(token: str, db: Session = Depends(get_db)):
    """Fase 8: de la escarapela digital a «Compartir mis datos con expositores» (enlace privado de ESA persona y evento)."""
    from fastapi.responses import RedirectResponse
    from app import contacts
    att, event, user = _resolve(db, token)
    card = contacts.person_card(db, event, user.id)
    db.commit()
    return RedirectResponse(f"/contacto/{card.token}", status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/b/{token}/data")
def digital_badge_data(token: str, db: Session = Depends(get_db)):
    att, event, user = _resolve(db, token)
    category = template_category_for_user(event, db, user.id)
    template = _serialize_template(_get_or_create_template(event, db, category))
    has_photo = bool(event.badge_bio_photo_allowed) and get_storage().exists(photo_key(event.tenant_id, user.id))      # interruptor de seguridad (A1)
    needed = _variables_used(template)
    labels = event.get_optional_labels()
    keys = digital_fields.visible_keys(digital_fields.parse_stored(event.digital_badge_fields), needed, labels)          # A3: sin lista = solo lo que pinta la plantilla y sin correo ni teléfono; con lista = lo que el evento eligió
    person = {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "has_photo": has_photo}          # «id» solo alimenta el QR de la escarapela; no es un dato elegible
    person.update(digital_fields.build_person(user, att, keys))
    return JSONResponse({
        "event": {"name": event.name, "code": event.event_code},
        "template": template,
        "person": person,
        "extra_list": _extra_list(db, event, person, keys),
        "wallet": wallet.availability(),          # sin credenciales de Wallet no se pinta ningún botón
    }, headers={"Cache-Control": "private, no-store"})        # puede traer teléfono/correo: nunca en cachés intermedias


@router.get("/b/{token}/qr")
def digital_badge_qr(token: str, db: Session = Depends(get_db)):
    """QR DINÁMICO de la credencial: los códigos de las próximas ventanas de 30 s (la página los rota por su reloj y vuelve a pedir antes de que se acaben). Firma y vigencia se validan en el servidor al escanear."""
    att, _, _ = _resolve(db, token)
    return JSONResponse(dynamic_qr.batch(att.id, att.digital_token), headers={"Cache-Control": "private, no-store"})


def _wallet_args(db: Session, token: str) -> dict:
    att, event, user = _resolve(db, token)
    return {"att_id": att.id, "person_name": f"{user.first_name or ''} {user.last_name or ''}".strip(), "event_name": event.name, "code": dynamic_qr.make_static(att.id, att.digital_token)}


@router.get("/b/{token}/wallet/google")
def digital_badge_google_wallet(token: str, db: Session = Depends(get_db)):
    """Enlace «Guardar en Google Wallet» (JWT firmado). 404 si Google Wallet no está configurado."""
    args = _wallet_args(db, token)
    if not wallet.availability()["google"]:
        raise HTTPException(status_code=404, detail="Google Wallet no está disponible")
    return JSONResponse({"url": wallet.google_save_url(origin=publicurl.configured(), **args)}, headers={"Cache-Control": "private, no-store"})


@router.get("/b/{token}/wallet/apple")
def digital_badge_apple_wallet(token: str, db: Session = Depends(get_db)):
    """Archivo .pkpass para Apple Wallet. 404 si Apple Wallet no está configurado."""
    args = _wallet_args(db, token)
    if not wallet.availability()["apple"]:
        raise HTTPException(status_code=404, detail="Apple Wallet no está disponible")
    return Response(wallet.apple_pkpass(**args), media_type="application/vnd.apple.pkpass", headers={"Cache-Control": "private, no-store", "Content-Disposition": 'attachment; filename="credencial.pkpass"'})


@router.get("/b/{token}/asset/{tenant_id}/{filename}")
def digital_badge_asset(token: str, tenant_id: str, filename: str, db: Session = Depends(get_db)):
    """Imágenes de la plantilla (fondo/logos) — solo del cliente de esta escarapela."""
    _, event, _ = _resolve(db, token)
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return get_storage().response(badge_asset_key(tenant_id, safe))


@router.get("/b/{token}/photo")
def digital_badge_photo(token: str, db: Session = Depends(get_db)):
    _, event, user = _resolve(db, token)
    key = photo_key(event.tenant_id, user.id)
    if not event.badge_bio_photo_allowed or not get_storage().exists(key):
        raise HTTPException(status_code=404, detail="Sin foto")
    content = crypto.read_bytes(key)                       # la foto puede estar cifrada en reposo
    if content is None:
        raise HTTPException(status_code=404, detail="Sin foto")
    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
