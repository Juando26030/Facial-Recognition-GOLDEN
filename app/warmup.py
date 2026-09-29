"""Precalentamiento automático de Cloud Run + Neon (doc 13 §7) a partir de lo que la app ya sabe: eventos en curso y aperturas de formularios.

  plan(db)    → {"web": n, "publico": n, "biometria": n, "neon": {...}} para AHORA y los próximos WARM_LOOKAHEAD_MIN minutos.
  apply(p)    → fija instancias mínimas de cada servicio (solo si cambian) y el apagado automático / mínimo de Neon.
  kick()      → pide un precalentamiento YA (al pasar un evento a «en proceso» o abrir un formulario): lanza el Job de operaciones.

Corre cada hora dentro del Job de operaciones (app/ops_runner.py), que ya despierta a Neon para el respaldo: un chequeo cada 5 minutos
que tocara la base mantendría a Neon despierta todo el mes (~US$19). Por eso mira WARM_LOOKAHEAD_MIN (75) minutos hacia adelante, y los
cambios de estado lo disparan al instante.

Variables: WARM_SERVICE_WEB / WARM_SERVICE_PUBLICO / WARM_SERVICE_BIOMETRIA (rutas completas de los servicios de Cloud Run),
WARM_WEB_MIN (2), WARM_PUBLICO_MIN (2), WARM_BIOMETRIA_MIN (1), WARM_AFTER_OPENING_MIN (60: una apertura sigue caliente ese tiempo),
NEON_API_KEY + NEON_PROJECT_ID + NEON_ENDPOINT_ID (sin ellas se salta Neon), NEON_WARM_MIN_CU (0.5), NEON_IDLE_MIN_CU (0.25),
OPS_JOB_NAME (Job de operaciones, para kick). Lo que no está configurado se salta con un aviso (desarrollo, VM)."""
import logging
import os
from datetime import datetime, timedelta
from app.timeutil import utcnow

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import cloudrun
from app.models import Event, SystemEvent, WebForm

log = logging.getLogger("golden.warmup")
NEON_API = "https://console.neon.tech/api/v2"


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _openings(db: Session, now_local: datetime, before: timedelta, after: timedelta) -> list:
    """Tramos «activo» de formularios con calendario que empiezan entre now-after y now+before (hora local del calendario)."""
    from app import formsvc
    out = []
    for form in db.query(WebForm).filter(WebForm.use_schedule == True).all():  # noqa: E712
        for seg in formsvc.get_schedule(form):
            try:
                start = datetime.fromisoformat(seg["from"])
            except (KeyError, ValueError):
                continue
            if seg.get("status") == "activo" and now_local - after <= start <= now_local + before:
                out.append({"form_id": form.id, "event_id": form.event_id, "starts": start.isoformat(timespec="minutes")})
    return out


def plan(db: Session, now_local: datetime = None) -> dict:
    from app import formsvc
    now_local = now_local or formsvc.now_local()
    running = db.query(func.count(Event.id)).filter(Event.status == "en_proceso").scalar() or 0
    facial = db.query(func.count(Event.id)).filter(Event.status == "en_proceso", Event.facial_enabled == True).scalar() or 0  # noqa: E712
    after = timedelta(minutes=_int("WARM_AFTER_OPENING_MIN", 60))
    opening = _openings(db, now_local, timedelta(minutes=_int("WARM_LOOKAHEAD_MIN", 75)), after)
    # Formularios abiertos A MANO (sin calendario): la app dejó constancia al abrirlos (routers/forms.py → «form_opened»).
    opening += [{"form_id": int(ref), "manual": True} for (ref,) in
                db.query(SystemEvent.ref).filter(SystemEvent.kind == "form_opened", SystemEvent.at > utcnow() - after).all()]
    busy = bool(running or opening)
    return {
        "web": _int("WARM_WEB_MIN", 2) if running else 0,
        "biometria": _int("WARM_BIOMETRIA_MIN", 1) if facial else 0,
        "publico": _int("WARM_PUBLICO_MIN", 2) if opening else 0,
        "neon": {"suspend_timeout_seconds": -1 if busy else 0,       # -1 = nunca se apaga; 0 = el de por defecto (5 min)
                 "autoscaling_limit_min_cu": float(os.getenv("NEON_WARM_MIN_CU" if busy else "NEON_IDLE_MIN_CU", "0.5" if busy else "0.25"))},
        "why": {"events_running": running, "facial_running": facial, "form_openings": opening},
    }


def _neon(method: str, path: str, **kw):
    import requests
    resp = requests.request(method, f"{NEON_API}{path}", headers={"Authorization": f"Bearer {os.environ['NEON_API_KEY']}", "Accept": "application/json"},
                            timeout=30, **kw)
    resp.raise_for_status()
    return resp.json()


def apply(p: dict) -> list:
    """Aplica el plan. Devuelve la lista de cambios hechos (vacía si ya estaba así). Lanza si una parte configurada falla."""
    changes, errors = [], []
    for key in ("web", "publico", "biometria"):
        service = os.getenv(f"WARM_SERVICE_{key.upper()}")
        if not service:
            continue
        try:
            if cloudrun.min_instances(service) != p[key]:
                cloudrun.set_min_instances(service, p[key])
                changes.append(f"{key}: mínimo {p[key]} instancia(s)")
        except Exception as e:  # noqa: BLE001 — se sigue con lo demás; el error se reporta al final
            errors.append(f"{key}: {e}")
    if os.getenv("NEON_API_KEY") and os.getenv("NEON_PROJECT_ID") and os.getenv("NEON_ENDPOINT_ID"):
        path = f"/projects/{os.environ['NEON_PROJECT_ID']}/endpoints/{os.environ['NEON_ENDPOINT_ID']}"
        try:
            current = _neon("GET", path)["endpoint"]
            wanted = p["neon"]
            if any(current.get(k) != v for k, v in wanted.items()):
                _neon("PATCH", path, json={"endpoint": {**wanted, "autoscaling_limit_max_cu": current.get("autoscaling_limit_max_cu")}})
                changes.append(f"neon: apagado {'nunca' if wanted['suspend_timeout_seconds'] == -1 else 'por defecto'}, mínimo {wanted['autoscaling_limit_min_cu']} CU")
        except Exception as e:  # noqa: BLE001
            errors.append(f"neon: {e}")
    if errors:
        raise RuntimeError("; ".join(errors) + (f" (sí se aplicó: {'; '.join(changes)})" if changes else ""))
    return changes


def kick() -> None:
    """Precalentar YA (lo llaman los cambios de estado de eventos y formularios). Nunca rompe la petición que lo llama."""
    job = os.getenv("OPS_JOB_NAME")
    if not job:
        return
    try:
        cloudrun.run_job(job, ["-m", "app.ops_runner", "warmup"])
    except Exception:  # noqa: BLE001 — el precalentamiento de cada hora lo recoge igual
        log.error("no se pudo lanzar el precalentamiento inmediato", exc_info=True)
