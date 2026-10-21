#!/usr/bin/env bash
# Secretos del bootstrap (put_secret idempotente + resumen). Lo carga deploy/gcp/bootstrap.sh con `source`; lo prueban tests/test_bootstrap_secrets.py con un `gcloud` de mentira.
# Requiere de quien lo carga: `secret_name` (config.sh), `exists`, `ok`, y la variable ROTATE.
#
# Reglas (todas verificadas por pruebas):
#   * Un secreto que YA tiene una versión usable NO se pide, NO se regenera y NO recibe otra versión (llave de rostros, SECRET_KEY, token de operaciones, cadena directa de Neon...),
#     salvo que su nombre corto esté en ROTATE (p. ej. ROTATE="ops-token").
#   * Un opcional con Enter no se crea; la próxima corrida vuelve a preguntarlo (Enter otra vez es seguro).
#   * Un secreto OBLIGATORIO sin valor y sin generador detiene el script.
gen_hex() { python3 -c "import secrets; print(secrets.token_hex(32))"; }
gen_fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }
ensure_secret() { exists gcloud secrets describe "$1" || gcloud secrets create "$1" --replication-policy automatic >/dev/null; }
secret_has_version() { exists gcloud secrets versions access latest --secret "$1"; }      # «versión usable»: lo que Cloud Run leerá como :latest

put_secret() {   # nombre-corto  ayuda  obligatorio(0/1)  [generador]
  local s; s="$(secret_name "$1")"
  if secret_has_version "$s" && [[ " ${ROTATE:-} " != *" $1 "* ]]; then ok "$s ya tiene valor"; return; fi
  local value=""
  read -rsp "   $s — $2: " value; echo
  if [ -z "$value" ] && [ -n "${4:-}" ]; then value="$($4)"; echo "     (generado al azar)"; fi
  if [ -z "$value" ]; then
    [ "$3" = 1 ] && { echo "   $s es obligatorio." >&2; exit 1; }
    echo "     (omitido)"; return
  fi
  ensure_secret "$s"
  printf '%s' "$value" | gcloud secrets versions add "$s" --data-file=- >/dev/null
  ok "$s guardado"
}

# Estado final de cada secreto (nombres cortos como argumentos): con versión, existe pero SIN versión, o no existe (opcional omitido). Nunca muestra valores.
secrets_summary() {
  local n s
  for n in "$@"; do
    s="$(secret_name "$n")"
    if secret_has_version "$s"; then echo "   ✓ $s: con versión"
    elif exists gcloud secrets describe "$s"; then echo "   ✗ $s: existe pero SIN versión"
    else echo "   – $s: no existe (opcional omitido)"; fi
  done
}
