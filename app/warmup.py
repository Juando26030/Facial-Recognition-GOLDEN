"""Precalentamiento automático de Cloud Run + Neon (doc 13 §7) a partir de la actividad real reciente (ingresos y envíos de formularios).

  plan(db)    → {"web": n, "publico": n, "biometria": n, "neon": {...}} para AHORA (según la actividad de los últimos NEON_WARM_ACTIVITY_MIN minutos).
  apply(p)    → fija instancias mínimas de cada servicio (solo si cambian) y el apagado automático / mínimo de Neon.
  kick()      → pide un precalentamiento YA (al primer ingreso o envío tras un rato inactivo): lanza el Job de operaciones.

Corre cada hora dentro del Job de operaciones (app/ops_runner.py), que ya despierta a Neon para el respaldo: un chequeo cada 5 minutos
que tocara la base mantendría a Neon despierta todo el mes (~US$19). Por eso la evaluación es horaria y el primer ingreso/envío tras un rato inactivo la dispara al instante.

Calienta SOLO con ACTIVIDAD real en los últimos NEON_WARM_ACTIVITY_MIN (15) min: ingresos/registros/reconocimientos (access_logs) o envíos de formularios
(form_submissions). No hay lógica de horarios: ni «en proceso», ni formularios abiertos o por abrir cuentan. Neon SIEMPRE con su apagado por defecto (suspend_timeout_seconds=0 = 5 min; jamás -1) y el mínimo de CU: NEON_WARM_MIN_CU ocupado, NEON_IDLE_MIN_CU en reposo.
apply() corrige un endpoint que hoy esté en -1. note_activity() (al insertar un AccessLog o FormSubmission) lanza kick() al primer evento tras un rato
inactivo, con límite en memoria WARM_KICK_MIN_INTERVAL_MIN (30) y en un hilo, sin consultas a la base.

Variables: WARM_SERVICE_WEB / WARM_SERVICE_PUBLICO / WARM_SERVICE_BIOMETRIA (rutas completas de los servicios de Cloud Run),
WARM_WEB_MIN (2), WARM_PUBLICO_MIN (2), WARM_BIOMETRIA_MIN (1), NEON_API_KEY + NEON_PROJECT_ID + NEON_ENDPOINT_ID (sin ellas se salta Neon), NEON_WARM_MIN_CU (0.25), NEON_IDLE_MIN_CU (0.25),
OPS_JOB_NAME (Job de operaciones, para kick). Lo que no está configurado se salta con un aviso (desarrollo, VM)."""
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from app.timeutil import utcnow

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import cloudrun
from app.models import AccessLog, Event, FormSubmission

log = logging.getLogger("golden.warmup")
NEON_API = "https://console.neon.tech/api/v2"


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def plan(db: Session, now_local: datetime = None) -> dict:
    from app import formsvc
    now_local = now_local or formsvc.now_local()
    # SIN lógica de horarios (ni de eventos ni de formularios): solo actividad REAL reciente. «en_proceso» y formularios abiertos/por abrir NO cuentan.
    since = utcnow() - timedelta(minutes=_int("NEON_WARM_ACTIVITY_MIN", 15))
    active = db.query(Event.id, Event.facial_enabled).join(AccessLog, AccessLog.event_id == Event.id) \
        .filter(Event.status == "en_proceso", AccessLog.timestamp > since).distinct().all()
    running = len(active)
    facial = sum(1 for _, f in active if f)
    submits = db.query(func.count(FormSubmission.id)).filter(FormSubmission.created_at > since).scalar() or 0
    busy = bool(running or submits)
    return {
        "web": _int("WARM_WEB_MIN", 2) if (running or submits) else 0,
        "biometria": _int("WARM_BIOMETRIA_MIN", 1) if facial else 0,
        "publico": _int("WARM_PUBLICO_MIN", 2) if submits else 0,
        # NUNCA -1 («nunca apagar»): mantendría a Neon cobrando CU-hora sin consultas. Siempre 0 = apagado por defecto (5 min sin consultas).
        "neon": {"suspend_timeout_seconds": 0,
                 "autoscaling_limit_min_cu": float(os.getenv("NEON_WARM_MIN_CU" if busy else "NEON_IDLE_MIN_CU", "0.25"))},
        "why": {"events_active": running, "facial_active": facial, "form_submissions": submits},
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
                changes.append(f"neon: apagado {'nunca' if wanted['suspend_timeout_seconds'] == -1 else str(wanted['suspend_timeout_seconds']) + ' s'}, mínimo {wanted['autoscaling_limit_min_cu']} CU")
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
    from app import ops_state
    ops_state.mark_active()          # el Job horario lo lee (sin tocar la base) para decidir si corre completo o la base descansa
    try:
        cloudrun.run_job(job, ["-m", "app.ops_runner", "warmup"])
    except Exception:  # noqa: BLE001 — el precalentamiento de cada hora lo recoge igual
        log.error("no se pudo lanzar el precalentamiento inmediato", exc_info=True)


_last_kick = 0.0
_kick_lock = threading.Lock()


def note_activity() -> None:
    """Primer ingreso/registro tras un periodo inactivo → precalentar. Barato: sin base, limitado en memoria y en un hilo aparte."""
    global _last_kick
    if not os.getenv("OPS_JOB_NAME"):
        return
    now = time.monotonic()
    with _kick_lock:
        if _last_kick and now - _last_kick < _int("WARM_KICK_MIN_INTERVAL_MIN", 30) * 60:
            return
        _last_kick = now
    threading.Thread(target=kick, daemon=True).start()


def _install_listener() -> None:
    from sqlalchemy import event as sa_event
    for model in (AccessLog, FormSubmission):
        sa_event.listen(model, "after_insert", lambda *a, **k: note_activity())


_install_listener()
