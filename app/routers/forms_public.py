"""Formularios Web — lado PÚBLICO (Sprint 5): `/f/<evento>/<formulario>`, sin iniciar sesión. Lo único que expone es
el formulario y lo que la persona misma envía: nada de la plataforma. Todo se valida en el servidor (estado, cupo,
contraseña de acceso, condiciones, tipos, archivos) sin fiarse de lo que mande el navegador.

Flujo (el navegador pregunta `GET .../state` y sigue la etapa que indique): `gate` (palabra/código de acceso) →
`identify` (cédula, para pre-llenar o para autorizar) → `form` → `thanks`. Cada etapa superada se recuerda en un token
firmado y con vencimiento (`t`), que el envío exige."""
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from PIL import Image
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import formlib, formsvc, security, wompi
from app.database import get_db
from app.email_check import check_email
from app.models import Event, FormEvent, FormInvite, FormPayment, FormSubmission, WebForm
from app.routers.badges import ALLOWED_IMAGE_EXT
import io

router = APIRouter()
TOKEN_MAX_AGE = 6 * 3600
_LIMIT = timedelta(minutes=10)


# ------------------------------------------------------------------ tokens de etapa
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="web-form-access")


def _issue(form: WebForm, **claims) -> str:
    return _serializer().dumps({"f": form.id, **claims})


def _read(token: Optional[str], form: WebForm) -> dict:
    if not token:
        return {}
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return {}
    return data if data.get("f") == form.id else {}


# ------------------------------------------------------------------ resolución
def _load(db: Session, event_id: int, slug: str) -> WebForm:
    form = db.query(WebForm).filter(WebForm.event_id == event_id, WebForm.slug == slug).first()
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no disponible")
    return form


def _access(db: Session, form: WebForm, k: Optional[str]) -> str:
    """Estado con el que se atiende esta visita: `activo`, `pruebas` (solo con la clave del enlace de pruebas),
    `cerrado` o `cupo_lleno`. `finalizado` y `pruebas` sin clave = como si la página no existiera (404)."""
    state = formsvc.public_state(db, form)
    if state == "finalizado":
        raise HTTPException(status_code=404, detail="Formulario no disponible")
    if state == "pruebas" and not (k and secrets.compare_digest(str(k), form.test_key)):
        raise HTTPException(status_code=404, detail="Formulario no disponible")
    return state


def _limit(db: Session, request: Request, kind: str, form: WebForm, max_hits: int):
    security.enforce_public_limit(db, request, kind, str(form.id), max_hits, _LIMIT)


def _needs(settings: dict):
    sec = settings["security"]
    needs_code = bool(sec["enabled"] and sec["type"] == "code")
    needs_cedula_gate = bool(sec["enabled"] and sec["type"] == "cedula")
    mode = settings["prefill"]["mode"]
    needs_identify = mode == "cedula" or needs_cedula_gate
    return needs_code, needs_identify, mode


def _payload_form(db: Session, form: WebForm, claims: dict) -> dict:
    """Todo lo que el navegador necesita para dibujar el formulario (+ los datos ya conocidos de la persona)."""
    design = formsvc.get_design(form)
    prefill, readonly = {}, []
    if claims.get("p"):
        person = formsvc.find_person(db, form, claims["p"])
        if person:
            prefill = formsvc.prefill_values(design, person)
            readonly = [fid for fid in prefill if design["fields"][fid].get("readonly_when_prefilled")]
    return {"design": design, "prefill": prefill, "readonly": readonly, "badge_email_field": formsvc.badge_email_field(design) if formsvc.wants_digital_badge(db, form) else None, "capacity_left": None if form.capacity is None else max(0, form.capacity - formsvc.held_count(db, form))}


# ------------------------------------------------------------------ páginas y estado
@router.get("/f/{event_id}/{slug}", response_class=HTMLResponse)
async def page(event_id: int, slug: str, request: Request, k: Optional[str] = None, db: Session = Depends(get_db)):
    from app.main import templates  # import tardío: main.py importa este módulo
    try:
        form = _load(db, event_id, slug)
        _access(db, form, k)
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Este formulario no está disponible</h3>", status_code=404)
    return templates.TemplateResponse(request=request, name="form_public.html", context={"event_id": event_id, "slug": slug, "form_title": form.name})


