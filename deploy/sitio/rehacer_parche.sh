#!/usr/bin/env bash
# Regenera deploy/sitio/parche/ cuando el sitio cambió y el parche ya no aplica (o para comprobar que aplica). No publica nada ni toca la nube.
#   bash deploy/sitio/rehacer_parche.sh comprobar            # ¿el parche actual aplica sobre el commit de deploy/sitio/VERSION?
#   bash deploy/sitio/rehacer_parche.sh abrir                # deja en build/sitio/parche-trabajo el sitio en VERSION con el parche aplicado (con «git apply --3way»: marca los choques)
#   bash deploy/sitio/rehacer_parche.sh guardar              # tras arreglar los choques a mano allí, escribe el parche nuevo en deploy/sitio/parche/
# SITIO_LOCAL=<carpeta con un clon de golden-sitio-web> evita clonar de GitHub.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
VERSION="$(tr -d ' \r\n' < deploy/sitio/VERSION)"
SITIO_REPO="${SITIO_LOCAL:-${SITIO_REPO:-https://github.com/Juando26030/golden-sitio-web.git}}"
T="$ROOT/build/sitio/parche-trabajo"
shopt -s nullglob; PARCHES=("$ROOT"/deploy/sitio/parche/*.patch); shopt -u nullglob
traer() { rm -rf "$T"; mkdir -p "$(dirname "$T")"; git clone -q "$SITIO_REPO" "$T"; git -C "$T" checkout -q --detach "$VERSION"; }
case "${1:-}" in
  comprobar)
    traer
    for p in "${PARCHES[@]}"; do git -C "$T" apply --check "$p" && echo "APLICA LIMPIO: $(basename "$p") sobre ${VERSION:0:7}"; done
    [ "${#PARCHES[@]}" -gt 0 ] || echo "No hay parche: nada que comprobar." ;;
  abrir)
    traer
    for p in "${PARCHES[@]}"; do git -C "$T" apply --3way "$p" || echo "Hay choques: ábrelos en $T (busca <<<<<<<), arréglalos y corre «guardar»."; done
    echo "Copia de trabajo: $T" ;;
  guardar)
    [ -d "$T/.git" ] || { echo "Primero corre «abrir»." >&2; exit 1; }
    if grep -rIl --exclude-dir=.git --exclude-dir=node_modules '^<<<<<<< ' "$T" >/dev/null 2>&1; then echo "Aún hay choques sin resolver en $T." >&2; exit 1; fi
    git -C "$T" add -A
    if git -C "$T" diff --cached --quiet; then rm -f "$ROOT"/deploy/sitio/parche/*.patch; echo "Sin diferencias: el sitio ya trae todo. deploy/sitio/parche quedó vacío."; exit 0; fi
    git -C "$T" -c user.name="Parche de montaje" -c user.email="noreply@golden-eventos.com" commit -q -m "Parche de montaje en golden-eventos.com sobre ${VERSION:0:7}"
    rm -f "$ROOT"/deploy/sitio/parche/*.patch
    git -C "$T" format-patch --binary -1 --stdout > "$ROOT/deploy/sitio/parche/0001-montaje-golden-eventos.patch"
    echo "Parche nuevo: deploy/sitio/parche/0001-montaje-golden-eventos.patch (revísalo y súbelo en un commit de la plataforma)." ;;
  *) echo "Uso: $0 comprobar|abrir|guardar" >&2; exit 2 ;;
esac
