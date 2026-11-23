"""API de herramientas del CRM (C3): búsqueda global, filtros guardados y exportación CSV. Con CRM_ENABLED apagado responde 404."""
from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.orm import Session

from app import audit_actions
from app.crm import tools
from app.database import get_db
from app.models import StaffUser
from app.routers import crm as crm_router
from app.routers.crm import _run, admin_staff, view_staff

router = APIRouter(prefix="/crm", tags=["crm-tools"], dependencies=[Depends(crm_router._require_crm_enabled)])
router.dependencies.append(Depends(crm_router._check_path_ids))


@router.get("/search")
def global_search(q: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: tools.search(db, q))


@router.get("/filters")
def list_filters(scope: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return {"items": tools.list_filters(db, staff, scope)}


@router.post("/filters")
def create_filter(data: dict = Body(...), db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: tools.serialize_filter(tools.create_filter(db, staff, data), staff.id))


@router.delete("/filters/{filter_id}")
def delete_filter(filter_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        tools.delete_filter(db, staff, filter_id)
        return {"message": "Filtro borrado"}
    return _run(db, work)


@router.get("/export/{scope}")
def export(scope: str, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    """Solo administradores. La auditoría guarda el tipo y el NÚMERO de filas, nunca los datos."""
    def work():
        data, n = tools.export_csv(db, tools.clean_scope(scope))
        audit_actions.record(db, staff, "export", "crm_export", 0, scope, f"{n} filas")
        return data
    data = _run(db, work)
    return Response(content=data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="crm-{scope}.csv"', "Cache-Control": "no-store"})
