#!/usr/bin/env bash
# ANOTA el estado de producción JUSTO ANTES de desplegar (25-oct-2026) y deja listo «vuelta_atras.sh» con esos valores escritos.
# Solo lectura en la nube: lee las revisiones de los servicios, la imagen de los Jobs y la versión del hosting. Escribe dos archivos AQUÍ (en Cloud Shell).
# Uso:  bash deploy/produccion_25oct/anotar_estado_previo.sh
# shellcheck disable=SC2015  # «bien» y «mal» siempre terminan bien: «A && bien || mal» es seguro aquí
set -u
cd "$(dirname "$0")" || exit 1
# shellcheck source=comun.sh
source ./comun.sh

FECHA="$(date +%Y%m%d-%H%M%S)"
ARCHIVO="estado_previo_${FECHA}.txt"

titulo "Leyendo el estado actual de $PROYECTO…"
declare -A REV IMG
falta=0
for s in $SERVICIOS; do
  REV[$s]="$(revision_con_trafico "$s")"
  [ -n "${REV[$s]}" ] && echo "   $s -> ${REV[$s]}" || { echo "   ❌ no se pudo leer la revisión de $s"; falta=1; }
done
for j in $JOBS; do
  IMG[$j]="$(imagen_job "$j")"
  [ -n "${IMG[$j]}" ] && echo "   Job $j -> ${IMG[$j]##*/}" || { echo "   ❌ no se pudo leer la imagen del Job $j"; falta=1; }
done
HOSTING="$(version_hosting_actual)"
[ -n "$HOSTING" ] && echo "   Hosting -> ${HOSTING##*/}" || { echo "   ❌ no se pudo leer la versión del hosting"; falta=1; }
if [ "$falta" = 1 ]; then echo; echo "No se escribió nada: falta algún dato. Revisa los ❌ (permisos o sesión) y vuelve a correr este script."; exit 1; fi

{
  echo "Estado de producción antes del despliegue — $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Proyecto: $PROYECTO   Región: $REGION"
  for s in $SERVICIOS; do echo "Servicio $s: ${REV[$s]}"; done
  for j in $JOBS; do echo "Job $j: ${IMG[$j]}"; done
  echo "Hosting $SITIO_HOSTING: $HOSTING"
} > "$ARCHIVO"

# --------------------------------------------------------------- vuelta_atras.sh con los valores ya escritos
cat > vuelta_atras.sh <<EOF
#!/usr/bin/env bash
# VUELTA ATRÁS del despliegue a producción del 25-oct-2026. GENERADO por anotar_estado_previo.sh el $(date '+%Y-%m-%d %H:%M:%S').
# Devuelve el tráfico de los tres servicios a las revisiones anotadas y (si lo confirmas aparte) los Jobs a su imagen anterior.
# Las migraciones 0069-0071 se QUEDAN: el código anterior funciona con ellas (probado en local el 25-oct-2026).
# Uso:  bash deploy/produccion_25oct/vuelta_atras.sh
set -u
cd "\$(dirname "\$0")" || exit 1
# shellcheck source=comun.sh
source ./comun.sh

echo "Esto devolverá el tráfico de producción ($PROYECTO) a:"
echo "   golden-web       -> ${REV[golden-web]}"
echo "   golden-publico   -> ${REV[golden-publico]}"
echo "   golden-biometria -> ${REV[golden-biometria]}"
read -r -p "Escribe VOLVER ATRAS (en mayúsculas) para continuar: " r
[ "\$r" = "VOLVER ATRAS" ] || { echo "Cancelado: no se cambió nada."; exit 1; }

g run services update-traffic golden-web       --region "$REGION" --to-revisions="${REV[golden-web]}=100"
g run services update-traffic golden-publico   --region "$REGION" --to-revisions="${REV[golden-publico]}=100"
g run services update-traffic golden-biometria --region "$REGION" --to-revisions="${REV[golden-biometria]}=100"
echo "✅ Tráfico devuelto a las revisiones anteriores."

read -r -p "¿Volver también los Jobs (carga masiva y operaciones) a su imagen anterior? Escribe SI para hacerlo: " r
if [ "\$r" = "SI" ]; then
  g run jobs update golden-bulk --region "$REGION" --image "${IMG[golden-bulk]}"
  g run jobs update golden-ops  --region "$REGION" --image "${IMG[golden-ops]}"
  echo "✅ Jobs devueltos a su imagen anterior (el de migraciones no hace falta: no se vuelve a correr)."
else
  echo "Jobs sin cambios."
fi

echo
echo "FIREBASE HOSTING (a mano, 1 minuto):"
echo "   Consola de Firebase -> Hosting -> sitio $SITIO_HOSTING -> «Historial de versiones»"
echo "   -> busca la versión ${HOSTING##*/} -> menú ⋮ -> «Revertir» (Rollback)."
echo "   (Las rutas nuevas, como /api/bulk_roster, no las usa el código anterior: no estorban si tardas en revertir el hosting.)"
echo
echo "Después: bash deploy/produccion_25oct/verificar_despues.sh"
EOF
chmod +x vuelta_atras.sh

echo
echo "✅ Estado anotado en: $(pwd)/$ARCHIVO"
echo "✅ Vuelta atrás lista en: $(pwd)/vuelta_atras.sh (pide confirmación escrita antes de actuar)"
echo "Guarda una copia de $ARCHIVO fuera de Cloud Shell (por ejemplo, pégalo en el chat con Claude)."
