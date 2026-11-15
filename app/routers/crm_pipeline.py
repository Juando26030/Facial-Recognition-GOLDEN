"""API del CRM, etapa C2: embudos y etapas, oportunidades (lista y tablero), leads con conversión y actividades. Todo bajo /api/crm.

* Con `CRM_ENABLED` apagado TODA ruta responde 404 (igual que el resto del CRM).
* Ver y editar: comercial, admin y super_admin. Embudos, archivar/restaurar y suprimir: admin y super_admin.
* Endpoints `def`; mensajes en español; respuestas como dicts planos. Nada de datos personales en logs ni en la auditoría (solo ids, códigos y conteos).
"""
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions
from app.crm import activities as act_svc, lead_erase, leads as lead_svc, opportunities as opp_svc, pipeline as pipe_svc
from app.crm.pipeline_rules import ACTIVITY_KINDS, CURRENCIES, LEAD_STATUSES, RESULTS
from app.database import get_db
from app.models import CrmChangeLog, StaffUser
from app.routers import crm as crm_router
from app.routers.crm import EraseIn, _check_erase, _erase_detail, _run, admin_staff, view_staff

router = APIRouter(prefix="/crm", dependencies=[Depends(crm_router._require_crm_enabled)])
router.dependencies.append(Depends(crm_router._check_path_ids))
svc = crm_router.svc

Number = Union[int, float, str]


# ------------------------------------------------------------------ modelos de entrada
class PipelineIn(BaseModel):
    name: Optional[str] = None


class StageIn(BaseModel):
    name: Optional[str] = None
    probability: Optional[Number] = None
    kind: Optional[str] = None


class ReorderIn(BaseModel):
    stage_ids: List[int]


class OpportunityIn(BaseModel):
    name: Optional[str] = None
    account_id: Optional[Union[int, str]] = None
    pipeline_id: Optional[Union[int, str]] = None
    stage_id: Optional[Union[int, str]] = None
    amount: Optional[Number] = None
    currency: Optional[str] = None
    probability: Optional[Number] = None
    expected_close: Optional[str] = None
    event_start: Optional[str] = None
    opp_type: Optional[str] = None
    source: Optional[str] = None
    next_step: Optional[str] = None
    description: Optional[str] = None
    city: Optional[str] = None
    owner_staff_id: Optional[Union[int, str]] = None
    primary_contact_id: Optional[Union[int, str]] = None
    updated_at: Optional[str] = None


class MoveIn(BaseModel):
    stage_id: int
    lost_reason: Optional[str] = None
    updated_at: Optional[str] = None


class LeadIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    owner_staff_id: Optional[Union[int, str]] = None
    confirm_duplicate: bool = False
    updated_at: Optional[str] = None


class ConvertIn(BaseModel):
    account_id: Optional[Union[int, str]] = None
    account_name: Optional[str] = None
    confirm_duplicate: bool = False
    create_opportunity: bool = False
    name: Optional[str] = None
    amount: Optional[Number] = None
    currency: Optional[str] = None
    expected_close: Optional[str] = None
    event_start: Optional[str] = None
    city: Optional[str] = None
    opp_type: Optional[str] = None


class ActivityIn(BaseModel):
    kind: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    remind_at: Optional[str] = None
    account_id: Optional[Union[int, str]] = None
    contact_id: Optional[Union[int, str]] = None
    lead_id: Optional[Union[int, str]] = None
    opportunity_id: Optional[Union[int, str]] = None
    owner_staff_id: Optional[Union[int, str]] = None
    updated_at: Optional[str] = None


class CompleteIn(BaseModel):
    result: Optional[str] = None


def _fields(model: BaseModel, drop: tuple = ()) -> dict:
    return {k: v for k, v in model.dict(exclude_unset=True).items() if k not in drop}


def _is_admin(staff: StaffUser) -> bool:
    return staff.role in ("admin", "super_admin")


