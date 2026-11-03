#!/usr/bin/env bash
# Valores y ayudas COMUNES de los scripts del paso a producción del 28-oct-2026. No se ejecuta solo: lo cargan los demás con «source».
# Nada de esto escribe en la nube. Los secretos se leen solo cuando hace falta, dentro de una variable, y NUNCA se imprimen.

# shellcheck disable=SC2034  # estas variables las usan los scripts que cargan este archivo
PROYECTO="goldenweb-prod"
REGION="us-east4"
SITIO_HOSTING="golden-app-617335535465"
DOMINIO="https://app.golden-eventos.com"
SERVICIOS="golden-web golden-publico golden-biometria"
JOBS="golden-bulk golden-ops golden-migrate"
SECRETOS="golden-database-url golden-direct-database-url golden-secret-key golden-face-encryption-key golden-ops-token"

# Tabla de resultados: cada verificación agrega una fila «✅ nombre | detalle» o «❌ nombre | razón».
RESULTADOS=()
bien()  { RESULTADOS+=("✅ $1 | $2"); echo "   ✅ $1: $2"; }
mal()   { RESULTADOS+=("❌ $1 | $2"); echo "   ❌ $1: $2"; }
aviso() { RESULTADOS+=("⚠️  $1 | $2"); echo "   ⚠️  $1: $2"; }
titulo() { echo; echo "== $*"; }

imprimir_tabla() {
  echo
  echo "================================ RESUMEN ================================"
  local r malos=0
  for r in "${RESULTADOS[@]}"; do echo "$r"; [[ "$r" == ❌* ]] && malos=$((malos + 1)); done
  echo "========================================================================="
  if [ "$malos" -eq 0 ]; then echo "TODO EN ORDEN: ninguna verificación con ❌."; else echo "HAY $malos VERIFICACIÓN(ES) CON ❌: no sigas; mándale este resumen a Claude."; fi
  return 0
}

# El proyecto se pasa en CADA comando (--project): no se cambia la configuración de tu Cloud Shell.
g() { gcloud "$@" --project "$PROYECTO"; }

# Token de acceso para leer Firebase Hosting (no se imprime).
token_acceso() { gcloud auth print-access-token 2>/dev/null; }

# Versión de Firebase Hosting que está publicada ahora (nombre completo «sites/.../versions/...»).
version_hosting_actual() {
  local tok; tok="$(token_acceso)"
  [ -n "$tok" ] || return 1
  curl -fsS -H "Authorization: Bearer $tok" -H "x-goog-user-project: $PROYECTO" \
    "https://firebasehosting.googleapis.com/v1beta1/sites/$SITIO_HOSTING/channels/live" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("release",{}).get("version",{}).get("name",""))'
}

# Revisión que recibe el tráfico de un servicio (la que hay que anotar para volver atrás).
revision_con_trafico() {
  g run services describe "$1" --region "$REGION" --format=json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
t = [x for x in d.get("status", {}).get("traffic", []) if x.get("percent")]
t.sort(key=lambda x: -x["percent"])
print(t[0].get("revisionName") or d["status"].get("latestReadyRevisionName", "") if t else d["status"].get("latestReadyRevisionName", ""))'
}

imagen_job() { g run jobs describe "$1" --region "$REGION" --format="value(spec.template.spec.template.spec.containers[0].image)" 2>/dev/null; }
