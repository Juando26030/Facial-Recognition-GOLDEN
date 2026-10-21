"""Firma de subidas directas del personal y receptor local (ver app/uploads.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import uploads
from app.auth import get_event_for_staff, require_role, require_role_excluding
from app.database import get_db
from app.models import StaffUser
from app.storage import get_storage

router = APIRouter()

# propósito → rol mínimo y roles excluidos (los mismos que exige el endpoint que después procesa el archivo)
_RULES = {
    "bulk_roster": ("coordinador", ("comercial",)),
    "bulk_zip": ("coordinador", ("comercial",)),
    "event_doc": ("coordinador", ()),
    "expense_evidence": ("coordinador", ()),
}


@router.post("/uploads")
def sign_upload(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("digitador"))):
    """`{purpose, event_id, filename, size, content_type}` → `{url, method, headers, token}`."""
    purpose = str(data.get("purpose") or "")
    if purpose not in _RULES:
        raise HTTPException(status_code=400, detail="Tipo de subida no válido")
    require_role_excluding(*_RULES[purpose])(staff)          # 403 con el mismo criterio del endpoint que procesa el archivo
    try:
        event_id = int(data.get("event_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Falta el evento")
    event = get_event_for_staff(event_id, db, staff)
    return uploads.create(purpose, {"e": event.id}, event.tenant_id, str(data.get("filename") or ""),
                          data.get("size"), str(data.get("content_type") or ""))


@router.put("/uploads/local/{token}")
async def local_put(token: str, request: Request):
    """Receptor del PUT cuando el almacenamiento es local (desarrollo y la VM): hace lo que en la nube hace la URL firmada. Asíncrono a
    propósito (como `submit`): lee el cuerpo por partes con tope y guarda en un hilo."""
    store = get_storage()
    if hasattr(store, "signed_put_url"):
        raise HTTPException(status_code=404, detail="No encontrado")
    data = uploads.read_token(token, max_age=uploads.URL_SECONDS)
    limit = data["m"]
    if int(request.headers.get("content-length") or 0) > limit:
        raise HTTPException(status_code=413, detail="El archivo supera el tamaño permitido")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="El archivo supera el tamaño permitido")
        chunks.append(chunk)
    await run_in_threadpool(store.put, data["k"], b"".join(chunks))
    return {"ok": True}