# ------------------------------------------------------------------ metadatos
@router.get("/pipeline/meta")
def pipeline_meta(db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Listas cerradas para formularios y filtros: tipos y resultados de actividad, monedas, estados de lead y los embudos vigentes con sus etapas (del catálogo en memoria)."""
    return {"activity_kinds": [{"key": k, "label": v} for k, v in ACTIVITY_KINDS.items()], "results": [{"key": k, "label": v} for k, v in RESULTS.items()],
            "currencies": list(CURRENCIES), "lead_statuses": list(LEAD_STATUSES), "pipelines": pipe_svc.live_catalog(db), "is_admin": _is_admin(staff)}


# ------------------------------------------------------------------ embudos y etapas (admin)
@router.get("/pipelines")
def list_pipelines(db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return {"pipelines": pipe_svc.catalog(db, fresh=True)}


@router.post("/pipelines")
def create_pipeline(data: PipelineIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = pipe_svc.create_pipeline(db, staff, _fields(data))
        audit_actions.record(db, staff, "create", "crm_pipeline", p.id, p.name)
        return {"id": p.id, "name": p.name}
    return _run(db, work)


@router.put("/pipelines/{pipeline_id}")
def rename_pipeline(pipeline_id: int, data: PipelineIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = pipe_svc.rename_pipeline(db, pipeline_id, _fields(data))
        return {"id": p.id, "name": p.name}
    return _run(db, work)


@router.post("/pipelines/{pipeline_id}/default")
def default_pipeline(pipeline_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = pipe_svc.set_default(db, pipeline_id)
        return {"id": p.id, "is_default": True}
    return _run(db, work)


@router.post("/pipelines/{pipeline_id}/archive")
def archive_pipeline(pipeline_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = pipe_svc.set_pipeline_archived(db, pipeline_id, True)
        audit_actions.record(db, staff, "archive", "crm_pipeline", p.id, p.name)
        return {"id": p.id, "archived": True}
    return _run(db, work)


@router.post("/pipelines/{pipeline_id}/restore")
def restore_pipeline(pipeline_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        p = pipe_svc.set_pipeline_archived(db, pipeline_id, False)
        return {"id": p.id, "archived": False}
    return _run(db, work)


@router.post("/pipelines/{pipeline_id}/stages")
def create_stage(pipeline_id: int, data: StageIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        s = pipe_svc.create_stage(db, pipeline_id, _fields(data))
        return {"id": s.id, "name": s.name, "kind": s.kind, "probability": s.probability, "position": s.position}
    return _run(db, work)


@router.post("/pipelines/{pipeline_id}/stages/reorder")
def reorder_stages(pipeline_id: int, data: ReorderIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        pipe_svc.reorder_stages(db, pipeline_id, data.stage_ids)
        return {"message": "Orden guardado"}
    return _run(db, work)


@router.put("/stages/{stage_id}")
def update_stage(stage_id: int, data: StageIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        s = pipe_svc.update_stage(db, stage_id, _fields(data))
        return {"id": s.id, "name": s.name, "kind": s.kind, "probability": s.probability, "position": s.position}
    return _run(db, work)


@router.post("/stages/{stage_id}/archive")
def archive_stage(stage_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        s = pipe_svc.set_stage_archived(db, stage_id, True)
        return {"id": s.id, "archived": True}
    return _run(db, work)


@router.post("/stages/{stage_id}/restore")
def restore_stage(stage_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        s = pipe_svc.set_stage_archived(db, stage_id, False)
        return {"id": s.id, "archived": False}
    return _run(db, work)


# ------------------------------------------------------------------ oportunidades
def _filters(staff: StaffUser, **kw) -> dict:
    if kw.get("archived") and not _is_admin(staff):
        raise svc.CrmError("Solo un administrador ve las oportunidades archivadas.", 403)
    return opp_svc.parse_filters(**kw)


@router.get("/opportunities/board")
def board(pipeline_id: Optional[int] = None, stage_id: Optional[int] = None, offset: int = 0, q: str = "", owner_id: Optional[int] = None, account_id: Optional[int] = None,
          currency: str = "", close_from: Optional[str] = None, close_to: Optional[str] = None, no_activity: bool = False, archived: bool = False,
          db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Tablero Kanban: dos consultas por carga (totales por etapa y moneda; tarjetas con row_number). `stage_id` + `offset` piden solo «ver más» de una columna."""
    return _run(db, lambda: opp_svc.board(db, pipeline_id, _filters(staff, owner_id=owner_id, account_id=account_id, currency=currency, close_from=close_from, close_to=close_to,
                                                                      no_activity=no_activity, archived=archived, q=q), stage_id=stage_id, offset=offset))


@router.get("/opportunities")
def list_opportunities(pipeline_id: Optional[int] = None, stage_id: Optional[int] = None, outcome: str = "", q: str = "", owner_id: Optional[int] = None, account_id: Optional[int] = None,
                       currency: str = "", close_from: Optional[str] = None, close_to: Optional[str] = None, no_activity: bool = False, archived: bool = False,
                       page: int = 1, size: int = svc.PAGE_SIZE, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: opp_svc.list_opportunities(db, _filters(staff, owner_id=owner_id, account_id=account_id, currency=currency, close_from=close_from, close_to=close_to,
                                                                    no_activity=no_activity, archived=archived, q=q), pipeline_id=pipeline_id, stage_id=stage_id, outcome=outcome, page=page, size=size))


@router.post("/opportunities")
def create_opportunity(data: OpportunityIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        o = opp_svc.create_opportunity(db, staff, _fields(data, ("updated_at",)))
        return opp_svc.detail(db, o)
    return _run(db, work)


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: opp_svc.detail(db, opp_svc.get_opportunity(db, opportunity_id)))


@router.put("/opportunities/{opportunity_id}")
def update_opportunity(opportunity_id: int, data: OpportunityIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        o = opp_svc.get_opportunity(db, opportunity_id)
        opp_svc.update_opportunity(db, staff, o, _fields(data, ("updated_at",)), data.updated_at)
        return opp_svc.detail(db, o)
    return _run(db, work)


@router.post("/opportunities/{opportunity_id}/move")
def move_opportunity(opportunity_id: int, data: MoveIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        o = opp_svc.get_opportunity(db, opportunity_id)
        opp_svc.move_stage(db, staff, o, data.stage_id, lost_reason=data.lost_reason, expected_updated_at=data.updated_at)
        return opp_svc.detail(db, o)
    return _run(db, work)


@router.post("/opportunities/{opportunity_id}/archive")
def archive_opportunity(opportunity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        o = opp_svc.set_archived(db, staff, opp_svc.get_opportunity(db, opportunity_id), True)
        audit_actions.record(db, staff, "archive", "crm_opportunity", o.id, str(o.code))
        return opp_svc.detail(db, o)
    return _run(db, work)


@router.post("/opportunities/{opportunity_id}/restore")
def restore_opportunity(opportunity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        o = opp_svc.set_archived(db, staff, opp_svc.get_opportunity(db, opportunity_id), False)
        audit_actions.record(db, staff, "restore", "crm_opportunity", o.id, str(o.code))
        return opp_svc.detail(db, o)
    return _run(db, work)


@router.get("/opportunities/{opportunity_id}/history")
def opportunity_history(opportunity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Cambios de la oportunidad (hasta 200). El texto libre (descripción, siguiente paso) muestra QUE cambió, nunca su contenido."""
    opp_svc.get_opportunity(db, opportunity_id)
    rows = (db.query(CrmChangeLog, StaffUser.full_name).join(StaffUser, StaffUser.id == CrmChangeLog.changed_by_id, isouter=True)
            .filter(CrmChangeLog.entity == "opportunity", CrmChangeLog.entity_id == opportunity_id).order_by(CrmChangeLog.changed_at.desc(), CrmChangeLog.id.desc()).limit(200).all())
    return [{"field": r.field_key, "old": r.old_value, "new": r.new_value, "by": name, "at": r.changed_at.isoformat()} for r, name in rows]


# ------------------------------------------------------------------ leads
@router.get("/leads")
def list_leads(q: str = "", status: str = "", owner_id: Optional[int] = None, archived: bool = False, page: int = 1, size: int = svc.PAGE_SIZE,
               db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    if archived and not _is_admin(staff):
        raise HTTPException(status_code=403, detail="Solo un administrador ve los leads archivados.")
    return lead_svc.list_leads(db, q=q, status=status, owner_id=owner_id, archived=archived, page=page, size=size)


@router.post("/leads")
def create_lead(data: LeadIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        lead = lead_svc.create_lead(db, staff, _fields(data, ("confirm_duplicate", "updated_at")), confirm_duplicate=data.confirm_duplicate)
        return lead_svc.detail(db, lead)
    return _run(db, work)


@router.get("/leads/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: lead_svc.detail(db, lead_svc.get_lead(db, lead_id)))


@router.put("/leads/{lead_id}")
def update_lead(lead_id: int, data: LeadIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        lead = lead_svc.get_lead(db, lead_id)
        lead_svc.update_lead(db, staff, lead, _fields(data, ("confirm_duplicate", "updated_at")), data.updated_at)
        return lead_svc.detail(db, lead)
    return _run(db, work)


@router.post("/leads/{lead_id}/convert")
def convert_lead(lead_id: int, data: ConvertIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        lead = lead_svc.get_lead(db, lead_id)
        result = lead_svc.convert(db, staff, lead, _fields(data))
        audit_actions.record(db, staff, "convert", "crm_lead", lead.id, None, f"cuenta {result['account_id']}")
        return result
    return _run(db, work)


@router.post("/leads/{lead_id}/discard")
def discard_lead(lead_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: lead_svc.detail(db, lead_svc.discard(db, staff, lead_svc.get_lead(db, lead_id))))


@router.post("/leads/{lead_id}/archive")
def archive_lead(lead_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: lead_svc.detail(db, lead_svc.set_archived(db, staff, lead_svc.get_lead(db, lead_id), True)))


@router.post("/leads/{lead_id}/restore")
def restore_lead(lead_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return _run(db, lambda: lead_svc.detail(db, lead_svc.set_archived(db, staff, lead_svc.get_lead(db, lead_id), False)))


@router.get("/leads/{lead_id}/erase-preview")
def erase_lead_preview(lead_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    counts = lead_erase.preview_lead(db, lead_id)
    if counts is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"counts": counts}


@router.post("/leads/{lead_id}/erase")
def erase_lead_route(lead_id: int, data: EraseIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        lead = lead_svc.get_lead(db, lead_id)
        _check_erase(data, lead_svc.lead_name(lead) or (lead.company_name or "") or (lead.email or ""))
        counts = lead_erase.erase_lead(db, lead_id)
        audit_actions.record(db, staff, "erase", "crm_lead", lead_id, None, _erase_detail(data.reason, counts))          # sin el nombre de la persona
        return {"message": "Datos del lead suprimidos", "counts": counts}
    return _run(db, work)


# ------------------------------------------------------------------ actividades
@router.get("/activities")
def list_activities(account_id: Optional[int] = None, contact_id: Optional[int] = None, lead_id: Optional[int] = None, opportunity_id: Optional[int] = None, status: str = "", page: int = 1,
                    db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: act_svc.list_for(db, account_id=account_id, contact_id=contact_id, lead_id=lead_id, opportunity_id=opportunity_id, status=status, page=page))


@router.get("/activities/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: act_svc.serialize(act_svc.get_activity(db, activity_id)))


@router.post("/activities")
def create_activity(data: ActivityIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: act_svc.serialize(act_svc.create_activity(db, staff, _fields(data, ("updated_at",)))))


@router.put("/activities/{activity_id}")
def update_activity(activity_id: int, data: ActivityIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        a = act_svc.get_activity(db, activity_id)
        return act_svc.serialize(act_svc.update_activity(db, staff, a, _fields(data, ("updated_at",)), data.updated_at))
    return _run(db, work)


@router.post("/activities/{activity_id}/complete")
def complete_activity(activity_id: int, data: CompleteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: act_svc.serialize(act_svc.complete(db, staff, act_svc.get_activity(db, activity_id), data.result)))


@router.post("/activities/{activity_id}/cancel")
def cancel_activity(activity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: act_svc.serialize(act_svc.cancel(db, staff, act_svc.get_activity(db, activity_id))))


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        act_svc.delete_activity(db, staff, act_svc.get_activity(db, activity_id))
        return {"message": "Actividad borrada"}
    return _run(db, work)
