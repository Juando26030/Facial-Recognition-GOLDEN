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
import os
import signal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import appmode, ops
from app.auth import get_current_staff, require_role
from app.database import get_db

router = APIRouter()
pages = APIRouter()


@router.get("/health")
@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/ready")
@router.get("/readyz")
def readyz() -> JSONResponse:
    checks = ops.readiness(require_model=appmode.loads_model())
    failing = {name: c["reason"] for name, c in checks.items() if not c["ok"]}
    body = {"status": "unavailable" if failing else "ready", "checks": checks}
    if failing:
        body["failing"] = failing
    return JSONResponse(body, status_code=503 if failing else 200)


def _ops_reader(request: Request, db: Session = Depends(get_db)) -> Optional[object]:
    """Admin+ con sesión, o el token de operaciones (para que el despliegue pregunte sin iniciar sesión)."""
    token, supplied = os.getenv("OPS_TOKEN"), request.headers.get("x-ops-token")
    if token and supplied and hmac.compare_digest(token, supplied):
        return None
    return require_role("admin")(get_current_staff(request, db))


def google_invoker(request: Request) -> None:
    """Única puerta de TODA ruta /internal/* (servicio público): token OIDC de Google válido (firma y emisor de Google, vigente), emitido
    PARA la audiencia `CLOUD_TASKS_URL` y A NOMBRE de la cuenta `JOBS_INVOKER_SA` del entorno, con el correo verificado.
    Sin token o token inválido → 401; token válido de otra cuenta → 403; sin configurar → 403 (nunca se abre por falta de variables).
    Ningún otro mecanismo (ni sesión de admin ni X-Ops-Token) sirve aquí."""
    audience, invoker = os.getenv("CLOUD_TASKS_URL"), os.getenv("JOBS_INVOKER_SA")
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
    from app import jobs, reconcile  # noqa: F401 — registra `payments_reconcile` (form_feed ya lo registra formsvc)
    return {"ran": jobs.drain(max_rounds=100_000, budget_seconds=float(os.getenv("JOBS_RUN_BUDGET_SECONDS", "45")))}


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
            "trust_cf_connecting_ip": os.getenv("TRUST_CF_CONNECTING_IP", "1") == "1", "cf_connecting_ip_present": bool(request.headers.get("cf-connecting-ip")),
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
