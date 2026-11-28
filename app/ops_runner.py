"""Job de operaciones de Cloud Run (`python -m app.ops_runner <tarea>`, misma imagen). Reemplaza los 4 cron de la VM con UNA tarea de Cloud
Scheduler (cabe en las 3 gratuitas): cada hora al minuto 05, hora de Bogotá, corre `hourly`.

  hourly         TAREA ECONÓMICA (economic(), 10-nov-2026): cada paso decide por el tiempo desde su última ejecución buena (ops/steps.json) y la base solo se toca si hay actividad, eventos cerca o un paso vence; el Scheduler puede
                 avisar cada 1 o 2 h (OPS_MIN_INTERVAL_MINUTES). Detalle y reglas en docs/FASE_10_AJUSTES_NOV10.md (Costos). `hourly-full` corre la versión antigua (todo según la hora):
                 respaldo de la base (cada hora) · a las OPS_DAILY_HOUR (3) también el diario · a las OPS_PURGE_HOUR (4) la purga biométrica
                 · revisión de respaldos · cola de trabajos pendiente · precalentamiento · y SOLO los domingos a las OPS_WEEKLY_HOUR (5) el archivado de la base de los eventos a los 90 días (L7). Cada paso va aislado: si uno falla los demás
                 corren igual, y el Job termina con código 1 (la alerta de Cloud Monitoring avisa de ejecuciones fallidas).
  db-health      chequeo de salud de la base de Neon (domingos 6 a. m.): avisa y reinicia el cómputo si ve riesgo de colapso, sin borrar datos (app/db_health.py)
  backup | backup-daily | purge | archive-events | check-backups | sweep | warmup      cada paso suelto, para correrlo a mano:
                 gcloud run jobs execute golden-ops-<entorno> --region <región> --args=-m,app.ops_runner,backup

Respaldos: `pg_dump` 18 con el DUEÑO (DIRECT_DATABASE_URL), `--no-owner --no-privileges` (se restaura en cualquier Postgres; en Neon con
scripts/migrate_db_to_neon.py --source-dump), comprimido, verificado (gzip íntegro + marca de volcado completo) y subido con MD5 a
gs://<BACKUP_BUCKET>/db/hourly|daily/AAAA/MM/golden_db_AAAAmmdd_HHMM.sql.gz. Retención por ciclo de vida del bucket
(deploy/gcs-lifecycle.json): horarios 3 días, diarios 30 (antes 60; los respaldos guardan el encoding cifrado, ver docs/15). Los archivos (fotos, firmas…) no se copian: viven en el bucket de la app con
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
import time
from datetime import datetime, timedelta, timezone
from app.timeutil import utcnow

log = logging.getLogger("golden.ops")
MARK = b"PostgreSQL database dump complete"


def _reason(e: Exception) -> str:
    """Motivo corto del fallo para el campo `message` del log (Cloud Logging: `--format='value(jsonPayload.message)'`); el traceback sigue en stack_trace."""
    return f"{type(e).__name__}: {e}"[:400]


def _bucket():
    from google.cloud import storage as gcs
    return gcs.Client().bucket(os.environ["BACKUP_BUCKET"])


def _local_now() -> datetime:
    from app.timeutil import to_local
    return to_local(utcnow())


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


def _scan_backups(bucket, now) -> tuple:
    """(problemas, avisos). Un entorno recién creado aún no tiene su primer respaldo diario (corre a las OPS_DAILY_HOUR): mientras el
    respaldo más viejo del bucket tenga menos de BACKUP_DAILY_MAX_AGE_H horas, que falte el diario es un AVISO, no un problema. Sin
    respaldos horarios, o con el diario ausente pasado ese plazo, sigue siendo problema (la alarma real no se debilita)."""
    limits = {"hourly": float(os.getenv("BACKUP_HOURLY_MAX_AGE_H", "2")), "daily": float(os.getenv("BACKUP_DAILY_MAX_AGE_H", "26"))}
    found, warned, listed = {}, {}, {}
    for kind, max_age in limits.items():
        blobs = sorted((b for b in bucket.client.list_blobs(bucket, prefix=f"db/{kind}/") if b.name.endswith(".sql.gz")), key=lambda b: b.updated)
        listed[kind] = blobs
        if not blobs:
            msg = f"No hay respaldos {kind} en gs://{bucket.name}/db/{kind}/."
            hourly = listed.get("hourly")
            if kind == "daily" and hourly and (now - hourly[0].updated).total_seconds() / 3600 <= max_age:
                warned["daily-none"] = msg + " Entorno nuevo: llegará a las %s:00 (o corre `backup-daily` una vez)." % os.getenv("OPS_DAILY_HOUR", "3")
            else:
                found[f"{kind}-none"] = msg
            continue
        last = blobs[-1]
        age = (now - last.updated).total_seconds() / 3600
        if age > max_age:
            found[f"{kind}-old"] = f"El último respaldo {kind} tiene {age:.1f} h ({last.name}); debería tener menos de {max_age:g} h."
        sizes = [b.size for b in blobs[-25:-1]]
        if len(sizes) >= 5 and last.size < 0.5 * statistics.median(sizes):
            found[f"{kind}-small"] = f"El último respaldo {kind} pesa {last.size} bytes y lo normal es ~{int(statistics.median(sizes))}: puede estar vacío o cortado."
    return found, warned


def backup_problems(bucket=None, now=None) -> dict:
    """Problemas de los respaldos en el bucket: ninguno, viejo o sospechosamente pequeño."""
    return _scan_backups(bucket or _bucket(), now or datetime.now(timezone.utc))[0]


def check_backups(bucket=None, now=None) -> str:
    found, warned = _scan_backups(bucket or _bucket(), now or datetime.now(timezone.utc))
    if found:
        raise RuntimeError("; ".join(found.values()))        # el Job falla y main() avisa por correo
    return "; ".join(["respaldos al día", *warned.values()]) if warned else "respaldos al día"


def offsite_copy() -> str:
    """Fase 9-B: copia semanal CIFRADA del respaldo más reciente a OneDrive (app/offsite_copy.py). Sin variables de OneDrive no hace nada; si falla o pasan >10 días, el paso falla y main() avisa."""
    from app import offsite_copy as oc
    return oc.run()


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
        since = utcnow() - timedelta(hours=float(os.getenv("REALERT_H", "6")))
        if db.query(SystemEvent.id).filter(SystemEvent.kind == "ops_alert", SystemEvent.ref == key, SystemEvent.at > since).first():
            return
    finally:
        db.close()
    from app.mailer import send_mail
    send_mail(email, subject, body)
    ops.record_system_event("ops_alert", key, subject)


# ------------------------------------------------------------------ otros pasos
def _load_handlers() -> None:
    """Registra en este proceso TODOS los manejadores de la cola general (cada módulo los registra al importarse). Los de rostro NO: esos trabajos van por su
    propia cola, en el servicio de biometría (2 CPU), y el barrido los excluye. Lo comprueba tests/test_trabajos_huerfanos.py."""
    from app import jobs
    jobs.load_handlers(jobs.GENERAL_KINDS)


def purge() -> str:
    """Retención biométrica (app/privacy.py): solo conteos en el resultado y en el log. Con errores el paso FALLA (alerta) y se reintenta la hora siguiente."""
    from app import acceptmail, formsvc, privacy, sessions
    _load_handlers()
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        r = privacy.purge_expired(db)
        r["mail_log_rows"] = acceptmail.purge_log(db)       # registro de envíos de enlaces personales (misma retención que lo biométrico)
        r["session_audit_rows"] = sessions.purge_audit(db)     # auditoría de sesiones cerradas/rechazadas/forzadas: 90 días (Ley 1581)
        r["sensitive_rows"] = formsvc.purge_sensitive(db)      # respuestas sensibles del compromiso del digitador: FORM_PLEDGE_HEALTH_RETENTION_DAYS (30) después de finalizado el evento
    finally:
        db.close()
    log.info("purga biométrica: %s", json.dumps(r))
    if r["errors"]:
        raise RuntimeError(f"la purga biométrica tuvo {r['errors']} error(es) al borrar fotos (se reintenta en la próxima corrida): {json.dumps(r)}")
    return json.dumps(r)


UNHANDLED_ALERT_WINDOW = timedelta(minutes=65)          # un trabajo sin manejador se avisa en el primer barrido después de crearse (no cada hora)


def sweep() -> str:
    """Ejecuta la cola general. FALLA (y así main() avisa por correo y el Job sale con 1) si en ESTE barrido algún trabajo pasó a «failed», o si apareció
    un trabajo nuevo de un tipo sin manejador (se queda en cola, sin gastar intentos). Solo lo nuevo: un fallo viejo no se vuelve a avisar cada hora."""
    from sqlalchemy import func

    from app import jobs
    from app.database import SessionLocal
    from app.models import Job
    _load_handlers()
    started = utcnow()
    ran = jobs.drain(exclude=jobs.FACE_KINDS)                 # los cálculos faciales NO corren aquí (este Job no tiene el manejador ni la CPU): van por su cola, en el servicio de biometría
    with SessionLocal() as db:
        faces_due = db.query(func.count(Job.id)).filter(Job.kind.in_(list(jobs.FACE_KINDS)), Job.status.in_(("queued", "running")), Job.run_at <= utcnow()).scalar() or 0
        failed_now = [(i, k) for i, k in db.query(Job.id, Job.kind).filter(Job.status == "failed", Job.finished_at >= started).order_by(Job.id).all()]
        orphans = jobs.unhandled_due(db, since=started - UNHANDLED_ALERT_WINDOW)
    if faces_due:
        jobs.kick(pool="faces")                               # el barrido horario despierta a la cola facial por si una tarea de Cloud Tasks se perdió
    detail = f"{ran} trabajo(s) pendiente(s) ejecutado(s); {faces_due} cálculo(s) facial(es) pendiente(s) avisados a su cola"
    problems = []
    if failed_now:                                            # solo tipo e id: ningún dato de la persona
        problems.append(f"{len(failed_now)} trabajo(s) fallaron en este barrido: " + ", ".join(f"{k}#{i}" for i, k in failed_now[:20]))
    if orphans:
        problems.append(f"{len(orphans)} trabajo(s) sin manejador en el Job (siguen en cola, sin gastar intentos): " + ", ".join(f"{k}#{i}" for i, k in orphans[:20]))
    if problems:
        raise RuntimeError(f"{'; '.join(problems)}. ({detail})")
    return detail


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


def archive_events() -> str:
    """L7 (Fase 3): archiva la BASE DE DATOS de los eventos finalizados con 90 días o más desde su cierre (el evento sigue en las listas; app/event_archive.py). Idempotente, NUNCA borra, registra en audit_actions
    con actor NULL (sistema). Solo conteos en el resultado. Corre UNA vez por semana (OPS_WEEKLY_DAY / OPS_WEEKLY_HOUR); si algún evento falla el paso FALLA (alerta) y se reintenta la semana siguiente (o a mano: `archive-events`)."""
    from app import event_archive
    from app.database import SessionLocal
    with SessionLocal() as db:
        r = event_archive.auto_archive_due(db)
    log.info("archivado automático de eventos: %s", json.dumps(r))
    if r["errors"]:
        raise RuntimeError(f"el archivado automático tuvo {r['errors']} error(es) (se reintenta en la próxima corrida semanal): {json.dumps(r)}")
    return json.dumps(r)


def purge_reports() -> str:
    """Borra los reportes Excel de Estadísticas que ya vencieron (duran una hora; ver app/report_jobs.py) y los paquetes de exportar evento de más de 24 h (app/event_transfer_jobs.py)."""
    from app.database import SessionLocal
    from app import bulk_steps, event_transfer_jobs
    from app.report_jobs import purge_expired
    with SessionLocal() as db:
        return (f"{purge_expired(db)} reporte(s) vencido(s), {bulk_steps.purge_expired(db)} carga(s) abandonada(s) y "
                f"{event_transfer_jobs.purge_expired(db)} paquete(s) de evento (a las 24 h) borrados")


def import_infra_costs() -> str:
    """Fase 9C: importa de la exportación de facturación de Google (BigQuery) el costo neto del mes en curso y del anterior a `infra_costs`. OPCIONAL: sin GCP_BILLING_EXPORT_TABLE no hace
    nada. Corre UNA vez por semana (OPS_INFRA_WEEKDAY, por defecto 6 = domingo, a las OPS_INFRA_HOUR, por defecto las 12 del día, hora local) o a mano (botón «Importar Google ahora» / `infra-costs-import`); no consulta nada más de seguido. Solo conteos en el resultado."""
    from app import infra_costs
    from app.database import SessionLocal
    with SessionLocal() as db:
        r = infra_costs.import_google(db)
    if not r["configured"]:
        return "importación de Google apagada (sin GCP_BILLING_EXPORT_TABLE)"
    return f"Google: {r['imported']} gasto(s) nuevo(s), {r['updated']} actualizado(s), {len(r['warnings'])} aviso(s)"


def db_health() -> str:
    """20-nov-2026: chequeo semanal de salud de la base de Neon; si ve riesgo de colapso avisa y reinicia el cómputo (nunca borra datos). Ver app/db_health.py."""
    from app import db_health as h
    return h.run()


def hourly(now=None) -> dict:
    now = now or _local_now()
    steps = [("backup", lambda: backup_db("hourly", now=now))]
    if now.hour == int(os.getenv("OPS_DAILY_HOUR", "3")):
        steps.append(("backup-daily", lambda: backup_db("daily", now=now)))
    if now.hour == int(os.getenv("OPS_PURGE_HOUR", "4")):
        steps.append(("purge", purge))
    if now.weekday() == int(os.getenv("OPS_WEEKLY_DAY", "6")) and now.hour == int(os.getenv("OPS_WEEKLY_HOUR", "5")):
        steps.append(("archive-events", archive_events))          # L7: UNA vez por semana (domingo 5 a. m.), para no despertar la base de Neon cada hora
    if os.getenv("GCP_BILLING_EXPORT_TABLE", "").strip() and now.weekday() == int(os.getenv("OPS_INFRA_WEEKDAY", "6")) and now.hour == int(os.getenv("OPS_INFRA_HOUR", "12")):
        steps.append(("infra-costs", import_infra_costs))          # Fase 9C: UNA vez por semana (domingo 12 m., hora local), y solo si el entorno activó la exportación de Google
    steps += [("check-backups", check_backups), ("offsite-copy", offsite_copy), ("sweep", sweep), ("reports", purge_reports), ("warmup", warmup)]
    results = {}
    for name, fn in steps:
        try:
            results[name] = {"ok": True, "detail": fn()}
        except Exception as e:  # noqa: BLE001 — un paso fallido no detiene los demás
            log.error("paso %s falló: %s", name, _reason(e), exc_info=True)
            results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    return results


# ------------------------------------------------------------------ Job económico (10-nov-2026)
PROBE_SQL = """
SELECT
  (SELECT count(*) FROM events WHERE status = 'en_proceso'),
  (SELECT count(*) FROM events WHERE status NOT IN ('en_proceso', 'finalizado')
     AND COALESCE(setup_date, start_date) <= :horizon AND COALESCE(end_date, start_date, setup_date) >= :today),
  (SELECT count(*) FROM jobs WHERE status IN ('queued', 'running') AND run_at <= :now)
