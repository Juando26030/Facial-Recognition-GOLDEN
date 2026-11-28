"""Notificaciones de cada cuenta del personal (Fase 5, 9-nov-2026): un aviso se guarda para la campana de la aplicación Y sale por correo al correo registrado de la persona.

  notify(db, staff_ids, kind=..., title=..., body=..., url=..., event_id=..., dedupe_key=...) -> cantidad de avisos nuevos
Agrega filas y trabajos a la transacción de `db` (no confirma); quien llama confirma y después llama `jobs.kick()`. Con `dedupe_key`, a la misma cuenta no se le repite el mismo aviso.
El correo va por la cola (`notification_mail`, idempotente). Nunca lleva datos personales de asistentes: solo el texto del aviso, el nombre del evento y un enlace.
"""
import html
import logging
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app import jobs, publicurl
from app.database import SessionLocal
from app.mailer import clean_subject, send_mail
from app.models import Notification, StaffUser
from app.staff_credentials import valid_email
from app.timeutil import utcnow

log = logging.getLogger(__name__)
KIND = "notification_mail"
MAX_TITLE, MAX_BODY = 160, 1500


def notify(db: Session, staff_ids: Iterable[int], *, kind: str, title: str, body: str = "", url: Optional[str] = None, event_id: Optional[int] = None,
           dedupe_key: Optional[str] = None, mail: bool = True) -> int:
    created = 0
    url = internal_url(url)
    for sid in dict.fromkeys(int(i) for i in staff_ids if i):
        if dedupe_key and db.query(Notification.id).filter(Notification.staff_user_id == sid, Notification.dedupe_key == dedupe_key).first():
            continue
        row = Notification(staff_user_id=sid, kind=kind[:40], title=title[:MAX_TITLE], body=(body or "")[:MAX_BODY] or None, url=url, event_id=event_id, dedupe_key=dedupe_key, created_at=utcnow())
        db.add(row)
        db.flush()
        created += 1
        if mail:
            jobs.enqueue(db, KIND, {"notification_id": int(row.id)}, max_attempts=4, dedupe_key=f"{KIND}:{row.id}")
    return created


def internal_url(url: Optional[str]) -> Optional[str]:
    """Solo rutas de la propia aplicación («/inventario»); «//otro-sitio», «/\\otro», esquemas o espacios se descartan (F5-9 D, D3: la campana y el correo no redirigen afuera)."""
    if not isinstance(url, str) or not url.startswith("/") or url.startswith("//") or "\\" in url or any(c.isspace() for c in url) or len(url) > 500:
        return None
    return url


def render_mail(title: str, body: str, url: str = "") -> dict:
    link = f"\n\nAbrir en Orum: {url}" if url else ""
    e = html.escape
    page = f"<p><a href=\"{e(url)}\">Abrir en Orum</a></p>" if url else ""
    return {"subject": clean_subject(title), "text": f"{title}\n\n{body or ''}{link}".strip(),
            "html": f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\"><p><b>{e(title)}</b></p><p>{e(body or '')}</p>{page}</div>"}


def absolute(url: Optional[str]) -> str:
    base = publicurl.base()
    return f"{base}{url}" if base and url and url.startswith("/") else ""


@jobs.handler("notification_mail")
def run_mail(payload: dict) -> None:
    with SessionLocal() as db:
        note = db.get(Notification, int(payload["notification_id"]))
        target = db.get(StaffUser, note.staff_user_id) if note is not None else None
        to = valid_email(target.email) if target is not None else ""
        if note is None or not to or not target.is_active or target.archived_at is not None:
            return                                           # ya no corresponde enviar: no es un error
        mail = render_mail(note.title, note.body or "", absolute(note.url))
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("notificación: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el correo de la notificación")


def serialize(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "url": n.url, "event_id": n.event_id, "created_at": n.created_at.isoformat() + "Z", "read": n.read_at is not None}
