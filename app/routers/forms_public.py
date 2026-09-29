"""Formularios Web — lado PÚBLICO (Sprint 5): `/f/<evento>/<formulario>`, sin iniciar sesión. Lo único que expone es
el formulario y lo que la persona misma envía: nada de la plataforma. Todo se valida en el servidor (estado, cupo,
contraseña de acceso, condiciones, tipos, archivos) sin fiarse de lo que mande el navegador.

Flujo (el navegador pregunta `GET .../state` y sigue la etapa que indique): `gate` (palabra/código de acceso) →
`identify` (cédula, para pre-llenar o para autorizar) → `form` → `thanks`. Cada etapa superada se recuerda en un token
firmado y con vencimiento (`t`), que el envío exige."""
import asyncio
import json
import os
import secrets
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from PIL import Image
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import formlib, formsvc, jobs, security, timing, uploads, wompi
from app.database import SessionLocal, get_db
from app.email_check import check_email
from app.models import Event, FormEvent, FormInvite, FormPayment, FormSubmission, WebForm
from app.routers.badges import ALLOWED_IMAGE_EXT
from app.storage import badge_asset_key, form_file_key, get_storage
from app.ttlcache import SlidingLimiter
import io
import logging

log = logging.getLogger("golden.forms")
router = APIRouter()
TOKEN_MAX_AGE = 6 * 3600
_LIMIT = timedelta(minutes=10)
_limiter = SlidingLimiter()                                     # en memoria (por proceso): frena abusos sin escribir en la base en cada visita
LIMIT_FACTOR = float(os.getenv("PUBLIC_LIMIT_FACTOR", "1"))    # subelo (p. ej. 20) si el evento reparte un mismo wifi a mucha gente: ver docs/runbook_evento.md


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


def _access(db: Session, form: WebForm, k: Optional[str], check_full: bool = True, held: Optional[int] = None) -> str:
    """Estado con el que se atiende esta visita: `activo`, `pruebas` (solo con la clave del enlace de pruebas),
    `cerrado` o `cupo_lleno`. `finalizado` y `pruebas` sin clave = como si la página no existiera (404).
    `check_full=False` salta el conteo de cupo (el envío lo comprueba después, ya con el formulario bloqueado)."""
    state = formsvc.public_state(db, form, held) if check_full else formsvc.status_of(form)
    if state == "finalizado":
        raise HTTPException(status_code=404, detail="Formulario no disponible")
    if state == "pruebas" and not (k and secrets.compare_digest(str(k), form.test_key)):
        raise HTTPException(status_code=404, detail="Formulario no disponible")
    return state


def _limit(db: Optional[Session], request: Request, kind: str, form: WebForm, max_hits: int) -> None:
    """Limite por IP en memoria (`db` se ignora: se conserva la firma que usan los demas modulos). Con varios procesos cada uno lleva su cuenta."""
    ip = security.limit_ip(request)
    if ip is None:                     # IP de infraestructura de Google (no confiable): sin límite por IP para no bloquear a todos a la vez; se cuenta en «Estado del sistema»
        return
    if not _limiter.hit((kind, form.id, ip), max(1, int(max_hits * LIMIT_FACTOR)), _LIMIT.total_seconds()):
        raise HTTPException(status_code=429, detail="Demasiadas consultas seguidas — espera unos minutos e intenta de nuevo.")


def _needs(settings: dict):
    sec = settings["security"]
    needs_code = bool(sec["enabled"] and sec["type"] == "code")
    needs_cedula_gate = bool(sec["enabled"] and sec["type"] == "cedula")
    mode = settings["prefill"]["mode"]
    needs_identify = mode == "cedula" or needs_cedula_gate
    return needs_code, needs_identify, mode


