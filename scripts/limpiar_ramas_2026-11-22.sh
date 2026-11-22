#!/usr/bin/env bash
# Limpieza de ramas remotas propuesta en docs/revision_2026-11-22/02_codigo_calidad_repo.md §6 (22-nov-2026).
# NADA se borra sin que Juan David lo decida: por defecto este script SOLO LISTA (no toca nada, no necesita red).
#
#   bash scripts/limpiar_ramas_2026-11-22.sh                 # = --solo-listar: qué haría, grupo por grupo
#   bash scripts/limpiar_ramas_2026-11-22.sh --ejecutar      # pregunta por cada grupo (hay que escribir «BORRAR <grupo>»)
#   bash scripts/limpiar_ramas_2026-11-22.sh --ejecutar A    # solo el grupo A (también: B, C1, C2, D; varios separados por espacio)
#
# Por cada rama, EN ESTE ORDEN: 1) etiqueta `archivo/<rama>` en el commit de la rama; 2) se sube la etiqueta; 3) se comprueba que la etiqueta
# quedó en GitHub; 4) solo entonces se borra la rama remota. Recuperar una rama después: `git push origin refs/tags/archivo/<rama>:refs/heads/<rama>`.
# Candados: una rama que ya no está en el commit que vio la revisión (alguien empujó después) NO se toca; las ramas que se conservan
# (lista PROTEGIDAS) nunca se borran aunque alguien las agregue a un grupo por error; si la etiqueta no sube, la rama no se borra.
set -euo pipefail

REMOTE="${REMOTE:-origin}"
MODE=listar
SOLO=()
for a in "$@"; do
  case "$a" in
    --solo-listar) MODE=listar ;;
    --ejecutar) MODE=ejecutar ;;
    A|B|C1|C2|D) SOLO+=("$a") ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Argumento desconocido: $a (usa --solo-listar, --ejecutar y/o A B C1 C2 D)" >&2; exit 2 ;;
  esac
done
[ "${#SOLO[@]}" -gt 0 ] || SOLO=(A B C1 C2 D)

# Se conservan (reporte 02 §6). Las cuatro últimas se borran aparte, DESPUÉS de fusionar la línea de producción a main.
PROTEGIDAS=" main saas/revision-integral feat/inventario-base diag/inventario-base feat/evento-compartido-nube hotfix/subida-formulario-2026-11-21 prod/llaves-escaner-2026-11-20 migra/fase1-2 archivo/corte-main-b5f861b archivo/ramas-borradas-0b-2026-11-02 fix/legal-1-1-borrador fix/offline-recarga diag/verde "

