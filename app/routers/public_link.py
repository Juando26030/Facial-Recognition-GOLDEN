"""Enlace limpio de inscripciones de un evento (D2.5k): ver/validar/cambiar su nombre y elegir el formulario principal. Solo admin, comercial y super_admin (el nombre público lo publica una persona con ese rol:
evita suplantaciones). El enlace en sí lo sirve app/routers/clean_url.py."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import event_lease, formsvc, public_slug, publicurl
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import AuditAction, SlugHistory, StaffUser, WebForm

router = APIRouter()
_who = require_role("comercial")


class LinkUpdate(BaseModel):
    slug: Optional[str] = None
    primary_form_id: Optional[int] = None
    clear_primary: bool = False


def _forms(db: Session, event_id: int) -> list:
    rows = db.query(WebForm).filter(WebForm.event_id == event_id, WebForm.archived_at.is_(None), WebForm.kind == "registration").order_by(WebForm.id).all()
    return [{"id": f.id, "name": f.name, "slug": f.slug, "is_primary": bool(f.is_primary), "status": formsvc.status_of(f)} for f in rows]


def _payload(db: Session, event, request_base: str = "") -> dict:
    host = public_slug.forms_host_base()
    return {
        "slug": event.public_slug, "host_base": host or None, "clean_enabled": bool(host),
        "base": host or publicurl.base(request_base),
        "forms": _forms(db, event.id),
        "history": [{"slug": h.slug, "hold_until": h.hold_until.isoformat()} for h in db.query(SlugHistory).filter(SlugHistory.event_id == event.id).order_by(SlugHistory.id.desc()).limit(10)],
    }


@router.get("/events/{event_id}/public-link")
def get_link(event_id: int, slug: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    """Con `?slug=` solo valida ese nombre (¿es válido y está libre?) para la vista previa mientras se escribe."""
    event = get_event_for_staff(event_id, db, staff)
    if slug is not None:
        s = slug.strip().lower()
        err = public_slug.validate(s) or ("Ese nombre de enlace ya lo usa otro evento" if s != event.public_slug and public_slug.is_taken(db, s, event.id) else None)
        return {"slug": s, "ok": err is None, "error": err}
    if not event.public_slug:                           # evento anterior a la 0113 que quedó sin nombre (p. ej. importado antes): se le da uno
        public_slug.ensure(db, event)
        db.commit()
    return _payload(db, event)


@router.put("/events/{event_id}/public-link")
def update_link(event_id: int, data: LinkUpdate, db: Session = Depends(get_db), staff: StaffUser = Depends(_who)):
    event = get_event_for_staff(event_id, db, staff)
    event_lease.assert_editable(event)
    changes = []
    if data.slug is not None:
        old = event.public_slug
        try:
            new = public_slug.rename(db, event, data.slug)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if new != old:
            changes.append(f"nombre del enlace: {old or '—'} → {new}")
    if data.clear_primary:
        db.query(WebForm).filter(WebForm.event_id == event.id, WebForm.is_primary.is_(True)).update({"is_primary": False}, synchronize_session=False)
        changes.append("sin formulario principal")
    elif data.primary_form_id is not None:
        form = db.query(WebForm).filter(WebForm.id == data.primary_form_id, WebForm.event_id == event.id, WebForm.kind == "registration", WebForm.archived_at.is_(None)).first()
        if form is None:
            raise HTTPException(status_code=404, detail="Formulario no encontrado en este evento")
        db.query(WebForm).filter(WebForm.event_id == event.id, WebForm.id != form.id, WebForm.is_primary.is_(True)).update({"is_primary": False}, synchronize_session=False)
        form.is_primary = True
        changes.append(f"formulario principal: {form.name}")
    if changes:
        db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action="edit", entity="event", entity_id=str(event.id), entity_name=event.name, detail=("Enlace de inscripciones — " + "; ".join(changes))[:500]))
        db.commit()
        formsvc.invalidate_public_cache()               # la página pública resuelve el nombre desde la caché: que el cambio se vea ya
    return _payload(db, event)
