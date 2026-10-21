#!/usr/bin/env bash
# CORS del bucket de la app para la subida directa con URL firmada (PUT desde el navegador). Lo corre Juan David en Cloud Shell (Claude no ejecuta gcloud). Idempotente:
# calcula los orígenes del entorno (config.sh: cors_origins, con las DOS URL de Cloud Run del servicio web si existe), compara con lo que tiene el bucket y solo cambia si difiere.
#
#   bash deploy/gcp/cors.sh <staging|production>
#
# bootstrap.sh lo corre al terminar (cuando los servicios ya existen y su URL con hash se puede leer). Si algún día cambia el dominio o se recrea el servicio web: volver a correrlo.
set -euo pipefail
cd "$(dirname "$0")/../.."
export REGION="${REGION:-us-east4}"
source deploy/gcp/config.sh "${1:-}"
mapfile -t ORIGINS < <(cors_origins)
[ "${#ORIGINS[@]}" -gt 0 ] || { echo "No hay orígenes que aplicar"; exit 1; }
WANT="$(python3 deploy/gcp/cors_json.py "${ORIGINS[@]}")"
HAVE="$(gcloud storage buckets describe "gs://$APP_BUCKET" --format=json 2>/dev/null | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin).get("cors_config") or []))')"
SAME="$(python3 - "$WANT" "$HAVE" <<'PY'
import json, sys
def norm(rules):
    return sorted((sorted(r.get("origin", [])), sorted(r.get("method", [])), sorted(r.get("responseHeader", [])), r.get("maxAgeSeconds")) for r in rules)
want, have = json.loads(sys.argv[1]), json.loads(sys.argv[2])
print("si" if norm(want) == norm(have) else "no")
PY
)"
if [ "$SAME" = si ]; then
  echo "CORS de gs://$APP_BUCKET ya está al día:"
else
  TMP="$(mktemp)"; echo "$WANT" > "$TMP"
  gcloud storage buckets update "gs://$APP_BUCKET" --cors-file "$TMP" --quiet >/dev/null; rm -f "$TMP"
  echo "CORS de gs://$APP_BUCKET aplicado:"
fi
printf '   %s\n' "${ORIGINS[@]}"
