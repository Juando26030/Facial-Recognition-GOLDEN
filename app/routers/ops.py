"""Salud y estado del sistema (docs/observabilidad.md).

  GET /healthz             liveness: NO toca ninguna dependencia, responde en milisegundos (el orquestador reinicia el proceso si falla).
  GET /readyz              readiness: base (con tiempo límite), almacenamiento y —en el servicio de biometría— el modelo facial. 503 dice cuál falla y por qué.
  GET /api/ops/status      (admin+) semáforo completo para la pantalla «Estado del sistema».
  GET /api/ops/deploy-allowed   ¿se puede desplegar ahora? (admin+, o la cabecera X-Ops-Token = OPS_TOKEN para el flujo de despliegue).
  GET /sistema             la pantalla (admin+)."""
import hmac
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import appmode, ops
from app.auth import get_current_staff, require_role
from app.database import get_db

router = APIRouter()
pages = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


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


def _jobs_invoker(request: Request) -> None:
    """Quién puede despertar la cola: Cloud Tasks / Cloud Scheduler con un token OIDC de `JOBS_INVOKER_SA` para la audiencia `CLOUD_TASKS_URL`,
    o el token de operaciones (pruebas y uso manual)."""
    token, supplied = os.getenv("OPS_TOKEN"), request.headers.get("x-ops-token")
    if token and supplied and hmac.compare_digest(token, supplied):
        return
    auth, sa = request.headers.get("authorization", ""), os.getenv("JOBS_INVOKER_SA")
    if sa and auth.startswith("Bearer "):
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        try:
            claims = id_token.verify_oauth2_token(auth[7:], google_requests.Request(), os.getenv("CLOUD_TASKS_URL"))
        except ValueError:
            claims = {}
        if claims.get("email") == sa and claims.get("email_verified"):
            return
    raise HTTPException(status_code=403, detail="No autorizado")


@router.post("/internal/jobs/run")
def run_jobs(_=Depends(_jobs_invoker)) -> dict:
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
