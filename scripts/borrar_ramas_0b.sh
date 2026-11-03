#!/usr/bin/env bash
# Borra del remoto las ramas aprobadas en 0B (docs/0B_ramas_borradas_lista.txt), SOLO si su punta ya está dentro de
# origin/main o de origin/archivo/ramas-borradas-0b-2026-11-02. Si alguna no cumple, la salta y lo dice.
# Uso:  bash scripts/borrar_ramas_0b.sh          (simulacro: solo muestra)
#       bash scripts/borrar_ramas_0b.sh --borrar (borra de verdad)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin 'refs/heads/*:refs/remotes/origin/*'
ok=0; salto=0
while read -r b; do
  [ -z "$b" ] && continue
  git rev-parse -q --verify "origin/$b" >/dev/null || { echo "ya no existe: $b"; continue; }
  if git merge-base --is-ancestor "origin/$b" origin/main || git merge-base --is-ancestor "origin/$b" origin/archivo/ramas-borradas-0b-2026-11-02; then
    if [ "${1:-}" = "--borrar" ]; then git push -q origin --delete "$b" && echo "borrada: $b"; else echo "se borraría: $b"; fi
    ok=$((ok+1))
  else
    echo "SALTADA (tiene commits que no están en main ni en el archivo): $b"; salto=$((salto+1))
  fi
done < docs/0B_ramas_borradas_lista.txt
echo "listo: $ok ok, $salto saltadas"
