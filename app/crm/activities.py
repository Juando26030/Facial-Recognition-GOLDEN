"""Actividades del CRM (C2): llamadas, tareas, reuniones y notas con fecha, ligadas a una cuenta, un contacto, un lead o una oportunidad. Sin commit propio.

* Al menos una liga; si hay varias deben ser coherentes (el contacto es de la cuenta, la oportunidad es de la cuenta). La cuenta se completa sola a partir del contacto o de la oportunidad.
* `crm_opportunities.next_activity_at` es una COPIA de la menor fecha entre las actividades planificadas de esa oportunidad. Se recalcula en la misma transacción en cada alta, cambio de fecha, cierre,
  cancelación o borrado (`refresh_next`): así el tablero marca «sin próxima actividad» sin consultar otra tabla.
* `subject` y `description` son texto libre. No pasan por el historial; si hablan de un contacto o un lead se borran con él (llave con ON DELETE CASCADE) y la supresión revisa su texto (lead_erase.py).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.crm.accounts import MAX_ID, MAX_PAGE, _check_owner, _check_version
from app.crm.errors import CrmError
from app.crm.pipeline_rules import ACTIVITY_KINDS, RESULTS, check_attached, clean_activity, clean_result, next_due
from app.models import CrmAccount, CrmActivity, CrmContact, CrmLead, CrmOpportunity, StaffUser
from app.timeutil import utcnow

LIST_MAX = 200


def get_activity(db: Session, activity_id: int) -> CrmActivity:
    a = db.get(CrmActivity, activity_id) if 0 < activity_id <= MAX_ID else None
    if a is None:
        raise CrmError("Actividad no encontrada.", 404)
    return a


def refresh_next(db: Session, opportunity_id: Optional[int]) -> None:
    """Recalcula `next_activity_at` de la oportunidad desde sus actividades planificadas."""
    if not opportunity_id:
        return
    opp = db.get(CrmOpportunity, opportunity_id)
    if opp is None:
        return
    rows = db.query(CrmActivity.status, CrmActivity.due_at).filter(CrmActivity.opportunity_id == opportunity_id, CrmActivity.status == "planned", CrmActivity.due_at.isnot(None)).all()
    due = next_due([(r[0], r[1]) for r in rows])
    if opp.next_activity_at != due:
        opp.next_activity_at = due          # sin tocar `updated_at`: agendar una actividad no es editar la oportunidad
        db.flush()


def _resolve_links(db: Session, fields: dict) -> None:
    """Completa y comprueba las ligas de una actividad nueva (modifica `fields`)."""
    opp = db.get(CrmOpportunity, fields["opportunity_id"]) if fields.get("opportunity_id") else None
    if fields.get("opportunity_id") and opp is None:
        raise CrmError("La oportunidad indicada no existe.")
    lead = db.get(CrmLead, fields["lead_id"]) if fields.get("lead_id") else None
    if fields.get("lead_id") and lead is None:
        raise CrmError("El lead indicado no existe.")
    contact = db.get(CrmContact, fields["contact_id"]) if fields.get("contact_id") else None
    if fields.get("contact_id") and contact is None:
        raise CrmError("El contacto indicado no existe.")
    account_id = fields.get("account_id")
    for derived in (opp.account_id if opp else None, contact.account_id if contact else None):
        if derived is not None:
            if account_id is not None and derived != account_id:
                raise CrmError("Las ligas de la actividad no corresponden a la misma cuenta.")
            account_id = derived
    if account_id is not None and db.get(CrmAccount, account_id) is None:
        raise CrmError("La cuenta indicada no existe.")
    fields["account_id"] = account_id


def create_activity(db: Session, staff: StaffUser, data: dict) -> CrmActivity:
    fields = clean_activity(data, creating=True)
    check_attached(fields.get("account_id"), fields.get("contact_id"), fields.get("lead_id"), fields.get("opportunity_id"))
    _resolve_links(db, fields)
    _check_owner(db, fields.get("owner_staff_id"))
    fields.setdefault("owner_staff_id", staff.id)
    a = CrmActivity(created_by_id=staff.id, status="done" if fields["kind"] == "note" else "planned", **fields)
    if a.status == "done":
        a.done_at = utcnow()          # una nota ya ocurrió: no queda pendiente
    db.add(a)
    db.flush()
    refresh_next(db, a.opportunity_id)
    return a


def update_activity(db: Session, staff: StaffUser, a: CrmActivity, data: dict, expected_updated_at: Optional[str]) -> CrmActivity:
    _check_version(a, expected_updated_at)
    if a.status != "planned":
        raise CrmError("Solo se edita una actividad pendiente.", 409)
    fields = clean_activity(data, creating=False)
    for key in ("account_id", "contact_id", "lead_id", "opportunity_id"):
        fields.pop(key, None)          # las ligas no se cambian: se crea otra actividad
    _check_owner(db, fields.get("owner_staff_id"))
    if "due_at" in fields or "remind_at" in fields:
        due, remind = fields.get("due_at", a.due_at), fields.get("remind_at", a.remind_at)
        if due and remind and remind > due:
            raise CrmError("El recordatorio debe ser antes de la fecha de la actividad.")
    for key, value in fields.items():
        setattr(a, key, value)
    a.updated_at = utcnow()
    db.flush()
    refresh_next(db, a.opportunity_id)
    return a


def complete(db: Session, staff: StaffUser, a: CrmActivity, result=None) -> CrmActivity:
    if a.status != "planned":
        raise CrmError("La actividad ya estaba cerrada.", 409)
    a.result = clean_result(result)
    a.status, a.done_at, a.updated_at = "done", utcnow(), utcnow()
    db.flush()
    refresh_next(db, a.opportunity_id)
    return a


def cancel(db: Session, staff: StaffUser, a: CrmActivity) -> CrmActivity:
    if a.status != "planned":
        raise CrmError("La actividad ya estaba cerrada.", 409)
    a.status, a.updated_at = "cancelled", utcnow()
    db.flush()
    refresh_next(db, a.opportunity_id)
    return a


def delete_activity(db: Session, staff: StaffUser, a: CrmActivity) -> None:
    if a.created_by_id != staff.id and staff.role not in ("admin", "super_admin"):
        raise CrmError("Solo quien creó la actividad o un administrador puede borrarla.", 403)
    opp_id = a.opportunity_id
    db.delete(a)
    db.flush()
    refresh_next(db, opp_id)


def serialize(a: CrmActivity, owner_name: Optional[str] = None) -> dict:
    return {"id": a.id, "kind": a.kind, "kind_label": ACTIVITY_KINDS.get(a.kind, a.kind), "status": a.status, "subject": a.subject, "description": a.description,
            "due_at": a.due_at.isoformat() if a.due_at else None, "remind_at": a.remind_at.isoformat() if a.remind_at else None, "done_at": a.done_at.isoformat() if a.done_at else None,
            "result": a.result, "result_label": RESULTS.get(a.result) if a.result else None, "account_id": a.account_id, "contact_id": a.contact_id, "lead_id": a.lead_id,
            "opportunity_id": a.opportunity_id, "owner_staff_id": a.owner_staff_id, "owner_name": owner_name, "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat()}


def list_for(db: Session, *, account_id=None, contact_id=None, lead_id=None, opportunity_id=None, status: str = "", page: int = 1) -> dict:
    """Actividades de UNA liga (la primera que venga), con el nombre del responsable en la misma consulta. Pendientes primero (la más próxima arriba), luego las cerradas, hasta 200."""
    query = db.query(CrmActivity, StaffUser.full_name).join(StaffUser, StaffUser.id == CrmActivity.owner_staff_id, isouter=True)
    for column, value in ((CrmActivity.opportunity_id, opportunity_id), (CrmActivity.lead_id, lead_id), (CrmActivity.contact_id, contact_id), (CrmActivity.account_id, account_id)):
        if value:
            if not 0 < int(value) <= MAX_ID:
                return {"items": [], "total": 0, "page": 1, "size": LIST_MAX}
            query = query.filter(column == value)
            break
    else:
        raise CrmError("Indica de qué cuenta, contacto, lead u oportunidad quieres ver las actividades.")
    if status in ("planned", "done", "cancelled"):
        query = query.filter(CrmActivity.status == status)
    total = query.count()
    page = max(1, min(int(page or 1), MAX_PAGE))
    rows = (query.order_by((CrmActivity.status != "planned"), CrmActivity.due_at.asc().nulls_last(), CrmActivity.created_at.desc(), CrmActivity.id.desc())
            .offset((page - 1) * LIST_MAX).limit(LIST_MAX).all())
    return {"items": [serialize(a, name) for a, name in rows], "total": total, "page": page, "size": LIST_MAX}