def _payload_form(db: Session, form: WebForm, claims: dict, held: Optional[int] = None) -> dict:
    """Todo lo que el navegador necesita para dibujar el formulario (+ los datos ya conocidos de la persona)."""
    design = formsvc.get_design(form)
    prefill, readonly = {}, []
    if claims.get("p"):
        person = formsvc.find_person(db, form, claims["p"])
        if person:
            prefill = formsvc.prefill_values(design, person)
            readonly = [fid for fid in prefill if design["fields"][fid].get("readonly_when_prefilled")]
    quota = formsvc.quota_public(db, form)
    db.commit()          # si hubo que recalcular las llaves de cupo (inscripciones anteriores), quedan guardadas
    return {"design": formlib.public_design(design), "id_docs": formlib.id_docs_public(), "quota": quota, "refund": formsvc.get_settings(form)["refunds"], "prefill": prefill, "readonly": readonly, "badge_email_field": formsvc.badge_email_field(design) if formsvc.wants_digital_badge(db, form) else None, "capacity_left": None if form.capacity is None else max(0, form.capacity - (held if held is not None else formsvc.held_count(db, form)))}


# ------------------------------------------------------------------ páginas y estado
# ------------------------------------------------------------------ caché de estado/página: NUNCA bloquea a nadie
# Stale-while-revalidate: un valor vigente se sirve al instante; uno VENCIDO (hasta FORM_PUBLIC_STALE_SECONDS después) también, y UN solo hilo propio (no del pool de la
# app) lo refresca en segundo plano; solo cuando no hay ningún valor utilizable se espera, y esa espera es un `await` (no ocupa ningún hilo del pool). Antes los que
# esperaban la recarga se quedaban bloqueados en un candado DENTRO del pool de hilos y, si la recarga tardaba, no dejaban arrancar a los envíos.
PUBLIC_STALE_SECONDS = float(os.getenv("FORM_PUBLIC_STALE_SECONDS", "5"))
_refreshing: set = set()
_refreshing_lock = threading.Lock()
_inflight: Dict[tuple, "asyncio.Task"] = {}          # solo se toca desde el bucle de eventos de ESTE proceso (sin candado)


def _spawn_refresh(cache, key, factory) -> None:
    """Refresca `key` en un hilo propio, uno solo a la vez por clave. Si falla, el valor viejo se sigue sirviendo hasta que caduque su margen."""
    with _refreshing_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def work():
        try:
            cache.set(key, factory())
        except Exception:  # noqa: BLE001
            log.warning("no se pudo refrescar la caché %s en segundo plano", key[0], exc_info=True)
        finally:
            with _refreshing_lock:
                _refreshing.discard(key)

    threading.Thread(target=work, name="form-cache-refresh", daemon=True).start()


async def _cached_async(cache, key, factory):
    """Valor de la caché sin bloquear: vigente → ya; vencido pero utilizable → ya (y refresco en segundo plano); nada → UNA sola recarga (un hilo) y los demás esperan
    con `await` a esa misma tarea (`shield`: si un cliente se desconecta no cancela la recarga de los demás)."""
    value, st = cache.peek(key, PUBLIC_STALE_SECONDS)
    if st == "fresh":
        return value
    if st == "stale":
        _spawn_refresh(cache, key, factory)
        return value
    loop_key = (id(asyncio.get_running_loop()), key)
    task = _inflight.get(loop_key)
    if task is None:
        async def load():
            result = await timing.run(factory)
            cache.set(key, result)
            return result

        task = asyncio.ensure_future(load())
        _inflight[loop_key] = task
        task.add_done_callback(lambda _t: _inflight.pop(loop_key, None))
    return await asyncio.shield(task)


def _page_title(event_id: int, slug: str, k: Optional[str]) -> dict:
    """Fallo de caché de la página: lo único que hace falta de la base es el título (y que el formulario exista y sea visible)."""
    db = SessionLocal()
    try:
        form = _load(db, event_id, slug)
        _access(db, form, k)
        return {"title": form.name}
    finally:
        db.close()


