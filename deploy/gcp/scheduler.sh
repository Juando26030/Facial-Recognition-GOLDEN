#!/usr/bin/env bash
# Tarea de Cloud Scheduler del entorno (`golden-ops-hourly[-staging]`: respaldos, revisión, purga, cola y precalentamiento). Lo corre Juan David en Cloud Shell; Claude Code no ejecuta nada en la nube.
#
#   bash deploy/gcp/scheduler.sh <staging|production> ensure [--resume]   # crea la tarea si falta o la CORRIGE si algo difiere (idempotente); nace EN PAUSA salvo --resume
#   bash deploy/gcp/scheduler.sh <staging|production> check  [--paused-ok] # solo lee: nombre, región, horario, zona, destino, cuenta, estado y respaldo reciente (sale 1 si algo falta)
#   bash deploy/gcp/scheduler.sh <staging|production> alert                # crea (idempotente) la alerta de AUSENCIA: el Job horario no terminó ninguna ejecución en 2 h (después de reanudar la tarea)
#
# Por qué existe: la tarea la creaba SOLO bootstrap.sh (paso 9) y en staging únicamente con SCHEDULE_STAGING=1; ni deploy.sh ni move_region.sh la creaban ni la comprobaban en staging,
# así que tras mover de región (o con un bootstrap sin esa variable) staging quedó sin respaldos horarios y nadie lo notó hasta que `check-backups` avisó (la alarma funcionó).
# `check` también lo usan move_region.sh (verify) y el runbook de corte (docs/15 D2.5).
#   --paused-ok  (producción ANTES del corte): la tarea debe existir y estar bien configurada pero puede seguir en pausa; sin él, debe estar ENABLED y haber corrido hace poco.
# Variables: BACKUP_HOURLY_MAX_AGE_H (9 en el entorno de nube: modo tranquilo, app/ops_state.py), PYTHON (python3).
set -euo pipefail
cd "$(dirname "$0")/../.."
ENV_ARG="${1:-}"; ACTION="${2:-}"; shift 2 2>/dev/null || true
# shellcheck source=/dev/null
source deploy/gcp/config.sh "$ENV_ARG"
PYTHON="${PYTHON:-python3}"
SCHEDULE="5 * * * *"; TZ_NAME="America/Bogota"                                  # cada hora al minuto 05, hora de Bogotá (= bootstrap.sh paso 9 y app/ops_runner.py)
URI="https://run.googleapis.com/v2/$(run_path jobs "$JOB_OPS"):run"
INVOKER="$(sa_email "$SA_INVOKER")"
DESC="Respaldos, revisión, purga, cola y precalentamiento"
exists() { "$@" >/dev/null 2>&1; }