"""


def probe(now=None, now_utc=None) -> dict:
    """UNA sola consulta barata (tres conteos en una ida a la base): eventos «en proceso», eventos que empiezan en las próximas OPS_EVENT_LOOKAHEAD_H (6) horas (o ya ocupan hoy sin haber arrancado)
    y trabajos de la cola vencidos. Solo números."""
    from sqlalchemy import text

    from app.database import SessionLocal
    now, now_utc = now or _local_now(), now_utc or utcnow()
    horizon = (now + timedelta(hours=float(os.getenv("OPS_EVENT_LOOKAHEAD_H", "6")))).date()
    with SessionLocal() as db:
        running, near, jobs_due = db.execute(text(PROBE_SQL), {"horizon": horizon, "today": now.date(), "now": now_utc}).one()
    return {"running": int(running), "near": int(near), "jobs_due": int(jobs_due)}


def warmup_down() -> str:
    """Baja a cero las instancias mínimas (y deja a Neon en su apagado normal) SIN tocar la base: solo la API de Cloud Run/Neon. Se usa cuando ya no hay eventos cerca."""
    from app import warmup as w
    changes = w.apply(w.idle_plan())
    return "; ".join(changes) or "sin cambios (ya en reposo)"


def economic(now=None, now_utc=None, steps=None, probe_fn=None) -> dict:
    """Tarea horaria ECONÓMICA: cada paso decide por el tiempo desde su última ejecución buena (ops/steps.json en el almacenamiento, sin base), de modo que el Scheduler puede avisar cada 1 o 2 h sin perder nada.
    Lo primero que toca la base es UNA consulta (`probe`), y solo si hay actividad reciente o toca el turno de reposo (OPS_IDLE_EVERY_H, 4 h). Sin eventos en proceso ni cercanos no hay precalentamiento
    (solo se bajan las instancias si estaban arriba), ni barrido de cola si no hay trabajos vencidos. Reglas que no cambian: respaldo diario y purga biométrica UNA vez al día desde OPS_DAILY_HOUR / OPS_PURGE_HOUR,
    respaldo horario cada ~50 min con actividad y cada OPS_IDLE_BACKUP_H (8) h sin ella, archivado semanal, copia a OneDrive y revisión de respaldos (que no abre la base)."""
    now, now_utc = now or _local_now(), now_utc or utcnow()
    from app import ops_state as S
    steps = S.load_steps() if steps is None else steps
    results, awake = {}, []

    def run(name, fn, key=None):
        try:
            results[name] = {"ok": True, "detail": fn()}
            if key:
                steps[key] = S.stamp(now_utc)
            return True
        except Exception as e:  # noqa: BLE001 — un paso fallido no detiene los demás; al no anotarse, el próximo aviso lo reintenta
            log.error("paso %s falló: %s", name, _reason(e), exc_info=True)
            results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
            return False

    hint = S.recently_active(now_utc)
    info = {"running": 0, "near": 0, "jobs_due": 0}
    if hint or S.due_every(steps, "probe", float(os.getenv("OPS_IDLE_EVERY_H", "4")), now_utc):
        def _probe():
            info.update((probe_fn or probe)(now, now_utc))
            return json.dumps(info)
        if not run("probe", _probe, "probe"):                                  # sin saber, se asume lo peor: todo corre
            info.update(running=1, jobs_due=1)
        awake.append("probe")
    busy = hint or bool(info["running"] or info["near"])

    ran_backup = False
    if S.due_every(steps, "backup", 50 / 60 if busy else float(os.getenv("OPS_IDLE_BACKUP_H", "8")), now_utc):
        ran_backup = run("backup", lambda: backup_db("hourly", now=now), "backup")
        awake.append("backup")
    if S.due_daily(steps, "backup-daily", now, int(os.getenv("OPS_DAILY_HOUR", "3"))):
        ran_backup = run("backup-daily", lambda: backup_db("daily", now=now), "backup-daily") or ran_backup
        awake.append("backup-daily")
    if S.due_daily(steps, "purge", now, int(os.getenv("OPS_PURGE_HOUR", "4"))):
        run("purge", purge, "purge")                    # retención biométrica: una vez al día; con errores NO se anota y el próximo aviso la repite
        awake.append("purge")
    if S.due_weekly(steps, "archive-events", now, int(os.getenv("OPS_WEEKLY_DAY", "6")), int(os.getenv("OPS_WEEKLY_HOUR", "5")), now_utc):
        run("archive-events", archive_events, "archive-events")
        awake.append("archive-events")
    if os.getenv("GCP_BILLING_EXPORT_TABLE", "").strip() and S.due_weekly(steps, "infra-costs", now, int(os.getenv("OPS_INFRA_WEEKDAY", "6")), int(os.getenv("OPS_INFRA_HOUR", "12")), now_utc):
        run("infra-costs", import_infra_costs, "infra-costs")
        awake.append("infra-costs")
    if S.due_weekly(steps, "db-health", now, int(os.getenv("OPS_HEALTH_WEEKDAY", "6")), int(os.getenv("OPS_HEALTH_HOUR", "6")), now_utc):
        run("db-health", db_health, "db-health")                                  # UNA vez por semana (domingo 6 a. m.): salud de la base y, si hace falta, reinicio del cómputo
        awake.append("db-health")
    if ran_backup or S.due_every(steps, "check-backups", 6, now_utc):          # solo lee el bucket: no despierta la base
        run("check-backups", check_backups, "check-backups")
    if S.due_every(steps, "offsite-copy", 6, now_utc):                         # OneDrive + bucket; la copia semanal decide sola si toca
        run("offsite-copy", offsite_copy, "offsite-copy")
    if info["jobs_due"]:                                                       # sin trabajos vencidos no hay barrido (si la sonda falló, jobs_due=1: se barre por seguridad)
        run("sweep", sweep)
    if awake and S.due_every(steps, "reports", float(os.getenv("OPS_REPORTS_EVERY_H", "6")), now_utc):
        run("reports", purge_reports, "reports")                               # solo si la base ya está despierta por otra razón
    if busy:
        run("warmup", warmup)
        steps["warm_up"] = "1"
    elif steps.get("warm_up", "1"):
        if run("warmup-down", warmup_down):
            steps["warm_up"] = ""
    steps["full_run"] = S.stamp(now_utc)
    if results:
        S.save_steps(steps)
    return results


def export_consent() -> str:
    """Atención a una autoridad: exporta los registros de consentimiento de UNA persona (`CONSENT_EXPORT_CEDULA`, y opcional `CONSENT_EXPORT_TENANT`) a un archivo en el almacenamiento
    (`consent-exports/…json`). Solo corre a mano (no está en la tarea horaria). El log y el resultado llevan SOLO la clave del archivo y el conteo, jamás la cédula."""
    from sqlalchemy import select

    from app import consent
    from app.database import SessionLocal
    from app.models import AuditConsentLog
    from app.storage import get_storage
    cedula = os.getenv("CONSENT_EXPORT_CEDULA", "").strip()
    if not cedula:
        raise RuntimeError("Falta CONSENT_EXPORT_CEDULA")
    tenant = os.getenv("CONSENT_EXPORT_TENANT", "").strip()
    h = consent.cedula_hash(cedula)
    with SessionLocal() as db:
        q = select(AuditConsentLog).where(AuditConsentLog.cedula_hash == h).order_by(AuditConsentLog.consent_timestamp_utc)
        if tenant:
            q = q.where(AuditConsentLog.tenant_id == tenant)
        rows = [{c.name: (getattr(r, c.name).isoformat() if hasattr(getattr(r, c.name), "isoformat") else getattr(r, c.name)) for c in AuditConsentLog.__table__.columns} for r in db.execute(q).scalars()]
    key = f"consent-exports/{h[:16]}-{utcnow():%Y%m%dT%H%M%S}.json"
    get_storage().put(key, json.dumps(rows, ensure_ascii=False, indent=1).encode("utf-8"))
    return f"{len(rows)} registros en {key}"


def bench_vector() -> str:
    """Mide cuánto tarda calcular el vector facial con 10 y 25 jitters EN ESTE ENTORNO (CPU y memoria del Job o servicio donde corre). Imagen SINTÉTICA generada aquí (ruido determinista, sin
    datos personales) con la ubicación del rostro dada: así no depende de detectar un rostro y mide justo lo que cuesta los jitters (la detección, ~decenas de ms, no entra).
    Variables: BENCH_REPS (por defecto 5). Imprime solo tiempos y los recursos visibles; nada personal. Correr con: gcloud run jobs execute <job> --args=-m,app.ops_runner,bench-vector"""
    import numpy as np

    from app.biometrics import _fr
    fr = _fr()
    reps = max(2, int(os.getenv("BENCH_REPS", "5")))
    img = np.random.default_rng(7).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    box = [(80, 440, 400, 160)]                                             # (arriba, derecha, abajo, izquierda): un recuadro del tamaño de un rostro cercano
    out = {"cpus": os.cpu_count(), "reps": reps}
    for jitters in (10, 25):
        fr.face_encodings(img, known_face_locations=box, num_jitters=1)       # calentamiento (carga de modelos): no cuenta
        times = []
        for _ in range(reps):
            t0 = time.perf_counter()
            fr.face_encodings(img, known_face_locations=box, num_jitters=jitters)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        out[f"jitters_{jitters}_ms"] = {"min": round(times[0]), "mediana": round(statistics.median(times)), "max": round(times[-1])}
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            out["memoria_limite"] = f.read().strip()
    except OSError:
        pass
    return json.dumps(out)


def list_minors() -> str:
    """Revisión (L3): personas con fecha de nacimiento que da MENOS de 18 años y que aún tienen vector o foto. NO borra nada: deja un archivo `minors-review/…json` (cédulas) en el almacenamiento para que
    una persona lo revise y decida; el resultado solo lleva el conteo y la clave del archivo. Los menores quedan además con `is_biometric_enabled=false` (no se reconocen)."""
    from app import minors
    from app.database import SessionLocal
    from app.models import User
    from app import enroll
    from app.storage import get_storage
    found = []
    with SessionLocal() as db:
        for u in db.query(User.id, User.tenant_id, User.birth_date, User.face_encoding).filter(User.birth_date.isnot(None)).yield_per(500):
            if minors.is_minor(u.birth_date) and (u.face_encoding or enroll.has_any_photo(u.tenant_id, u.id)):
                found.append({"tenant": u.tenant_id, "id": u.id})
    if not found:
        return "0 menores con datos biométricos"
    key = f"minors-review/{utcnow():%Y%m%dT%H%M%S}.json"
    get_storage().put(key, json.dumps(found, ensure_ascii=False, indent=1).encode("utf-8"))
    return f"{len(found)} menores con datos biométricos en {key}"


def export_person_data() -> str:
    """Atención de una consulta de habeas data: dada una cédula (`EXPORT_CEDULA`), lista QUÉ datos hay de esa persona (mapa de datos: qué campos tienen dato y cuántos registros hay en eventos, accesos,
    formularios, pagos y consentimientos), SIN biometría ni valores personales. La salida es solo este texto: no se guarda en ningún archivo ni tabla y no lleva la cédula."""
    from sqlalchemy import text

    from app import consent, enroll, minors
    from app.database import SessionLocal
    from app.models import User
    cedula = os.getenv("EXPORT_CEDULA", "").strip()
    if not cedula:
        raise RuntimeError("Falta EXPORT_CEDULA")
    h = consent.cedula_hash(cedula)
    out = {"personas": [], "suprimida": False}
    with SessionLocal() as db:
        p = {"u": cedula}
        for u in db.query(User).filter(User.id == cedula).all():
            fields = [c for c in ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1", "opt_2", "extra_fields", "birth_date") if getattr(u, c)]
            out["personas"].append({"campos_con_dato": fields, "tiene_vector_facial": bool(u.face_encoding), "tiene_foto": enroll.has_any_photo(u.tenant_id, u.id),
                                    "es_menor": minors.is_minor(u.birth_date), "biometria_habilitada": u.is_biometric_enabled})
        count = lambda sql: db.execute(text(sql), p).scalar() or 0       # noqa: E731
        out["eventos_inscrito"] = count("SELECT count(*) FROM event_attendees WHERE user_id = :u")
        out["ingresos"] = count("SELECT count(*) FROM access_logs WHERE user_id = :u")
        out["impresiones_de_escarapela"] = count("SELECT count(*) FROM print_logs WHERE user_id = :u")
        out["movimientos_de_areas"] = count("SELECT count(*) FROM area_movements WHERE user_id = :u")
        out["entregas_de_inventario"] = count("SELECT count(*) FROM inventory_deliveries WHERE user_id = :u")
        out["inscripciones_de_formularios"] = count("SELECT count(*) FROM form_submissions WHERE person_id = :u")
        out["invitaciones_y_listas_de_formularios"] = count("SELECT (SELECT count(*) FROM form_invites WHERE person_id = :u) + (SELECT count(*) FROM form_people WHERE person_id = :u)")
        out["pagos"] = count("SELECT count(*) FROM form_payments WHERE person_id = :u")
        out["pagos_con_correo"] = count("SELECT count(*) FROM form_payments WHERE person_id = :u AND payer_email IS NOT NULL")
        out["consentimientos"] = [{"version": v, "motivo": r, "acepto": a, "mayor_de_edad": ad, "fecha": f.isoformat()} for v, r, a, ad, f in db.execute(
            text("SELECT consent_version, reason, accepted_biometric, confirmed_adult, consent_timestamp_utc FROM audit_consent_logs WHERE cedula_hash = :h ORDER BY consent_timestamp_utc"), {"h": h}).all()]
        out["solicitudes_de_privacidad"] = [r for (r,) in db.execute(text("SELECT radicado FROM privacy_requests WHERE cedula = :u ORDER BY id"), p).all()]
        out["reclamo_en_tramite"] = bool(count("SELECT count(*) FROM privacy_requests WHERE cedula = :u AND claim_flag"))
        out["suprimida"] = bool(db.execute(text("SELECT 1 FROM suppressed_people WHERE cedula_hash = :h LIMIT 1"), {"h": h}).first())
    return json.dumps(out, ensure_ascii=False)


def retry_face_jobs() -> str:
    """Reintenta los cálculos faciales que se agotaron (estado `failed`) o quedaron en curso con el arriendo vencido: vuelven a la cola con los intentos en cero y se despierta a la cola facial."""
    from app import jobs
    from app.database import SessionLocal
    from app.models import Job
    with SessionLocal() as db:
        rows = db.query(Job).filter(Job.kind.in_(list(jobs.FACE_KINDS)), Job.status == "failed").all()
        for j in rows:
            j.status, j.attempts, j.run_at, j.last_error, j.locked_until = "queued", 0, utcnow(), None, None
        db.commit()
    jobs.kick(pool="faces")
    return f"{len(rows)} cálculo(s) facial(es) devueltos a la cola"


TASKS = {"backup": lambda: backup_db("hourly"), "backup-daily": lambda: backup_db("daily"), "purge": purge,
         "archive-events": archive_events, "check-backups": check_backups, "offsite-copy": offsite_copy, "sweep": sweep, "warmup": warmup, "export-consent": export_consent, "bench-vector": bench_vector, "list-minors": list_minors, "export-person-data": export_person_data, "retry-face-jobs": retry_face_jobs, "infra-costs-import": import_infra_costs, "db-health": db_health}


def main(task: str) -> int:
    if task == "hourly":
        from app import ops_state
        steps = ops_state.load_steps()
        last = ops_state._parse(steps.get("full_run"))
        gap = ops_state.min_interval_minutes()
        if last and gap and utcnow() - last < timedelta(minutes=gap):       # el Scheduler avisó de nuevo muy pronto: ni se abre la base
            print(json.dumps({"ops": task, "skipped": f"corrió hace menos de {gap} min (OPS_MIN_INTERVAL_MINUTES)"}, ensure_ascii=False))
            return 0
        results = economic(steps=steps)
        if not results:
            print(json.dumps({"ops": task, "skipped": "ningún paso vence ahora: la base descansa"}, ensure_ascii=False))
            return 0
    elif task == "hourly-full":                      # a mano: todos los pasos según la hora, sin las reglas de ahorro
        results = hourly()
    elif task in TASKS:
        try:
            results = {task: {"ok": True, "detail": TASKS[task]()}}
        except Exception as e:  # noqa: BLE001
            log.error("tarea %s falló: %s", task, _reason(e), exc_info=True)
            results = {task: {"ok": False, "detail": f"{type(e).__name__}: {e}"}}
    else:
        print(f"Tarea desconocida: {task}. Usa: hourly, {', '.join(TASKS)}")
        return 2
    print(json.dumps({"ops": task, "results": results}, ensure_ascii=False))
    failed = [k for k, v in results.items() if not v["ok"]]
    if failed:
        _alert(f"ops-{'-'.join(failed)}", f"[Orum] ⚠️ Falló la tarea de operaciones: {', '.join(failed)}",
               "\n".join(f"- {k}: {results[k]['detail']}" for k in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    from app.obs import configure_logging
    configure_logging()
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hourly"))
