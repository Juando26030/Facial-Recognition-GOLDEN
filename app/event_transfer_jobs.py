"""Exportar / importar eventos EN SEGUNDO PLANO, con progreso (docs/18_EXPORTAR_EVENTOS.md, F4). Mismo patrón que `app/report_jobs.py`: un hilo del propio servicio arma el trabajo (un
evento grande no cabe en los 60 s por petición de Firebase Hosting) y el navegador consulta el avance. El seguimiento vive en `event_transfer_log` (columnas de la migración 0075).

  - Exportar: el .zip se guarda en el almacenamiento (`transfers/<cliente>/<n>.zip`), se descarga con una URL FIRMADA de vida corta y se BORRA a las 24 h (paso `reports` del Job de ops).
  - Importar: el paquete llega por subida directa (`app/uploads.py`, propósito `event_package`), se valida («inspeccionar»), se hace el simulacro y, si todo está bien, la importación de
    verdad; el paquete subido se borra al terminar. La frase de transporte de la biometría SOLO existe en memoria durante el trabajo: nunca se guarda ni se loguea.
Nada de esto escribe datos personales en los logs: solo conteos."""
import json
import logging
import os
import threading
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app import event_transfer, uploads
from app.database import SessionLocal
from app.models import Event, EventTransferLog
from app.storage import get_storage, key_of
from app.timeutil import utcnow

log = logging.getLogger("golden.event_transfer")
TTL = timedelta(hours=int(os.getenv("EVENT_TRANSFER_TTL_HOURS", "24")))
START_WAIT = float(os.getenv("EVENT_TRANSFER_START_WAIT", "8"))


def _spawn(fn, *args) -> None:
    """Hilo del propio servicio (en las pruebas, EVENT_TRANSFER_INLINE=1 lo corre a la vista). Espera como mucho START_WAIT s a que termine: lo normal con eventos chicos."""
    if os.getenv("EVENT_TRANSFER_INLINE") == "1":
        fn(*args)
        return
    t = threading.Thread(target=fn, args=args, daemon=True, name="event-transfer")
    t.start()
    t.join(START_WAIT)


def _progress(job_id: int):
    """Callback de avance con su PROPIA sesión (no toca la transacción del trabajo)."""
    def cb(stage: str, pct: int) -> None:
        s = SessionLocal()
        try:
            s.query(EventTransferLog).filter(EventTransferLog.id == job_id).update({"stage": stage[:60], "progress": max(0, min(100, int(pct)))})
            s.commit()
        except Exception:  # noqa: BLE001 — el avance es cosmético
            s.rollback()
        finally:
            s.close()
    return cb


def _finish(job_id: int, status: str, result: dict, file_key: Optional[str] = None, event_id: Optional[int] = None, event_code: Optional[str] = None) -> None:
    s = SessionLocal()
    try:
        row = s.get(EventTransferLog, job_id)
        row.status, row.result_json, row.finished_at = status, json.dumps(result, ensure_ascii=False), utcnow()
        if status == "done":
            row.progress = 100
        if file_key:
            row.file_key = file_key
        if event_id:
            row.event_id = event_id
        if event_code:
            row.event_code = event_code
        s.commit()
    finally:
        s.close()


# ------------------------------------------------------------------------------------------------ exportar
def start_export(db: Session, staff, event: Event, *, include_biometrics: bool, passphrase: Optional[str]) -> int:
    if include_biometrics and len(passphrase or "") < event_transfer.MIN_PASSPHRASE:
        raise event_transfer.TransferError(f"La frase de transporte debe tener al menos {event_transfer.MIN_PASSPHRASE} caracteres.")
    job = EventTransferLog(kind="job_export", staff_username=staff.username, event_id=event.id, event_code=event.event_code, status="running", stage="Preparando", progress=0,
                           options_json=json.dumps({"include_biometrics": bool(include_biometrics)}))
    db.add(job)
    db.commit()
    _spawn(_run_export, job.id, event.id, bool(include_biometrics), passphrase if include_biometrics else None, staff.username)
    return job.id


def _run_export(job_id: int, event_id: int, include_biometrics: bool, passphrase: Optional[str], username: str) -> None:
    s = SessionLocal()
    try:
        event = s.get(Event, event_id)
        data, manifest = event_transfer.export_event(s, event, staff_username=username, include_biometrics=include_biometrics, passphrase=passphrase, progress=_progress(job_id))
        key = key_of("transfers", event.tenant_id, f"{job_id}.zip")
        get_storage().put(key, data)
        _finish(job_id, "done", {"counts": {k: v["count"] for k, v in manifest["tables"].items()}, "files": len(manifest["files"]), "warnings": manifest["warnings"][:20],
                                 "size": len(data), "biometrics": include_biometrics, "filename": f"evento_{event.event_code}.zip"}, file_key=key)
    except Exception as e:  # noqa: BLE001
        s.rollback()
        log.exception("event_export job=%s falló", job_id)
        _finish(job_id, "error", {"error": str(e) if isinstance(e, event_transfer.TransferError) else "No se pudo generar el paquete. Vuelve a intentarlo."})
    finally:
        s.close()


# ------------------------------------------------------------------------------------------------ importar
def package_scope(staff) -> dict:
    return {"u": staff.id}


