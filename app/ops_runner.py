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
def purge() -> str:
    """Retención biométrica (app/privacy.py): solo conteos en el resultado y en el log. Con errores el paso FALLA (alerta) y se reintenta la hora siguiente."""
    from app import acceptmail, privacy
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        r = privacy.purge_expired(db)
        r["mail_log_rows"] = acceptmail.purge_log(db)       # registro de envíos de enlaces personales (misma retención que lo biométrico)
    finally:
        db.close()
    log.info("purga biométrica: %s", json.dumps(r))
    if r["errors"]:
        raise RuntimeError(f"la purga biométrica tuvo {r['errors']} error(es) al borrar fotos (se reintenta en la próxima corrida): {json.dumps(r)}")
    return json.dumps(r)


def sweep() -> str:
    from sqlalchemy import func

    from app import formsvc, jobs, reconcile  # noqa: F401 — registran sus trabajos
    from app.database import SessionLocal
    from app.models import Job
    ran = jobs.drain(exclude=jobs.FACE_KINDS)                 # los cálculos faciales NO corren aquí (este Job no tiene el manejador ni la CPU): van por su cola, en el servicio de biometría
    with SessionLocal() as db:
        faces_due = db.query(func.count(Job.id)).filter(Job.kind.in_(list(jobs.FACE_KINDS)), Job.status.in_(("queued", "running")), Job.run_at <= utcnow()).scalar() or 0
    if faces_due:
        jobs.kick(pool="faces")                               # el barrido horario despierta a la cola facial por si una tarea de Cloud Tasks se perdió
    return f"{ran} trabajo(s) pendiente(s) ejecutado(s); {faces_due} cálculo(s) facial(es) pendiente(s) avisados a su cola"


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


def purge_reports() -> str:
    """Borra los reportes Excel de Estadísticas que ya vencieron (duran una hora; ver app/report_jobs.py)."""
    from app.database import SessionLocal
    from app.report_jobs import purge_expired
    with SessionLocal() as db:
        return f"{purge_expired(db)} reporte(s) vencido(s) borrado(s)"


def hourly(now=None) -> dict:
    now = now or _local_now()
    steps = [("backup", lambda: backup_db("hourly", now=now))]
    if now.hour == int(os.getenv("OPS_DAILY_HOUR", "3")):
        steps.append(("backup-daily", lambda: backup_db("daily", now=now)))
    if now.hour == int(os.getenv("OPS_PURGE_HOUR", "4")):
        steps.append(("purge", purge))
    steps += [("check-backups", check_backups), ("sweep", sweep), ("reports", purge_reports), ("warmup", warmup)]
    results = {}
    for name, fn in steps:
        try:
            results[name] = {"ok": True, "detail": fn()}
        except Exception as e:  # noqa: BLE001 — un paso fallido no detiene los demás
            log.error("paso %s falló: %s", name, _reason(e), exc_info=True)
            results[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
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
    from app.storage import get_storage, photo_key
    found = []
    with SessionLocal() as db:
        for u in db.query(User.id, User.tenant_id, User.birth_date, User.face_encoding).filter(User.birth_date.isnot(None)).yield_per(500):
            if minors.is_minor(u.birth_date) and (u.face_encoding or get_storage().exists(photo_key(u.tenant_id, u.id))):
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

    from app import consent, minors
    from app.database import SessionLocal
    from app.models import User
    from app.storage import get_storage, photo_key
    cedula = os.getenv("EXPORT_CEDULA", "").strip()
    if not cedula:
        raise RuntimeError("Falta EXPORT_CEDULA")
    h = consent.cedula_hash(cedula)
    out = {"personas": [], "suprimida": False}
    with SessionLocal() as db:
        p = {"u": cedula}
        for u in db.query(User).filter(User.id == cedula).all():
            fields = [c for c in ("first_name", "last_name", "role", "entity", "phone", "email", "opt_1", "opt_2", "extra_fields", "birth_date") if getattr(u, c)]
            out["personas"].append({"campos_con_dato": fields, "tiene_vector_facial": bool(u.face_encoding), "tiene_foto": get_storage().exists(photo_key(u.tenant_id, u.id)),
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
         "check-backups": check_backups, "sweep": sweep, "warmup": warmup, "export-consent": export_consent, "bench-vector": bench_vector, "list-minors": list_minors, "export-person-data": export_person_data, "retry-face-jobs": retry_face_jobs}


def main(task: str) -> int:
    if task == "hourly":
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
        _alert(f"ops-{'-'.join(failed)}", f"[GoldenWeb 2.0] ⚠️ Falló la tarea de operaciones: {', '.join(failed)}",
               "\n".join(f"- {k}: {results[k]['detail']}" for k in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    from app.obs import configure_logging
    configure_logging()
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hourly"))
