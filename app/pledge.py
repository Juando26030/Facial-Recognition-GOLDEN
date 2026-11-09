"""Compromiso digital del digitador POR EVENTO (Fase 4), construido SOBRE el motor de formularios web (formlib / formsvc / forms_public / form-render.js), no al lado.

Qué es del motor y qué agrega este módulo
  * El compromiso ES un `WebForm` con `kind='pledge'`, uno por evento. Sus campos (identificación, nombre, celular, contacto de emergencia, encuesta Sí/No, casilla de aceptación y firma)
    son campos normales del diseño (`build_design` → `formlib.sanitize_design`). La página pública `/f/<evento>/<slug>`, el estado, el envío, el límite por IP, la caché, los archivos
    (la firma viaja como un archivo PNG), el idempotente por `sid` y el CSRF por Origin son los del motor. El ENLACE SECRETO es el `slug` (144 bits aleatorios): regenerarlo = otro slug.
  * Extensiones MÍNIMAS al motor (todas con un solo punto de entrada en `forms_public`/`formsvc`): campos `sensitive` (se guardan cifrados en `form_submissions.sensitive_json` y fuera de data_json,
    se purgan: `formsvc.purge_sensitive`), campo de archivo `capture='signature'` (lienzo táctil), gancho `on_confirmed` (cuenta temporal + evidencia), `public_state` (el enlace vive hasta que el
    evento finaliza), `confirm_submission` (no alimenta la base del evento).
  * Aquí vive solo lo propio del compromiso: texto, cuenta temporal (usuario = cédula, contraseña inicial = cédula, igual que el Excel), la evidencia por evento y persona
    (`event_staff_pledges`: huella SHA-256, versión del texto, firma, documento), la puerta del ingreso (Camino B/C) y el bloqueo de aprobación.
Nada de datos personales en logs; la auditoría (`audit_actions`) guarda ids, nunca cédulas ni respuestas."""
import hashlib
import html
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit_actions, formlib, formsvc, obs, pledge_texts as T
from app.inputcheck import check_text, check_username
from app.models import Event, EventStaffAuthorization, EventStaffPledge, FormSubmission, StaffUser, WebForm
from app.timeutil import to_local, utcnow
from app.ttlcache import SlidingLimiter

log = logging.getLogger("golden.pledge")

KIND = formsvc.PLEDGE_KIND
SESSION_KEY = "pledge_req"             # en la cookie firmada del navegador que ingresó con la cédula y falta el compromiso: {"uid", "psid"}
FID_ID, FID_NAME, FID_PHONE = "p_id", "p_name", "p_phone"
FID_EM_NAME, FID_EM_PHONE = "p_em_name", "p_em_phone"
FID_MED, FID_DRUG, FID_SUPPORT, FID_CONTRACT, FID_ATTEND = "p_q_med", "p_q_drug", "p_q_support", "p_q_contract", "p_q_attend"
FID_DECL, FID_AUTH_TXT, FID_AUTH, FID_SIG = "p_decl", "t_auth", "p_auth", "p_sig"
SENSITIVE_FIDS = (FID_EM_NAME, FID_EM_PHONE, FID_MED, FID_DRUG, FID_SUPPORT)
HEALTH_FIDS = (FID_MED, FID_DRUG, FID_SUPPORT)
SIGNATURE_MAX_BYTES = 200 * 1024
SIGNATURE_MAX_PIXELS = 1200 * 600
SIGNATURE_MIN_INK = 60            # píxeles con trazo: una firma en blanco o un punto no valen
_PHONE_DIGITS = re.compile(r"\D")


