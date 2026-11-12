"""API del CRM (C1b-1): cuentas, contactos, notas, historial y supresión. Todo bajo /api/crm; solo existe para el personal de Golden (sin cliente asignado cuando ENFORCE_STAFF_TENANT=1).

* Con `CRM_ENABLED` apagado TODA ruta responde 404 (el servidor local y producción hoy).
* Ver y editar: comercial, admin y super_admin (el coordinador puro no entra; con doble rol coordinador+comercial sí). Archivar/restaurar y suprimir: admin y super_admin.
* Endpoints `def` (acceso síncrono a la base). Mensajes en español; respuestas como dicts planos. Nada de datos personales en logs ni en la auditoría (solo ids y conteos).
"""
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions
from app.auth import require_platform_role
from app.crm import ACCOUNT_STATUSES, accounts as svc, crm_enabled
from app.crm.codes import CodeCounterNotReady
from app.crm.erase import erase_account, erase_contact
from app.database import get_db
from app.models import CrmAccount, CrmChangeLog, CrmContact, CrmNote, StaffUser, Tenant


def _require_crm_enabled() -> None:
    if not crm_enabled():
        raise HTTPException(status_code=404, detail="No encontrado")


router = APIRouter(prefix="/crm", dependencies=[Depends(_require_crm_enabled)])
view_staff = require_platform_role("comercial")
admin_staff = require_platform_role("admin")


def _run(db: Session, fn):
    """Ejecuta `fn`, confirma al terminar y traduce los errores del CRM a respuestas HTTP (revirtiendo la transacción)."""
    try:
        result = fn()
        db.commit()
        return result
    except svc.CrmError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except CodeCounterNotReady as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El contador de códigos del CRM no está listo. Pide a un administrador que lo fije antes de crear cuentas.") from exc