@router.get("/f/{event_id}/{slug}", response_class=HTMLResponse)
async def page(event_id: int, slug: str, request: Request, k: Optional[str] = None):
    """El cascaron HTML es el mismo para todos: el formulario y su estado llegan por `/state`. Sin clave de pruebas se puede guardar en la cache del
    navegador/Cloudflare unos segundos (`s-maxage`); con `?k=` (pruebas) nunca.
    `async` a propósito: la caché se sirve en el bucle de eventos, sin pasar por el pool de hilos (ver `_cached_async`)."""
    from app.main import templates  # import tardio: main.py importa este modulo
    key = ("page", event_id, slug)
    try:
        if k:
            cached = await timing.run(_page_title, event_id, slug, k)
        else:
            cached = await _cached_async(formsvc.public_cache, key, lambda: _page_title(event_id, slug, k))
    except HTTPException:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Este formulario no está disponible</h3>", status_code=404)
    response = templates.TemplateResponse(request=request, name="form_public.html", context={"event_id": event_id, "slug": slug, "form_title": cached["title"]})
    if not k:
        response.headers["Cache-Control"] = "public, max-age=30, s-maxage=60"
    return response


def _state_compute(event_id: int, slug: str, k: Optional[str], i: Optional[str], t: Optional[str]) -> dict:
    db = SessionLocal()                  # la sesión (y su conexión) solo existe en el fallo de caché
    try:
        return _state(db, event_id, slug, k, i, t)
    finally:
        db.close()


def _cdn_seconds() -> int:
    """FORM_STATE_CDN_SECONDS (apagado = 0): segundos de `s-maxage` para el estado ANÓNIMO. Se limita a 1-10 s."""
    try:
        return max(0, min(10, int(os.getenv("FORM_STATE_CDN_SECONDS", "0"))))
    except ValueError:
        return 0


@router.get("/f/{event_id}/{slug}/state")
async def state(event_id: int, slug: str, request: Request, k: Optional[str] = None, i: Optional[str] = None, t: Optional[str] = None):
    """Lo que el navegador necesita para dibujar el formulario. Para quien llega «en frio» (sin clave de pruebas, enlace personal ni token) el resultado
    es identico para todos: se calcula una vez cada pocos segundos y se sirve de la memoria (con 10.000 aperturas, eran 10.000 conteos de cupo).
    `async` y sin bloqueos: ver `_cached_async`. Con FORM_STATE_CDN_SECONDS > 0 la respuesta ANÓNIMA (sin parámetros, sin cookie, sin Set-Cookie) lleva
    `Cache-Control: public, max-age=0, s-maxage=N` para que la CDN de Firebase la sirva sin llegar a Cloud Run; cualquier otra petición (clave de pruebas, enlace personal,
    token, cookie o sesión) NUNCA se cachea ahí."""
    if not (k or i or t):
        key = ("state", event_id, slug)
        result = await _cached_async(formsvc.public_cache, key, lambda: _state_compute(event_id, slug, k, i, t))
        seconds = _cdn_seconds()
        if seconds and not request.query_params and not request.headers.get("cookie") and not request.headers.get("authorization"):
            return JSONResponse(jsonable_encoder(result), headers={"Cache-Control": f"public, max-age=0, s-maxage={seconds}"})
        return result
    return await timing.run(_state_compute, event_id, slug, k, i, t)


def _state(db: Session, event_id: int, slug: str, k: Optional[str], i: Optional[str], t: Optional[str]) -> dict:
    form = _load(db, event_id, slug)
    held = formsvc.held_count(db, form) if form.capacity is not None else None      # UN solo conteo por fallo de caché (estado + «quedan N cupos»)
    access = _access(db, form, k, held=held)
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
    return {**base, "stage": "form", "token": _issue(form, **claims), "thanks": settings["thanks"], **_payload_form(db, form, claims, held)}


