"""Estadísticas de un formulario y acceso de CLIENTE por formulario (solo estadísticas, sin datos personales). Ver app/form_client.py y app/form_stats.py.

- Personal (coordinador+): `GET /api/events/{evento}/forms/{formulario}/stats` y la gestión de accesos (`client-access`, solo comercial/admin/super_admin como el resto de cuentas cliente).
- Cliente de formulario: `GET /api/form-client/stats` (el formulario sale de su cuenta, nunca de un parámetro)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions, form_client, form_stats, security
from app.auth import effective_roles, get_current_staff, get_event_for_staff, hash_password, require_role
from app.database import get_db
from app.models import FormClientUser, StaffUser
from app.routers.forms import _get_form
from app.timeutil import utcnow

router = APIRouter()
STAFF = require_role("coordinador")
NO_STORE = {"Cache-Control": "no-store"}


class ClientAccessIn(BaseModel):
    days: Optional[int] = form_client.DEFAULT_DAYS
    full_name: Optional[str] = None


def _row(g: FormClientUser) -> dict:
    u = g.staff_user
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "is_active": u.is_active, "expires_at": g.expires_at.isoformat(timespec="seconds") + "Z",
            "expired": g.expires_at <= utcnow(), "created_at": g.created_at.isoformat(timespec="seconds") + "Z" if g.created_at else None}


def _form_for_manager(db: Session, event_id: int, form_id: int, staff: StaffUser) -> tuple:
    event = get_event_for_staff(event_id, db, staff)          # tenant, pertenencia (ENFORCE_STAFF_*) y existencia del evento
    return event, _get_form(db, event, form_id)                # el formulario debe ser de ESE evento


@router.get("/events/{event_id}/forms/{form_id}/stats")
def form_stats_staff(event_id: int, form_id: int, include_tests: bool = False, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    _, form = _form_for_manager(db, event_id, form_id, staff)
    return JSONResponse(form_stats.build(db, form, include_tests, with_origin=True), headers=NO_STORE)


@router.get("/events/{event_id}/forms/{form_id}/client-access")
def list_client_access(event_id: int, form_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    _, form = _form_for_manager(db, event_id, form_id, staff)
    grants = db.query(FormClientUser).filter(FormClientUser.form_id == form.id).order_by(FormClientUser.id.desc()).all()
    return {"users": [_row(g) for g in grants]}


@router.post("/events/{event_id}/forms/{form_id}/client-access")
def create_client_access(event_id: int, form_id: int, data: ClientAccessIn, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Crea el usuario y la contraseña temporal (se muestran UNA sola vez). Misma regla que las cuentas cliente de evento: comercial, admin o super_admin."""
    if not ({"comercial", "admin", "super_admin"} & effective_roles(staff)):
        raise HTTPException(status_code=403, detail="Solo un comercial o Admin puede crear accesos para clientes")
    event, form = _form_for_manager(db, event_id, form_id, staff)
    days = data.days or form_client.DEFAULT_DAYS
    if not 1 <= days <= form_client.MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"La duración debe estar entre 1 y {form_client.MAX_DAYS} días")
    username, password = form_client.new_username(db, form), form_client.new_password()
    user = StaffUser(username=username, password_hash=hash_password(password), role="cliente", tenant_id=event.tenant_id, created_by_id=staff.id,
                     must_change_password=security.must_change_on_set_by_other("cliente"),          # Fase 4: la contraseña temporal la entrega el comercial; el cliente elige la suya
                     full_name=(data.full_name or "").strip()[:120] or f"Cliente de «{form.name}»"[:120])
    db.add(user)
    db.flush()                                                  # `autoflush=False`: el id del usuario hace falta para la fila de acceso
    grant = FormClientUser(form_id=form.id, staff_user_id=user.id, created_by_id=staff.id, expires_at=form_client.expiry(days))
    db.add(grant)
    db.commit()
    return JSONResponse({"username": username, "password": password, "expires_at": grant.expires_at.isoformat(timespec="seconds") + "Z", "days": days,
                         "login_path": "/login", "message": "Guarda estos datos ahora: la contraseña no se vuelve a mostrar."}, headers=NO_STORE)


@router.delete("/events/{event_id}/forms/{form_id}/client-access/{staff_id}")
def revoke_client_access(event_id: int, form_id: int, staff_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    _, form = _form_for_manager(db, event_id, form_id, staff)
    grant = db.query(FormClientUser).filter(FormClientUser.form_id == form.id, FormClientUser.staff_user_id == staff_id).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Ese acceso no existe en este formulario")
    user = grant.staff_user
    user.is_active = False                                      # la sesión abierta cae en la siguiente petición
    audit_actions.record(db, staff, "delete", "form_client_access", grant.id, None, f"formulario {form.id}, evento {event_id}: acceso del cliente revocado")
    db.delete(grant)
    db.commit()
    return {"message": "Acceso revocado"}


# ---------------------------------------------------------------- lo que ve el cliente de formulario
@router.get("/form-client/me")
def form_client_me(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    grant, form, event = form_client.resolve(db, staff)
    return {"form": {"id": form.id, "name": form.name}, "event": {"name": event.name}, "expires_at": grant.expires_at.isoformat(timespec="seconds") + "Z"}


@router.get("/form-client/stats")
def form_client_stats(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    _, form, _ = form_client.resolve(db, staff)
    return JSONResponse(form_stats.build(db, form, False), headers=NO_STORE)
