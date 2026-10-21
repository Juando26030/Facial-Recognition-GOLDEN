#!/usr/bin/env bash
# Reintento de permisos de IAM recién referidos (lo carga bootstrap.sh; lo prueba tests/test_bootstrap_iam_retry.py con un `gcloud` de mentira).
#
# Por qué: un rol personalizado (goldenBackupLister, goldenRunOperationsViewer) tarda unos segundos en «existir en la jerarquía» después de `gcloud iam roles create`. Asignarlo de inmediato falla
# con «HTTPError 400: Role (projects/<proyecto>/roles/<rol>) does not exist in the resource's hierarchy» (producción, 9-oct-2026, paso 6). No es un error real: es propagación de IAM.
# retry_iam repite SOLO ese tipo de error (hasta IAM_RETRY_TRIES veces, esperando IAM_RETRY_WAIT segundos); cualquier otro error (permiso denegado, recurso inexistente...) falla de inmediato
# y se muestra tal cual. Si se agotan los intentos, falla con un mensaje claro.
IAM_RETRY_PATTERN="does not exist in the resource's hierarchy|is not supported for this resource|Role .* does not exist"

retry_iam() {   # comando completo de gcloud (o cualquier comando)
  local tries="${IAM_RETRY_TRIES:-6}" wait="${IAM_RETRY_WAIT:-20}" n=1 out
  while true; do
    if out="$("$@" 2>&1)"; then return 0; fi
    if ! printf '%s' "$out" | grep -qE "$IAM_RETRY_PATTERN"; then
      printf '%s\n' "$out" >&2
      return 1
    fi
    if [ "$n" -ge "$tries" ]; then
      printf '%s\n' "$out" >&2
      echo "   El rol personalizado sigue sin estar disponible tras $tries intentos de ${wait} s (propagación de IAM). Espera unos minutos y vuelve a correr el MISMO comando: es idempotente." >&2
      return 1
    fi
    echo "   esperando que el rol se propague (intento $n de $tries; reintento en ${wait} s)..." >&2
    sleep "$wait"
    n=$((n + 1))
  done
}