@router.get("/f/{event_id}/{slug}/state")
async def state(event_id: int, slug: str, k: Optional[str] = None, i: Optional[str] = None, t: Optional[str] = None, db: Session = Depends(get_db)):
    form = _load(db, event_id, slug)
    access = _access(db, form, k)
    settings = formsvc.get_settings(form)
    design = formsvc.get_design(form)
    theme = design["theme"]
    base = {"theme": theme, "is_test": access == "pruebas", "title": form.name, "ui": {"language": settings["language"], "translate": settings["translate"]}}
    if access in ("cerrado", "cupo_lleno"):
        return {**base, "stage": "closed", "reason": access, "template": settings["closed_template"]}

    needs_code, needs_identify, mode = _needs(settings)
    claims = _read(t, form)
    # Enlace personalizado por invitado: ya identifica a la persona (y cumple el «identify»).
    if mode == "invite":
        inv = db.query(FormInvite).filter_by(form_id=form.id, token=i or "").first() if i else None
        person = formsvc.find_person(db, form, inv.person_id) if inv else None
        if not inv or not person:
            return {**base, "stage": "invalid", "message": "Este enlace personal no es válido. Pide uno nuevo a los organizadores."}
        claims = {**claims, "p": inv.person_id, "inv": inv.id}
        needs_identify = False
    if needs_code and not claims.get("g"):
        return {**base, "stage": "gate", "kind": "code"}
    if needs_identify and not claims.get("id_ok"):
        return {**base, "stage": "identify", "required": bool(settings["security"]["enabled"] and settings["security"]["type"] == "cedula"), "token": _issue(form, **claims)}
    claims = {**claims, "g": True}
    return {**base, "stage": "form", "token": _issue(form, **claims), "thanks": settings["thanks"], **_payload_form(db, form, claims)}


