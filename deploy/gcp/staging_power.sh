#!/usr/bin/env bash
# Staging «apagado salvo cuando se prueba» (decisión de Juan David, 2026-11-06). Lo corre Juan David en Cloud Shell; Claude Code no ejecuta nada en la nube.
#
#   bash deploy/gcp/staging_power.sh off      # PAUSA la tarea horaria de staging (golden-ops-hourly-staging) y su alerta de ausencia: nada despierta la base de staging por su cuenta
#   bash deploy/gcp/staging_power.sh on       # REANUDA la tarea y la alerta: úsalo SOLO mientras se prueba (y vuelve a `off` al terminar)
#   bash deploy/gcp/staging_power.sh status   # solo lee: estado de la tarea, de la alerta y recordatorio de Neon
#
# Por qué: la tarea horaria (:05 America/Bogota: respaldos, revisión, purga, cola y precalentamiento) despierta la base de staging ~24 veces al día aunque nadie la use, y el consumo de staging
# (37 CU-h en 6 días, 2026-11) igualó al de producción. Con la tarea en pausa la base de staging solo se enciende cuando alguien abre la app de staging; Neon la suspende sola a los 5 minutos sin consultas
# y la puerta de inactividad de las pantallas (GW.idle, 60 s) deja de consultar. Los servicios de Cloud Run de staging ya tienen 0 instancias mínimas.
# Efecto colateral aceptado: staging no hace respaldos horarios mientras está apagado (son datos sintéticos). NUNCA toca producción: el script se niega a correr con otro entorno.
set -euo pipefail
cd "$(dirname "$0")/../.."
ACTION="${1:-}"
# shellcheck source=/dev/null
source deploy/gcp/config.sh staging
[ "${GOLDEN_ENV:-staging}" = "staging" ] || { echo "Solo staging." >&2; exit 2; }
ALERT_NAME="Golden staging: el Job horario no corre (sin respaldos ni revisión)"

policy_id() { gcloud monitoring policies list --filter "displayName=\"$ALERT_NAME\"" --format 'value(name)' 2>/dev/null | head -n1; }
set_alert() {   # $1 = true|false
  local p; p="$(policy_id)"
  if [ -z "$p" ]; then echo "alerta de ausencia: no existe (nada que cambiar)"; return 0; fi
  if [ "$1" = "true" ]; then gcloud monitoring policies update "$p" --enabled >/dev/null; else gcloud monitoring policies update "$p" --no-enabled >/dev/null; fi
  echo "alerta de ausencia: $([ "$1" = true ] && echo activada || echo desactivada)"
}
state() { gcloud scheduler jobs describe "$SCHEDULER_OPS" --location "$REGION" --format 'value(state)'; }

case "$ACTION" in
  off)
    gcloud scheduler jobs pause "$SCHEDULER_OPS" --location "$REGION" --quiet >/dev/null
    set_alert false
    echo "staging APAGADO: tarea $SCHEDULER_OPS en $(state). La base de staging se suspende sola a los 5 minutos sin uso."
    ;;
  on)
    gcloud scheduler jobs resume "$SCHEDULER_OPS" --location "$REGION" --quiet >/dev/null
    set_alert true
    echo "staging ENCENDIDO para pruebas: tarea $SCHEDULER_OPS en $(state). Al terminar: bash deploy/gcp/staging_power.sh off"
    ;;
  status)
    echo "tarea $SCHEDULER_OPS: $(state)"
    p="$(policy_id)"; if [ -n "$p" ]; then echo "alerta de ausencia: $(gcloud monitoring policies describe "$p" --format 'value(enabled)')"; else echo "alerta de ausencia: no existe"; fi
    echo "Neon: comprueba en System operations del proyecto goldenweb STAGING que no haya «Start compute» nuevos mientras nadie prueba."
    ;;
  *) echo "Uso: $0 off | on | status" >&2; exit 2 ;;
esac
