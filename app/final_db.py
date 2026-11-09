"""Base de datos FINAL del evento (Fase 5, decisión del dueño 8-nov-2026): el coordinador sube UN archivo (xlsx o csv) con la base ya procesada por humanos. Es la que se le entrega
al cliente al facturar; NO es la base de estadísticas ni la de personas del evento.

* Se guarda por `app/storage.py` con una clave por evento: `<cliente>/final_database/<evento>/base_final<ext>` (subir otra reemplaza la anterior y borra la vieja si cambió la extensión).
* Queda registrado en `events.final_db_*` (clave, nombre, cuándo, quién) y en `audit_actions` (`final_db_upload` / `final_db_replace`; sin el nombre del archivo ni datos personales).
* Al subirla o reemplazarla se encola (misma transacción) un correo a la comercial del evento: «Ya se subió la base de datos final… Revisa si ya se puede facturar». El trabajo solo guarda ids."""
import html
import io
import logging
import os
import zipfile
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import audit_actions, jobs, publicurl
from app.database import SessionLocal
from app.mailer import clean_subject, send_mail
from app.models import Event, StaffUser
from app.staff_credentials import valid_email
from app.storage import get_storage, key_of, normalize_key
from app.timeutil import utcnow

log = logging.getLogger("golden.finaldb")

KIND = "final_db_notice"
EXTENSIONS = {".xlsx", ".csv"}
MAX_BYTES = 50 * 1024 * 1024
MEDIA_TYPES = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".csv": "text/csv"}
BAD_TYPE = "La base de datos final debe ser un archivo Excel (.xlsx) o CSV (.csv)"


def validate(filename: Optional[str], content: bytes) -> str:
    """Devuelve la extensión (en minúsculas) o lanza 400 en español. Se mira el CONTENIDO real, no solo el nombre."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in EXTENSIONS:
        raise HTTPException(status_code=400, detail=BAD_TYPE)
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"El archivo pesa más de {MAX_BYTES // (1024 * 1024)} MB")
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail=BAD_TYPE)
        if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
            raise HTTPException(status_code=400, detail=BAD_TYPE)
    elif b"\x00" in content[:65536] or content.startswith((b"PK\x03\x04", b"%PDF", bytes.fromhex("d0cf11e0"))):
        raise HTTPException(status_code=400, detail=BAD_TYPE)
    return ext


def storage_key(event: Event, ext: str) -> str:
    return key_of(event.tenant_id, "final_database", event.id, f"base_final{ext}")


def save(db: Session, event: Event, staff: StaffUser, filename: str, content: bytes) -> dict:
    """Valida, guarda (reemplaza si ya había), registra y encola el aviso a la comercial. No confirma: quien llama hace `db.commit()` y luego `jobs.kick()`."""
    ext = validate(filename, content)
    key = storage_key(event, ext)
    replacing = bool(event.final_db_key)
    old_key = event.final_db_key
    get_storage().put(key, content)
    if old_key and normalize_key(old_key) != key:
        try:
            get_storage().delete(old_key)          # cambió de formato: la nueva reemplaza a la vieja
        except Exception:
            log.warning("base final: no se pudo borrar la anterior del evento %s", event.id)
    now = utcnow()
    event.final_db_key, event.final_db_name = key, (os.path.basename(filename or "") or f"base_final{ext}")[:200]
    event.final_db_uploaded_at, event.final_db_uploaded_by_id = now, staff.id
    audit_actions.record(db, staff, "final_db_replace" if replacing else "final_db_upload", "event", event.id, event.name, f"{len(content)} bytes, {ext}")
    queued = enqueue_notice(db, event, nonce=now.isoformat())
    return {"replaced": replacing, "notice_queued": queued}


def event_link(event: Event, request_base: str = "") -> str:
    """Enlace a la edición del evento (https salvo localhost). Vacío si el entorno no tiene dirección pública."""
    base = publicurl.base(request_base)
    if not base:
        return ""
    parts = urlsplit(base)
    if parts.scheme == "http" and (parts.hostname or "") not in ("localhost", "127.0.0.1", "[::1]", "testserver"):
        base = "https://" + base[len("http://"):]
    return f"{base}/eventos?editar={int(event.id)}"


def render(event_name: str, commercial_name: str, link: str) -> dict:
    nombre = (commercial_name or "").strip()
    saludo = f"Hola {nombre}:" if nombre else "Hola:"
    frase = f"Ya se subió la base de datos final del evento {event_name}. Revisa si ya se puede facturar el evento."
    text = "\n".join([saludo, "", frase] + (["", f"Abre la edición del evento: {link}"] if link else []))
    e = html.escape
    html_body = (f"<div style=\"font-family:Agrandir,Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#222;line-height:1.5\"><p>{e(saludo)}</p><p>{e(frase)}</p>"
                 + (f"<p><a href=\"{e(link)}\">Abrir la edición del evento</a></p>" if link else "") + "</div>")
    return {"subject": clean_subject(f"Base de datos final del evento {event_name}"), "text": text, "html": html_body}


def enqueue_notice(db: Session, event: Event, nonce: str = "") -> bool:
    """Encola el correo a la comercial del evento. False (y no falla) si el evento no tiene comercial o ella no tiene un correo válido."""
    commercial = event.commercial
    if commercial is None or not valid_email(commercial.email):
        return False
    jobs.enqueue(db, KIND, {"event_id": int(event.id)}, max_attempts=4, dedupe_key=f"{KIND}:{event.id}:{nonce}")
    return True


@jobs.handler("final_db_notice")
def run_notice(payload: dict) -> None:
    with SessionLocal() as db:
        event = db.get(Event, int(payload["event_id"]))
        if event is None or not event.final_db_key:
            return                                           # el evento ya no existe o la base se quitó: no hay nada que avisar
        commercial = event.commercial
        to = valid_email(commercial.email) if commercial is not None else ""
        if not to or not commercial.is_active:
            return                                           # sin comercial o sin correo: no es un error
        mail = render(event.name, commercial.full_name or "", event_link(event))
        result = send_mail(to, mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("base final: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar el aviso de la base final")          # se reintenta con espera creciente
