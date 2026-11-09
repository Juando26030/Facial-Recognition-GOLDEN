"""URL limpia de las inscripciones públicas (docs/15 D2.5k, docs/20): `<app>/inscripciones/<evento>` y `/inscripciones/<evento>/<formulario>` (mismo host de la app).

Un evento tiene un `public_slug` ÚNICO en todo el sistema (índice único en minúsculas): se genera de «nombre + año» y lo edita admin/comercial/super_admin. Al renombrar, el viejo
queda en `slug_history` y responde 301 al nuevo; no se reasigna a otro evento durante 12 meses (nadie secuestra un enlace ya enviado). `/f/{id}/{slug}` sigue funcionando siempre.
Este módulo es lo puro (validar, generar) más lo que toca la base; las rutas públicas están en app/routers/clean_url.py y la edición del personal en app/routers/public_link.py."""
import os
import re
import unicodedata
from datetime import timedelta
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import publicurl
from app.models import Event, SlugHistory, WebForm
from app.timeutil import utcnow

MIN_LEN, MAX_LEN = 3, 60
HOLD_DAYS = 365                                  # un slug viejo no se reasigna a otro evento durante 12 meses
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Rutas y nombres de la aplicación que un evento no puede usar como slug (las páginas viven bajo `/inscripciones/`, así que no chocan; la lista se conserva por claridad y por si algún día cambia el prefijo).
RESERVED = frozenset({
    "static", "api", "health", "ready", "healthz", "readyz", "webhooks", "f", "b", "c", "r", "login", "logout", "kiosk", "sistema", "admin", "privacidad", "terminos", "reembolsos",
    "inscripciones", "www", "app", "aceptar", "entrega", "internal", "ver", "dashboard", "eventos", "clientes", "calendario", "configuracion", "staff", "inventario", "sincronizacion",
    "servidor-local", "cambiar-contrasena", "reimpresion", "favicon-ico", "robots-txt", "sitemap-xml", "assets", "docs", "openapi-json", "redoc", "formularios", "formulario",
})


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def validate(slug: str) -> Optional[str]:
    """Mensaje de error (en español) o None si el slug es válido."""
    s = slug or ""
    if len(s) < MIN_LEN or len(s) > MAX_LEN:
        return f"El nombre del enlace debe tener entre {MIN_LEN} y {MAX_LEN} caracteres"
    if not _SLUG_RE.match(s):
        return "Solo letras minúsculas sin tildes, números y guiones (sin espacios ni guiones al inicio o al final)"
    if s.isdigit():
        return "El nombre del enlace no puede ser solo números"
    if s in RESERVED:
        return "Ese nombre está reservado por el sistema: elige otro"
    return None


def candidate(name: str, year: Optional[int]) -> str:
    """«nombre + año» (p. ej. «Congreso G12 2026» -> congreso-g12-2026); acorta el nombre si pasa el límite y garantiza un mínimo válido."""
    base = slugify(name) or "evento"
    suffix = f"-{year}" if year and not re.search(rf"(^|-){year}$", base) else ""
    base = base[: MAX_LEN - len(suffix) - 4].strip("-")
    slug = f"{base}{suffix}".strip("-")
    if len(slug) < MIN_LEN or slug.isdigit() or slug in RESERVED:
        slug = f"evento-{slug}".strip("-")[:MAX_LEN]
    return slug


def with_counter(base: str, n: int) -> str:
    tail = f"-{n}"
    return base[: MAX_LEN - len(tail)].rstrip("-") + tail


def is_taken(db: Session, slug: str, exclude_event_id: Optional[int] = None) -> bool:
    """¿Lo usa otro evento, o está retenido por el historial de otro evento (12 meses)?"""
    q = db.query(Event.id).filter(func.lower(Event.public_slug) == slug)
    if exclude_event_id:
        q = q.filter(Event.id != exclude_event_id)
    if q.first():
        return True
    h = db.query(SlugHistory).filter(SlugHistory.slug == slug, SlugHistory.hold_until > utcnow())
    if exclude_event_id:
        h = h.filter(SlugHistory.event_id != exclude_event_id)
    return h.first() is not None


