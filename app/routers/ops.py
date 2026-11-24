"""Salud y estado del sistema (docs/observabilidad.md).

  GET /health  (= /healthz) liveness: NO toca ninguna dependencia, responde en milisegundos (el orquestador reinicia el proceso si falla).
  GET /ready   (= /readyz)  readiness: base (con tiempo límite), almacenamiento y —en el servicio de biometría— el modelo facial. 503 dice cuál falla y por qué.
  En Cloud Run se usan /health y /ready: Google reserva rutas que terminan en «z» (/healthz da 404 del propio Google, ver
  docs.cloud.google.com/run/docs/known-issues). /healthz y /readyz se mantienen para la VM y por compatibilidad.
  GET /api/ops/status      (admin+) semáforo completo para la pantalla «Estado del sistema».
  GET /api/ops/deploy-allowed   ¿se puede desplegar ahora? (admin+, o la cabecera X-Ops-Token = OPS_TOKEN para el flujo de despliegue).
  GET /api/ops/client-ip   (admin+ u OPS_TOKEN) qué IP de X-Forwarded-For toma la app como la del visitante (verificar XFF_CLIENT_INDEX detrás de Firebase).
  POST /api/ops/simulate-crash   SOLO staging con CHAOS_ENABLED=1 (simulacro «matar instancia» de docs/15); en cualquier otro caso responde 404.
  GET /sistema             la pantalla (admin+)."""
import hmac
import logging
import os
import signal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import appmode, event_lease, ops
from app.obs import mask_pii
from app.safeeq import safe_eq
from app.auth import get_current_staff, require_role, require_role_or_any
from app.database import get_db

router = APIRouter()
pages = APIRouter()
log = logging.getLogger("golden.ops")


@router.get("/health")
@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/ready")
@router.get("/readyz")
def readyz() -> JSONResponse:
    """S10: la respuesta es PÚBLICA, así que solo dice qué componente está bien o mal; el motivo (texto de la excepción: host de la base, bucket…) va solo al log,
    enmascarado. El detalle completo sigue en «Estado del sistema» (admin+)."""
    checks = ops.readiness(require_model=appmode.loads_model())
    failing = sorted(name for name, c in checks.items() if not c["ok"])
    for name in failing:
        log.warning("readyz: %s no está listo: %s", name, mask_pii(checks[name].get("reason", "")))
    body = {"status": "unavailable" if failing else "ready", "checks": {name: {"ok": bool(c["ok"])} for name, c in checks.items()}}
    if failing:
        body["failing"] = failing
    return JSONResponse(body, status_code=503 if failing else 200)


def _ops_reader(request: Request, db: Session = Depends(get_db)) -> Optional[object]:
    """Admin+ con sesión, o el token de operaciones (para que el despliegue pregunte sin iniciar sesión)."""
    token, supplied = os.getenv("OPS_TOKEN"), request.headers.get("x-ops-token")
    if token and supplied and safe_eq(token, supplied):
        return None
    return require_role("admin")(get_current_staff(request, db))


def google_invoker(request: Request) -> None:
    """Única puerta de TODA ruta /internal/* (servicio público): token OIDC de Google válido (firma y emisor de Google, vigente), emitido
    PARA la audiencia `CLOUD_TASKS_URL` y A NOMBRE de la cuenta `JOBS_INVOKER_SA` del entorno, con el correo verificado.
    Sin token o token inválido → 401; token válido de otra cuenta → 403; sin configurar → 403 (nunca se abre por falta de variables).
    Ningún otro mecanismo (ni sesión de admin ni X-Ops-Token) sirve aquí."""
    audience = os.getenv("CLOUD_TASKS_FACES_URL" if request.url.path == "/internal/faces/run" else "CLOUD_TASKS_URL")      # cada cola tiene su propia audiencia
    invoker = os.getenv("JOBS_INVOKER_SA")
    if not audience or not invoker:
        raise HTTPException(status_code=403, detail="No autorizado")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not auth[7:].strip():
        raise HTTPException(status_code=401, detail="Falta el token", headers={"WWW-Authenticate": "Bearer"})
    from google.auth import exceptions as google_exceptions
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    try:
        claims = id_token.verify_oauth2_token(auth[7:].strip(), google_requests.Request(), audience)
    except google_exceptions.TransportError:
        raise HTTPException(status_code=503, detail="No se pudo verificar el token", headers={"Retry-After": "10"})
    except ValueError:                                   # firma, emisor, vencimiento o audiencia no válidos
        raise HTTPException(status_code=401, detail="Token no válido", headers={"WWW-Authenticate": "Bearer"})
    if claims.get("email") != invoker or claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="No autorizado")


