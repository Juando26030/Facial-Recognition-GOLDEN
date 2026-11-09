#!/usr/bin/env bash
# Borra del remoto las ramas ya integradas en f4/integracion (lista: docs/4B_ramas_integradas_en_f4.txt).
# Seguro: antes de borrar cada una comprueba que esté fusionada en origin/f4/integracion; nunca toca main, migra/fase1-2 ni f4/integracion.
# Requiere permiso de escritura en GitHub (gh auth login, o git con credenciales). Lo corre Juan David.
set -u
cd "$(dirname "$0")/.."
git fetch -q origin
while read -r b; do
  [ -z "$b" ] && continue
  case "$b" in main|migra/fase1-2|f4/integracion) echo "SALTO $b"; continue;; esac
  git rev-parse -q --verify "origin/$b" >/dev/null || { echo "ya no existe: $b"; continue; }
  if git merge-base --is-ancestor "origin/$b" origin/f4/integracion; then
    git push -q origin --delete "$b" && echo "borrada: $b"
  else
    echo "NO fusionada, se deja: $b"
  fi
done < docs/4B_ramas_integradas_en_f4.txt
