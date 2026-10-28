"""Carga masiva de la base POR PASOS, dirigida por la petición (orden del 24-oct-2026).

Por qué: en Cloud Run (CPU «solo durante las peticiones») un hilo en segundo plano casi no recibe CPU: medido en staging, 8.000 personas tardaron de 4 a 8 minutos a 20–100 filas/s aunque la base respondía
en milisegundos. Aquí NADA corre fuera de una petición: el navegador pide cada paso y el servidor procesa un grupo de filas DENTRO de esa petición, con toda la CPU.

Flujo (el navegador repite el paso hasta que termina; ver kiosk_roster.html):
  1. `POST /api/bulk_register` (background=true): lee y valida el archivo UNA vez (`_bulk_register_impl(step={"phase": "prepare"})`), guarda lo preparado CIFRADO en el almacenamiento, y
     responde con `job_id` y `mode: "steps"`. Con hasta `BULK_SYNC_ROWS` (500) filas todo ocurre en esa misma petición.
  2. `POST /api/bulk_jobs/{id}/step`: procesa las siguientes `BULK_STEP_ROWS` (1.500) filas y confirma en la base. El avance (posición, cuenta y observaciones) vive en la MISMA fila de la tarea
     (`result_json`) y se confirma en la MISMA transacción que las filas: o quedan las dos cosas o ninguna. Repetir un paso (red cortada, otra pestaña, un reinicio) no duplica nada, porque las
     filas se escriben como «crear o actualizar». Dos pasos a la vez se serializan (la fila de la tarea se bloquea hasta confirmar).
  3. `GET /api/bulk_jobs/{id}` solo lee el estado; `GET /api/bulk_steps/active?event_id=` permite retomar una carga que quedó a medias (cerraste la página, se reinició el servicio).
Privacidad: lo preparado lleva datos personales: se guarda cifrado (`crypto.encrypt_bytes`), con un nombre sin datos (`<cliente>/bulk_steps/<id al azar>/…`), solo lo ve quien lo pidió, y se borra al
terminar, al fallar y, si se abandona, a la hora (`BULK_STEPS_TTL_MINUTES`), también desde la tarea horaria de operaciones. Nada de datos personales en logs.
Solo para cargas SIN fotos (zip) ni pre-cálculo facial y con Cloud Run Job apagado: lo demás sigue por el camino de siempre."""
import json
import logging
import os
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import bulk_jobs, crypto
from app.auth import get_event_for_staff
from app.models import BulkJob, Event, StaffUser
from app.storage import get_storage, key_of
from app.timeutil import utcnow

log = logging.getLogger("golden.bulk_steps")
KIND = json.dumps({"kind": "bulk_steps"})
STEP_ROWS = int(os.getenv("BULK_STEP_ROWS", "1500"))
SYNC_ROWS = int(os.getenv("BULK_SYNC_ROWS", "500"))
TTL = timedelta(minutes=int(os.getenv("BULK_STEPS_TTL_MINUTES", "60")))


def key_ready() -> bool:
    """Lo temporal lleva datos personales: SOLO se guarda cifrado. Sin `FACE_ENCRYPTION_KEY` (variable que Cloud Run monta desde el secreto `golden-face-encryption-key[-staging]`) esta carga NO usa pasos y
    sigue por el camino de siempre (sin archivo temporal propio). `BULK_STEPS_ALLOW_CLEAR=1` solo existe para desarrollo y pruebas locales."""
    return crypto.enabled() or os.getenv("BULK_STEPS_ALLOW_CLEAR") == "1"


def decide(event: Event, has_zip: bool, has_roster: bool) -> tuple:
    """(¿por pasos?, motivo). Una carga que solo trae el archivo de la base (Excel/CSV, sin fotos/zip) va SIEMPRE por pasos, sea cual sea `BULK_BACKEND`: el Job de Cloud Run queda para las cargas con
    fotos o con pre-cálculo facial (su arranque en frío tarda más que la carga de la base). Las ÚNICAS razones para no usar pasos están en el motivo (y se anotan en el log de cada carga)."""
    if os.getenv("BULK_STEPS", "1") == "0":
        return False, "pasos_desactivados"
    if has_zip:
        return False, "con_fotos"
    if not has_roster:
        return False, "sin_archivo_solo_traer_personas"
    if not key_ready():
        return False, "sin_llave_de_cifrado"
    if event.controller_mode == "tercero" and bool(event.precalculo_autorizado):
        return False, "evento_de_tercero_con_precalculo_facial"
    return True, "solo_excel"


