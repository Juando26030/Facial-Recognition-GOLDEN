#!/usr/bin/env bash
# Detección de la cola de cálculos faciales (golden-faces[-staging]) para deploy.sh.
#
# Antes la detección era `gcloud tasks queues describe ... >/dev/null 2>&1`: si la cuenta de despliegue NO tenía permiso para LEER la cola, el error (PERMISSION_DENIED) se tragaba y el despliegue
# seguía como si la cola no existiera: los servicios quedaban sin CLOUD_TASKS_FACES_QUEUE / CLOUD_TASKS_FACES_URL y los cálculos faciales corrían por la cola general (staging, 6-oct-2026).
# Ahora se distingue: la cola EXISTE, FALTA de verdad, o hubo un ERROR (permisos, red): el error DETIENE el despliegue con el motivo a la vista.
#
# Uso:  source deploy/gcp/lib_faces.sh;  faces_queue_state   → imprime «existe», «falta» o «error: <motivo>».
faces_queue_state() {
  local out
  if out="$(gcloud tasks queues describe "$QUEUE_FACES" --location "$REGION" --format='value(name)' 2>&1)"; then
    echo "existe"
  elif echo "$out" | grep -qiE 'NOT_FOUND|not found|does not exist'; then
    echo "falta"
  else
    echo "error: $(echo "$out" | tr '\n' ' ' | cut -c1-400)"
  fi
}
