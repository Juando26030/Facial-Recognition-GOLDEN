#!/usr/bin/env bash
# VERIFICACIÓN DESPUÉS del despliegue a producción (28-oct-2026). SOLO LECTURA.
# Uso:  bash deploy/produccion_28oct/verificar_despues.sh [commit esperado, por defecto el del paquete]
# Mira: errores en los registros de los últimos 30 minutos, /health, qué revisión atiende cada servicio y con qué código, las rutas nuevas y el hosting.
# shellcheck disable=SC2015  # «bien» y «mal» siempre terminan bien: «A && bien || mal» es seguro aquí
set -u
cd "$(dirname "$0")" || exit 1
# shellcheck source=comun.sh
source ./comun.sh
ESPERADO="${1:-}"

titulo "1. /health"
code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$DOMINIO/health")"
[ "$code" = "200" ] && bien "app.golden-eventos.com/health" "200" || mal "app.golden-eventos.com/health" "respondió $code"

titulo "2. Revisión y código de cada servicio"
for s in $SERVICIOS; do
  rev="$(revision_con_trafico "$s")"
  commit="$(g run revisions describe "$rev" --region "$REGION" --format=json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(next((e.get("value", "") for e in d["spec"]["containers"][0].get("env", []) if e["name"] == "APP_COMMIT"), "")[:7])' 2>/dev/null)"
  if [ -z "$rev" ]; then mal "Servicio $s" "no se pudo leer"; continue; fi
  if [ -n "$ESPERADO" ] && [ "$commit" != "${ESPERADO:0:7}" ]; then mal "Servicio $s" "revisión $rev con código $commit (se esperaba ${ESPERADO:0:7})"
  else bien "Servicio $s" "revisión $rev, código $commit"; fi
done

titulo "3. Rutas nuevas detrás del dominio (sin sesión deben pedir login, NO dar 404)"
for ruta in /api/session/ping /api/bulk_steps/active; do
  m=GET
  c="$(curl -s -o /dev/null -w "%{http_code}" -X "$m" --max-time 20 "$DOMINIO$ruta")"
  if [ "$c" = "404" ] || [ "$c" = "000" ] || [ "${c:0:1}" = "5" ]; then mal "Ruta $ruta" "respondió $c (¿se publicó el hosting nuevo y el código nuevo?)"
  else bien "Ruta $ruta" "responde $c (existe; pide sesión)"; fi
done

titulo "3b. Modo sin conexión (contingencia) encendido"
cont="$(curl -s --max-time 20 "$DOMINIO/kiosk/sw.js")"
if echo "$cont" | grep -q "contingencia APAGADO"; then mal "Contingencia" "el service worker servido dice «APAGADO»: CONTINGENCY_ENABLED no quedó en 1"
elif echo "$cont" | grep -q "addEventListener"; then bien "Contingencia" "el service worker del quiosco está ENCENDIDO"
else aviso "Contingencia" "no se pudo leer /kiosk/sw.js"; fi
for s in $SERVICIOS; do
  v="$(g run services describe "$s" --region "$REGION" --format=json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(next((e.get("value", "") for e in d["spec"]["template"]["spec"]["containers"][0].get("env", []) if e["name"] == "CONTINGENCY_ENABLED"), "?"))' 2>/dev/null)"
  [ "$v" = "1" ] && bien "CONTINGENCY_ENABLED en $s" "1" || mal "CONTINGENCY_ENABLED en $s" "vale «${v:-?}» (se esperaba 1)"
done

titulo "4. Firebase Hosting"
v="$(version_hosting_actual)"
# shellcheck disable=SC2012  # los nombres los pone anotar_estado_previo.sh (fecha y hora, sin espacios)
previo="$(ls -t estado_previo_*.txt 2>/dev/null | head -1)"
antes="$( [ -n "$previo" ] && sed -n 's/^Hosting [^:]*: //p' "$previo")"
if [ -z "$v" ]; then mal "Hosting" "no se pudo leer la versión publicada"
elif [ -n "$antes" ] && [ "$v" = "$antes" ]; then mal "Hosting" "sigue la MISMA versión de antes (${v##*/}): el paso de Firebase Hosting no publicó"
else bien "Hosting" "versión publicada ${v##*/}${antes:+ (antes ${antes##*/})}"; fi

titulo "5. Errores en los registros (últimos 30 minutos)"
errores="$(g logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --freshness=30m --limit=200 --format=json 2>/dev/null)"
if [ -z "$errores" ]; then aviso "Registros" "no se pudieron leer"
else
  n="$(echo "$errores" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [ "$n" = "0" ]; then bien "Registros" "0 errores en 30 minutos"
  else
    echo "$errores" | python3 -c '
import json, sys, collections
rows = json.load(sys.stdin)
c = collections.Counter((r.get("resource", {}).get("labels", {}).get("service_name", "?"), str(r.get("jsonPayload", {}).get("message") or r.get("textPayload") or "")[:110]) for r in rows)
for (svc, msg), k in c.most_common(10): print(f"     {k:>3} × {svc}: {msg}")'
    if [ "$n" -gt 10 ]; then mal "Registros" "$n errores en 30 minutos (ver arriba los más repetidos)"; else aviso "Registros" "$n error(es) en 30 minutos (ver arriba; pocos y aislados pueden ser normales)"; fi
  fi
fi

imprimir_tabla
echo "Criterio para volver atrás: no se puede iniciar sesión, falla la carga o la impresión, errores 5xx sostenidos, o /health distinto de 200."
echo "Si se cumple: avísale a Claude y, con su recomendación y tu OK, corre: bash deploy/produccion_28oct/vuelta_atras.sh"
