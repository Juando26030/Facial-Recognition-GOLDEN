"""Plantilla de evento (Fase 2, entrega 2): GET la lee el personal con acceso a crear eventos y al calendario (coordinador o más); PUT la edita solo admin y super_admin.
Contrato completo en docs/FASE_2_ALCANCE.md («Plantilla de evento: modelo y contratos»); lógica en app/event_template.py y app/event_template_svc.py."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import event_template as et
from app import event_template_svc as svc
from app.auth import require_role
from app.database import get_db
from app.models import StaffUser

router = APIRouter()


@router.get("/event-template")
def get_event_template(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    """La plantilla vigente (o la de fábrica, `version` 0 e `is_default` true, si nadie la ha editado) y el catálogo de tipos/interruptores/límites. No escribe nada."""
    return svc.public_view(db)


@router.put("/event-template")
def put_event_template(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Guarda la plantilla completa. Cuerpo: {version, fields, creation_layout, calendar_layout}. 400 con el motivo si algo no vale; 409 si otro administrador guardó antes."""
    if len(json.dumps(data, ensure_ascii=False)) > et.MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="La plantilla es demasiado grande")
    return svc.save(db, staff, data)


@router.get("/event-template/revisions")
def get_event_template_revisions(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    """Auditoría simple: quién guardó cada versión y cuándo (las últimas 20)."""
    return {"revisions": svc.revisions(db)}