# «rama sha»: el commit (7 caracteres) en que estaba cada rama el 22-nov-2026.
GRUPO_A=(
  "f4/integracion 2c8c4d7"
  "f5/integracion 4a7b153"
  "feat/ajustes-nov11 e0c7ff1"
  "feat/costo-ops 8a55de5"
  "feat/forms-acta 1886f42"
  "feat/historial-instalador 7f2a492"
  "feat/inventario-areas 56f8f8a"
)
DESC_A="ya fusionadas en main (git branch -r --merged origin/main): borrarlas no pierde nada"
GRUPO_B=(
  "crm/c1-cuentas f15242c"
  "crm/c1b-pantallas 9b50cdc"
  "crm/c1c-c4 ec93ee2"
  "crm/importar-aplicar 04c132d"
  "crm/reporte-limpio 24c1935"
  "integ/subcat-crm 2a7167c"
  "diag/tests 2a7167c"
  "almacen/p1-catalogo 3b9ad70"
  "almacen/p2-movimientos f87ebf3"
  "gastos/grafico-barras 9f6b006"
  "feat/crm-implica-inventario 9b829a0"
  "feat/disenador-emergente 37443bf"
  "fix/disenador-movil-compacto 635f6f7"
  "fix/guia-disenador 970dc47"
  "hotfix/descarga-archivos-digitador 3d332ca"
  "prod/bloqueo-wipe 589e21f"
  "prod/categorias-preimpresion 62659c1"
  "prod/categorias-preimpresion-2 7906fc1"
  "prod/disenador-emergente 11caee8"
  "prod/guardado-unificado 145ffd4"
  "prod/recuperados-2026-11-18 43e6fa5"
  "prod/todo-integrado 755f317"
  "prod/integrado-2026-11-18 6bbb581"
  "prod/lector-2026-11-19 f320244"
  "staging/escaner-todo bdd3e0e"
  "staging/llaves-servidor-local cf5347e"
)
DESC_B="ancestros de saas/revision-integral: TODO su contenido está en la rama actual"
GRUPO_C1=(
  "fix/wipe-bloqueo-entorno ef49bb7"
  "feat/subcategorias-codigo d73c244"
  "fix/descarga-archivos-digitador 6c072ab"
  "crm/importar-volcado de9f7de"
  "fix/local-eventos-vista 467b2d2"
  "staging/integracion-mas-p2 5efee9a"
  "ux/base 5a5bcf6"
  "ux/kiosk 448c536"
  "ux/crm 4a7e890"
  "ux/admin 5d11b50"
  "feat/menu-ocultable ce62935"
  "feat/preimpresion 97744de"
  "integracion/legalizaciones-reporte 16f7574"
  "prod/qr-inventario-digital fb83233"
  "staging/integrada-0156 cc22ecb"
  "local/ejecutable-2026-11-18 8914883"
  "staging/integrada 46deb29"
  "staging/lector-cedula 01c5673"
  "fix/precarga-variantes 6f44d78"
  "legalizaciones/formato-excel 9f40267"
  "ux/almacen 1afc06d"
  "ux/evento d65438f"
  "legalizaciones/sobre-crm ac13814"
  "fix/variantes-nombre 670e6ba"
  "feat/prueba-lector-cedula a16683a"
  "ux/inventario 1eced01"
  "f5/base 546ff2e"
  "f5/a-facturado 60aa149"
  "f5/b-encuesta a5a8c5b"
  "f5/c-jornada faf0f19"
  "f5/d-inventario 09ac845"
  "f5/e-historial 0fd4c51"
  "feat/formulario-categoria 0a7fd2e"
  "feat/flujo-categoria 9f77862"
  "feat/preimpresion-estado a80853d"
  "fix/nombre-item-zonas cc298b0"
  "feat/disenador-movil ed0a0e6"
  "fix/obligatorios-categoria 1afd93c"
  "fix/formulario-persona-interruptor b87ea87"
  "ux/guardado-unificado b87ea87"
)
DESC_C1="ramas de trabajo de nov-2026 cuyo contenido llegó por otra rama (0 a 4 commits sin parche equivalente; revisar con git log -p las de >=1)"
GRUPO_C2=(
  "f6/a-descargar a748325"
  "f6/b-token 3dce836"
  "f6/c-cuentas 7f10017"
  "f6/d-instalador a2b0a4c"
  "f7/url-limpia 35847d0"
  "f8/7-cobros 5edbab6"
  "sec/a-local fce327c"
  "sec/b-publico cebec90"
  "sec/c-pagos 494d716"
  "sec/d-eventos 8ffd16b"
  "sec/e-plataforma 0d7aca3"
  "vis/f5-9 f68d54b"
  "ux/cargas b7695e3"
  "feat/cobros-gastos 9bfad47"
  "feat/vcard-ruleta-calendario 4473c59"
  "docs/fase-1-5-plan 2ac0abf"
  "ux/fase-1-7 6493f91"
  "feat/1a-carga-flexible fd22e6e"
)
DESC_C2="ramas de las Fases 5-9 integradas en f5/integracion por reescritura; en producción desde el 11-nov. Mejor DESPUÉS de poner main al día"
GRUPO_D=(
  "ux/fase1-visual e290d77"
  "producto/constancia-puerta 20906f8"
  "producto/impresion-ajustes 196614e"
  "candidato/produccion-25oct 16b32b3"
  "candidato/produccion-28oct 5ff752b"
  "candidato/produccion-29oct 979f2ae"
  "producto/eventos-flujo 6f52ac1"
  "chore/0b-calidad 4e3c793"
  "docs/0b-indice-y-heredado 78a05dd"
  "chore/0c-escaneres 1521393"
  "docs/0c-hallazgos 77c2713"
  "fix/0c-altas e070657"
  "fix/0c-medios 209e411"
  "fix/0c-dependencias 0fe86c6"
  "fix/0c-retest 338339d"
  "fix/0c-setuptools 80a0a0f"
  "docs/0c-cierre 3455d9c"
  "fix/0c-lote2-a df9d65b"
  "fix/0c-lote2-b fea8c55"
  "fix/0c-lote2-c 26dbc49"
  "fix/0c-d9-integrity 81c09e1"
  "fix/0c-escaneres-limpios f2dc127"
  "producto/1a-pr1-medicion 8aec5e0"
  "producto/1a-pr2-search-core 722f04c"
  "producto/1a-pr3-autoimpresion-4a ad897e4"
  "producto/1a-base-diseno f335db1"
  "producto/ahorro-neon 0796cf9"
  "producto/sesion-exencion-acotada e1f4ca3"
  "feat/cupo-cerrado af17243"
  "docs/estandares-visuales 8c23ad4"
  "feat/1a-buscador-unico a515fe6"
  "feat/1a-cola-compartida 5b67d87"
)
DESC_D="línea anterior al corte 0B (oct a 4-nov); fases 0B, 0C y 1A cerradas. Mejor DESPUÉS de poner main al día"

