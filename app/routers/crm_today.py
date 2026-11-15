"""API del CRM, etapa C4: «Mi día», tableros y ganar una oportunidad (cliente + evento). Todo bajo /api/crm.

* Con `CRM_ENABLED` apagado TODA ruta responde 404. Ver: comercial, admin y super_admin. El comercial solo ve lo suyo; el admin ve todo el equipo y puede filtrar por responsable.
* Endpoints `def`; solo lectura salvo `win`; sin sondeos: una carga por pantalla.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crm import opportunities as opp_svc, today as today_svc, won
from app.database import get_db
from app.models import StaffUser
from app.routers import crm as crm_router
from app.routers.crm import _run, view_staff

router = APIRouter(prefix="/crm", dependencies=[Depends(crm_router._require_crm_enabled)])
router.dependencies.append(Depends(crm_router._check_path_ids))


@router.get("/today")
def my_day(db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return today_svc.my_day(db, staff.id)


@router.get("/calendar")
def calendar(start: date, end: date, owner_id: Optional[int] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Lo del CRM para el Calendario: actividades, cierres esperados y cotizaciones por vencer. El comercial solo ve lo suyo; el admin ve todo el equipo o filtra por responsable."""
    if staff.role in ("admin", "super_admin"):
        owner = owner_id if owner_id and 0 < owner_id <= crm_router.svc.MAX_ID else None
    else:
        owner = staff.id
    return today_svc.calendar_range(db, owner_id=owner, start=start, end=end)


@router.get("/dashboards")
def dashboards(days: int = 90, owner_id: Optional[int] = None, pipeline_id: Optional[int] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    is_admin = staff.role in ("admin", "super_admin")
    if is_admin:
        owner = owner_id if owner_id and 0 < owner_id <= crm_router.svc.MAX_ID else None
    else:
        owner = staff.id          # el comercial solo ve lo suyo
    return today_svc.dashboards(db, owner_id=owner, days=days, pipeline_id=pipeline_id)


@router.post("/opportunities/{opportunity_id}/win")
def win_opportunity(opportunity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Gana la oportunidad y crea el cliente (si falta) y el evento con el mismo número; si ya estaba ganada sin evento, solo crea el evento."""
    def work():
        o = opp_svc.get_opportunity(db, opportunity_id)
        event = won.win(db, staff, o)
        out = opp_svc.detail(db, o)
        out["event"] = {"id": event.id, "event_code": event.event_code, "name": event.name}
        return out
    return _run(db, work)
