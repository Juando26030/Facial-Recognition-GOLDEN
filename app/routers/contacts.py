"""Captura de contactos para expositores (Fase 8; docs/22_CONTACTOS_EXPOSITORES.md).

Cuatro caras, todas con enlaces secretos y aleatorios (ninguna lleva cédula en la dirección):
  · /contacto/<token>      la PERSONA decide si comparte sus datos con expositores (autorización expresa, retirable) y ve su QR/NFC.
  · /tarjeta/<token>       lo que abre el teléfono de quien escanea el QR/NFC: «Guardar contacto» (.vcf). De una persona SOLO si comparte; de un expositor, su tarjeta.
  · /expositor/<token>     el EXPOSITOR escanea asistentes, ve su lista (solo quienes siguen compartiendo) y la baja a Excel.
  · /api/events/{id}/exhibitors   el PERSONAL (coordinador en adelante) crea expositores y entrega sus enlaces.
Los endpoints son `def` (todo el acceso a base es síncrono). Nada de datos personales en los logs."""
import io
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import contacts, xlsafe
from app.auth import get_event_for_staff, require_role
from app.database import get_db
from app.models import ContactCard, Event, EventExhibitor, ExhibitorLead, StaffUser, User
from app.timeutil import to_local, utcnow
from app.ttlcache import SlidingLimiter

router = APIRouter()
_limiter = SlidingLimiter()
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
GONE_HTML = "<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Enlace no disponible</h3>"