if [ "$MODE" = ejecutar ]; then
  echo "Actualizando referencias de $REMOTE (git fetch --prune)…"
  git fetch --prune "$REMOTE"
fi

total_ok=0; total_skip=0
for g in "${SOLO[@]}"; do
  eval "items=(\"\${GRUPO_${g}[@]}\")"; eval "desc=\$DESC_${g}"
  echo
  echo "=== Grupo $g (${#items[@]} ramas): $desc"
  hacer=0
  if [ "$MODE" = ejecutar ]; then
    read -r -p "¿Etiquetar y borrar el grupo $g? Escribe exactamente «BORRAR $g» (cualquier otra cosa lo salta): " resp
    if [ "$resp" = "BORRAR $g" ]; then hacer=1; else echo "Grupo $g: saltado."; fi
  fi
  for item in "${items[@]}"; do
    rama="${item% *}"; sha="${item#* }"; tag="archivo/$rama"
    case "$PROTEGIDAS" in *" $rama "*) echo "  PROTEGIDA, no se toca: $rama"; total_skip=$((total_skip + 1)); continue ;; esac
    actual="$(git rev-parse --verify --quiet --short=7 "refs/remotes/$REMOTE/$rama" || true)"
    if [ -z "$actual" ]; then echo "  ya no existe en $REMOTE: $rama"; total_skip=$((total_skip + 1)); continue; fi
    if [ "$actual" != "$sha" ]; then echo "  CAMBIÓ desde la revisión ($sha → $actual), no se toca: $rama"; total_skip=$((total_skip + 1)); continue; fi
    if [ "$hacer" != 1 ]; then
      echo "  git tag $tag $REMOTE/$rama && git push $REMOTE refs/tags/$tag && git push $REMOTE --delete refs/heads/$rama    # $sha"
      continue
    fi
    full="$(git rev-parse "refs/remotes/$REMOTE/$rama")"
    if git rev-parse --verify --quiet "refs/tags/$tag" >/dev/null; then
      [ "$(git rev-parse "refs/tags/$tag^{commit}")" = "$full" ] || { echo "  la etiqueta $tag ya existe en OTRO commit, no se toca: $rama"; total_skip=$((total_skip + 1)); continue; }
    else
      git tag "$tag" "refs/remotes/$REMOTE/$rama"
    fi
    git push "$REMOTE" "refs/tags/$tag"
    remoto="$(git ls-remote "$REMOTE" "refs/tags/$tag" | cut -f1)"
    if [ "$remoto" != "$full" ]; then echo "  la etiqueta $tag NO quedó en $REMOTE; la rama se conserva: $rama"; total_skip=$((total_skip + 1)); continue; fi
    git push "$REMOTE" --delete "refs/heads/$rama"
    echo "  borrada: $rama (queda la etiqueta $tag en $sha)"
    total_ok=$((total_ok + 1))
  done
done
echo
if [ "$MODE" = ejecutar ]; then
  echo "Listo: $total_ok ramas etiquetadas y borradas; $total_skip sin tocar."
else
  echo "Modo listado: no se tocó nada. Para hacerlo de verdad: bash scripts/limpiar_ramas_2026-11-22.sh --ejecutar [A B C1 C2 D]"
fi