@router.post("/f/{event_id}/{slug}/gate")
async def gate(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    form = _load(db, event_id, slug)
    _access(db, form, data.get("k"))
    _limit(db, request, "form_gate", form, 15)               # freno a quien intenta adivinar el código
    sec = formsvc.get_settings(form)["security"]
    if not (sec["enabled"] and sec["type"] == "code"):
        raise HTTPException(status_code=400, detail="Este formulario no pide código")
    if not secrets.compare_digest(str(data.get("code") or "").strip().lower(), sec["code"].strip().lower()):
        raise HTTPException(status_code=403, detail="El código no es correcto")
    claims = _read(data.get("t"), form)
    return {"token": _issue(form, **{**claims, "g": True})}


@router.post("/f/{event_id}/{slug}/lookup")
async def lookup(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """Autoservicio por cédula: si la persona está en la base elegida, se pre-llenan y bloquean sus datos; si no está, el
    formulario se llena de cero — salvo que la seguridad sea «la propia cédula», que exige estar en la base."""
    form = _load(db, event_id, slug)
    _access(db, form, data.get("k"))
    _limit(db, request, "form_lookup", form, 60)
    settings = formsvc.get_settings(form)
    claims = _read(data.get("t"), form)
    needs_code, _, _ = _needs(settings)
    if needs_code and not claims.get("g"):
        raise HTTPException(status_code=403, detail="Primero escribe el código de acceso")
    pid = str(data.get("id") or "").strip().replace(".", "").replace(" ", "")
    if not pid:
        raise HTTPException(status_code=400, detail="Escribe tu número de identificación")
    person = formsvc.find_person(db, form, pid)
    sec = settings["security"]
    if sec["enabled"] and sec["type"] == "cedula" and not person:
        raise HTTPException(status_code=403, detail="Tu identificación no está autorizada para este formulario")
    new_claims = {**claims, "g": True, "id_ok": True, "typed_id": pid}
    if person:
        new_claims["p"] = pid
    return {"token": _issue(form, **new_claims), "found": bool(person)}


@router.post("/f/{event_id}/{slug}/beacon")
async def beacon(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """Marcas de uso para la analítica: `view` (abrió), `start` (empezó a llenar). Sin datos personales."""
    form = _load(db, event_id, slug)
    access = _access(db, form, data.get("k"))
    kind = data.get("kind")
    sid = str(data.get("sid") or "")[:40]
    if kind not in ("view", "start") or not sid:
        raise HTTPException(status_code=400, detail="Marca inválida")
    _limit(db, request, "form_beacon", form, 400)
    exists = db.query(FormEvent).filter_by(form_id=form.id, sid=sid, kind=kind).first()
    if not exists:
        db.add(FormEvent(form_id=form.id, sid=sid, kind=kind, source=str(data.get("source") or "")[:40] or None, is_test=(access == "pruebas")))
        db.commit()
    return {"ok": True}


@router.get("/f/{event_id}/{slug}/asset/{tenant_id}/{filename}")
async def asset(event_id: int, slug: str, tenant_id: str, filename: str, k: Optional[str] = None, db: Session = Depends(get_db)):
    form = _load(db, event_id, slug)
    _access(db, form, k)
    event = db.query(Event).filter(Event.id == form.event_id).first()
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    path = os.path.join("data", tenant_id, "badge_assets", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path)


# ------------------------------------------------------------------ envío
def _check_upload(f: dict, name: str, content: bytes, settings: dict) -> Optional[str]:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    limit_mb = min(f.get("max_mb", 10), settings.get("max_mb", 10)) if settings.get("max_mb") else f.get("max_mb", 10)
    if ext not in f.get("accept", formlib.FILE_EXTENSIONS):
        return f"«{f['label']}»: formato no permitido (.{ext}). Se aceptan: {', '.join(f.get('accept', []))}"
    if len(content) > limit_mb * 1024 * 1024:
        return f"«{f['label']}»: el archivo pesa más de {limit_mb} MB"
    if not content:
        return f"«{f['label']}»: el archivo está vacío"
    ok = True
    if ext == "pdf":
        ok = content.startswith(b"%PDF")
    elif ext in ("docx", "xlsx", "pptx"):
        ok = content.startswith(b"PK\x03\x04")
    elif ext in ("doc", "xls", "ppt"):
        ok = content.startswith(bytes.fromhex("d0cf11e0"))
    elif ext in ("png", "jpg", "jpeg", "webp", "gif"):
        try:
            Image.open(io.BytesIO(content)).verify()
        except Exception:
            ok = False
    elif ext in ("txt", "csv"):
        ok = b"\x00" not in content[:2048]
    return None if ok else f"«{f['label']}»: el contenido no corresponde a un archivo .{ext}"


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "archivo")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80] or "archivo"


@router.post("/f/{event_id}/{slug}/submit")
async def submit(event_id: int, slug: str, request: Request, db: Session = Depends(get_db)):
    form = _load(db, event_id, slug)
    ctype = request.headers.get("content-type", "")
    if "multipart" in ctype:
        raw_form = await request.form()
        payload = json.loads(str(raw_form.get("data") or "{}"))
        files = {k[5:]: v for k, v in raw_form.multi_items() if k.startswith("file:") and hasattr(v, "read")}
    else:
        payload, files = await request.json(), {}
    access = _access(db, form, payload.get("k"))
    if access in ("cerrado", "cupo_lleno"):
        return JSONResponse({"detail": "Este formulario ya no recibe inscripciones", "stage": "closed"}, status_code=409)
    _limit(db, request, "form_submit", form, 60)

    settings = formsvc.get_settings(form)
    design = formsvc.get_design(form)
    claims = _read(payload.get("t"), form)
    needs_code, needs_identify, mode = _needs(settings)
    if mode == "invite" and not claims.get("inv"):
        raise HTTPException(status_code=403, detail="Usa tu enlace personal para inscribirte")
    if needs_code and not claims.get("g"):
        raise HTTPException(status_code=403, detail="Falta el código de acceso")
    if needs_identify and mode != "invite" and not claims.get("id_ok"):
        raise HTTPException(status_code=403, detail="Primero identifícate con tu número de documento")

    values = dict(payload.get("values") or {})
    fields = design["fields"]
    # Campos «solo lectura cuando ya se conocen»: el valor sale de la base, nunca de lo que mande el navegador.
    person = formsvc.find_person(db, form, claims["p"]) if claims.get("p") else None
    if person:
        for fid, val in formsvc.prefill_values(design, person).items():
            if fields[fid].get("readonly_when_prefilled"):
                values[fid] = val
    # Archivos
    uploaded, file_errors, pending = {}, {}, {}
    visible = formlib.visible_ids(design, values)
    for fid, up in files.items():
        f = fields.get(fid)
        if not f or f["type"] != "file" or fid not in visible:
            continue
        content = await up.read()
        err = _check_upload(f, up.filename or "", content, settings)
        if err:
            file_errors[fid] = err
        else:
            uploaded[fid] = {"filename": _safe_name(up.filename), "size": len(content)}
            pending[fid] = content

    clean, errors = formlib.validate_submission(design, values, uploaded, check_email)
    errors.update(file_errors)
    if errors:
        return JSONResponse({"detail": "Revisa los campos marcados", "errors": errors}, status_code=422)

    person_id = None
    for fid, f in fields.items():
        if f.get("key") == "id" and clean.get(fid):
            person_id = str(clean[fid]).strip()
    is_test = access == "pruebas"

    # Campo «Pago»: si está visible y el monto (según reglas y descuentos) es mayor que 0, la inscripción NO se confirma
    # aquí: queda «esperando pago» hasta que Wompi confirme (ver app/routers/form_payments.py).
    quote = charge = cfg = None
    pay_field = formlib.payment_field(design, {**values, **{k: True for k in uploaded}})
    if pay_field:
        quote = formlib.compute_amount(pay_field["pay"], formlib.priced_values(design, clean), formsvc.now_local().date(), 1 + formlib.companions_count(design, clean))
        if quote["amount"] > formlib.MAX_PAYMENT_COP:
            return JSONResponse({"detail": f"El total a pagar (${quote['amount']:,}) supera el máximo de ${formlib.MAX_PAYMENT_COP:,} COP por pago de Wompi. Reduce el número de acompañantes.".replace(",", ".")}, status_code=422)
        if quote["amount"] > 0:
            if quote["amount"] < formlib.MIN_PAYMENT_COP:
                return JSONResponse({"detail": f"El monto a pagar (${quote['amount']}) es menor al mínimo de ${formlib.MIN_PAYMENT_COP} COP por transacción. Avisa a los organizadores."}, status_code=422)
            cfg = wompi.config(is_test)
            if not cfg:
                return JSONResponse({"detail": "El pago en línea todavía no está disponible para este formulario. Intenta más tarde."}, status_code=503)
            charge = quote["amount"]

    # Cupo y duplicados, con la fila del formulario BLOQUEADA: dos personas enviando el último cupo a la vez no lo llenan dos veces.
    locked = db.query(WebForm).filter(WebForm.id == form.id).with_for_update().first()
    formsvc.purge_stale_pending(db, form)
    if charge and (person_id or payload.get("sid")):      # reintento de pago: el intento anterior de esta persona/sesión se descarta
        prior = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == formsvc.PENDING)
        cond = [FormSubmission.sid == str(payload["sid"])[:40]] if payload.get("sid") else []
        if person_id:
            cond.append(FormSubmission.person_id == person_id)
        for old in prior.filter(or_(*cond)).all():
            formsvc.discard_submission(db, form, old)
        db.flush()
    if formsvc.is_full(db, locked) and not is_test:
        db.rollback()
        return JSONResponse({"detail": "El cupo de este formulario se completó", "stage": "closed"}, status_code=409)
    if person_id and not is_test:
        dup = formsvc.real_submissions(db, form).filter(FormSubmission.person_id == person_id).first()
        if dup:
            db.rollback()
            return JSONResponse({"detail": "Ya existe una inscripción con ese número de documento", "duplicate": True}, status_code=409)

    sid = str(payload.get("sid") or "")[:40] or None
    started = db.query(FormEvent).filter_by(form_id=form.id, sid=sid, kind="start").first() if sid else None
    sub = FormSubmission(
        form_id=form.id, event_id=form.event_id, data_json=json.dumps(clean), is_test=is_test, person_id=person_id, invite_id=claims.get("inv"),
        source=str(payload.get("source") or "")[:40] or None, sid=sid, started_at=started.created_at if started else None,
        status=formsvc.PENDING if charge else "confirmed",
    )
    db.add(sub)
    db.flush()
    event = db.query(Event).filter(Event.id == form.event_id).first()
    if pending:
        directory = formsvc.form_files_dir(event.tenant_id, form.id)
        for fid, content in pending.items():
            stored = f"{sub.id}_{fid}_{clean[fid]['filename']}"
            with open(os.path.join(directory, stored), "wb") as fh:
                fh.write(content)
            clean[fid]["stored"] = stored
        sub.data_json = json.dumps(clean)
    if charge:
        pay = FormPayment(form_id=form.id, event_id=form.event_id, submission_id=sub.id, amount_cents=charge * 100, currency="COP", is_test=is_test or cfg["test"],
                          reference=f"GW-{form.event_id}-{form.id}-{sub.id}-{secrets.token_hex(3)}", person_id=person_id,
                          breakdown_json=json.dumps({"base": quote["base"], "applied": quote["applied"], "amount": charge}))
        db.add(pay)
        db.commit()
        return {"ok": True, "payment_required": True, "pay_token": _issue(form, pay=pay.id), "payment": _widget_params(pay, cfg, design, clean, quote)}
    formsvc.finalize_submission(db, form, sub)
    return {"ok": True, "thanks": settings["thanks"], "is_test": is_test}


def _widget_params(pay: FormPayment, cfg: dict, design: dict, clean: dict, quote: dict) -> dict:
    """Lo que el navegador necesita para abrir el widget de Wompi (llave PÚBLICA y firma de integridad; el secreto nunca sale)."""
    customer, first, last = {}, "", ""
    for fid, f in design["fields"].items():
        if f.get("key") == "email" and clean.get(fid):
            customer["email"] = str(clean[fid])
        elif f.get("key") == "first_name" and clean.get(fid):
            first = str(clean[fid])
        elif f.get("key") == "last_name" and clean.get(fid):
            last = str(clean[fid])
    if first or last:
        customer["fullName"] = f"{first} {last}".strip()
    return {"reference": pay.reference, "amount_in_cents": pay.amount_cents, "currency": pay.currency, "public_key": cfg["public_key"],
            "integrity": wompi.integrity_signature(pay.reference, pay.amount_cents, pay.currency, cfg["integrity_secret"]),
            "widget_url": wompi.WIDGET_URL, "test": cfg["test"], "amount": quote["amount"], "applied": quote["applied"], "customer": customer}