def unique_for(db: Session, name: str, year: Optional[int], exclude_event_id: Optional[int] = None) -> str:
    base = candidate(name, year)
    slug, n = base, 2
    while validate(slug) or is_taken(db, slug, exclude_event_id):
        slug, n = with_counter(base, n), n + 1
    return slug


def ensure(db: Session, event: Event) -> str:
    """El evento nuevo (o un viejo sin slug) recibe el suyo. No hace commit."""
    if not event.public_slug:
        year = (event.start_date or event.created_at or utcnow()).year
        event.public_slug = unique_for(db, event.name, year, event.id)
    return event.public_slug


def rename(db: Session, event: Event, wanted: str) -> str:
    """Cambia el slug del evento (validado y libre). El anterior queda en el historial con su retención. No hace commit."""
    new = (wanted or "").strip().lower()
    err = validate(new)
    if err:
        raise ValueError(err)
    old = event.public_slug
    if old == new:
        return new
    if is_taken(db, new, event.id):
        raise ValueError("Ese nombre de enlace ya lo usa otro evento")
    hist = db.query(SlugHistory).filter(SlugHistory.slug == new, SlugHistory.event_id == event.id).first()
    if hist:                                                            # volver a un nombre propio anterior: deja de ser «viejo»
        db.delete(hist)
    if old:
        db.add(SlugHistory(slug=old, event_id=event.id, hold_until=utcnow() + timedelta(days=HOLD_DAYS)))
    event.public_slug = new
    return new


# ------------------------------------------------------------------ resolución pública (la usa clean_url.py)
def resolve(db: Session, slug: str, form_slug: Optional[str] = None) -> dict:
    """{'event_id', 'form_slug'} para servir la página; {'redirect': <slug nuevo>} si el slug es viejo; {} si no existe / no hay formulario."""
    s = (slug or "").lower()
    ev = db.query(Event).filter(func.lower(Event.public_slug) == s).first()
    if ev is None:
        h = db.query(SlugHistory).filter(SlugHistory.slug == s).order_by(SlugHistory.id.desc()).first()
        new = db.get(Event, h.event_id).public_slug if h else None
        return {"redirect": new} if new else {}
    forms = db.query(WebForm).filter(WebForm.event_id == ev.id, WebForm.archived_at.is_(None), WebForm.kind == "registration").all()
    if form_slug:
        form = next((f for f in forms if f.slug == form_slug), None)
    else:
        form = next((f for f in forms if f.is_primary), None)
        if form is None:                                                # sin principal marcado: si hay UN solo formulario abierto al público, ese
            open_ = [f for f in forms if f.manual_status == "activo" or f.use_schedule]
            form = open_[0] if len(open_) == 1 else None
    return {"event_id": ev.id, "form_slug": form.slug} if form else {}


# ------------------------------------------------------------------ enlaces que salen del sistema
def forms_host_base() -> str:
    """`PUBLIC_FORMS_BASE_URL` (p. ej. https://app.golden-eventos.com/inscripciones) sin «/» final; vacío = no configurada (todo sigue saliendo como /f/...)."""
    return (os.getenv("PUBLIC_FORMS_BASE_URL") or "").strip().rstrip("/")


def forms_host() -> str:
    return urlsplit(forms_host_base()).netloc


def form_link(request_base: str, event: Event, form: WebForm) -> str:
    """Enlace público de un formulario: limpio si hay `PUBLIC_FORMS_BASE_URL` configurada y el evento ya tiene slug; si no, el de siempre (`/f/<id>/<slug>`)."""
    base = forms_host_base()
    if base and event is not None and event.public_slug:
        return f"{base}/{event.public_slug}/{form.slug}"
    return f"{publicurl.base(request_base)}/f/{form.event_id}/{form.slug}"
