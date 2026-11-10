"""Captura de contactos para expositores (Fase 8, docs/22_CONTACTOS_EXPOSITORES.md).

La persona decide si comparte sus datos (nombre, empresa, cargo, teléfono y correo) con los expositores del evento; la decisión queda en `audit_contact_shares` (solo INSERT; vigente = el último registro).
Sin autorización vigente NO sale ningún dato: ni en la tarjeta pública, ni en la lista del expositor, ni en el Excel. Los menores de 18 años no comparten. Nada de lo que se guarda va a los logs.
Este módulo no toca la red: tarjetas vCard, texto de la autorización, reglas y consultas.
"""
import re
import secrets
import uuid
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import consent, minors, qr_vcard
from app.models import AuditContactShare, ContactCard, Event, EventAttendee, EventExhibitor, ExhibitorLead, User
from app.timeutil import utcnow

VERSION = "v1.0_contacto"
SHARE_TEXT = (
    "Autorizo de forma libre, previa, expresa e informada que mi nombre, empresa, cargo, teléfono y correo electrónico sean entregados a los expositores de este evento "
    "a quienes yo les permita escanear mi código, con la única finalidad de que me contacten sobre sus productos o servicios relacionados con el evento. "
    "Es voluntario: puedo no aceptar sin perder mi ingreso, y puedo retirar esta autorización en cualquier momento desde esta misma página."
)
ADULT_TEXT = "Confirmo que soy mayor de 18 años."
EXHIBITOR_MAX_SCANS = (60, 60.0)            # intentos por minuto y por expositor (frena a quien pruebe cédulas al azar)
EXHIBITOR_MAX_DAILY = 800                   # contactos distintos que un expositor puede registrar (la lista no es un volcado del evento)


def new_token() -> str:
    return secrets.token_urlsafe(18)


def text_hash() -> str:
    return consent.text_hash(SHARE_TEXT)


