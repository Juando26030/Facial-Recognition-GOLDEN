#!/usr/bin/env bash
# VERIFICACIÓN PREVIA al paso a producción (29-oct-2026). SOLO LECTURA: no crea, no cambia ni borra nada en la nube.
# Uso en Cloud Shell (con tu usuario de Google que administra goldenweb-prod):
#     bash deploy/produccion_29oct/verificar_antes.sh
# Al final imprime una tabla con ✅ / ❌ y la razón de cada ❌. Mándale esa tabla a Claude.
# shellcheck disable=SC2015  # «bien» y «mal» siempre terminan bien: «A && bien || mal» es seguro aquí
set -u
cd "$(dirname "$0")" || exit 1
# shellcheck source=comun.sh
source ./comun.sh

titulo "0. Cuenta y proyecto"
cuenta="$(gcloud config get-value account 2>/dev/null)"
if [ -n "$cuenta" ] && g projects describe "$PROYECTO" --format="value(projectId)" >/dev/null 2>&1; then bien "Acceso al proyecto" "$PROYECTO con la cuenta $cuenta"
else mal "Acceso al proyecto" "no se pudo leer $PROYECTO (¿iniciaste sesión con la cuenta correcta? gcloud auth login)"; fi

titulo "1. Servicios de Cloud Run (revisión y variables)"
for s in $SERVICIOS; do
  json="$(g run services describe "$s" --region "$REGION" --format=json 2>/dev/null)"
  if [ -z "$json" ]; then mal "Servicio $s" "no existe o no se pudo leer"; continue; fi
  info="$(echo "$json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
env = {e["name"]: ("(secreto)" if "valueFrom" in e else e.get("value", "")) for e in d["spec"]["template"]["spec"]["containers"][0].get("env", [])}
rev = d["status"].get("latestReadyRevisionName", "")
probs = []
if env.get("BULK_BACKEND") != "cloudrun": probs.append("BULK_BACKEND=" + str(env.get("BULK_BACKEND")))
if not str(env.get("BULK_JOB_NAME", "")).endswith("/jobs/golden-bulk"): probs.append("BULK_JOB_NAME=" + str(env.get("BULK_JOB_NAME")))
if env.get("FACE_ENCRYPTION_KEY") != "(secreto)": probs.append("FACE_ENCRYPTION_KEY no viene de Secret Manager")
if env.get("DEPLOY_ENV") != "production": probs.append("DEPLOY_ENV=" + str(env.get("DEPLOY_ENV")))
print(rev + "|" + str(env.get("APP_COMMIT", "?"))[:7] + "|" + "; ".join(probs))')"
  rev="${info%%|*}"; resto="${info#*|}"; commit="${resto%%|*}"; probs="${resto#*|}"
  if [ -z "$probs" ]; then bien "Servicio $s" "revisión $rev (código $commit), BULK_BACKEND=cloudrun, BULK_JOB_NAME=…/golden-bulk, llave de rostros desde Secret Manager"
  else mal "Servicio $s" "revisión $rev: $probs"; fi
done

titulo "2. Jobs de Cloud Run"
for j in $JOBS; do
  img="$(imagen_job "$j")"
  if [ -n "$img" ]; then bien "Job $j" "existe (imagen actual ${img##*/}); el despliegue lo vuelve a desplegar con la imagen nueva"
  else mal "Job $j" "no existe o no se pudo leer"; fi
done

titulo "3. Secretos (solo que existan; NO se lee su valor)"
for s in $SECRETOS; do
  if g secrets describe "$s" --format="value(name)" >/dev/null 2>&1; then bien "Secreto $s" "existe"
  else mal "Secreto $s" "FALTA (no lo crees sin hablarlo: la llave de rostros no se puede reemplazar)"; fi
done

titulo "4. Cloud Tasks y Cloud Scheduler"
estado_cola() { g tasks queues describe "$1" --location "$REGION" --format="value(state)" 2>/dev/null; }
e="$(estado_cola golden-jobs)"; [ "$e" = "RUNNING" ] && bien "Cola golden-jobs" "RUNNING" || mal "Cola golden-jobs" "estado «${e:-no existe}»"
e="$(estado_cola golden-faces)"; [ "$e" = "RUNNING" ] && bien "Cola golden-faces" "RUNNING" || aviso "Cola golden-faces" "estado «${e:-no existe}» (opcional: sin ella los cálculos faciales van por la cola general)"
e="$(g scheduler jobs describe golden-ops-hourly --location "$REGION" --format="value(state)" 2>/dev/null)"
[ "$e" = "ENABLED" ] && bien "Scheduler golden-ops-hourly" "ENABLED (el barrido horario)" || mal "Scheduler golden-ops-hourly" "estado «${e:-no existe}»"
echo "   (el paquete NO agrega colas ni tareas programadas nuevas)"

titulo "5. Firebase Hosting"
v="$(version_hosting_actual)"
if [ -n "$v" ]; then bien "Hosting $SITIO_HOSTING" "versión publicada ${v##*/} (el despliegue manual vuelve a publicar el hosting con las rutas nuevas)"
else mal "Hosting $SITIO_HOSTING" "no se pudo leer la versión publicada (¿permisos de Firebase Hosting?)"; fi

titulo "6. Base de datos (versión de las migraciones, solo lectura)"
if command -v psql >/dev/null 2>&1; then
  url="$(g secrets versions access latest --secret golden-direct-database-url 2>/dev/null)"        # se usa sin imprimirse
  ver="$(psql "$url" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null)"; unset url
  if [ "$ver" = "0073_attendee_origin" ]; then bien "Migraciones" "la base está en $ver (el despliegue aplicará 0074 y 0075: bitácora y seguimiento de exportar/importar eventos; son aditivas)"
  elif [ -n "$ver" ]; then mal "Migraciones" "la base está en «$ver» y se esperaba 0073_attendee_origin"
  else mal "Migraciones" "no se pudo leer alembic_version"; fi
else aviso "Migraciones" "psql no está instalado aquí: revísalo en la consola SQL de Neon (SELECT version_num FROM alembic_version; -> 0073_attendee_origin)"; fi

titulo "7. Eventos en curso o por abrir (el despliegue se bloquea solo si hay)"
tok="$(g secrets versions access latest --secret golden-ops-token 2>/dev/null)"                     # se usa sin imprimirse
resp="$(curl -fsS --max-time 30 -H "X-Ops-Token: $tok" "$DOMINIO/api/ops/deploy-allowed" 2>/dev/null)"; unset tok
if [ -z "$resp" ]; then mal "Eventos en curso" "no se pudo preguntar a $DOMINIO/api/ops/deploy-allowed"
elif echo "$resp" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("allowed") else 1)'; then bien "Eventos en curso" "ninguno en curso ni por abrir en las próximas 3 h"
else mal "Eventos en curso" "$(echo "$resp" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin).get("reasons",[])))')"; fi

titulo "8. Dominio"
code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$DOMINIO/health")"
[ "$code" = "200" ] && bien "app.golden-eventos.com/health" "200" || mal "app.golden-eventos.com/health" "respondió $code"

titulo "9. Punto de restauración de Neon (lo creas tú en la consola de Neon)"
aviso "Rama de Neon antes-produccion-29oct" "este script no la puede ver: créala justo antes de desplegar (Neon -> Branches -> Create branch, «current point in time»)"

imprimir_tabla