@router.post("/internal/jobs/run")
def run_jobs(_=Depends(google_invoker)) -> dict:
    """Ejecuta la cola dentro de ESTA petición (en Cloud Run con facturación por petición la CPU se reduce apenas se responde):
    hasta vaciarla o hasta JOBS_RUN_BUDGET_SECONDS (45 por defecto, por debajo del timeout de 60 de Gunicorn); lo que quede lo toma
    otra tarea de Cloud Tasks."""
    from app import jobs                          # los manejadores ya están registrados desde el arranque (app/main.py; jobs.assert_handlers lo exige)
    return {"ran": jobs.drain(max_rounds=100_000, budget_seconds=float(os.getenv("JOBS_RUN_BUDGET_SECONDS", "45")), exclude=jobs.general_excludes())}


@router.post("/internal/faces/run")
def run_face_jobs(_=Depends(google_invoker)) -> dict:
    """Cola APARTE de los cálculos faciales (vector tras la aceptación): corre en el servicio de biometría (2 CPU, 2 Gi), con tope de 2 despachos simultáneos en Cloud Tasks y reintentos de espera creciente,
    para que el cálculo no le quite CPU a la puerta. Mismo token OIDC y misma cuenta que la cola general; solo ejecuta trabajos de `jobs.FACE_KINDS` (idempotentes)."""
    from app import enroll, jobs  # noqa: F401 — enroll registra `face_enroll`
    return {"ran": jobs.drain(max_rounds=100_000, budget_seconds=float(os.getenv("JOBS_RUN_BUDGET_SECONDS", "45")), kinds=jobs.FACE_KINDS, pool="faces")}


@router.get("/api/ops/version")
def version() -> dict:
    """Versión de este servidor (commit, fecha y última migración). Pública y sin base de datos: la consultan los servidores locales para saber si están al día (app/versioning.py)."""
    from app import versioning
    return versioning.local_version()


@router.get("/api/ops/version-check")
def version_check(request: Request, force: bool = False) -> dict:
    """Solo servidores locales (con PRODUCTION_URL): compara su versión con la de producción para mostrar el aviso de «desactualizado». En la nube responde {configured: false}. Pide sesión (cookie)
    pero NO toca la base de datos: la página lo consulta al abrir y en la nube no debe costar nada."""
    from app import versioning
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    return versioning.check(force=force)


@router.get("/api/ops/local-address")
def local_address(request: Request) -> dict:
    """Solo servidores locales: la IP y el puerto para conectar OTROS equipos de la misma red a este servidor (se muestra junto al aviso de versión). En la nube: {configured: false}. Pide sesión; sin base de datos."""
    from app import localmode
    if not localmode.is_local_server():
        return {"configured": False}
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    host = (request.headers.get("host") or "").rsplit(":", 1)
    port = int(host[1]) if len(host) == 2 and host[1].isdigit() else int(os.getenv("LOCAL_APP_PORT", "8443"))
    details = localmode.lan_address_details()          # [{ip, kind: cable|wifi|otro}], la recomendada primero (cable antes que Wi‑Fi)
    return {"configured": True, "port": port, "addresses": [d["ip"] for d in details], "details": details}


@router.get("/api/ops/server-id")
def server_id(request: Request) -> dict:
    """Solo servidores locales: el ID del servidor (= su llave de producto), que se ve como etiqueta morada junto a la versión. En la nube: {configured: false}. Pide sesión; sin base de datos."""
    from app import local_env, localmode, server_lock
    if not localmode.is_local_server():
        return {"configured": False}
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    local_env.refresh()
    code = (os.getenv("SERVER_KEY") or "").strip()
    return {"configured": bool(code), "id": code, "disabled": server_lock.is_locked()}


@router.get("/api/ops/update-manifest")
def update_manifest(request: Request) -> dict:
    """Lo que producción publica para que los servidores locales se actualicen (dirección HTTPS del paquete y su huella SHA-256, de variables de entorno). Público: commit y esquema los ve cualquiera
    (la franja «Al día» los compara); la dirección del paquete solo la ve quien tenga un token de servidor o el permiso de un instalador cuando `UPDATE_PACKAGE_AUTH=1` (app/routers/server_keys.py)."""
    from app import local_update
    from app.routers import server_keys as keys_router
    m = local_update.published_manifest()
    if m.get("available") and not keys_router.package_allowed(request):
        return {**m, "package_url": None, "sha256": None, "locked": True}
    return m


