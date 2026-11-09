"""Notificaciones dentro de la aplicación (campana): cada cuenta ve SOLO las suyas. Cualquier cuenta con sesión (incluidos digitador y cliente). Sin sondeo: la página las pide al abrir y al pulsar la campana."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import notifications
from app.auth import get_current_staff
from app.database import get_db
from app.models import Notification, StaffUser
from app.timeutil import utcnow

router = APIRouter()


@router.get("/notifications")
def list_notifications(unread: bool = False, limit: int = 30, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    limit = max(1, min(int(limit or 30), 100))
    base = db.query(Notification).filter(Notification.staff_user_id == staff.id)
    count = base.filter(Notification.read_at.is_(None)).count()
    q = base.filter(Notification.read_at.is_(None)) if unread else base
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return {"unread": count, "items": [notifications.serialize(n) for n in rows]}


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    n = db.query(Notification).filter(Notification.staff_user_id == staff.id, Notification.read_at.is_(None)).update({"read_at": utcnow()}, synchronize_session=False)
    db.commit()
    return {"marked": n, "unread": 0}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(get_current_staff)):
    row = db.query(Notification).filter(Notification.id == notification_id, Notification.staff_user_id == staff.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    if row.read_at is None:
        row.read_at = utcnow()
        db.commit()
    unread = db.query(Notification).filter(Notification.staff_user_id == staff.id, Notification.read_at.is_(None)).count()
    return {"ok": True, "unread": unread}
