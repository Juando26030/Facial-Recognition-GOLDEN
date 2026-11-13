"""Alertas del sistema (Fase 9-A): quién recibe el aviso de borrado masivo y desde cuántos registros se envía. Solo admin y super admin (Configuración → «Alertas del sistema»)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions, jobs, mass_delete
from app.auth import require_role
from app.database import get_db
from app.models import AlertRecipient, StaffUser, SystemAlert
from app.staff_credentials import valid_email
from app.timeutil import utcnow

router = APIRouter()
ELIGIBLE_ROLES = ("coordinador", "comercial", "admin", "super_admin")


class SettingsIn(BaseModel):
    enabled: bool = True
    per_action: int = 50
    window_count: int = 200
    window_minutes: int = 10


class RecipientIn(BaseModel):
    email: str = ""
    staff_user_id: int = 0


class RecipientPatch(BaseModel):
    active: bool


def _recipient(r: AlertRecipient, staff_by_id: dict) -> dict:
    s = staff_by_id.get(r.staff_user_id)
    return {"id": r.id, "kind": r.kind, "email": r.email if r.kind == "email" else (s.email if s else None), "active": bool(r.active),
            "staff_user_id": r.staff_user_id, "label": (s.full_name or s.username) if s else None, "role": s.role if s else None}


def _who(db: Session, r: AlertRecipient) -> str:
    """Quién era el destinatario, para el aviso a los demás: el correo externo enmascarado o el usuario de la cuenta."""
    if r.kind == "staff":
        s = db.get(StaffUser, r.staff_user_id) if r.staff_user_id else None
        return f"cuenta {s.username}" if s else "una cuenta"
    email = r.email or ""
    user, _, domain = email.partition("@")
    return f"{user[:2]}…@{domain}" if domain else "un correo"


@router.get("/system-alerts")
def overview(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    rows = db.query(AlertRecipient).order_by(AlertRecipient.id).all()
    staff_ids = [r.staff_user_id for r in rows if r.staff_user_id]
    staff_by_id = {s.id: s for s in db.query(StaffUser).filter(StaffUser.id.in_(staff_ids)).all()} if staff_ids else {}
    taken = set(staff_ids)
    candidates = db.query(StaffUser).filter(StaffUser.is_active == True, StaffUser.archived_at.is_(None), StaffUser.role.in_(ELIGIBLE_ROLES)).order_by(StaffUser.full_name).all()      # noqa: E712
    recent = db.query(SystemAlert).order_by(SystemAlert.id.desc()).limit(15).all()
    return {"settings": mass_delete.get_settings(db), "limits": {k: list(v) for k, v in mass_delete.LIMITS.items()},
            "recipients": [_recipient(r, staff_by_id) for r in rows],
            "staff_options": [{"id": s.id, "label": s.full_name or s.username, "role": s.role, "has_email": bool(valid_email(s.email))} for s in candidates if s.id not in taken],
            "recent": [{"id": a.id, "title": a.title, "body": a.body, "created_at": a.created_at.isoformat() + "Z", "actor": a.actor_label} for a in recent]}


@router.put("/system-alerts/settings")
def save_settings(body: SettingsIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    before = mass_delete.get_settings(db)
    clean = mass_delete.clean_settings(body.model_dump())
    if clean != before:
        # Seguridad (F5-9 E): apagar la alerta o subir el umbral se avisa a los destinatarios actuales, para que no se pueda silenciar en secreto.
        changes = ", ".join(f"{k}: {before.get(k)} → {clean[k]}" for k in ("enabled", "per_action", "window_count", "window_minutes") if before.get(k) != clean[k])
        mass_delete.config_change(db, staff, f"cambió el umbral de la alerta de borrado masivo ({changes})")
        audit_actions.record(db, staff, "settings", "system_alerts", "mass_delete", None, changes)
    clean = mass_delete.save_settings(db, clean)
    db.commit()
    jobs.kick()
    return {"settings": clean}


@router.post("/system-alerts/recipients")
def add_recipient(body: RecipientIn, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    if body.staff_user_id:
        target = db.get(StaffUser, body.staff_user_id)
        if target is None or not target.is_active or target.role not in ELIGIBLE_ROLES:
            raise HTTPException(status_code=404, detail="Esa cuenta no existe o no puede recibir alertas")
        if db.query(AlertRecipient.id).filter(AlertRecipient.staff_user_id == target.id).first():
            raise HTTPException(status_code=409, detail="Esa cuenta ya recibe las alertas")
        if not valid_email(target.email):
            raise HTTPException(status_code=422, detail="Esa cuenta no tiene un correo registrado: recibiría el aviso solo en la campana. Agrégale un correo en Staff y permisos")
        row = AlertRecipient(kind="staff", staff_user_id=target.id, active=True)
    else:
        email = valid_email(body.email)
        if not email:
            raise HTTPException(status_code=422, detail="Escribe un correo válido")
        if db.query(AlertRecipient.id).filter(AlertRecipient.kind == "email", AlertRecipient.email.ilike(email)).first():
            raise HTTPException(status_code=409, detail="Ese correo ya está en la lista")
        row = AlertRecipient(kind="email", email=email, active=True)
    db.add(row)
    db.flush()
    audit_actions.record(db, staff, "create", "alert_recipient", row.id, None, row.kind)
    db.commit()
    return {"id": row.id}


@router.patch("/system-alerts/recipients/{rid}")
def toggle_recipient(rid: int, body: RecipientPatch, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    row = db.get(AlertRecipient, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="No existe ese destinatario")
    if row.active and not body.active:
        mass_delete.config_change(db, staff, f"pausó un destinatario de las alertas ({_who(db, row)})")
        audit_actions.record(db, staff, "pause", "alert_recipient", row.id, None, row.kind)
    elif body.active and not row.active:
        audit_actions.record(db, staff, "resume", "alert_recipient", row.id, None, row.kind)
    row.active = body.active
    db.commit()
    jobs.kick()
    return {"id": row.id, "active": row.active}


@router.delete("/system-alerts/recipients/{rid}")
def delete_recipient(rid: int, db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    row = db.get(AlertRecipient, rid)
    if row is None:
        raise HTTPException(status_code=404, detail="No existe ese destinatario")
    mass_delete.config_change(db, staff, f"quitó un destinatario de las alertas ({_who(db, row)})")     # se avisa ANTES de quitarlo: también le llega a él
    audit_actions.record(db, staff, "delete", "alert_recipient", row.id, None, row.kind)
    db.delete(row)
    db.commit()
    jobs.kick()
    return {"ok": True}


@router.post("/system-alerts/test")
def send_test(db: Session = Depends(get_db), staff: StaffUser = Depends(require_role("admin"))):
    now = utcnow()
    alert = SystemAlert(kind="test", title="Prueba: alerta del sistema de GoldenWeb",
                        body=f"Este es un mensaje de prueba enviado por {staff.username}. Si lo recibe, las alertas de borrado masivo le van a llegar a este correo.",
                        actor_id=staff.id, actor_label=staff.username, dedupe_key=f"test:{staff.id}:{uuid.uuid4().hex}", created_at=now)
    db.add(alert)
    db.flush()
    count = mass_delete.deliver(db, alert)
    if not count:
        db.rollback()
        raise HTTPException(status_code=422, detail="No hay destinatarios activos: agrega o activa al menos uno")
    db.commit()
    jobs.kick()
    return {"sent_to": count}