def _page(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    from app.main import event_logo_url, templates  # import tardío: main.py importa este módulo
    from app import brandcolor
    event: Optional[Event] = ctx.pop("event", None)
    ctx.update({"logo_url": event_logo_url(event) if event else "", "brand_css": brandcolor.css(event.brand_color) if event else ""})
    resp = templates.TemplateResponse(request=request, name=name, context=ctx, status_code=status_code)
    resp.headers.update(NO_STORE)
    return resp


def _json(data: dict, status: int = 200) -> Response:
    import json
    return Response(json.dumps(data, ensure_ascii=False), status_code=status, media_type="application/json", headers=NO_STORE)


# ------------------------------------------------------------------------------------------------ la PERSONA (enlace privado)
def _own(db: Session, token: str):
    card = db.query(ContactCard).filter(ContactCard.token == token).first()
    event = db.get(Event, card.event_id) if card else None
    user = db.query(User).filter(User.id == card.user_id, User.tenant_id == card.tenant_id).first() if card else None
    if not card or not user or not contacts.event_open(event):
        raise HTTPException(status_code=404, detail="Enlace no disponible")
    return card, event, user


@router.get("/contacto/{token}", response_class=HTMLResponse)
def person_page(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        _, event, _ = _own(db, token)
    except HTTPException:
        return HTMLResponse(GONE_HTML, status_code=404, headers=NO_STORE)
    return _page(request, "contact_manage.html", token=token, event=event, event_name=event.name)


@router.get("/contacto/{token}/data")
def person_data(token: str, db: Session = Depends(get_db)):
    card, event, user = _own(db, token)
    minor = contacts.is_minor(user)
    return _json({"event_name": event.name, "first_name": (user.first_name or "").strip(), "minor": minor, "sharing": contacts.is_sharing(db, event.tenant_id, user.id, event.id),
                  "needs_adult": (not minor) and user.birth_date is None, "text": contacts.SHARE_TEXT, "adult_text": contacts.ADULT_TEXT, "version": contacts.VERSION,
                  "card_path": f"/tarjeta/{card.share_token}"})


@router.post("/contacto/{token}/share")
def person_share(token: str, data: dict, db: Session = Depends(get_db)):
    """Acepta o retira. Aceptar exige mayoría de edad; la constancia queda en `audit_contact_shares` (solo INSERT)."""
    card, event, user = _own(db, token)
    accept = bool((data or {}).get("accept"))
    if accept and not _limiter.hit(("share", token), 20, 3600):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un momento.")
    try:
        contacts.record(db, event, user, accept=accept, adult=bool((data or {}).get("adult")) or user.birth_date is not None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Para compartir tus datos debes ser mayor de 18 años y confirmarlo.")
    db.commit()
    return _json({"sharing": accept})


# ------------------------------------------------------------------------------------------------ la TARJETA pública (lo que abre el teléfono al escanear)
def _card_subject(db: Session, token: str):
    """('person', evento, usuario) | ('exhibitor', evento, expositor) | None. Una persona solo si comparte; un expositor solo si está activo."""
    found = contacts.find_person_by_card(db, token)
    if found:
        _, event, user = found
        if contacts.event_open(event) and not contacts.is_minor(user) and contacts.is_sharing(db, event.tenant_id, user.id, event.id):
            return "person", event, user
        return None
    ex = db.query(EventExhibitor).filter(EventExhibitor.card_token == token).first()
    event = db.get(Event, ex.event_id) if ex else None
    if ex and ex.active and contacts.event_open(event):
        return "exhibitor", event, ex
    return None


@router.get("/tarjeta/{token}", response_class=HTMLResponse)
def card_page(token: str, request: Request, db: Session = Depends(get_db)):
    found = _card_subject(db, token)
    event = found[1] if found else None
    return _page(request, "contact_card.html", token=token, event=event, event_name=event.name if event else "", available=bool(found), status_code=200 if found else 404)


@router.get("/tarjeta/{token}/data")
def card_data(token: str, db: Session = Depends(get_db)):
    found = _card_subject(db, token)
    if not found:
        return _json({"available": False}, 404)
    kind, event, subject = found
    if kind == "person":
        d = contacts.shared_data(subject)
        return _json({"available": True, "kind": "person", "event_name": event.name, "name": " ".join(x for x in (d["first_name"], d["last_name"]) if x), "company": d["company"], "title": d["title"],
                      "phone": d["phone"], "email": d["email"]})
    return _json({"available": True, "kind": "exhibitor", "event_name": event.name, "name": subject.contact_name or subject.name, "company": subject.name, "title": subject.title or "",
                  "phone": subject.phone or "", "email": subject.email or ""})


@router.get("/tarjeta/{token}/vcard")
def card_vcard(token: str, db: Session = Depends(get_db)):
    found = _card_subject(db, token)
    if not found:
        raise HTTPException(status_code=404, detail="Enlace no disponible")
    kind, event, subject = found
    if kind == "person":
        body, name = contacts.person_vcard(subject, event.name), contacts.file_name(subject.first_name, subject.last_name)
    else:
        body, name = contacts.exhibitor_vcard(subject, event.name), contacts.file_name(subject.name)
    return Response(body, media_type="text/vcard; charset=utf-8", headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------------------------------------ el EXPOSITOR (enlace privado)
def _exhibitor(db: Session, token: str):
    ex = db.query(EventExhibitor).filter(EventExhibitor.token == token).first()
    event = db.get(Event, ex.event_id) if ex else None
    if not ex or not ex.active or not contacts.event_open(event):
        raise HTTPException(status_code=404, detail="Enlace no disponible")
    return ex, event


@router.get("/expositor/{token}", response_class=HTMLResponse)
def exhibitor_page(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        ex, event = _exhibitor(db, token)
    except HTTPException:
        return HTMLResponse(GONE_HTML, status_code=404, headers=NO_STORE)
    return _page(request, "expositor.html", token=token, event=event, event_name=event.name, exhibitor_name=ex.name)


@router.get("/expositor/{token}/data")
def exhibitor_data(token: str, db: Session = Depends(get_db)):
    ex, event = _exhibitor(db, token)
    leads = contacts.leads_with_data(db, ex)
    return _json({"name": ex.name, "event_name": event.name, "card_path": f"/tarjeta/{ex.card_token}", "count": len(leads), "leads": leads})


@router.post("/expositor/{token}/scan")
def exhibitor_scan(token: str, data: dict, db: Session = Depends(get_db)):
    """Lo que leyó la cámara. Respuesta SIEMPRE igual si no hay datos que dar («no comparte o no está inscrita»), para que escanear cédulas al azar no revele quién está inscrito."""
    ex, event = _exhibitor(db, token)
    if not _limiter.hit(("scan", ex.id), *contacts.EXHIBITOR_MAX_SCANS):
        return _json({"status": "limit", "message": "Vas muy rápido: espera unos segundos."}, 429)
    scanned = contacts.parse_scanned((data or {}).get("text"))
    user = None
    if scanned["kind"] == "card":
        found = contacts.find_person_by_card(db, scanned["token"])
        if found and found[1].id == event.id:
            user = found[2]
    elif scanned["kind"] == "cedula":
        user = contacts.find_person_by_cedula(db, event, scanned["cedula"])
    if user is None or contacts.is_minor(user) or not contacts.is_sharing(db, event.tenant_id, user.id, event.id):
        return _json({"status": "not_sharing", "message": "Esta persona no comparte sus datos con expositores (o no está inscrita en este evento)."})
    since = utcnow() - timedelta(hours=24)
    if db.query(func.count(ExhibitorLead.id)).filter(ExhibitorLead.exhibitor_id == ex.id, ExhibitorLead.scanned_at >= since).scalar() >= contacts.EXHIBITOR_MAX_DAILY:
        return _json({"status": "limit", "message": "Llegaste al máximo de contactos de hoy."}, 429)
    is_new = contacts.add_lead(db, ex, user)
    card = contacts.person_card(db, event, user.id)
    db.commit()
    return _json({"status": "new" if is_new else "known", "person": contacts.shared_data(user), "card": card.share_token})


@router.get("/expositor/{token}/vcard/{share}")
def exhibitor_lead_vcard(token: str, share: str, db: Session = Depends(get_db)):
    ex, event = _exhibitor(db, token)
    found = contacts.find_person_by_card(db, share)
    if not found or found[1].id != event.id or not contacts.is_sharing(db, event.tenant_id, found[2].id, event.id) or contacts.is_minor(found[2]):
        raise HTTPException(status_code=404, detail="Contacto no disponible")
    if not db.query(ExhibitorLead).filter_by(exhibitor_id=ex.id, tenant_id=event.tenant_id, user_id=str(found[2].id)).first():
        raise HTTPException(status_code=404, detail="Contacto no disponible")
    name = contacts.file_name(found[2].first_name, found[2].last_name)
    return Response(contacts.person_vcard(found[2], event.name), media_type="text/vcard; charset=utf-8", headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/expositor/{token}/leads.xlsx")
def exhibitor_xlsx(token: str, db: Session = Depends(get_db)):
    ex, event = _exhibitor(db, token)
    wb = Workbook()
    ws = wb.active
    ws.title = "Contactos"
    ws.append(["Nombre", "Apellido", "Empresa", "Cargo", "Teléfono", "Correo", "Escaneado"])
    for l in contacts.leads_with_data(db, ex):
        ws.append([l["first_name"], l["last_name"], l["company"], l["title"], l["phone"], l["email"], to_local(_naive(l["scanned_at"])).strftime("%Y-%m-%d %H:%M")])
    xlsafe.safe_workbook(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{contacts.file_name("contactos", ex.name)[:-4]}.xlsx"'})


def _naive(iso: str):
    from datetime import datetime
    return datetime.fromisoformat(iso).replace(tzinfo=None)


# ------------------------------------------------------------------------------------------------ el PERSONAL: crear expositores y entregar sus enlaces
STAFF = require_role("coordinador")


def _ser(ex: EventExhibitor) -> dict:
    return {"id": ex.id, "name": ex.name, "contact_name": ex.contact_name or "", "title": ex.title or "", "email": ex.email or "", "phone": ex.phone or "", "active": bool(ex.active),
            "private_path": f"/expositor/{ex.token}", "card_path": f"/tarjeta/{ex.card_token}"}


def _clean(data: dict, partial: bool = False) -> dict:
    out = {}
    for key, limit in (("name", 120), ("contact_name", 120), ("title", 120), ("email", 160), ("phone", 40)):
        if key in data or not partial:
            out[key] = " ".join(str((data or {}).get(key) or "").split())[:limit]
    if "name" in out and not out["name"]:
        raise HTTPException(status_code=400, detail="Escribe el nombre del expositor (empresa o stand)")
    if out.get("email") and not __import__("re").fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", out["email"]):
        raise HTTPException(status_code=400, detail="El correo no parece válido")
    return out


def _ex_or_404(db: Session, event_id: int, ex_id: int) -> EventExhibitor:
    ex = db.query(EventExhibitor).filter_by(id=ex_id, event_id=event_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Expositor no encontrado")
    return ex


@router.get("/api/events/{event_id}/exhibitors")
def list_exhibitors(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    rows = db.query(EventExhibitor).filter_by(event_id=event.id).order_by(EventExhibitor.name).all()
    counts = dict(db.query(ExhibitorLead.exhibitor_id, func.count(ExhibitorLead.id)).filter(ExhibitorLead.event_id == event.id).group_by(ExhibitorLead.exhibitor_id).all())
    return [{**_ser(r), "leads": int(counts.get(r.id, 0))} for r in rows]


@router.post("/api/events/{event_id}/exhibitors")
def create_exhibitor(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    ex = EventExhibitor(tenant_id=event.tenant_id, event_id=event.id, token=contacts.new_token(), card_token=contacts.new_token(), created_by_id=staff.id, **_clean(data))
    db.add(ex)
    db.commit()
    return _ser(ex)


@router.patch("/api/events/{event_id}/exhibitors/{ex_id}")
def update_exhibitor(event_id: int, ex_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    ex = _ex_or_404(db, event.id, ex_id)
    for k, v in _clean(data or {}, partial=True).items():
        setattr(ex, k, v)
    if "active" in (data or {}):
        ex.active = bool(data["active"])
    db.commit()
    return _ser(ex)


@router.post("/api/events/{event_id}/exhibitors/{ex_id}/rotate")
def rotate_exhibitor(event_id: int, ex_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    """Cambia los DOS enlaces (el privado y el de la tarjeta): sirve si el enlace se filtró. Los anteriores dejan de funcionar."""
    event = get_event_for_staff(event_id, db, staff)
    ex = _ex_or_404(db, event.id, ex_id)
    ex.token, ex.card_token = contacts.new_token(), contacts.new_token()
    db.commit()
    return _ser(ex)


@router.delete("/api/events/{event_id}/exhibitors/{ex_id}")
def delete_exhibitor(event_id: int, ex_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(STAFF)):
    event = get_event_for_staff(event_id, db, staff)
    ex = _ex_or_404(db, event.id, ex_id)
    db.query(ExhibitorLead).filter_by(exhibitor_id=ex.id).delete(synchronize_session=False)
    db.delete(ex)
    db.commit()
    return {"ok": True}
