#!/usr/bin/env bash
# Deja una copia PROPIA del lector ZXing (WebAssembly, licencia Apache-2.0) en static/vendor/zxing/ para que el escáner de la cámara lea la cédula VIEJA (PDF417) y los QR en cualquier
# navegador y sin internet. Se corre UNA vez, desde un equipo con internet (Cloud Shell sirve), en la raíz del repo:
#     bash scripts/vendor_zxing.sh
# Después: git push a la rama que se vaya a desplegar (el script deja el commit hecho). La versión queda fijada en la 2.x más reciente; si cambia el nombre de algún archivo, el script avisa.
set -euo pipefail
cd "$(dirname "$0")/.."
VER="${ZXING_WASM_VERSION:-2}"                     # rango de npm: la 2.x más reciente; para fijar una exacta: ZXING_WASM_VERSION=2.2.1 bash scripts/vendor_zxing.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
( cd "$TMP" && npm pack "zxing-wasm@${VER}" --silent >/dev/null && tar -xzf zxing-wasm-*.tgz )
PKG="$TMP/package"
JS="$(find "$PKG/dist" -path '*iife*reader*' -name 'index.js' | head -1 || true)"
WASM="$(find "$PKG/dist" -name 'zxing_reader.wasm' | head -1 || true)"
if [ -z "$JS" ] || [ -z "$WASM" ]; then echo "ERROR: no encontré el lector (IIFE) o el .wasm dentro del paquete zxing-wasm. Archivos disponibles:" >&2; find "$PKG/dist" -maxdepth 3 | head -40 >&2; exit 1; fi
DEST=static/vendor/zxing
mkdir -p "$DEST"
cp "$JS" "$DEST/zxing-reader.js"
cp "$WASM" "$DEST/zxing_reader.wasm"
[ -f "$PKG/LICENSE" ] && cp "$PKG/LICENSE" "$DEST/ZXING-WASM-LICENSE.txt"
echo "zxing-wasm $(sed -n 's/.*"version": "\(.*\)".*/\1/p' "$PKG/package.json" | head -1)" > "$DEST/VERSION.txt"
grep -q "ZXingWASM" "$DEST/zxing-reader.js" || { echo "AVISO: el lector no declara la variable global ZXingWASM; revisa la versión de zxing-wasm" >&2; }
git add "$DEST" && git commit -m "Lector universal ZXing (PDF417 y QR) copiado a static/vendor/zxing ($(cat "$DEST/VERSION.txt"))" >/dev/null && echo "Listo: commit hecho. Ahora súbelo con git push."