# ------------------------------------------------------------------------------------------------ vCard
def _esc(v) -> str:
    """Valor de texto de vCard 3.0: barra, coma, punto y coma y saltos de línea escapados; sin caracteres de control."""
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]", "", str(v or ""))          # F5-9 B: también NEL/C1 y los separadores de línea Unicode (algunos lectores parten la línea con ellos)
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _fold(line: str) -> str:
    """Líneas de máximo 75 octetos, continuación con espacio (RFC 6350 §3.2); se parte por caracteres, nunca en medio de uno."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def vcard(first_name="", last_name="", org="", title="", phone="", email="", note="") -> str:
    """Tarjeta vCard 3.0 (la que abren de una vez «Contactos» de iPhone y Android). Solo trae los campos que vengan con valor."""
    full = " ".join(x for x in (str(first_name or "").strip(), str(last_name or "").strip()) if x) or str(org or "").strip() or "Contacto"
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{_esc(last_name)};{_esc(first_name)};;;", f"FN:{_esc(full)}"]
    if org:
        lines.append(f"ORG:{_esc(org)}")
    if title:
        lines.append(f"TITLE:{_esc(title)}")
    if phone:
        lines.append(f"TEL;TYPE=CELL:{_esc(phone)}")
    if email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_esc(email)}")
    if note:
        lines.append(f"NOTE:{_esc(note)}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def file_name(*parts) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p or "") for p in parts)).strip("_")[:40]
    return (base or "contacto") + ".vcf"


# ------------------------------------------------------------------------------------------------ consentimiento
def latest(db: Session, tenant_id: str, user_id: str, event_id: int) -> Optional[AuditContactShare]:
    return (db.query(AuditContactShare).filter(AuditContactShare.tenant_id == tenant_id, AuditContactShare.event_id == event_id, AuditContactShare.user_id == str(user_id))
            .order_by(AuditContactShare.at.desc(), AuditContactShare.id.desc()).first())


def is_sharing(db: Session, tenant_id: str, user_id: str, event_id: int) -> bool:
    row = latest(db, tenant_id, user_id, event_id)
    return bool(row and row.reason == "consent" and row.shared and row.adult_confirmed)


def sharing_ids(db: Session, tenant_id: str, event_id: int, user_ids) -> set:
    """De estas cédulas, cuáles tienen autorización VIGENTE (una consulta; el último registro de cada una manda)."""
    ids = [str(u) for u in user_ids]
    if not ids:
        return set()
    last = (db.query(AuditContactShare.user_id, func.max(AuditContactShare.at).label("at")).filter(AuditContactShare.tenant_id == tenant_id, AuditContactShare.event_id == event_id,
                                                                                                  AuditContactShare.user_id.in_(ids)).group_by(AuditContactShare.user_id).subquery())
    rows = (db.query(AuditContactShare).join(last, (AuditContactShare.user_id == last.c.user_id) & (AuditContactShare.at == last.c.at))
            .filter(AuditContactShare.tenant_id == tenant_id, AuditContactShare.event_id == event_id).all())
    return {r.user_id for r in rows if r.reason == "consent" and r.shared and r.adult_confirmed}


def is_minor(user: User) -> bool:
    if user.is_biometric_enabled is False:
        return True
    if user.birth_date:
        return minors.age_years(user.birth_date) < minors.ADULT_AGE
    return False


def record(db: Session, event: Event, user: User, *, accept: bool, adult: bool, device: str = "web-card") -> AuditContactShare:
    """Inserta la constancia. Aceptar exige ser mayor de 18 (la base o la confirmación de la persona); retirar siempre se puede. No hace commit."""
    if accept and (is_minor(user) or not adult):
        raise ValueError("adult_required")
    row = AuditContactShare(id=str(uuid.uuid4()), tenant_id=event.tenant_id, event_id=event.id, user_id=str(user.id), cedula_hash=consent.cedula_hash(user.id), at=utcnow(),
                            version=VERSION, text_hash=text_hash(), shared=bool(accept), adult_confirmed=bool(accept and adult), reason="consent" if accept else "revocation")
    db.add(row)
    return row


# ------------------------------------------------------------------------------------------------ tarjetas y datos
def event_open(event: Optional[Event]) -> bool:
    return bool(event and event.archived_at is None and event.data_archived_at is None)


def person_card(db: Session, event: Event, user_id: str) -> ContactCard:
    card = db.query(ContactCard).filter_by(event_id=event.id, tenant_id=event.tenant_id, user_id=str(user_id)).first()
    if card is None:
        card = ContactCard(tenant_id=event.tenant_id, event_id=event.id, user_id=str(user_id), token=new_token(), share_token=new_token())
        db.add(card)
        db.flush()
    return card


def shared_data(user: User) -> dict:
    """Lo único que sale de una persona que comparte. Nada más (ni cédula, ni fecha de nacimiento, ni extras)."""
    return {"first_name": (user.first_name or "").strip(), "last_name": (user.last_name or "").strip(), "company": (user.entity or "").strip(),
            "title": (user.role or "").strip(), "phone": (user.phone or "").strip(), "email": (user.email or "").strip()}


def person_vcard(user: User, event_name: str = "") -> str:
    d = shared_data(user)
    return vcard(d["first_name"], d["last_name"], d["company"], d["title"], d["phone"], d["email"], note=f"Contacto en {event_name}" if event_name else "")


def exhibitor_vcard(ex: EventExhibitor, event_name: str = "") -> str:
    first, _, last = (ex.contact_name or "").strip().partition(" ")
    return vcard(first, last, ex.name, ex.title or "", ex.phone or "", ex.email or "", note=f"Expositor en {event_name}" if event_name else "")


def find_person_by_card(db: Session, share_token: str):
    """(tarjeta, evento, persona) de una tarjeta pública, o None. No mira si comparte: eso lo decide quien llama."""
    card = db.query(ContactCard).filter(ContactCard.share_token == share_token).first()
    if not card:
        return None
    event = db.get(Event, card.event_id)
    user = db.query(User).filter(User.id == card.user_id, User.tenant_id == card.tenant_id).first()
    if not event or not user:
        return None
    return card, event, user


_CARD_URL = re.compile(r"/tarjeta/([A-Za-z0-9_-]{16,})")


def parse_scanned(text: str) -> dict:
    """Lo que leyó la cámara del expositor: la tarjeta pública de una persona (`…/tarjeta/<token>`), o la cédula del QR de la escarapela (como en Registro: `cédula` o `cédula|nombre|apellido`)."""
    raw = qr_vcard.unwrap(str(text or "")[:1500]).strip()[:500]          # QR en vCard (Fase 10, C): el código va en NOTE
    m = _CARD_URL.search(raw)
    if m:
        return {"kind": "card", "token": m.group(1)}
    if not raw:
        return {"kind": "none"}
    parts = [p.strip() for p in raw.split("|") if p.strip()] if "|" in raw else [raw]
    idx = next((i for i, p in enumerate(parts) if re.fullmatch(r"\d[\d.\s-]{2,}\d", p) and len(re.sub(r"\D", "", p)) >= 4), 0)
    ced = re.sub(r"[.\s]", "", parts[idx]) if parts else ""
    return {"kind": "cedula", "cedula": ced} if re.fullmatch(r"[A-Za-z0-9-]{4,30}", ced) else {"kind": "none"}


def find_person_by_cedula(db: Session, event: Event, cedula: str) -> Optional[User]:
    """La persona del evento con esa cédula (con o sin ceros a la izquierda). None si no está inscrita en ESTE evento."""
    ced = str(cedula or "").strip()
    stripped = ced.lstrip("0") or ced
    att = (db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.tenant_id == event.tenant_id)
           .filter((EventAttendee.user_id == ced) | (func.ltrim(EventAttendee.user_id, "0") == stripped)).first())
    if not att:
        return None
    return db.query(User).filter(User.id == att.user_id, User.tenant_id == event.tenant_id).first()


def add_lead(db: Session, ex: EventExhibitor, user: User) -> bool:
    """Registra el contacto del expositor (una sola vez por persona). True si es nuevo. No hace commit."""
    if db.query(ExhibitorLead).filter_by(exhibitor_id=ex.id, tenant_id=ex.tenant_id, user_id=str(user.id)).first():
        return False
    db.add(ExhibitorLead(exhibitor_id=ex.id, event_id=ex.event_id, tenant_id=ex.tenant_id, user_id=str(user.id)))
    return True


def leads_with_data(db: Session, ex: EventExhibitor) -> list:
    """Los contactos del expositor que SIGUEN compartiendo, con los datos autorizados y la tarjeta para guardarlos. Quien retiró su autorización desaparece."""
    leads = db.query(ExhibitorLead).filter_by(exhibitor_id=ex.id).order_by(ExhibitorLead.scanned_at.desc(), ExhibitorLead.id.desc()).all()
    ok = sharing_ids(db, ex.tenant_id, ex.event_id, [l.user_id for l in leads])
    ids = list({l.user_id for l in leads if l.user_id in ok})
    users, cards = {}, {}
    if ids:                                                   # F5-9 B: dos consultas, no dos por contacto (la página del expositor recarga la lista tras cada escaneo; con 800 eran 1 600)
        users = {u.id: u for u in db.query(User).filter(User.tenant_id == ex.tenant_id, User.id.in_(ids)).all()}
        cards = {c.user_id: c for c in db.query(ContactCard).filter(ContactCard.event_id == ex.event_id, ContactCard.tenant_id == ex.tenant_id, ContactCard.user_id.in_(ids)).all()}
    out = []
    for l in leads:
        if l.user_id not in ok:
            continue
        user, card = users.get(l.user_id), cards.get(l.user_id)
        if user and card and not is_minor(user):
            out.append({**shared_data(user), "scanned_at": l.scanned_at.isoformat(), "card": card.share_token})
    return out
