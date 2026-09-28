"""Job de operaciones de Cloud Run (`python -m app.ops_runner <tarea>`, misma imagen). Reemplaza los 4 cron de la VM con UNA tarea de Cloud
Scheduler (cabe en las 3 gratuitas): cada hora al minuto 05, hora de Bogotá, corre `hourly`.

  hourly         respaldo de la base (cada hora) · a las OPS_DAILY_HOUR (3) también el diario · a las OPS_PURGE_HOUR (4) la purga biométrica
                 · revisión de respaldos · cola de trabajos pendiente · precalentamiento. Cada paso va aislado: si uno falla los demás
                 corren igual, y el Job termina con código 1 (la alerta de Cloud Monitoring avisa de ejecuciones fallidas).
  backup | backup-daily | purge | check-backups | sweep | warmup      cada paso suelto, para correrlo a mano:
                 gcloud run jobs execute golden-ops-<entorno> --region <región> --args=-m,app.ops_runner,backup

Respaldos: `pg_dump` 18 con el DUEÑO (DIRECT_DATABASE_URL), `--no-owner --no-privileges` (se restaura en cualquier Postgres; en Neon con
scripts/migrate_db_to_neon.py --source-dump), comprimido, verificado (gzip íntegro + marca de volcado completo) y subido con MD5 a
gs://<BACKUP_BUCKET>/db/hourly|daily/AAAA/MM/golden_db_AAAAmmdd_HHMM.sql.gz. Retención por ciclo de vida del bucket
(deploy/gcs-lifecycle.json): horarios 3 días, diarios 60. Los archivos (fotos, firmas…) no se copian: viven en el bucket de la app con
versiones de objeto (lo borrado o sobrescrito se conserva 30 días). Los secretos viven versionados en Secret Manager.
Avisos por correo a ALERT_EMAIL como máximo cada 6 h por el mismo problema."""
import gzip
import json
import logging
import os
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

log = logging.getLogger("golden.ops")
MARK = b"PostgreSQL database dump complete"


def _bucket():
    from google.cloud import storage as gcs
    return gcs.Client().bucket(os.environ["BACKUP_BUCKET"])


def _local_now() -> datetime:
    from app.timeutil import to_local
    return to_local(datetime.utcnow())


# ------------------------------------------------------------------ respaldos
def backup_db(kind: str = "hourly", bucket=None, now=None) -> str:
    from scripts.migrate_db_to_neon import libpq_env, tool
    now, bucket = now or _local_now(), bucket or _bucket()
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ["DATABASE_URL"]
    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
        path = tmp.name
    try:
        with gzip.open(path, "wb") as out:
            dump = subprocess.Popen(tool("PG_DUMP", "pg_dump") + ["--no-owner", "--no-privileges", "--format=plain"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=libpq_env(url))
            for chunk in iter(lambda: dump.stdout.read(1 << 20), b""):
                out.write(chunk)
            err = dump.stderr.read()
        if dump.wait() != 0:
            raise RuntimeError("pg_dump falló: " + err.decode("utf8", "replace")[-300:])
        with gzip.open(path, "rb") as check:                  # recorre todo el archivo: un gzip cortado falla aquí
            tail = b""
            for chunk in iter(lambda: check.read(1 << 20), b""):
                tail = (tail + chunk)[-4096:]
        if MARK not in tail:
            raise RuntimeError("el volcado no terminó (falta la marca de volcado completo)")
        name = f"db/{kind}/{now:%Y/%m}/golden_db_{now:%Y%m%d_%H%M}.sql.gz"
        bucket.blob(name).upload_from_filename(path, content_type="application/gzip", checksum="md5")
        return f"{name} ({os.path.getsize(path) / 1024:.0f} KB)"
    finally:
        os.remove(path)


def backup_problems(bucket=None, now=None) -> dict:
    """Problemas de los respaldos en el bucket: ninguno, viejo o sospechosamente pequeño."""
    bucket, now = bucket or _bucket(), now or datetime.now(timezone.utc)
    limits = {"hourly": float(os.getenv("BACKUP_HOURLY_MAX_AGE_H", "2")), "daily": float(os.getenv("BACKUP_DAILY_MAX_AGE_H", "26"))}
    found = {}
    for kind, max_age in limits.items():
        blobs = sorted((b for b in bucket.client.list_blobs(bucket, prefix=f"db/{kind}/") if b.name.endswith(".sql.gz")), key=lambda b: b.updated)
        if not blobs:
            found[f"{kind}-none"] = f"No hay respaldos {kind} en gs://{bucket.name}/db/{kind}/."
            continue
        last = blobs[-1]
        age = (now - last.updated).total_seconds() / 3600
        if age > max_age:
            found[f"{kind}-old"] = f"El último respaldo {kind} tiene {age:.1f} h ({last.name}); debería tener menos de {max_age:g} h."
        sizes = [b.size for b in blobs[-25:-1]]
        if len(sizes) >= 5 and last.size < 0.5 * statistics.median(sizes):
            found[f"{kind}-small"] = f"El último respaldo {kind} pesa {last.size} bytes y lo normal es ~{int(statistics.median(sizes))}: puede estar vacío o cortado."
    return found


def check_backups(bucket=None, now=None) -> str:
    found = backup_problems(bucket, now)
    if found:
        raise RuntimeError("; ".join(found.values()))        # el Job falla y main() avisa por correo
    return "respaldos al día"


def _alert(key: str, subject: str, body: str) -> None:
    """Correo a ALERT_EMAIL, como máximo una vez cada REALERT_H (6) horas por clave (constancia en system_events)."""
    from app import ops
    from app.database import SessionLocal
    from app.models import SystemEvent
    email = os.getenv("ALERT_EMAIL", "").strip()
    if not email:
        return
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=float(os.getenv("REALERT_H", "6")))
        if db.query(SystemEvent.id).filter(SystemEvent.kind == "ops_alert", SystemEvent.ref == key, SystemEvent.at > since).first():
            return
    finally:
        db.close()
    from app.mailer import send_mail
    send_mail(email, subject, body)
    ops.record_system_event("ops_alert", key, subject)