@router.get("/api/ops/update-package/{name}")
def update_package(name: str, request: Request):
    """El paquete de actualización del servidor local (código de la app, sin datos ni secretos; el servidor local verifica su huella SHA-256 antes de aplicarlo). Con `UPDATE_PACKAGE_AUTH=1` exige un
    token de servidor (`X-Node-Token`) o el permiso de un instalador (`X-Install-Ticket` + `X-Install-Id`); sin esa variable sigue público."""
    from fastapi.responses import Response
    from app import local_update
    from app.routers import server_keys as keys_router
    if not keys_router.package_allowed(request):
        raise HTTPException(status_code=401, detail="Para bajar el paquete hace falta un servidor autorizado o una llave de producto válida")
    data = local_update.package_bytes(name)
    if data is None:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    return Response(content=data, media_type="application/zip", headers={"Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/ops/update-status")
def update_status(request: Request) -> dict:
    """Avance de «Actualizar ahora» (lo escribe el servicio de actualización del servidor local). Sin base de datos; pide sesión."""
    from app import local_update
    if not request.session.get("staff_user_id"):
        raise HTTPException(status_code=401, detail="No autenticado")
    if not local_update.is_local_server():
        return {"enabled": False}
    return {"enabled": True, **local_update.read_status()}


@router.post("/api/ops/update")
def update_now(data: dict, db: Session = Depends(get_db), staff=Depends(require_role_or_any("coordinador", event_lease.LEASE_ROLES))) -> dict:
    """«Actualizar ahora» (solo servidores locales). Si hay un turno en marcha responde 409 `shift_active` y exige repetir con `confirm_shift: true` (la pantalla lo pregunta con showConfirm)."""
    from datetime import timedelta
    from app import local_update
    from app.models import AccessLog, Event
    from app.timeutil import utcnow
    in_progress = db.query(Event).filter(Event.status == "en_proceso").count()
    since = utcnow() - timedelta(minutes=local_update.RECENT_ACTIVITY_MINUTES)
    recent = db.query(AccessLog).filter(AccessLog.timestamp >= since).count()
    try:
        return local_update.request_update(staff_id=staff.id, events_in_progress=in_progress, recent_checkins=recent, confirm_shift=bool((data or {}).get("confirm_shift")))
    except local_update.UpdateRefused as e:
        raise HTTPException(status_code=409 if e.code in ("shift_active", "busy") else 400, detail={"code": e.code, "message": e.message})


@router.get("/api/ops/status")
def status(db: Session = Depends(get_db), staff=Depends(require_role("admin"))) -> dict:
    return ops.system_status(db)


@router.get("/api/ops/deploy-allowed")
def deploy_allowed(hours: Optional[int] = None, db: Session = Depends(get_db), _=Depends(_ops_reader)) -> dict:
    if hours is not None and not 0 <= hours <= 72:
        raise HTTPException(status_code=400, detail="hours debe estar entre 0 y 72")
    return ops.deploy_allowed(db, hours)


@router.get("/api/ops/client-ip")
def client_ip_diagnostic(request: Request, _=Depends(_ops_reader)) -> dict:
    """Diagnóstico para elegir XFF_CLIENT_INDEX detrás de Firebase Hosting: lista la cadena `X-Forwarded-For` tal como llega, y qué entrada toma `client_ip()`.
    Se llama desde el navegador/`curl` de quien prueba (con su propia IP conocida y, si se quiere, mandando una cabecera `X-Forwarded-For` inventada para ver
    si el índice elegido se deja engañar). Solo para admin+ o con OPS_TOKEN; no se registra la respuesta."""
    from app.security import client_ip, infra_info, is_google_infra
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return {"x_forwarded_for": hops, "hops": len(hops), "google_infra": [is_google_infra(h) for h in hops], "chosen_ip": client_ip(request),
            "strip_google": os.getenv("XFF_STRIP_GOOGLE", "0") == "1", "ranges": infra_info(), "xff_client_index": os.getenv("XFF_CLIENT_INDEX", "0"),
            "trust_cf_connecting_ip": os.getenv("TRUST_CF_CONNECTING_IP", "0") == "1", "cf_connecting_ip_present": bool(request.headers.get("cf-connecting-ip")),
            "socket_peer": request.client.host if request.client else None}


def _die() -> None:
    """Termina la instancia: SIGQUIT al proceso maestro de Gunicorn (apagado inmediato de los workers, el contenedor sale y Cloud Run levanta otra);
    sin Gunicorn (uvicorn), sale el propio proceso."""
    try:
        os.kill(os.getppid(), getattr(signal, "SIGQUIT", signal.SIGTERM))
    finally:
        os._exit(1)


@router.post("/api/ops/simulate-crash")
def simulate_crash(background: BackgroundTasks, _=Depends(_ops_reader)) -> dict:
    """Simulacro 1 de la Fase 4 («matar una instancia» mientras hay carga). Triple candado: solo con DEPLOY_ENV=staging, CHAOS_ENABLED=1 (Juan David lo pone
    con `gcloud run services update … --update-env-vars CHAOS_ENABLED=1` para el simulacro y lo quita al terminar) y admin+ u OPS_TOKEN. Producción y
    cualquier otro entorno responden 404 como si la ruta no existiera. Responde y DESPUÉS se cae."""
    if os.getenv("DEPLOY_ENV", "").strip().lower() != "staging" or os.getenv("CHAOS_ENABLED") != "1":
        raise HTTPException(status_code=404, detail="Not Found")
    background.add_task(_die)
    return {"crashing": True}


@pages.get("/sistema")
def system_page(request: Request):
    from app.main import _display_role, _require_page_role, templates
    redirect = _require_page_role(request, "admin")
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="sistema.html", context={
        "staff_name": request.session.get("staff_name"),
        "staff_role": _display_role(request.session.get("staff_role"), request.session.get("staff_secondary_role")),
        "sidebar_active": "sistema",
    })
