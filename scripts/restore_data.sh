#!/usr/bin/env bash
# Restaura los archivos de data/ (y opcionalmente el .env) desde el bucket de datos, en una VM nueva o tras una
# pérdida (Sprint 4, recuperación ante desastre). Ver docs/recuperacion_desastre.md.
#
# Uso:   scripts/restore_data.sh gs://golden-datos-XXXX [carpeta_destino_de_data]
#        RESTORE_ENV=1 scripts/restore_data.sh gs://golden-datos-XXXX     # además baja el .env a ../.env
set -euo pipefail

BUCKET="${1:?Falta el bucket de datos (ej. gs://golden-datos-XXXX)}"
BUCKET="${BUCKET%/}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${2:-$APP_DIR/data}"

mkdir -p "$DATA_DIR"
echo "Bajando $BUCKET/data -> $DATA_DIR"
gcloud storage rsync --recursive "$BUCKET/data" "$DATA_DIR" --quiet
echo "Archivos restaurados: $(find "$DATA_DIR" -type f | wc -l)"

if [ "${RESTORE_ENV:-0}" = "1" ]; then
  if [ -f "$APP_DIR/.env" ]; then
    echo "Ya existe $APP_DIR/.env — no se sobrescribe. Bájalo a mano si lo necesitas: gcloud storage cp $BUCKET/config/.env $APP_DIR/.env.restaurado"
  else
    gcloud storage cp "$BUCKET/config/.env" "$APP_DIR/.env" --quiet
    chmod 600 "$APP_DIR/.env"
    echo ".env restaurado (revísalo: DATABASE_URL debe apuntar a la base de esta máquina)."
  fi
fi