# ------------------------------------------------------------------ modelos de entrada
class AccountIn(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    nit: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    billing_address: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_country: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_country: Optional[str] = None
    billing_contact_name: Optional[str] = None
    billing_contact_phone: Optional[str] = None
    payment_term: Optional[str] = None
    payment_days: Optional[Union[int, str]] = None          # int o texto: si no es número, responde 400 en español (clean_account) y no un 422 de FastAPI en inglés
    billing_close: Optional[str] = None
    agency_percent: Optional[Union[str, float]] = None
    owner_staff_id: Optional[Union[int, str]] = None
    description: Optional[str] = None
    confirm_duplicate: bool = False
    updated_at: Optional[str] = None          # versión que vio quien edita (solo al editar)


class ContactIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    notes: Optional[str] = None
    make_primary: bool = False
    updated_at: Optional[str] = None


class NoteIn(BaseModel):
    body: str
    contact_id: Optional[int] = None


class EraseIn(BaseModel):
    reason: str
    confirm_name: str = ""          # el nombre del contacto (o el de la cuenta) tal como se ve en pantalla


def _fields(model: BaseModel, drop: tuple) -> dict:
    return {k: v for k, v in model.dict(exclude_unset=True).items() if k not in drop}


# ------------------------------------------------------------------ cuentas
@router.get("/meta")
def meta(db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Listas para los filtros y formularios: estados, responsables (personal activo con rol de ventas) y ciudades ya usadas."""
    owners = db.query(StaffUser.id, StaffUser.full_name).filter(StaffUser.is_active.is_(True), StaffUser.archived_at.is_(None),
                                                               StaffUser.role.in_(("comercial", "admin", "super_admin"))).order_by(StaffUser.full_name).all()
    cities = [r[0] for r in db.query(CrmAccount.billing_city).filter(CrmAccount.billing_city.isnot(None)).distinct().order_by(CrmAccount.billing_city).limit(500).all()]
    terms = [r[0] for r in db.query(CrmAccount.payment_term).filter(CrmAccount.payment_term.isnot(None)).distinct().order_by(CrmAccount.payment_term).limit(100).all()]
    return {"statuses": list(ACCOUNT_STATUSES), "owners": [{"id": o[0], "name": o[1]} for o in owners], "cities": cities, "payment_terms": terms}


@router.get("/accounts")
def list_accounts(q: str = "", status: str = "", owner_id: Optional[int] = None, city: str = "", archived: bool = False, page: int = 1, size: int = svc.PAGE_SIZE,
                  db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return svc.list_accounts(db, q=q, status=status, owner_id=owner_id, city=city, archived=archived, page=page, size=size)


@router.post("/accounts")
def create_account(data: AccountIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        account = svc.create_account(db, staff, _fields(data, ("confirm_duplicate", "updated_at")), confirm_duplicate=data.confirm_duplicate)
        return svc.serialize_account(account, None, detail=True)
    return _run(db, work)


@router.get("/accounts/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        account = svc.get_account(db, account_id)
        return svc.serialize_account(account, svc.primary_of(db, account.id), detail=True)
    return _run(db, work)


@router.put("/accounts/{account_id}")
def update_account(account_id: int, data: AccountIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        account = svc.get_account(db, account_id)
        svc.update_account(db, staff, account, _fields(data, ("confirm_duplicate", "updated_at")), data.updated_at)
        return svc.serialize_account(account, svc.primary_of(db, account.id), detail=True)
    return _run(db, work)


@router.post("/accounts/{account_id}/archive")
def archive_account(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        account = svc.get_account(db, account_id)
        svc.set_archived(db, staff, account, True)
        audit_actions.record(db, staff, "archive", "crm_account", account.id, account.name)
        return svc.serialize_account(account, svc.primary_of(db, account.id), detail=True)
    return _run(db, work)


@router.post("/accounts/{account_id}/restore")
def restore_account(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        account = svc.get_account(db, account_id)
        svc.set_archived(db, staff, account, False)
        audit_actions.record(db, staff, "restore", "crm_account", account.id, account.name)
        return svc.serialize_account(account, svc.primary_of(db, account.id), detail=True)
    return _run(db, work)


@router.post("/accounts/{account_id}/make-client")
def make_client(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Convierte la cuenta en cliente de la plataforma: crea el `tenant` con el MISMO número (no saca otro del contador) y los datos del contacto principal."""
    from app.routers.tenants import _slugify

    def work():
        account = svc.get_account(db, account_id)
        if account.tenant_id is not None:
            raise svc.CrmError("La cuenta ya es cliente de la plataforma.", 409)
        code = str(account.code)
        if db.query(Tenant.id).filter((Tenant.client_code == code) | (Tenant.legacy_client_code == code)).first() is not None:
            raise svc.CrmError("Ya existe un cliente de la plataforma con ese código. Hay que emparejarlo a mano antes de convertir esta cuenta.", 409)
        base_id = _slugify(account.name)
        tenant_id, n = base_id, 1
        while db.get(Tenant, tenant_id) is not None:
            n += 1
            tenant_id = f"{base_id}_{n}"
        db.add(Tenant(id=tenant_id, client_code=code, name=account.name))
        db.flush()
        account.tenant_id = tenant_id
        svc.mirror_primary_to_tenant(db, account)
        audit_actions.record(db, staff, "make_client", "crm_account", account.id, account.name, f"cliente {tenant_id}")
        db.flush()
        return svc.serialize_account(account, svc.primary_of(db, account.id), detail=True)
    return _run(db, work)


@router.post("/accounts/{account_id}/erase")
def erase_account_route(account_id: int, data: EraseIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        account = svc.get_account(db, account_id)
        _check_erase(data, account.name)
        name, aid = account.name, account.id
        counts = erase_account(db, aid)
        audit_actions.record(db, staff, "erase", "crm_account", aid, name, _erase_detail(data.reason, counts))
        return {"message": "Cuenta suprimida", "counts": counts}
    return _run(db, work)


# ------------------------------------------------------------------ contactos
@router.get("/accounts/{account_id}/contacts")
def list_contacts(account_id: int, archived: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    account = db.get(CrmAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    query = db.query(CrmContact).filter(CrmContact.account_id == account_id)
    query = query.filter(CrmContact.archived_at.isnot(None) if archived else CrmContact.archived_at.is_(None))
    return [svc.serialize_contact(c) for c in query.order_by(CrmContact.is_primary.desc(), CrmContact.full_name_norm, CrmContact.id).all()]


@router.post("/accounts/{account_id}/contacts")
def create_contact(account_id: int, data: ContactIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        account = svc.get_account(db, account_id)
        return svc.serialize_contact(svc.create_contact(db, staff, account, _fields(data, ("make_primary", "updated_at")), make_primary=data.make_primary))
    return _run(db, work)


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: int, data: ContactIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        contact = svc.get_contact(db, contact_id)
        return svc.serialize_contact(svc.update_contact(db, staff, contact, _fields(data, ("make_primary", "updated_at")), data.updated_at))
    return _run(db, work)


@router.post("/contacts/{contact_id}/make-primary")
def make_primary(contact_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.serialize_contact(svc.make_primary(db, staff, svc.get_contact(db, contact_id))))


@router.post("/contacts/{contact_id}/archive")
def archive_contact(contact_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.serialize_contact(svc.set_contact_archived(db, staff, svc.get_contact(db, contact_id), True)))


@router.post("/contacts/{contact_id}/restore")
def restore_contact(contact_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    return _run(db, lambda: svc.serialize_contact(svc.set_contact_archived(db, staff, svc.get_contact(db, contact_id), False)))


@router.post("/contacts/{contact_id}/erase")
def erase_contact_route(contact_id: int, data: EraseIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        contact = svc.get_contact(db, contact_id)
        _check_erase(data, svc.full_name(contact))
        account = db.get(CrmAccount, contact.account_id)
        cid, aid, aname = contact.id, contact.account_id, account.name if account is not None else None
        counts = erase_contact(db, cid)
        audit_actions.record(db, staff, "erase", "crm_contact", cid, aname, _erase_detail(data.reason, counts, aid))          # nombre de la CUENTA, nunca el de la persona
        return {"message": "Datos del contacto suprimidos", "counts": counts}
    return _run(db, work)


def _check_erase(data: EraseIn, expected_name: str) -> None:
    if not (data.reason or "").strip():
        raise svc.CrmError("Escribe el motivo de la supresión.")
    if (data.confirm_name or "").strip().lower() != (expected_name or "").strip().lower():
        raise svc.CrmError("El nombre escrito no coincide: la supresión no se hizo.")


def _erase_detail(reason: str, counts: dict, account_id=None) -> str:
    flat = ", ".join(f"{k}={v}" for k, v in counts.items() if isinstance(v, int))
    return (f"cuenta {account_id}; " if account_id else "") + f"motivo: {reason.strip()[:200]}; {flat}"


# ------------------------------------------------------------------ notas e historial
@router.get("/accounts/{account_id}/notes")
def list_notes(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    if db.get(CrmAccount, account_id) is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    names = {s.id: s.full_name for s in db.query(StaffUser.id, StaffUser.full_name).all()}
    rows = db.query(CrmNote).filter(CrmNote.account_id == account_id).order_by(CrmNote.created_at.desc(), CrmNote.id.desc()).limit(500).all()
    return [{"id": n.id, "contact_id": n.contact_id, "kind": n.kind, "body": n.body, "author": names.get(n.created_by_id), "created_at": n.created_at.isoformat()} for n in rows]


@router.post("/accounts/{account_id}/notes")
def add_note(account_id: int, data: NoteIn, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        note = svc.add_note(db, staff, svc.get_account(db, account_id), data.body, data.contact_id)
        return {"id": note.id, "contact_id": note.contact_id, "kind": note.kind, "body": note.body, "author": staff.full_name, "created_at": note.created_at.isoformat()}
    return _run(db, work)


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    def work():
        note = db.get(CrmNote, note_id)
        if note is None:
            raise svc.CrmError("Nota no encontrada.", 404)
        if note.created_by_id != staff.id and staff.role not in ("admin", "super_admin"):
            raise svc.CrmError("Solo quien escribió la nota o un administrador puede borrarla.", 403)
        db.delete(note)
        return {"message": "Nota borrada"}
    return _run(db, work)


@router.get("/accounts/{account_id}/history")
def account_history(account_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(view_staff)):
    """Cambios de la cuenta y de sus contactos, del más reciente al más antiguo (hasta 500). Los valores se recortan como en el historial de personas."""
    if db.get(CrmAccount, account_id) is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    contact_ids = [r[0] for r in db.query(CrmContact.id).filter(CrmContact.account_id == account_id).all()]
    q = db.query(CrmChangeLog).filter(((CrmChangeLog.entity == "account") & (CrmChangeLog.entity_id == account_id)) |
                                      ((CrmChangeLog.entity == "contact") & (CrmChangeLog.entity_id.in_(contact_ids or [-1]))))
    names = {s.id: s.full_name for s in db.query(StaffUser.id, StaffUser.full_name).all()}
    rows = q.order_by(CrmChangeLog.changed_at.desc(), CrmChangeLog.id.desc()).limit(500).all()
    return [{"entity": r.entity, "entity_id": r.entity_id, "field": r.field_key, "old": r.old_value, "new": r.new_value, "by": names.get(r.changed_by_id), "source": r.source, "at": r.changed_at.isoformat()} for r in rows]
