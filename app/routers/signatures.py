"""Captura de firma (reunión 2026-09-21, ítem 10): la firma dibujada en el formulario de una
persona se guarda como PNG por (evento, persona, campo) en
`data/<tenant>/signatures/<event_id>/<cédula>__<campo>.png` — mismo patrón de archivos en disco que
las fotos de `known_people`, sin tabla nueva. Es POR EVENTO a propósito (el mismo asistente firma
de nuevo en otro evento), a diferencia de `User.extra_fields` que es por tenant."""
import base64
import io
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser, User
from app.storage import get_storage, key_of

router = APIRouter()

MAX_SIGNATURE_BYTES = 600_000


def signature_key(tenant_id: str, event_id: int, user_id: str, field_key: str) -> str:
    return key_of(tenant_id, "signatures", event_id, f"{user_id}__{field_key}.png")


def delete_signatures(tenant_id: str, event_id: int, user_id: str) -> None:
    for key in get_storage().list(key_of(tenant_id, "signatures", event_id)):
        if key.rsplit("/", 1)[-1].startswith(f"{user_id}__"):
            get_storage().delete(key)


def rename_signatures(tenant_id: str, old_id: str, new_id: str) -> None:
    """Cambio de cédula: las firmas de esa persona (en todos los eventos del cliente) la siguen."""
    for key in get_storage().list(key_of(tenant_id, "signatures")):
        folder, name = key.rsplit("/", 1)
        if name.startswith(f"{old_id}__"):
            get_storage().move(key, f"{folder}/{new_id}{name[len(old_id):]}")


def _resolve(db: Session, event_id: int, user_id: str, field_key: str, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    if not field_key.startswith("opcional_"):
        raise HTTPException(status_code=400, detail="Campo de firma inválido")
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    return event


@router.put("/events/{event_id}/users/{user_id}/signature/{field_key}")
def put_signature(
    event_id: int, user_id: str, field_key: str, data: dict, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    event = _resolve(db, event_id, user_id, field_key, staff)
    raw = str(data.get("image", ""))
    if not raw.startswith("data:image/png;base64,"):
        raise HTTPException(status_code=400, detail="La firma debe enviarse como imagen PNG (data URL)")
    try:
        blob = base64.b64decode(raw.split(",", 1)[1], validate=True)
        if len(blob) > MAX_SIGNATURE_BYTES:
            raise ValueError("demasiado grande")
        img = Image.open(io.BytesIO(blob))
        img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="La imagen de la firma no es válida")
    get_storage().put(signature_key(event.tenant_id, event_id, user_id, field_key), blob)
    return {"message": "Firma guardada"}


@router.get("/events/{event_id}/users/{user_id}/signature/{field_key}")
def get_signature(
    event_id: int, user_id: str, field_key: str, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    event = _resolve(db, event_id, user_id, field_key, staff)
    key = signature_key(event.tenant_id, event_id, user_id, field_key)
    if not get_storage().exists(key):
        raise HTTPException(status_code=404, detail="Sin firma")
    return get_storage().response(key, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/events/{event_id}/users/{user_id}/signature/{field_key}")
def delete_signature(
    event_id: int, user_id: str, field_key: str, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    event = _resolve(db, event_id, user_id, field_key, staff)
    get_storage().delete(signature_key(event.tenant_id, event_id, user_id, field_key))
    return {"message": "Firma eliminada"}