class Skip(Exception):
    """El envío no genera compromiso (cédula de una cuenta que no es de digitador, compromiso ya firmado sin permiso de repetir…). A quien envía se le responde EXACTAMENTE igual que a un envío
    exitoso (no se puede averiguar si una cédula existe); no se guarda nada."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------------------------------- configuración
def _truthy(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def sensitive_enabled() -> bool:
    """PLEDGE_REQUIRE_SENSITIVE_AUTH (1 por defecto): el compromiso pide los datos sensibles (salud, apoyo emocional, contacto de emergencia) y la autorización de la auditora. Con 0 el formulario
    NO los pide ni los guarda (el compromiso y la encuesta de contrato/asistencia siguen) y puede publicarse sin esperar el texto de la auditora."""
    return _truthy("PLEDGE_REQUIRE_SENSITIVE_AUTH", "1")


def draft_allowed() -> bool:
    """¿Se puede publicar el BORRADOR de la autorización? Solo en staging/pruebas/desarrollo o con PLEDGE_ALLOW_DRAFT_TEXT=1."""
    if os.getenv("PLEDGE_ALLOW_DRAFT_TEXT", "").strip() == "1":
        return True
    if os.getenv("DEPLOY_ENV", "").strip().lower() in ("staging", "test", "dev"):
        return True
    return os.getenv("ENVIRONMENT", "development") != "production"


def text_available() -> bool:
    """¿El texto exigido ya se puede mostrar? Sin datos sensibles siempre; con ellos, solo si la auditora lo aprobó (o es un entorno de pruebas / PLEDGE_ALLOW_DRAFT_TEXT=1)."""
    return (not sensitive_enabled()) or T.APPROVED or draft_allowed()


def fingerprint() -> str:
    """Identifica el contenido que el diseño debe tener: texto del compromiso + texto de la autorización + si pide datos sensibles."""
    return f"{T.VERSION}|{T.SENSITIVE_AUTH_VERSION if sensitive_enabled() else '-'}|{int(sensitive_enabled())}"


# ---------------------------------------------------------------------------------------------------- diseño del formulario
def _p(text: str) -> str:
    return "<p>" + html.escape(text, quote=False) + "</p>"


def _ul(items) -> str:
    return "<ul>" + "".join("<li>" + html.escape(i, quote=False) + "</li>" for i in items) + "</ul>"


def _date(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def event_info(db: Optional[Session], event: Event) -> str:
    """Datos del evento que el PDF original pide (evento, fecha, lugar, coordinador)."""
    coord = db.get(StaffUser, event.coordinator_staff_id) if db is not None and event.coordinator_staff_id else None
    when = _date(event.start_date) + (f" al {_date(event.end_date)}" if event.end_date and event.end_date != event.start_date else "")
    parts = [f"Evento: {event.name}"]
    if when:
        parts.append(f"Fecha del evento: {when}")
    place = ", ".join(x for x in (event.location, event.city) if x)
    if place:
        parts.append(f"Lugar: {place}")
    if coord and (coord.full_name or "").strip():
        parts.append(f"Coordinador del evento: {coord.full_name.strip()}")
    return " · ".join(parts)


def event_info_html(db: Optional[Session], event: Event) -> str:
    """Los mismos datos de `event_info`, uno por línea y con el rótulo en negrilla (se ve como una ficha del evento)."""
    lines = []
    for part in event_info(db, event).split(" · "):
        label, _, value = part.partition(": ")
        lines.append(f"<p><b>{html.escape(label, quote=False)}:</b> {html.escape(value, quote=False)}</p>")
    return "".join(lines)


def build_design(db: Optional[Session], event: Event) -> dict:
    """El diseño del formulario del compromiso, validado por el MISMO `formlib.sanitize_design` de cualquier formulario."""
    fields: dict = {}
    rows: list = []

    def add(fid: str, ftype: str, **kw):
        fields[fid] = {"id": fid, "type": ftype, **kw}
        return fid

    def row(*ids):
        rows.append({"align": "left", "items": list(ids)})

    row(add("t_title", "heading", content=T.TITLE + " — " + T.SUBTITLE))
    row(add("t_tag", "paragraph", content=_p(T.TAGLINE)))
    row(add("t_event", "paragraph", content=event_info_html(db, event)))
    row(add("t_intro", "paragraph", content=_p(T.INTRO)))
    n = 0
    last = len(T.SECTIONS)
    for idx, (title, blocks) in enumerate(T.SECTIONS, start=1):
        n += 1
        row(add(f"t_h{n}", "heading", content=title))
        for block in blocks:
            n += 1
            if isinstance(block, str):
                # ids por tipo de bloque (solo para darles estilo en la pantalla): t_sub = subtítulo corto (MUJERES/HOMBRES), t_k = aviso final (IMPACTO), t_b = párrafo y listas
                if len(block) <= 12:
                    row(add(f"t_sub{n}", "paragraph", content=f"<p><b>{html.escape(block, quote=False)}</b></p>"))
                else:
                    row(add(f"t_k{n}" if idx == last else f"t_b{n}", "paragraph", content=_p(block)))
            else:
                row(add(f"t_b{n}", "paragraph", content=_ul(block)))
    row(add("t_data", "heading", content="Tus datos"))
    row(add(FID_ID, "text_short", key="id", label="Identificación (C.C.)", required=True, readonly_when_prefilled=True, placeholder="Solo números"),
        add(FID_NAME, "text_short", key="first_name", label="Nombre completo", required=True))
    row(add(FID_PHONE, "phone", key="phone", label="Celular", required=True))
    yes_no = [T.YES, T.NO]
    sens = sensitive_enabled()
    if sens:
        row(add("t_emerg", "heading", content="Contacto de emergencia"))
        row(add(FID_EM_NAME, "text_short", label="Nombre del familiar", required=True, sensitive=True),
            add(FID_EM_PHONE, "phone", label="Teléfono del familiar", required=True, sensitive=True))
    row(add("t_survey", "heading", content="Encuesta"))
    if sens:
        for fid, q in ((FID_MED, T.Q_MEDICAL), (FID_DRUG, T.Q_MEDICATION), (FID_SUPPORT, T.Q_SUPPORT)):
            row(add(fid, "radio", label=q, options=yes_no, required=True, sensitive=True))
    row(add(FID_CONTRACT, "radio", label=T.Q_CONTRACT, options=yes_no, required=True))
    row(add(FID_ATTEND, "radio", label=T.Q_ATTENDANCE, options=yes_no, required=True))
    if sens:
        row(add(FID_AUTH_TXT, "paragraph", content=_p(T.SENSITIVE_AUTH_TEXT)))
        row(add(FID_AUTH, "checkbox", label="Autorizo el tratamiento de mis datos sensibles en los términos del texto anterior.", required=True))
    row(add("t_footer", "paragraph", content=_p(T.FOOTER)))
    row(add(FID_DECL, "checkbox", label=T.DECLARATION, required=True))
    row(add(FID_SIG, "file", label="Firma del digitador(a) — RECIBIDO", required=True, capture="signature", help="Dibuja tu firma con el dedo o con el mouse."))
    design = {"theme": {"title": "Compromiso digital del digitador", "subtitle": "", "button_text": "Firmar y enviar compromiso"}, "rows": rows, "fields": fields}
    return formlib.sanitize_design(design, set())


def default_settings() -> dict:
    s = formlib.sanitize_settings({
        "closed_template": {"title": "Este compromiso no está disponible", "text": "Pídele a tu coordinador el enlace vigente.", "image": ""},
        "thanks": {"mode": "template", "title": "¡Listo! Recibimos tu compromiso", "text": "Ya puedes ingresar con tu cédula el día del evento; el coordinador te autorizará allí.", "image": "", "url": ""},
        "translate": False, "feed": "manual",
    })
    return {**s, "pledge": {"fingerprint": fingerprint()}}


def form_for(db: Session, event: Event, include_archived: bool = False) -> Optional[WebForm]:
    q = db.query(WebForm).filter(WebForm.event_id == event.id, WebForm.kind == KIND)
    if not include_archived:
        q = q.filter(WebForm.archived_at.is_(None))
    return q.order_by(WebForm.id.desc()).first()


def new_slug(db: Session, event_id: int) -> str:
    """El enlace secreto: 144 bits (18 bytes) aleatorios, único por evento."""
    while True:
        slug = "c" + secrets.token_urlsafe(18).replace("_", "x").replace("-", "y").lower()
        if not db.query(WebForm.id).filter(WebForm.event_id == event_id, WebForm.slug == slug).first():
            return slug


def ensure_design(db: Session, form: WebForm, event: Event) -> bool:
    """Reconstruye el diseño si cambió el texto (o los datos del evento o la configuración de datos sensibles). Devuelve True si lo cambió (sin commit). Las firmas anteriores conservan la
    huella y la versión del texto que cada persona VIO."""
    meta = (formsvc.get_settings(form).get("pledge") or {})
    design = build_design(db, event)
    if meta.get("fingerprint") == fingerprint() and json.dumps(design, sort_keys=True) == json.dumps(formsvc.get_design(form), sort_keys=True):
        return False
    form.design_json = json.dumps(design)
    form.settings_json = json.dumps({**formsvc.get_settings(form), "pledge": {"fingerprint": fingerprint()}})
    return True


def create_or_regenerate(db: Session, event: Event, staff: StaffUser, regenerate: bool = False) -> WebForm:
    """Crea el formulario del compromiso del evento (si no existe) o, con `regenerate`, le cambia el enlace. Lo deja ACTIVO y el compromiso exigido. Sin commit."""
    form = form_for(db, event)
    if form is None:
        form = WebForm(event_id=event.id, name="Compromiso digital del digitador", slug=new_slug(db, event.id), manual_status="activo", use_schedule=False, kind=KIND,
                       design_json=json.dumps(build_design(db, event)), settings_json=json.dumps(default_settings()), test_key=secrets.token_urlsafe(12), created_by_id=staff.id)
        db.add(form)
        action = "create"
    else:
        ensure_design(db, form, event)
        if regenerate or form.manual_status != "activo":
            form.slug = new_slug(db, event.id) if regenerate else form.slug
            form.manual_status = "activo"
        action = "regenerate" if regenerate else "reopen"
    event.pledge_enabled = True
    db.flush()
    audit_actions.record(db, staff, f"pledge_link_{action}", "event", event.id, event.name)
    formsvc.invalidate_public_cache()
    return form


def revoke(db: Session, event: Event, staff: StaffUser) -> bool:
    form = form_for(db, event)
    if form is None or form.manual_status == "finalizado":
        return False
    form.manual_status = "finalizado"          # 404 para el público
    audit_actions.record(db, staff, "pledge_link_revoke", "event", event.id, event.name)
    formsvc.invalidate_public_cache()
    return True


# ---------------------------------------------------------------------------------------------------- estado público del formulario (gancho de formsvc.public_state)
def required(event: Optional[Event]) -> bool:
    return bool(event and event.pledge_enabled and event.status != "finalizado" and event.archived_at is None and event.data_archived_at is None)


def public_state(db: Session, form: WebForm, st: str) -> str:
    """Vigencia del enlace: hasta que el evento finalice (o se archive); y solo con el texto exigido ya aprobado (o permitido en pruebas)."""
    event = db.get(Event, form.event_id)
    if not required(event):
        return "finalizado"
    if not text_available():
        return "cerrado"
    if ensure_design(db, form, event):
        db.commit()
        formsvc.invalidate_public_cache()
    return st


# ---------------------------------------------------------------------------------------------------- validación propia del compromiso
def normalize_cedula(raw) -> str:
    return re.sub(r"[\s.,]", "", str(raw or "")).strip()


def normalize_phone(raw) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()


def extra_errors(form: WebForm, clean: dict, claims: dict) -> dict:
    """Reglas del compromiso que el motor no conoce (se suman a sus errores por campo)."""
    errors = {}
    ced = normalize_cedula(clean.get(FID_ID))
    # Camino B/C (sesión de espera): la cuenta YA existe y su usuario viene fijado, así que se acepta el que tenga (las cuentas creadas a mano o por Excel pueden tener menos de 5 caracteres;
    # el campo no se puede editar y rechazarlo dejaba a la persona sin salida). Por el enlace público (Camino A, crea la cuenta) se mantiene el mínimo de 5.
    minimum = 3 if claims.get("pc") else 5
    try:
        check_username(ced)
        if not re.fullmatch(r"[0-9A-Za-z]{%d,20}" % minimum, ced):
            raise ValueError("x")
    except ValueError:
        errors[FID_ID] = f"«Identificación (C.C.)»: escribe solo tu número de documento ({minimum} a 20 letras o números)"
    for fid in (FID_NAME, FID_EM_NAME):
        if clean.get(fid):
            try:
                check_text(clean[fid], "El nombre")
            except ValueError as exc:
                errors[fid] = str(exc)
    if clean.get(FID_NAME) and len(str(clean[FID_NAME]).strip()) < 3:
        errors[FID_NAME] = "«Nombre completo»: escríbelo completo"
    for fid in (FID_PHONE, FID_EM_PHONE):
        if clean.get(fid) and not 7 <= len(_PHONE_DIGITS.sub("", str(clean[fid]))) <= 15:
            errors[fid] = "Escribe un teléfono válido (7 a 15 dígitos)"
    return errors


def signature_problem(content: bytes) -> Optional[str]:
    """Una firma válida: PNG de lienzo de hasta 200 KiB, de tamaño razonable y con trazo (no en blanco)."""
    import io

    from PIL import Image
    if len(content) > SIGNATURE_MAX_BYTES:
        return "La firma pesa demasiado; bórrala y dibújala de nuevo"
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "La firma debe ser una imagen PNG"
    try:
        with Image.open(io.BytesIO(content)) as im:
            w, h = im.size
            if w * h > SIGNATURE_MAX_PIXELS or w < 100 or h < 40:
                return "La firma tiene un tamaño no válido; bórrala y dibújala de nuevo"
            rgba = im.convert("RGBA")
        alpha = rgba.getchannel("A")
        ink = sum(1 for a in alpha.getdata() if a > 40)
    except Exception:  # noqa: BLE001
        return "La imagen de la firma no es válida"
    if ink < SIGNATURE_MIN_INK:
        return "Dibuja tu firma en el recuadro"
    return None


# ---------------------------------------------------------------------------------------------------- huella
def accepted_text(design: dict) -> list:
    """El texto que la persona VIO, en el orden del formulario: elementos estáticos y rótulos de los campos."""
    out = []
    for row in design.get("rows", []):
        for fid in row["items"]:
            f = design["fields"][fid]
            out.append([fid, f.get("content") if f["type"] in formlib.STATIC_TYPES else f.get("label"), f.get("options")])
    return out


def content_hash(design: dict, answers: dict, event_id: int, cedula: str, signature_sha: str) -> str:
    body = json.dumps({"v": T.VERSION, "auth": T.SENSITIVE_AUTH_VERSION if sensitive_enabled() else None, "event": event_id, "cedula": cedula, "text": accepted_text(design),
                       "answers": {k: answers[k] for k in sorted(answers)}, "signature_sha256": signature_sha}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------- cuenta temporal
def _hash_password(ident: str) -> str:
    from app.routers.events import _temp_password_hash          # la MISMA función de la creación a mano y del Excel (contraseña inicial = cédula)
    return _temp_password_hash(ident)


def resolve_account(db: Session, event: Event, cedula: str, full_name: str) -> Optional[StaffUser]:
    """Camino A: la cuenta temporal (usuario = cédula) se crea si no existe y se asigna al evento; si ya existe como digitador del mismo cliente, se reutiliza y solo se asigna. Una cuenta que no
    es de digitador (u otro cliente, desactivada o archivada) no se toca: devuelve None. El costo de bcrypt se paga SIEMPRE (no se distingue por tiempo si la cédula existía)."""
    pw_hash = _hash_password(cedula)
    target = db.query(StaffUser).filter(StaffUser.username == cedula).first()
    if target is None:
        target = StaffUser(username=cedula, password_hash=pw_hash, full_name=(full_name or "").strip()[:120] or None, role="digitador", tenant_id=event.tenant_id, created_by_id=event.coordinator_staff_id)
        try:
            with db.begin_nested():
                db.add(target)
                db.flush()
        except IntegrityError:           # otra petición la creó a la vez
            target = db.query(StaffUser).filter(StaffUser.username == cedula).first()
            if target is None:
                return None
    if target.role != "digitador" or target.tenant_id != event.tenant_id or not target.is_active or target.archived_at is not None:
        return None
    if not db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=target.id).first():
        db.add(EventStaffAuthorization(event_id=event.id, staff_user_id=target.id, authorized_by_id=event.coordinator_staff_id))
        db.flush()
    return target


# ---------------------------------------------------------------------------------------------------- gancho de envío (forms_public._reserve_and_store)
def on_confirmed(db: Session, form: WebForm, sub: FormSubmission, design: dict, clean: dict, secret: dict, signature: bytes, claims: dict, ip: Optional[str], session) -> dict:
    """Dentro de la transacción del envío (con la inscripción ya insertada). Crea/asigna la cuenta, escribe la evidencia, guarda el documento firmado y audita. Lanza `Skip` si no hay compromiso
    que guardar. Devuelve {"next_url": ruta|None, "login_tok": token|None, "staff_id": id} para lo que ocurre DESPUÉS del commit (Camino B/C)."""
    event = db.get(Event, form.event_id)
    answers = {**clean, **secret}
    cedula = normalize_cedula(answers.get(FID_ID))
    name = str(answers.get(FID_NAME) or "").strip()
    if claims.get("pc"):          # Camino B/C: la identidad sale de la sesión de espera, no de lo que escribió
        staff = db.get(StaffUser, int(claims["pc"]))
        req = session.get(SESSION_KEY) if session is not None else None
        ok = (staff is not None and staff.username == cedula and staff.role == "digitador" and staff.is_active and isinstance(req, dict) and req.get("uid") == staff.id
              and db.query(EventStaffAuthorization.id).filter_by(event_id=event.id, staff_user_id=staff.id).first() is not None)
        if not ok:
            raise Skip("session")
        source = "session"
    else:
        staff = resolve_account(db, event, cedula, name)
        if staff is None:
            audit_actions.record(db, None, "pledge_conflict", "event", event.id, event.name)
            raise Skip("account")
        source = "link"
    now = utcnow()
    active = db.query(EventStaffPledge).filter(EventStaffPledge.event_id == event.id, EventStaffPledge.staff_id == staff.id, EventStaffPledge.superseded_at.is_(None)).first()
    if active is not None and active.resign_allowed_at is None:
        audit_actions.record(db, None, "pledge_repeat", "event", event.id, event.name)
        raise Skip("repeat")
    if active is not None:
        active.superseded_at = now
        db.flush()
    stored = (clean.get(FID_SIG) or {}).get("stored")
    from app.storage import form_file_key, get_storage
    signature_key = form_file_key(event.tenant_id, form.id, stored)
    ip_masked = obs.mask_ip(ip)
    row = EventStaffPledge(
        event_id=event.id, staff_id=staff.id, submission_id=sub.id, signed_at=now, source=source, text_version=T.VERSION,
        sensitive_auth_version=T.SENSITIVE_AUTH_VERSION if sensitive_enabled() else None,
        content_hash=content_hash(design, answers, event.id, cedula, hashlib.sha256(signature).hexdigest()), signature_key=signature_key,
        attendance_confirmed=answers.get(FID_ATTEND) == T.YES, understands_terms=answers.get(FID_CONTRACT) == T.YES,
        has_health_info=any(answers.get(f) == T.YES for f in HEALTH_FIDS), ip_masked=ip_masked,
        health_flags=",".join(k for k, f in (("med", FID_MED), ("drug", FID_DRUG), ("support", FID_SUPPORT)) if answers.get(f) == T.YES) or None)
    db.add(row)
    db.flush()
    row.doc_key = signature_key.rsplit("/", 1)[0] + f"/pledge_{row.id}.html"
    get_storage().put(row.doc_key, render_document(event, design, answers, signature, row).encode("utf-8"))
    audit_actions.record(db, None, "pledge_signed", "event", event.id, event.name, f"compromiso {row.id}, origen {source}")
    out = {"next_url": None, "login_tok": None, "staff_id": staff.id}
    if source == "session":
        from app import login_control
        nxt = missing_for_login(db, staff)
        if nxt is not None:
            out["next_url"] = session_link(db, staff, nxt)
        else:
            out["login_tok"] = login_control.new_request(staff)
            out["next_url"] = "/ingreso/espera"
    return out


# ---------------------------------------------------------------------------------------------------- documento firmado
_env = None


def render_document(event: Event, design: dict, answers: dict, signature: bytes, row: EventStaffPledge) -> str:
    """HTML imprimible y de solo lectura del compromiso firmado (no hay librería de PDF instalada: el navegador lo guarda como PDF con «Imprimir»). Solo lleva lo NO sensible:
    identificación, nombre, celular, el texto aceptado, las dos respuestas de contrato y asistencia, la firma y la huella. El contacto de emergencia y las respuestas de salud NUNCA van aquí."""
    global _env
    import base64

    from jinja2 import Environment, FileSystemLoader, select_autoescape
    if _env is None:
        _env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
    blocks = []
    for row_ in design["rows"]:
        for fid in row_["items"]:
            f = design["fields"][fid]
            if f["type"] in formlib.STATIC_TYPES and fid not in (FID_AUTH_TXT, "t_footer", "t_event"):
                blocks.append({"kind": f["type"], "html": f.get("content", "")})
    return _env.get_template("pledge_document.html").render(
        event_name=event.name, info=event_info(None, event), blocks=blocks, version=T.VERSION, declaration=T.DECLARATION, footer=T.FOOTER,
        cedula=normalize_cedula(answers.get(FID_ID)), name=answers.get(FID_NAME), phone=answers.get(FID_PHONE),
        contract=(T.Q_CONTRACT, answers.get(FID_CONTRACT)), attendance=(T.Q_ATTENDANCE, answers.get(FID_ATTEND)),
        signature="data:image/png;base64," + base64.b64encode(signature).decode(), signed_at=row.signed_at.strftime("%Y-%m-%d %H:%M:%S") + " UTC",
        signed_local=to_local(row.signed_at).strftime("%d/%m/%Y %H:%M"), content_hash=row.content_hash, ip=row.ip_masked or "—", source=row.source)


# ---------------------------------------------------------------------------------------------------- puerta del ingreso (Camino B/C) y aprobación
RESIGN_WINDOW = timedelta(hours=48)


def release_stale(db: Session, form: WebForm, cedula: str) -> int:
    """Libera la cédula de los envíos ANTERIORES que ya no respaldan una firma vigente, para que el motor de formularios no responda «Ya estás inscrito» (9-nov-2026, bug de Juan David).
    El motor impide dos envíos con la misma cédula en un formulario (uq_form_person), pero en el compromiso lo que cuenta es si la CUENTA tiene su firma vigente (`active_pledge`), no si alguna vez
    hubo un envío con esa cédula (por ejemplo, el de una cuenta que se eliminó y se volvió a crear). Solo se conserva con cédula el envío que respalda una firma vigente de una cuenta que existe
    y a la que el coordinador no le ha permitido firmar de nuevo; los demás envíos reales de esa cédula pierden SOLO la cédula del envío (`person_id` = NULL). La evidencia (huella, firma,
    documento y respuestas) no se toca. Una firma vigente de una cuenta que existe NO se libera: ese caso sí es «ya firmaste». Devuelve cuántos liberó (no hace commit)."""
    if not cedula:
        return 0
    keep = db.query(EventStaffPledge.submission_id).filter(
        EventStaffPledge.event_id == form.event_id, EventStaffPledge.staff_id.isnot(None),
        EventStaffPledge.superseded_at.is_(None),
        or_(EventStaffPledge.resign_allowed_at.is_(None), EventStaffPledge.resign_allowed_at < datetime.utcnow() - RESIGN_WINDOW))      # el permiso de firmar de nuevo vence (F4 seguridad): pasada la ventana, la firma vuelve a estar protegida
    return db.query(FormSubmission).filter(
        FormSubmission.form_id == form.id, FormSubmission.person_id == cedula, FormSubmission.is_test == False,        # noqa: E712
        ~FormSubmission.id.in_(keep)).update({"person_id": None}, synchronize_session=False)


def active_pledge(db: Session, event_id: int, staff_id: int) -> Optional[EventStaffPledge]:
    return db.query(EventStaffPledge).filter(EventStaffPledge.event_id == event_id, EventStaffPledge.staff_id == staff_id, EventStaffPledge.superseded_at.is_(None)).first()


def missing_for_login(db: Session, staff: StaffUser) -> Optional[Event]:
    """El primer evento EN PROCESO de la cuenta que exige el compromiso y del que no hay uno vigente; None si no falta ninguno."""
    events = (db.query(Event).join(EventStaffAuthorization, EventStaffAuthorization.event_id == Event.id)
              .filter(EventStaffAuthorization.staff_user_id == staff.id, Event.status == "en_proceso", Event.pledge_enabled.is_(True), Event.archived_at.is_(None)).order_by(Event.id).all())
    for event in events:
        if form_for(db, event) is None or not text_available():
            continue          # nunca se publicó el formulario, o el texto de la auditora aún no está aprobado: no se puede firmar, así que no se bloquea la operación del evento
        if active_pledge(db, event.id, staff.id) is None:
            return event
    return None


def session_link(db: Session, staff: StaffUser, event: Event) -> Optional[str]:
    """Ruta `/f/<evento>/<slug>?t=<token>` del MISMO formulario público, con el token de etapa del motor que ya identifica a la persona (no vuelve a pedir la cédula). None si el formulario
    no está disponible."""
    form = form_for(db, event)
    if form is None or form.manual_status != "activo" or not text_available():
        return None
    from app.routers import forms_public
    token = forms_public._issue(form, g=True, id_ok=True, pc=staff.id)          # sin la cédula en el token (viaja en la URL y la firma no cifra): la identidad sale de `pc`
    return f"/f/{event.id}/{form.slug}?t={token}"


def begin_session_flow(request, db: Session, staff: StaffUser, event: Event, prev_sid) -> Optional[str]:
    """Deja en la cookie firmada que esta cuenta debe firmar antes de entrar a la fila y devuelve a dónde ir; None si el compromiso no está disponible."""
    link = session_link(db, staff, event)
    if link is None:
        return None
    request.session.clear()
    request.session[SESSION_KEY] = {"uid": staff.id, "psid": prev_sid}
    return link


def blocked_message(db: Session, staff: StaffUser) -> Optional[str]:
    """Mensaje para negar la aprobación del ingreso si falta algún compromiso; None si puede autorizarse."""
    event = missing_for_login(db, staff)
    if event is None:
        return None
    return f"Esta persona aún no ha firmado el compromiso del evento «{event.name}». Cuando lo firme podrás autorizar su ingreso."


def finish_session(request, extras: dict) -> None:
    """Después del commit del Camino B/C: si el compromiso quedó completo, la cookie pasa de «falta el compromiso» a «espera la autorización» (el mismo mecanismo de app/login_control.py)."""
    if request is None or not extras.get("login_tok"):
        return
    from app import login_control
    prev = request.session.get(SESSION_KEY) or {}
    request.session.clear()
    request.session[login_control.SESSION_KEY] = {"uid": extras["staff_id"], "tok": extras["login_tok"], "psid": prev.get("psid")}


# ---------------------------------------------------------------------------------------------------- límites propios del compromiso (además de los del motor)
_limiter = SlidingLimiter()
LINK_MAX_PER_HOUR = int(os.getenv("PLEDGE_LINK_MAX_PER_HOUR", "600"))
IP_MAX_PER_10MIN = int(os.getenv("PLEDGE_IP_MAX_PER_10MIN", "25"))


def throttle(form: WebForm, ip: Optional[str]) -> bool:
    """False si el enlace (todas las IP) o esta IP ya enviaron demasiados compromisos. En memoria por proceso, sin tocar la base."""
    if not _limiter.hit(("pledge_link", form.id), LINK_MAX_PER_HOUR, 3600.0):
        return False
    if ip is not None and not _limiter.hit(("pledge_ip", form.id, ip), IP_MAX_PER_10MIN, 600.0):
        return False
    return True
