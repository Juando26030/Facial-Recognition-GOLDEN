"""Enlace CRM ↔ plataforma (Eventos y Clientes), regla de Juan David (16-nov-2026):

* Un evento que existe («creado» o después) es una oportunidad GANADA; cualquier otra etapa significa «aún no se sabe» y el evento no existe.
* Camino de ida (ya existía, app/crm/won.py): ganar la oportunidad crea el cliente y el evento.
* Camino de vuelta (aquí): un evento creado en Eventos tiene su cuenta y su oportunidad ganada en el CRM (se crean solas si faltan), enlazadas por `event_id`.
* Sacar una oportunidad de «ganada» mientras su evento está en «creado» y sin uso lo ARCHIVA (no se borra nada; se restaura al volver a ganarla). Con el evento ya «en proceso» o «finalizado» no se puede.

Todo sin commit propio: quien llama confirma. Nada de datos personales en logs ni en la auditoría (solo ids y códigos). Si el CRM falla, crear el evento NO debe fallar: `link_new_event` va en un SAVEPOINT."""
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app import audit_actions
from app.crm import crm_enabled
from app.crm.codes import next_code
from app.crm.errors import CrmError
from app.models import CrmAccount, CrmOpportunity, CrmStage, Event, StaffUser, Tenant
from app.timeutil import utcnow

log = logging.getLogger("golden.crm_link")
_NUMERIC = re.compile(r"^[0-9]{1,7}$")          # los consecutivos del CRM son menores de 10.000.000; un hexadecimal de 8 caracteres (aunque sean solo dígitos) NO es un consecutivo


def account_for_tenant(db: Session, tenant_id: Optional[str]) -> Optional[CrmAccount]:
    return db.query(CrmAccount).filter(CrmAccount.tenant_id == tenant_id).first() if tenant_id else None


def ensure_account(db: Session, staff: StaffUser, tenant: Tenant) -> Optional[CrmAccount]:
    """La cuenta del CRM de este cliente; si no existe y el cliente ya tiene número consecutivo, la crea con ese MISMO número. Un cliente con código hexadecimal (de antes del CRM) queda
    para el emparejamiento que revisa Juan David: aquí no se le inventa número. Devuelve None si no se pudo."""
    acc = account_for_tenant(db, tenant.id)
    if acc is not None:
        return acc
    if not _NUMERIC.match(tenant.client_code or ""):
        return None
    if db.query(CrmAccount.id).filter(CrmAccount.code == int(tenant.client_code)).first() is not None:
        return None          # ese número ya es de otra cuenta (p. ej. una importada): se empareja a mano
    from app.routers.tenants import _create_crm_account
    _create_crm_account(db, staff, tenant)
    audit_actions.record(db, staff, "link_client", "tenant", tenant.id, tenant.name, f"cuenta {tenant.client_code}")
    return account_for_tenant(db, tenant.id)


def _won_stage(db: Session, pipeline_id: int) -> Optional[int]:
    row = (db.query(CrmStage.id).filter(CrmStage.pipeline_id == pipeline_id, CrmStage.kind == "won", CrmStage.archived_at.is_(None)).order_by(CrmStage.position).first())
    return row[0] if row else None


def opportunity_for_event(db: Session, event_id: int) -> Optional[CrmOpportunity]:
    return db.query(CrmOpportunity).filter(CrmOpportunity.event_id == event_id).first()


def ensure_opportunity(db: Session, staff: StaffUser, event: Event) -> Optional[CrmOpportunity]:
    """La oportunidad ganada de este evento; si falta, la crea (con la cuenta del cliente, que también se crea si falta). None si el cliente no tiene cuenta posible."""
    from app.crm import pipeline as pipe
    found = opportunity_for_event(db, event.id)
    if found is not None:
        return found
    tenant = db.get(Tenant, event.tenant_id)
    account = ensure_account(db, staff, tenant) if tenant is not None else None
    if account is None or account.archived_at is not None:
        return None
    pipeline_id = pipe.default_pipeline_id(db)
    stage_id = _won_stage(db, pipeline_id)
    if stage_id is None:
        return None
    now = utcnow()
    name = (event.name or "Evento").strip()[:200]
    o = CrmOpportunity(code=next_code(db, "event"), account_id=account.id, pipeline_id=pipeline_id, stage_id=stage_id, name=name, outcome="won", closed_at=now, stage_entered_at=now,
                       city=(event.city or None) and event.city[:120], event_start=event.start_date, event_id=event.id,
                       owner_staff_id=event.commercial_staff_id or staff.id, created_by_id=staff.id)
    db.add(o)
    db.flush()
    audit_actions.record(db, staff, "link_event", "crm_opportunity", o.id, str(o.code), f"evento {event.event_code}")
    return o


def link_new_event(db: Session, staff: StaffUser, event: Event) -> None:
    """Se llama al crear un evento en Eventos. Con el CRM apagado no hace nada; si algo falla, solo se anota (en un SAVEPOINT) y el evento se crea igual."""
    if not crm_enabled():
        return
    try:
        with db.begin_nested():
            ensure_opportunity(db, staff, event)
    except Exception:          # noqa: BLE001 - el CRM nunca debe impedir crear un evento
        log.error("no se pudo enlazar el evento %s con el CRM", event.id, exc_info=True)


def leave_won(db: Session, staff: StaffUser, o: CrmOpportunity) -> None:
    """La oportunidad sale de «ganada»: su evento «creado» y sin uso se archiva; si ya está en proceso o finalizado, se niega con un mensaje claro. Sin evento no hace nada."""
    from app import event_archive
    if o.event_id is None:
        return
    event = db.get(Event, o.event_id)
    if event is None or event.archived_at is not None:
        return
    if event.status != "creado":
        raise CrmError("El evento de esta oportunidad ya está en proceso o finalizado: no se puede sacar de «ganada». Si fue un error, un administrador debe devolver primero el evento a «Creado».", 409)
    event_archive.archive(db, event, staff, "la oportunidad salió de «ganada»")
    audit_actions.record(db, staff, "unwin", "crm_opportunity", o.id, str(o.code), f"evento {event.event_code} archivado")


def rewin(db: Session, staff: StaffUser, o: CrmOpportunity) -> bool:
    """La oportunidad vuelve a «ganada»: si su evento quedó archivado por salir de «ganada», se restaura en vez de crear otro (el código ya está ocupado). True si lo restauró."""
    from app import event_archive
    if o.event_id is None:
        return False
    event = db.get(Event, o.event_id)
    if event is None or event.archived_at is None or event.status != "creado":
        return False
    event_archive.restore(db, event, staff)
    audit_actions.record(db, staff, "rewin", "crm_opportunity", o.id, str(o.code), f"evento {event.event_code} restaurado")
    return True

