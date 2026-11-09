"""Historial de cambios del evento (Fase 5; reglas en app/event_history.py).

  GET /api/events/{event_id}/change-history?field=&page=&per_page=   solo lectura, paginado, filtrable por campo. Coordinador del evento, comercial, admin y super_admin;
                                                                      digitador y cliente reciben 403. Sin datos de asistentes."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import event_history
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import StaffUser

router = APIRouter()


@router.get("/events/{event_id}/change-history")
def get_change_history(event_id: int, field: Optional[str] = None, page: int = 1, per_page: int = 25, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("coordinador"))):
    get_event_for_staff(event_id, db, staff)          # tenant y pertenencia al evento (404 si no es suyo)
    return event_history.history(db, event_id, field=(field or "").strip()[:64] or None, page=page, per_page=per_page)
