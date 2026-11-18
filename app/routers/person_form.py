"""Formulario de persona diseñado por el admin (Fase 1A, pieza 5): ver app/personform.py. Endpoints `def` (acceso síncrono a la base).
GET lo lee cualquier personal del evento (el quiosco lo pide para su copia sin red); PUT lo guarda solo admin+. Con PERSON_FORM_ENABLED apagado: GET dice «apagado» y PUT responde 404."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import personform
from app.auth import get_current_staff, get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser
from app.routers import parametros

router = APIRouter()


def _json(data: dict) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.get("/events/{event_id}/person-form")
def get_person_form(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    event = get_event_for_staff(event_id, db, staff)
    if not personform.env_enabled():
        return _json({"env_enabled": False, "enabled": False, "definition": None})
    configs = parametros.field_configs_for_event(db, event)
    return _json({**personform.view(db, event, configs), "fields": configs, "categories": event.get_categories()})


@router.put("/events/{event_id}/person-form")
def put_person_form(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    if not personform.env_enabled():
        raise HTTPException(status_code=404, detail="El formulario de persona no está habilitado en este entorno")
    event = get_event_for_staff(event_id, db, staff)
    configs = parametros.field_configs_for_event(db, event)
    try:
        personform.save(db, event, data, configs)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    configs = parametros.field_configs_for_event(db, event)          # lo obligatorio recién escrito
    return _json({**personform.view(db, event, configs), "fields": configs, "categories": event.get_categories()})