case "$ACTION" in
  ensure)
    resume=0; for a in "$@"; do [ "$a" = "--resume" ] && resume=1; done
    if exists gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION"; then
      gcloud scheduler jobs update http "$SCHEDULER_OPS" --location "$REGION" --schedule "$SCHEDULE" --time-zone "$TZ_NAME" --uri "$URI" --http-method POST \
        --oauth-service-account-email "$INVOKER" --description "$DESC" --quiet
      echo "tarea $SCHEDULER_OPS ($REGION): actualizada"
    else
      gcloud scheduler jobs create http "$SCHEDULER_OPS" --location "$REGION" --schedule "$SCHEDULE" --time-zone "$TZ_NAME" --uri "$URI" --http-method POST \
        --oauth-service-account-email "$INVOKER" --description "$DESC" --quiet
      gcloud scheduler jobs pause "$SCHEDULER_OPS" --location "$REGION" --quiet >/dev/null       # nace en pausa (docs/15: el día del cambio se reanuda)
      echo "tarea $SCHEDULER_OPS ($REGION): creada (en pausa)"
    fi
    if [ "$resume" = 1 ]; then gcloud scheduler jobs resume "$SCHEDULER_OPS" --location "$REGION" --quiet >/dev/null; fi
    echo "estado: $(gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION" --format 'value(state)')"
    ;;

  check)
    paused_ok=0; for a in "$@"; do [ "$a" = "--paused-ok" ] && paused_ok=1; done
    fail=0
    job_json="$(gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION" --format=json 2>/dev/null || true)"
    if [ -z "$job_json" ]; then
      echo "  FALTA la tarea $SCHEDULER_OPS en $REGION (no existe: bash deploy/gcp/scheduler.sh $GOLDEN_ENV ensure --resume)"; exit 1
    fi
    # Respaldos: el más reciente de db/hourly/ (fecha de modificación) y el despliegue más reciente del servicio web (para exigir un respaldo POSTERIOR a él).
    newest="$(gcloud storage ls -l "gs://$BACKUP_BUCKET/db/hourly/**" 2>/dev/null | grep '\.sql\.gz$' | awk '{print $2}' | sort | tail -1 || true)"
    deployed="$(gcloud run revisions list --service "$SVC_WEB" --region "$REGION" --limit 1 --format 'value(metadata.creationTimestamp)' 2>/dev/null || true)"
    printf "%s" "$job_json" | PYTHONIOENCODING=utf-8 PAUSED_OK="$paused_ok" WANT_NAME="$SCHEDULER_OPS" WANT_REGION="$REGION" WANT_SCHEDULE="$SCHEDULE" WANT_TZ="$TZ_NAME" WANT_URI="$URI" WANT_SA="$INVOKER" \
      NEWEST="$newest" DEPLOYED="$deployed" MAX_AGE_H="${BACKUP_HOURLY_MAX_AGE_H:-9}" "$PYTHON" -c '
import json, os, sys
from datetime import datetime, timezone
j = json.load(sys.stdin); e = os.environ; bad = 0
def ts(s):
    s = s.strip().replace("Z", "+00:00")
    if "." in s:                                   # fracciones de más de 6 dígitos (nanosegundos) que datetime no acepta
        head, rest = s.split(".", 1); frac = "".join(c for c in rest if c.isdigit())[:6]; tail = rest[len("".join(c for c in rest if c.isdigit())):]; s = f"{head}.{frac}{tail}"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
def chk(ok, good, wrong):
    global bad
    print(("  OK    " + good) if ok else ("  FALTA " + wrong)); bad += 0 if ok else 1
now = datetime.now(timezone.utc)
chk(j.get("name", "").endswith("/locations/%s/jobs/%s" % (e["WANT_REGION"], e["WANT_NAME"])), "tarea %s en %s" % (e["WANT_NAME"], e["WANT_REGION"]), "la tarea no es %s en %s: %s" % (e["WANT_NAME"], e["WANT_REGION"], j.get("name")))
chk(j.get("schedule") == e["WANT_SCHEDULE"], "horario «%s»" % e["WANT_SCHEDULE"], "horario «%s», debería ser «%s»" % (j.get("schedule"), e["WANT_SCHEDULE"]))
chk(j.get("timeZone") == e["WANT_TZ"], "zona horaria %s" % e["WANT_TZ"], "zona horaria %s, debería ser %s" % (j.get("timeZone"), e["WANT_TZ"]))
t = j.get("httpTarget") or {}
chk(t.get("uri") == e["WANT_URI"], "destino: el Job de operaciones del entorno", "destino %s, debería ser %s" % (t.get("uri"), e["WANT_URI"]))
chk((t.get("oauthToken") or {}).get("serviceAccountEmail") == e["WANT_SA"], "corre como %s" % e["WANT_SA"], "corre como %s, debería ser %s" % ((t.get("oauthToken") or {}).get("serviceAccountEmail"), e["WANT_SA"]))
state = j.get("state")
paused_ok = e["PAUSED_OK"] == "1"
chk(state == "ENABLED" or (paused_ok and state == "PAUSED"), "estado %s" % state, "estado %s: la tarea no corre (reanudar: bash deploy/gcp/scheduler.sh <entorno> ensure --resume)" % state)
last = j.get("lastAttemptTime")
if state == "ENABLED":
    age = (now - ts(last)).total_seconds() / 3600 if last else None
    chk(age is not None and age <= 1.5, "última ejecución hace %.1f h" % (age or 0), "la tarea está activa pero no corrió en la última hora y media (último intento: %s)" % (last or "nunca"))
    code = (j.get("status") or {}).get("code")
    chk(not code, "el último intento no dio error", "el último intento de la tarea falló (código %s): %s" % (code, (j.get("status") or {}).get("message", "")))
