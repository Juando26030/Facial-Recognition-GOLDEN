"""Captura de firma (reunión 2026-09-21, ítem 10): la firma dibujada en el formulario de una
persona se guarda como PNG por (evento, persona, campo) en
`data/<tenant>/signatures/<event_id>/<cédula>__<campo>.png` — mismo patrón de archivos en disco que
las fotos de `known_people`, sin tabla nueva. Es POR EVENTO a propósito (el mismo asistente firma
de nuevo en otro evento), a diferencia de `User.extra_fields` que es por tenant."""
import base64
import glob
import io
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser, User

router = APIRouter()

MAX_SIGNATURE_BYTES = 600_000


def signature_path(tenant_id: str, event_id: int, user_id: str, field_key: str) -> str:
    return os.path.join("data", tenant_id, "signatures", str(event_id), f"{user_id}__{field_key}.png")


def delete_signatures(tenant_id: str, event_id: int, user_id: str) -> None:
    for path in glob.glob(os.path.join("data", tenant_id, "signatures", str(event_id), f"{user_id}__*.png")):
        os.remove(path)


def rename_signatures(tenant_id: str, old_id: str, new_id: str) -> None:
    """Cambio de cédula: las firmas de esa persona (en todos los eventos del cliente) la siguen."""
    for path in glob.glob(os.path.join("data", tenant_id, "signatures", "*", f"{old_id}__*.png")):
        folder, name = os.path.split(path)
        os.rename(path, os.path.join(folder, new_id + name[len(old_id):]))


def _resolve(db: Session, event_id: int, user_id: str, field_key: str, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    if not field_key.startswith("opcional_"):
        raise HTTPException(status_code=400, detail="Campo de firma inválido")
    user = db.query(User).filter(User.id == user_id, User.tenant_id == event.tenant_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Persona no encontrada")
    return event


@router.put("/events/{event_id}/users/{user_id}/signature/{field_key}")
async def put_signature(
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
    path = signature_path(event.tenant_id, event_id, user_id, field_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)
    return {"message": "Firma guardada"}


@router.get("/events/{event_id}/users/{user_id}/signature/{field_key}")
async def get_signature(
    event_id: int, user_id: str, field_key: str, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    event = _resolve(db, event_id, user_id, field_key, staff)
    path = signature_path(event.tenant_id, event_id, user_id, field_key)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Sin firma")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.delete("/events/{event_id}/users/{user_id}/signature/{field_key}")
async def delete_signature(
    event_id: int, user_id: str, field_key: str, db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    event = _resolve(db, event_id, user_id, field_key, staff)
    path = signature_path(event.tenant_id, event_id, user_id, field_key)
    if os.path.isfile(path):
        os.remove(path)
    return {"message": "Firma eliminada"}