def wants(event: Event, has_zip: bool, has_roster: bool) -> bool:
    return decide(event, has_zip, has_roster)[0]


def eligible(event: Event, zip_bytes, content) -> bool:
    return wants(event, bool(zip_bytes), content is not None)


def _key(tenant_id: str, job_id: str, name: str = "") -> str:
    return key_of(tenant_id, "bulk_steps", job_id, name) if name else key_of(tenant_id, "bulk_steps", job_id)


def _save(tenant_id: str, job_id: str, name: str, obj) -> None:
    get_storage().put(_key(tenant_id, job_id, name), crypto.encrypt_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8")))


def _load(tenant_id: str, job_id: str, name: str):
    try:
        raw = get_storage().get(_key(tenant_id, job_id, name))
    except Exception:  # noqa: BLE001 — no existe (venció o se borró)
        return None
    plain = crypto.decrypt_bytes(raw)
    return json.loads(plain.decode("utf-8")) if plain is not None else None


def _drop(tenant_id: str, job_id: str) -> None:
    try:
        get_storage().delete_prefix(_key(tenant_id, job_id))
    except Exception:  # noqa: BLE001 — la tarea horaria lo reintenta
        log.warning("no se pudo borrar lo temporal de una carga por pasos", exc_info=True)


def serialize_job(job: BulkJob) -> dict:
    """Estado para el navegador. A diferencia de la carga en hilo, una carga por pasos NO se da por interrumpida a los 10 minutos: se puede retomar hasta que venza (`TTL`)."""
    out = {"id": job.id, "job_id": job.id, "mode": "steps", "status": job.status, "stage": job.stage, "done": job.done, "total": job.total,
           "elapsed": ((job.finished_at or utcnow()) - job.created_at).total_seconds()}
    if job.status == "done" and job.result_json:
        out["result"] = json.loads(job.result_json)
    if job.status == "error":
        out["error"] = {"status": job.error_status, "detail": job.error_detail}
    return out


def _fail(job: BulkJob, status: int, detail: str) -> None:
    job.status, job.error_status, job.error_detail, job.stage = "error", status, str(detail), "Error"
    job.finished_at = job.updated_at = utcnow()


def _is_steps(job: Optional[BulkJob]) -> bool:
    return job is not None and job.spec_json == KIND


def start(db: Session, event: Event, staff: StaffUser, args: dict, cleanup) -> dict:
    """Prepara la carga y devuelve el estado de la tarea. `args` son los de `_bulk_register_impl`; `cleanup(resultado)` borra los archivos subidos (salvo que haya que reenviarlos)."""
    from app.routers import api
    purge_expired(db)
    if bulk_jobs.active_job(db, event.id):
        raise HTTPException(status_code=409, detail="Ya hay una carga en curso para este evento — espera a que termine.")
    job_id = bulk_jobs.create_job(db, event.id, staff.id, {"kind": "bulk_steps"})
    job = db.get(BulkJob, job_id)
    job.status, job.stage = "running", "Leyendo el archivo"
    db.commit()
    try:
        res = api._bulk_register_impl(db, staff, step={"phase": "prepare"}, **args)
    except HTTPException as e:
        db.rollback()
        cleanup(None)
        job = db.get(BulkJob, job_id)
        _fail(job, e.status_code, e.detail)
        db.commit()
        return serialize_job(job)
    except Exception as e:  # noqa: BLE001 — cualquier fallo se le muestra al usuario, no se pierde
        log.error("la preparación de la carga %s falló", job_id, exc_info=True)
        db.rollback()
        cleanup(None)
        job = db.get(BulkJob, job_id)
        _fail(job, 500, f"Error inesperado: {e}")
        db.commit()
        return serialize_job(job)
    cleanup(res)
    job = db.get(BulkJob, job_id)
    if "prepared" not in res:                       # NEEDS_LABELS (el navegador reenvía la misma carga con los nombres de columnas): ya es el resultado final
        job.status, job.stage, job.result_json = "done", "Listo", json.dumps(res)
        job.finished_at = job.updated_at = utcnow()
        db.commit()
        return serialize_job(job)
    total = len(res["prepared"]["rows"])
    _save(event.tenant_id, job_id, "prepared", res["prepared"])
    job.result_json = json.dumps({"state": res["state"]})              # el avance vive en la fila de la tarea (atómico con las filas de cada paso)
    job.total, job.done, job.stage, job.updated_at = total, 0, "Listo para guardar", utcnow()
    db.commit()
    # El PRIMER paso corre en esta misma petición (sin esperar otro viaje del navegador): con hasta 500 filas la carga termina aquí; con más, la primera respuesta ya trae el avance.
    return run_step(db, job_id, staff, limit=total if total <= SYNC_ROWS else STEP_ROWS)


def run_step(db: Session, job_id: str, staff: StaffUser, limit: Optional[int] = None) -> dict:
    """Procesa el siguiente grupo de filas de la tarea. Idempotente y serializado (la fila de la tarea se bloquea mientras dura el paso)."""
    from app.routers import api
    job = db.query(BulkJob).filter(BulkJob.id == job_id, BulkJob.spec_json == KIND).with_for_update().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Carga no encontrada")
    event = get_event_for_staff(job.event_id, db, staff)
    if job.staff_user_id != staff.id:
        raise HTTPException(status_code=404, detail="Carga no encontrada")
    if job.status in ("done", "error"):
        return serialize_job(job)
    prepared = _load(event.tenant_id, job.id, "prepared")
    try:
        state = json.loads(job.result_json)["state"]
    except (TypeError, ValueError, KeyError):
        state = None
    if prepared is None or state is None:
        _fail(job, 410, "Esta carga venció o se perdió lo temporal. Súbela de nuevo.")
        db.commit()
        return serialize_job(job)
    try:
        res = api._bulk_register_impl(db, staff, event_id=job.event_id, roster_filename=None, content=None, zip_bytes=None, field_labels=None, source_event_id=None,
                                      step={"phase": "rows", "prepared": prepared, "state": state, "limit": limit or STEP_ROWS})
        if res.get("done") is False:
            job.done, job.updated_at = res["state"]["pos"], utcnow()
            job.stage = f"Guardando personas ({job.done} de {job.total})"
            job.result_json = json.dumps({"state": res["state"]})
        db.commit()                                 # las filas y el avance, JUNTOS: o se guardan las dos cosas o ninguna
    except HTTPException as e:
        db.rollback()
        job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
        _fail(job, e.status_code, e.detail)
        db.commit()
        _drop(event.tenant_id, job.id)
        return serialize_job(job)
    except Exception:  # noqa: BLE001 — error de paso (red, base): la carga NO se pierde, el navegador reintenta el mismo paso
        log.error("un paso de la carga %s falló", job_id, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=503, detail="No se pudo guardar este grupo de personas. Se reintenta solo.")
    job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
    if res.get("done") is False:
        return serialize_job(job)
    job.status, job.stage, job.result_json = "done", "Listo", json.dumps(res)
    job.done = job.total
    job.finished_at = job.updated_at = utcnow()
    db.commit()
    _drop(event.tenant_id, job.id)
    return serialize_job(job)


def active_for(db: Session, event_id: int, staff: StaffUser) -> Optional[dict]:
    """La carga por pasos en curso de esta persona en este evento (para retomarla tras cerrar la página)."""
    job = (db.query(BulkJob).filter(BulkJob.event_id == event_id, BulkJob.staff_user_id == staff.id, BulkJob.spec_json == KIND, BulkJob.status == "running",
                                    BulkJob.updated_at > utcnow() - TTL).order_by(BulkJob.created_at.desc()).first())
    return serialize_job(job) if job is not None else None


def purge_expired(db: Session) -> int:
    """Borra lo temporal de las cargas por pasos terminadas o abandonadas hace más de `TTL` (y las marca como vencidas)."""
    cut = utcnow() - TTL
    n = 0
    for job in db.query(BulkJob).filter(BulkJob.spec_json == KIND, BulkJob.updated_at < cut, BulkJob.status.in_(("running", "queued"))).all():
        event = db.get(Event, job.event_id)
        if event is not None:
            _drop(event.tenant_id, job.id)
        _fail(job, 410, "Esta carga se abandonó y venció. Súbela de nuevo.")
        n += 1
    if n:
        db.commit()
    return n
