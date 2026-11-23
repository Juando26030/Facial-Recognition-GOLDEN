#!/usr/bin/env bash
# Construye el instalador de Windows (GoldenLocal-Setup-<versión>.exe) DESDE LINUX: sirve en Cloud Shell, que ya tiene Docker e internet. No hace falta Windows.
#   bash deploy/windows/build_en_cloudshell.sh            -> deja el .exe en build/windows/out/
# Paso 1 (Python 3.13 en un contenedor): app + Python de Windows + PostgreSQL + WinSW (deploy/windows/build_cross.py).
# Paso 2 (Inno Setup bajo Wine, imagen amake/innosetup): compila el instalador con deploy/windows/GoldenLocal.iss.
set -euo pipefail
cd "$(dirname "$0")/../.."
COMMIT=$(git rev-parse --short=12 HEAD)
VERSION="${1:-$(date +%Y.%m.%d)-$COMMIT}"
echo "== Golden Local $VERSION (commit $COMMIT) =="
docker run --rm -v "$PWD:/repo" -w /repo python:3.13-slim python deploy/windows/build_cross.py "$VERSION" "$COMMIT"
# El contenedor de Inno Setup corre con otro usuario: la carpeta de salida (la creó el paso 1 como root) debe poder escribirla.
docker run --rm -v "$PWD:/repo" python:3.13-slim sh -c "chmod -R a+rwX /repo/build/windows"          # lo creó root dentro del contenedor: se cambia desde otro contenedor
# El .iss lee la versión de una variable de entorno; aquí se fija en una copia para no depender de que Wine la pase.
STAMP=$(date -u +%Y%m%d%H%M%S)          # hora UTC de ESTA construcción: el instalador avisa si se instala encima de algo más nuevo
sed -E -e "s|^#define AppVersion GetEnv\(\"GOLDEN_LOCAL_VERSION\"\)|#define AppVersion \"$VERSION\"|" -e "s|^#define BuildStamp GetEnv\(\"GOLDEN_BUILD_STAMP\"\)|#define BuildStamp \"$STAMP\"|" deploy/windows/GoldenLocal.iss > deploy/windows/GoldenLocal.build.iss
docker run --rm -v "$PWD:/work" amake/innosetup deploy/windows/GoldenLocal.build.iss
rm -f deploy/windows/GoldenLocal.build.iss
echo; echo "Listo. En build/windows/out/:"; ls -lh build/windows/out/
