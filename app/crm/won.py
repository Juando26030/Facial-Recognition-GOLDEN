"""Oportunidad ganada → cliente y evento (C4). Sin commit propio: quien llama (el router) confirma o revierte, así mover a «Ganada» y crear el evento son UNA sola transacción.

* La cuenta se vuelve cliente de la plataforma (`tenant`) si aún no lo era (mismo número que la cuenta, igual que «Convertir en cliente»).
* El evento nace con el MISMO número de la oportunidad (`event_code`), en estado «creado», con el nombre, la fecha de inicio y la ciudad de la oportunidad, y con la persona de prueba de siempre.
  El resto (lugar, horarios, plantilla de evento) se completa en Eventos: crear el evento desde el CRM no exige los campos de la plantilla.
* Si el código ya existe como evento, responde 409 con mensaje claro y NO crea nada (ni cliente ni evento).
* Sin datos personales en la auditoría: solo ids y códigos.
"""
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import audit_actions
from app.crm.errors import CrmError
from app.models import CrmAccount, CrmOpportunity, Event, StaffUser, Tenant


def make_client(db: Session, staff: StaffUser, account: CrmAccount) -> Tenant:
    """Convierte la cuenta en cliente de la plataforma: crea el `tenant` con el MISMO número (no saca otro del contador) y copia los datos del contacto principal. Sin commit."""
    from app.crm import accounts as acc_svc
    from app.routers.tenants import _slugify
    if account.tenant_id is not None:
        raise CrmError("La cuenta ya es cliente de la plataforma.", 409)
    code = str(account.code)
    if db.query(Tenant.id).filter((Tenant.client_code == code) | (Tenant.legacy_client_code == code)).first() is not None:
        raise CrmError("Ya existe un cliente de la plataforma con ese código. Hay que emparejarlo a mano antes de convertir esta cuenta.", 409)
    base_id = _slugify(account.name)
    tenant_id, n = base_id, 1
    while db.get(Tenant, tenant_id) is not None:
        n += 1
        tenant_id = f"{base_id}_{n}"
    tenant = Tenant(id=tenant_id, client_code=code, name=account.name)
    db.add(tenant)
    db.flush()
    account.tenant_id = tenant_id
    acc_svc.mirror_primary_to_tenant(db, account)
    audit_actions.record(db, staff, "make_client", "crm_account", account.id, account.name, f"cliente {tenant_id}")
    db.flush()
    return tenant


def event_code_for(o: CrmOpportunity) -> str:
    """Código del evento que nace de la oportunidad: el MISMO número (DECISIÓN, docs/crm/ETAPA_C1C_C4_DISENO.md §4). Si algún día se quiere prefijo o año, se cambia solo aquí."""
    return str(o.code)


def _commercial_for(db: Session, owner_id: Optional[int]) -> Optional[int]:
    """El dueño de la oportunidad queda como comercial del evento solo si sigue activo y es comercial; si no, el evento queda sin comercial (la columna admite NULL)."""
    if owner_id is None:
        return None
    ok = db.query(StaffUser.id).filter(StaffUser.id == owner_id, StaffUser.is_active == True,           # noqa: E712
                                       or_(StaffUser.role == "comercial", StaffUser.secondary_role == "comercial")).first()
    return owner_id if ok else None


def create_event_for(db: Session, staff: StaffUser, o: CrmOpportunity) -> Event:
    """Crea el cliente (si falta) y el evento de una oportunidad ganada que aún no tiene evento. Deja `o.event_id`. Sin commit."""
    from app import event_rules, public_slug, testperson
    if o.outcome != "won":
        raise CrmError("Solo una oportunidad ganada puede crear su evento.", 409)
    if o.event_id is not None:
        raise CrmError("Esta oportunidad ya tiene su evento creado.", 409)
    account = db.get(CrmAccount, o.account_id)
    if account is None or account.archived_at is not None:
        raise CrmError("La cuenta está archivada: restáurala antes de crear el evento.", 409)
    code = event_code_for(o)
    if db.query(Event.id).filter(func.lower(func.btrim(Event.event_code)) == code.lower()).first() is not None:
        raise CrmError(f"Ya existe un evento con el código {code}. Revisa el contador de eventos (docs/crm/CODIGOS.md) antes de ganar esta oportunidad.", 409)
    if account.tenant_id is None:
        make_client(db, staff, account)
    tenant = db.get(Tenant, account.tenant_id)
    if tenant is None or tenant.archived_at is not None:
        raise CrmError("El cliente de la plataforma de esta cuenta está archivado: restáuralo antes de crear el evento.", 409)
    data = {"tenant_id": account.tenant_id, "event_code": code, "name": o.name, "city": o.city, "start_date": o.event_start, "status": "creado",
            "commercial_staff_id": _commercial_for(db, o.owner_staff_id), "created_by_id": staff.id,
            "accept_no_birth_mode": "require_personal_link", "pledge_enabled": True}
    initial = event_rules.default_state(db, "creado")
    if initial is not None:
        data["state_id"] = initial.id
    event = Event(**data)
    db.add(event)
    db.flush()
    public_slug.ensure(db, event)
    testperson.ensure_for_event(db, event)
    from app import pledge
    if pledge.text_available():
        pledge.create_or_regenerate(db, event, staff)
    o.event_id = event.id
    audit_actions.record(db, staff, "win", "crm_opportunity", o.id, str(o.code), f"evento {event.event_code}")
    db.flush()
    return event


def win(db: Session, staff: StaffUser, o: CrmOpportunity) -> Event:
    """Gana la oportunidad (la mueve a la primera etapa «ganada» de su embudo, lo que ya crea el evento) o, si ya estaba ganada sin evento (caso de antes de C4 o de una importación),
    solo crea el evento. Devuelve el evento. Sin commit."""
    from app.crm import opportunities as opp_svc
    from app.models import CrmStage
    if o.event_id is not None:
        raise CrmError("Esta oportunidad ya tiene su evento creado.", 409)
    if o.archived_at is not None:
        raise CrmError("La oportunidad está archivada: restáurala primero.")
    if o.outcome == "won":
        return create_event_for(db, staff, o)
    stage = (db.query(CrmStage.id).filter(CrmStage.pipeline_id == o.pipeline_id, CrmStage.kind == "won", CrmStage.archived_at.is_(None)).order_by(CrmStage.position).first())
    if stage is None:
        raise CrmError("El embudo de esta oportunidad no tiene una etapa «ganada».")
    opp_svc.move_stage(db, staff, o, stage[0])
    return db.get(Event, o.event_id)