if not (state == "PAUSED" and paused_ok):
    newest = e.get("NEWEST", "").strip()
    if not newest:
        chk(False, "", "no hay respaldos horarios en db/hourly/ del bucket de respaldos")
    else:
        age = (now - ts(newest)).total_seconds() / 3600
        chk(age <= float(e["MAX_AGE_H"]), "último respaldo horario hace %.1f h" % age, "el último respaldo horario tiene %.1f h (máximo %s h)" % (age, e["MAX_AGE_H"]))
        dep = e.get("DEPLOYED", "").strip()
        if dep:
            d = ts(dep); fresh = ts(newest) > d
            waited = (now - d).total_seconds() / 3600
            if fresh: print("  OK    hay un respaldo posterior al último despliegue (%s)" % dep)
            elif waited < 1.25: print("  AVISO el último despliegue es de hace %.1f h y aún no hay un respaldo posterior: corre `backup` a mano (gcloud run jobs execute ... --args=-m,app.ops_runner,backup) y repite el check" % waited)
            else: chk(False, "", "el último despliegue (%s) es anterior a %.1f h y no hay respaldo posterior a él" % (dep, waited))
sys.exit(1 if bad else 0)
' || fail=1
    [ "$fail" = 0 ] && echo "Scheduler y respaldos en orden." || { echo "Faltan cosas en el Scheduler o los respaldos (arriba)." >&2; exit 1; }
    ;;

  alert)
    # Alerta por AUSENCIA: si el Job de operaciones no termina ninguna ejecución en 2 h (la tarea del Scheduler no existe, está en pausa o no corre), avisa por correo. Es lo que faltaba:
    # `check-backups` corre DENTRO de ese Job, así que sin la tarea nadie lo ejecuta y la alarma de respaldos calla (staging pasó 149 h así). No cambia ni debilita ninguna alerta existente.
    # Hay que crearla DESPUÉS de reanudar la tarea (si no, avisaría por una pausa deliberada). Idempotente: si existe una con ese nombre, no hace nada.
    NAME="Golden ${GOLDEN_ENV}: el Job horario no corre (sin respaldos ni revisión)"
    CHANNEL="$(gcloud beta monitoring channels list --filter "displayName=\"Golden alertas\"" --format 'value(name)' | head -n1)"
    [ -n "$CHANNEL" ] || { echo "No hay canal «Golden alertas» (lo crea bootstrap.sh, paso 10)." >&2; exit 1; }
    if [ -n "$(gcloud monitoring policies list --filter "displayName=\"$NAME\"" --format 'value(name)')" ]; then echo "alerta «$NAME»: ya existe"; exit 0; fi
    pol="$(mktemp)"; trap 'rm -f "$pol"' EXIT
    cat > "$pol" <<EOF
{"displayName": "$NAME", "combiner": "OR",
 "conditions": [{"displayName": "ninguna ejecución terminada en 2 horas", "conditionAbsent": {
   "filter": "metric.type=\"run.googleapis.com/job/completed_execution_count\" AND resource.type=\"cloud_run_job\" AND resource.label.job_name=\"${JOB_OPS}\"",
   "duration": "7200s", "trigger": {"count": 1},
   "aggregations": [{"alignmentPeriod": "3600s", "perSeriesAligner": "ALIGN_SUM"}]}}]}
EOF
    gcloud monitoring policies create --policy-from-file "$pol" --notification-channels "$CHANNEL" >/dev/null
    echo "alerta «$NAME»: creada"
    ;;

  *) echo "Uso: $0 <staging|production> ensure [--resume] | check [--paused-ok] | alert" >&2; exit 2 ;;
esac