@router.post("/f/{event_id}/{slug}/gate")
def gate(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
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
def lookup(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
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
def beacon(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
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
def asset(event_id: int, slug: str, tenant_id: str, filename: str, k: Optional[str] = None, db: Session = Depends(get_db)):
    form = _load(db, event_id, slug)
    _access(db, form, k)
    event = db.query(Event).filter(Event.id == form.event_id).first()
    safe = os.path.basename(filename)
    if tenant_id != event.tenant_id or os.path.splitext(safe)[1].lower() not in ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return get_storage().response(badge_asset_key(tenant_id, safe))


# ------------------------------------------------------------------ envío
def _limit_mb(f: dict, settings: dict) -> int:
    return min(f.get("max_mb", 10), settings.get("max_mb", 10)) if settings.get("max_mb") else f.get("max_mb", 10)


def _check_stage(settings: dict, claims: dict) -> None:
    """Las mismas etapas que exige el envío (enlace personal, código, identificación): sin ellas tampoco se firma una subida."""
    needs_code, needs_identify, mode = _needs(settings)
    if mode == "invite" and not claims.get("inv"):
        raise HTTPException(status_code=403, detail="Usa tu enlace personal para inscribirte")
    if needs_code and not claims.get("g"):
        raise HTTPException(status_code=403, detail="Falta el código de acceso")
    if needs_identify and mode != "invite" and not claims.get("id_ok"):
        raise HTTPException(status_code=403, detail="Primero identifícate con tu número de documento")


@router.post("/f/{event_id}/{slug}/upload")
def sign_file(event_id: int, slug: str, data: dict, request: Request, db: Session = Depends(get_db)):
    """Firma la subida directa de un archivo del formulario (ver app/uploads.py): `{fid, filename, size, content_type, k, t}`. El
    archivo va del navegador al almacenamiento; el envío manda solo el token (así varios archivos de 20 MB no chocan con los 32 MiB)."""
    form = _load(db, event_id, slug)
    if _access(db, form, data.get("k"), check_full=False) in ("cerrado", "cupo_lleno"):
        return JSONResponse({"detail": "Este formulario ya no recibe inscripciones", "stage": "closed"}, status_code=409)
    _limit(db, request, "form_upload", form, 60)
    settings = formsvc.get_settings(form)
    _check_stage(settings, _read(data.get("t"), form))
    fid = str(data.get("fid") or "")
    f = formsvc.get_design(form)["fields"].get(fid)
    if not f or f["type"] != "file":
        raise HTTPException(status_code=400, detail="Ese campo no recibe archivos")
    event = db.query(Event).filter(Event.id == form.event_id).first()
    return uploads.create("form_file", {"f": form.id, "fid": fid}, event.tenant_id, str(data.get("filename") or ""), data.get("size"),
                          str(data.get("content_type") or ""), max_bytes=_limit_mb(f, settings) * 1024 * 1024,
                          extensions={"." + e for e in f.get("accept", formlib.FILE_EXTENSIONS)})


def _check_upload(f: dict, name: str, content: bytes, settings: dict) -> Optional[str]:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    limit_mb = _limit_mb(f, settings)
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
async def submit(event_id: int, slug: str, request: Request):
    """Lee el cuerpo (lo unico asincrono) y pasa el resto —consultas, cupo, insercion— a un hilo: el bucle de eventos nunca espera a la base de datos."""
    ctype = request.headers.get("content-type", "")
    files: Dict[str, Tuple[str, bytes]] = {}
    try:
        if "multipart" in ctype:
            raw_form = await request.form()
            payload = json.loads(str(raw_form.get("data") or "{}"))
            for name, value in raw_form.multi_items():
                if name.startswith("file:") and hasattr(value, "read"):
                    files[name[5:]] = (value.filename or "", await value.read())
        else:
            payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="La solicitud no se pudo leer")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="La solicitud no se pudo leer")
    return await timing.run(_submit_sync, event_id, slug, request, payload, files)


def _record_submit_event(form_id: int, sid: str, source: Optional[str], is_test: bool) -> None:
    """La marca «submit» de la analítica, en su propia transacción CORTA y DESPUÉS del commit: ya no ocupa una ida y vuelta con el cupo bloqueado. Si fallara solo
    se pierde ese punto de la analítica (la inscripción ya está confirmada)."""
    db = SessionLocal()
    try:
        db.add(FormEvent(form_id=form_id, sid=sid, kind="submit", source=source, is_test=is_test))
        db.commit()
    except Exception:  # noqa: BLE001
        log.warning("no se pudo registrar el evento de envío del formulario %s", form_id, exc_info=True)
    finally:
        db.close()


def _submit_sync(event_id: int, slug: str, request: Request, payload: dict, files: Dict[str, Tuple[str, bytes]]):
    """La sesión se abre AQUÍ, dentro del hilo del envío (antes `Depends(get_db)` pedía un turno de hilo solo para crearla: dos esperas en la misma cola por envío)."""
    db = SessionLocal()
    try:
        return _submit(db, event_id, slug, request, payload, files)
    finally:
        db.close()


def _submit(db: Session, event_id: int, slug: str, request: Request, payload: dict, files: Dict[str, Tuple[str, bytes]]):
    form = _load(db, event_id, slug)
    db.expunge(form)          # el formulario sigue usable (sus columnas ya están cargadas)…
    db.rollback()             # …y la conexión vuelve al pool ANTES de validar (DNS del correo, archivos, CPU): no se retiene mientras no se necesita
    access = _access(db, form, payload.get("k"), check_full=False)      # el cupo se comprueba abajo, con el formulario bloqueado
    if access in ("cerrado", "cupo_lleno"):
        return JSONResponse({"detail": "Este formulario ya no recibe inscripciones", "stage": "closed"}, status_code=409)
    _limit(db, request, "form_submit", form, 60)

    settings = formsvc.get_settings(form)
    design = formsvc.get_design(form)
    claims = _read(payload.get("t"), form)
    _check_stage(settings, claims)
    # Archivos ya subidos directo al almacenamiento (`uploads`: {campo: token}); los viejos multipart siguen llegando en `files`.
    staged, token_errors = [], {}
    for fid, tok in (payload.get("uploads") or {}).items() if isinstance(payload.get("uploads"), dict) else []:
        try:
            up = uploads.fetch(str(tok), "form_file", {"f": form.id, "fid": str(fid)})
        except HTTPException as exc:
            token_errors[str(fid)] = exc.detail
            continue
        if up:
            files[str(fid)] = (up.filename, up.content)
            staged.append(up)

    values = dict(payload.get("values") or {})
    fields = design["fields"]
    # Campos «solo lectura cuando ya se conocen»: el valor sale de la base, nunca de lo que mande el navegador.
    person = formsvc.find_person(db, form, claims["p"]) if claims.get("p") else None
    if claims.get("p"):
        db.rollback()          # `find_person` devuelve un dict (no un objeto de la sesión): la conexión se suelta otra vez antes de validar
    if person:
        for fid, val in formsvc.prefill_values(design, person).items():
            if fields[fid].get("readonly_when_prefilled"):
                values[fid] = val
    # Archivos
    uploaded, file_errors, pending = {}, dict(token_errors), {}
    visible = formlib.visible_ids(design, values)
    for fid, (filename, content) in files.items():
        f = fields.get(fid)
        if not f or f["type"] != "file" or fid not in visible:
            continue
        err = _check_upload(f, filename, content, settings)
        if err:
            file_errors[fid] = err
        else:
            uploaded[fid] = {"filename": _safe_name(filename), "size": len(content)}
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
    sid = str(payload.get("sid") or "")[:40] or None

    # VÍA RÁPIDA «cupo lleno»: si la cuenta (con caché de ~2 s, SIN bloquear la fila) ya llegó al tope, se rechaza sin pedir el bloqueo: cientos de envíos sobrantes no hacen fila
    # detrás de los que sí compiten por el último cupo. Un reintento con la MISMA `sid` de una inscripción ya confirmada sigue respondiendo «replayed» (va al camino normal).
    # Solo puede rechazar de MÁS unos segundos si se liberó un cupo; nunca deja pasar de más: quien pasa se vuelve a comprobar con el bloqueo (`form_reserve_slot`).
    if form.capacity is not None and not is_test and formsvc.held_count_cached(db, form) >= form.capacity and not formsvc.has_confirmed_sid(db, form, sid, person_id):
        db.rollback()
        return JSONResponse({"detail": "El cupo de este formulario se completó", "stage": "closed"}, status_code=409)

    # Campo «Pago»: si esta visible y el monto (segun reglas y descuentos) es mayor que 0, la inscripcion NO se confirma
    # aqui: queda «esperando pago» hasta que Wompi confirme (ver app/routers/form_payments.py).
    quote = charge = cfg = code_row = None
    pay_field = formlib.payment_field(design, {**values, **{k: True for k in uploaded}})
    if pay_field:
        ctx, code_row, code_problem = formsvc.price_context(db, form, pay_field["pay"], payload.get("d"), payload.get("code"))
        if formsvc.normalize_code(payload.get("code")) and code_problem:
            return JSONResponse({"detail": formsvc.CODE_MESSAGES[code_problem], "code_error": True}, status_code=422)
        quote = formlib.compute_amount(pay_field["pay"], formlib.priced_values(design, clean), formsvc.now_local().date(), 1 + formlib.companions_count(design, clean), ctx)
        if code_row and not any(a.get("id") == code_row.discount_id for a in quote["applied"]):
            return JSONResponse({"detail": formsvc.CODE_MESSAGES["not_applicable"], "code_error": True}, status_code=422)
        if quote["amount"] > formlib.MAX_PAYMENT_COP:
            return JSONResponse({"detail": f"El total a pagar (${quote['amount']:,}) supera el máximo de ${formlib.MAX_PAYMENT_COP:,} COP por pago de Wompi. Reduce el número de acompañantes.".replace(",", ".")}, status_code=422)
        if quote["amount"] > 0:
            if quote["amount"] < formlib.MIN_PAYMENT_COP:
                return JSONResponse({"detail": f"El monto a pagar (${quote['amount']}) es menor al mínimo de ${formlib.MIN_PAYMENT_COP} COP por transacción. Avisa a los organizadores."}, status_code=422)
            cfg = wompi.config(is_test)
            if not cfg:
                return JSONResponse({"detail": "El pago en línea todavía no está disponible para este formulario. Intenta más tarde."}, status_code=503)
            charge = quote["amount"]

    started = db.query(FormEvent).filter_by(form_id=form.id, sid=sid, kind="start").first() if sid else None
    rules = formsvc.quota_rules(form)
    try:
        # Reintento, cupos y duplicado en UNA ida y vuelta, que deja la fila del formulario BLOQUEADA hasta el commit: dos personas enviando el
        # ultimo cupo a la vez no lo llenan dos veces. Despues solo se inserta y se confirma; correo y base del evento van a la cola.
        if charge and (person_id or sid):      # reintento de pago: el intento anterior de esta persona/sesion se descarta (antes del bloqueo)
            prior = db.query(FormSubmission).filter(FormSubmission.form_id == form.id, FormSubmission.status == formsvc.PENDING)
            cond = [FormSubmission.sid == sid] if sid else []
            if person_id:
                cond.append(FormSubmission.person_id == person_id)
            for old in prior.filter(or_(*cond)).all():
                formsvc.discard_submission(db, form, old)
            db.flush()
        res = formsvc.reserve_slot(db, form, person_id, sid, is_test, rules, clean)
        if not res["ok"]:
            db.rollback()
            reason = res["reason"]
            if reason == "capacity":
                formsvc.mark_full(form)                # los siguientes se rechazan por la vía rápida, sin pedir el bloqueo
            if reason == "retry":
                return {"ok": True, "thanks": settings["thanks"], "is_test": is_test, "replayed": True}
            if reason == "quota":
                return JSONResponse({"detail": f"El cupo «{res['label']}» ya se completó. Cambia tu elección o escribe a los organizadores.", "stage": "quota"}, status_code=409)
            if reason == "duplicate":
                return JSONResponse({"detail": "Ya existe una inscripción con ese número de documento", "duplicate": True}, status_code=409)
            return JSONResponse({"detail": "El cupo de este formulario se completó", "stage": "closed"}, status_code=409)
        if pay_field:                          # solo los formularios con pago tienen inscripciones en espera que purgar
            formsvc.purge_stale_pending(db, form)
        if code_row and formsvc.code_uses(db, code_row) >= code_row.max_uses:        # otra persona se llevo el ultimo uso mientras esta escribia
            db.rollback()
            return JSONResponse({"detail": formsvc.CODE_MESSAGES["exhausted"], "code_error": True}, status_code=422)

        sub = FormSubmission(
            form_id=form.id, event_id=form.event_id, data_json=json.dumps(clean), is_test=is_test, person_id=person_id, invite_id=claims.get("inv"),
            source=str(payload.get("source") or "")[:40] or None, sid=sid, started_at=started.created_at if started else None,
            status=formsvc.PENDING if charge else "confirmed", discount_code_id=code_row.id if code_row else None,
            quota_keys=formsvc.quota_keys_for(rules, clean),
        )
        db.add(sub)
        db.flush()
        if pending:
            event = db.query(Event).filter(Event.id == form.event_id).first()      # solo hace falta con archivos (antes era una consulta MÁS con el bloqueo tomado en todos los envíos)
            for fid, content in pending.items():
                stored = f"{sub.id}_{fid}_{clean[fid]['filename']}"
                get_storage().put(form_file_key(event.tenant_id, form.id, stored), content)
                clean[fid]["stored"] = stored
            sub.data_json = json.dumps(clean)
        if charge:
            pay = FormPayment(form_id=form.id, event_id=form.event_id, submission_id=sub.id, amount_cents=charge * 100, currency="COP", is_test=is_test or cfg["test"],
                              reference=f"GW-{form.event_id}-{form.id}-{sub.id}-{secrets.token_hex(3)}", person_id=person_id,
                              breakdown_json=json.dumps({"base": quote["base"], "applied": quote["applied"], "amount": charge}))
            db.add(pay)
            db.commit()
            formsvc.bump_held(form)
            uploads.discard(*staged)
            return {"ok": True, "payment_required": True, "pay_token": _issue(form, pay=pay.id), "payment": _widget_params(pay, cfg, design, clean, quote)}
        formsvc.confirm_submission(db, form, sub, record_event=False)
        submit_event = (form.id, sub.sid or os.urandom(4).hex(), sub.source, sub.is_test)      # se leen ANTES del commit (después los objetos quedan expirados)
        db.commit()
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) == "55P03":     # lock_not_available: la espera del bloqueo del cupo pasó de FORM_LOCK_TIMEOUT_MS
            return JSONResponse({"detail": "Estamos recibiendo muchísimas inscripciones a la vez. Tu envío se reintentará solo en unos segundos.", "busy": True}, status_code=503,
                                headers={"Retry-After": "2"})           # el navegador reintenta con la MISMA `sid` (nunca duplica): ver templates/form_public.html
        raise
    except Exception:
        db.rollback()                 # nunca dejar la fila del formulario bloqueada
        raise
    formsvc.bump_held(form)
    _record_submit_event(*submit_event)
    uploads.discard(*staged)
    jobs.kick()
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