def read_uploaded(token: str, staff) -> bytes:
    up = uploads.fetch(token, "event_package", package_scope(staff))
    if up is None:
        raise event_transfer.TransferError("Falta el paquete: súbelo primero.")
    return up.content


def inspect(token: str, staff) -> dict:
    """Valida el paquete subido (formato, versión, huellas) y resume qué trae, sin escribir nada."""
    data = read_uploaded(token, staff)
    manifest, rows, _ = event_transfer.read_package(data)
    ev = rows["events"][0]
    return {"event_code": ev.get("event_code"), "name": ev.get("name"), "status": ev.get("status"), "tenant": manifest.get("tenant"), "source_env": manifest.get("source_env"),
            "created_at": manifest.get("created_at"), "counts": {k: v["count"] for k, v in manifest["tables"].items()}, "files": len(manifest.get("files", [])),
            "has_biometrics": "biometrics" in manifest["tables"], "warnings": manifest.get("warnings", [])[:20], "alembic_revision": manifest.get("alembic_revision")}


def start_import(db: Session, staff, *, token: str, dry_run: bool, new_event_code: Optional[str], new_name: Optional[str], target_tenant_id: Optional[str],
                 keep_original_state: bool, import_biometrics: bool, passphrase: Optional[str]) -> int:
    uploads.read_token(token)                                      # token válido y vigente (400 si no)
    job = EventTransferLog(kind="job_import", staff_username=staff.username, event_code=new_event_code, status="running", stage="Leyendo el paquete", progress=0,
                           options_json=json.dumps({"dry_run": dry_run, "keep_original_state": keep_original_state, "import_biometrics": import_biometrics, "tenant": target_tenant_id}))
    db.add(job)
    db.commit()
    _spawn(_run_import, job.id, token, staff.id, staff.username, dry_run, new_event_code, new_name, target_tenant_id, keep_original_state, import_biometrics, passphrase)
    return job.id


def _run_import(job_id: int, token: str, staff_id: int, username: str, dry_run: bool, code, name, tenant, keep_state: bool, import_bio: bool, passphrase) -> None:
    s = SessionLocal()
    try:
        class _Who:                                                # lo mínimo de «staff» que usa uploads (alcance del token)
            id = staff_id
        data = read_uploaded(token, _Who)
        report = event_transfer.import_package(s, data, staff_username=username, new_event_code=code, new_name=name, keep_original_state=keep_state, dry_run=dry_run,
                                               target_tenant_id=tenant, transport_passphrase=passphrase, import_biometrics=import_bio, progress=_progress(job_id))
        if report.get("ok") and not dry_run:
            report["fidelity"] = event_transfer.fidelity_report(s, report["event_id"], data, report)
        _finish(job_id, "done" if report.get("ok") else "error", report, event_id=report.get("event_id") if not dry_run else None, event_code=report.get("event_code"))
        if not dry_run and report.get("ok"):
            _discard_upload(token)
    except Exception as e:  # noqa: BLE001
        s.rollback()
        log.exception("event_import job=%s falló", job_id)
        _finish(job_id, "error", {"error": str(e) if isinstance(e, event_transfer.TransferError) else "No se pudo importar el paquete. No se creó nada. Vuelve a intentarlo."})
    finally:
        s.close()


def _discard_upload(token: str) -> None:
    try:
        key = uploads.read_token(token).get("k")
        if key:
            get_storage().delete(key)
    except Exception:  # noqa: BLE001
        log.warning("no se pudo borrar el paquete subido")


# ------------------------------------------------------------------------------------------------ consultar, descargar y purgar
def status(db: Session, job_id: int) -> Optional[dict]:
    row = db.get(EventTransferLog, job_id)
    if not row or not row.kind.startswith("job_"):
        return None
    return {"id": row.id, "kind": row.kind, "status": row.status, "stage": row.stage, "progress": row.progress, "result": json.loads(row.result_json) if row.result_json else None,
            "ready": bool(row.file_key) and row.status == "done", "event_id": row.event_id if row.kind == "job_import" else None, "started_at": row.created_at.isoformat()}


def history(db: Session, limit: int = 40) -> list:
    """Bitácora: quién, cuándo, qué evento y conteos. SIN datos personales."""
    rows = db.query(EventTransferLog).filter(EventTransferLog.kind.in_(("export", "import"))).order_by(EventTransferLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "at": r.created_at.isoformat(), "kind": r.kind, "by": r.staff_username, "event_id": r.event_id, "event_code": r.event_code, "status": r.status,
             "rows": sum(json.loads(r.counts_json or "{}").values()) if r.counts_json else None, "pending_confirm": r.status == "pending_confirm"} for r in rows]


def purge_expired(db: Session) -> int:
    """Borra del almacenamiento los paquetes generados hace más de TTL (24 h) y marca la tarea. Lo corre el paso `reports` del Job de ops."""
    cut = utcnow() - TTL
    n = 0
    for row in db.query(EventTransferLog).filter(EventTransferLog.kind == "job_export", EventTransferLog.file_key.isnot(None), EventTransferLog.finished_at < cut).all():
        try:
            get_storage().delete(row.file_key)
        except Exception:  # noqa: BLE001 — se reintenta en la siguiente pasada
            log.warning("no se pudo borrar un paquete vencido", exc_info=True)
            continue
        row.file_key, row.result_json = None, json.dumps({"expired": True})
        n += 1
    if n:
        db.commit()
    return n