# ------------------------------------------------------------------ otros pasos
def purge() -> str:
    from app import privacy
    from app.database import SessionLocal
    days = privacy.retention_days()
    if not days:
        return "retención apagada (BIOMETRIC_RETENTION_DAYS=0)"
    db = SessionLocal()
    try:
        return json.dumps(privacy.purge_expired(db, days))
    finally:
        db.close()


def sweep() -> str:
    from app import formsvc, jobs, reconcile  # noqa: F401 — registran sus trabajos
    return f"{jobs.drain()} trabajo(s) pendiente(s) ejecutado(s)"


def warmup() -> str:
    from app import warmup as w
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        p = w.plan(db)
    finally:
        db.close()
    changes = w.apply(p)
    return f"{'; '.join(changes) or 'sin cambios'} · {json.dumps(p['why'])}"


def hourly(now=None) -> dict:
    now = now or _local_now()
    steps = [("backup", lambda: backup_db("hourly", now=now))]
    if now.hour == int(os.getenv("OPS_DAILY_HOUR", "3")):
        steps.append(("backup-daily", lambda: backup_db("daily", now=now)))
    if now.hour == int(os.getenv("OPS_PURGE_HOUR", "4")):
        steps.append(("purge", purge))
    steps += [("check-backups", check_backups), ("sweep", sweep), ("warmup", warmup)]
    results = {}
    for name, fn in steps:
        try:
            results[name] = {"ok": True, "detail": fn()}
        except Exception as e:  # noqa: BLE001 — un paso fallido no detiene los demás
            log.error("paso %s falló", name, exc_info=True)
            results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return results


TASKS = {"backup": lambda: backup_db("hourly"), "backup-daily": lambda: backup_db("daily"), "purge": purge,
         "check-backups": check_backups, "sweep": sweep, "warmup": warmup}


def main(task: str) -> int:
    if task == "hourly":
        results = hourly()
    elif task in TASKS:
        try:
            results = {task: {"ok": True, "detail": TASKS[task]()}}
        except Exception as e:  # noqa: BLE001
            log.error("tarea %s falló", task, exc_info=True)
            results = {task: {"ok": False, "detail": f"{type(e).__name__}: {e}"}}
    else:
        print(f"Tarea desconocida: {task}. Usa: hourly, {', '.join(TASKS)}")
        return 2
    print(json.dumps({"ops": task, "results": results}, ensure_ascii=False))
    failed = [k for k, v in results.items() if not v["ok"]]
    if failed:
        _alert(f"ops-{'-'.join(failed)}", f"[Golden] ⚠️ Falló la tarea de operaciones: {', '.join(failed)}",
               "\n".join(f"- {k}: {results[k]['detail']}" for k in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    from app.obs import configure_logging
    configure_logging()
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hourly"))
