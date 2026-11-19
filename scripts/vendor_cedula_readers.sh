#!/usr/bin/env bash
# Copia PROPIA de las librerías de los lectores de cédula (zxing-wasm para el código de barras, tesseract.js + idioma «eng» para las 3 líneas),
# para que el escáner del quiosco funcione sin CDN y sin internet. Hoy, si esta carpeta no existe, los lectores usan cdn.jsdelivr.net (respaldo unpkg.com).
# Correr UNA vez, en una máquina con internet y Node/npm:   bash scripts/vendor_cedula_readers.sh   y luego commitear static/vendor/cedula/.
# (Este script NO se ha ejecutado desde el entorno de desarrollo, que no tiene red: revisar la salida y probar el escáner en staging.)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=static/vendor/cedula
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rm -rf "$OUT"; mkdir -p "$OUT/zxing" "$OUT/tesseract" "$OUT/tesseract-core" "$OUT/tesseract-lang"
( cd "$TMP"
  npm pack zxing-wasm@3.1.3 tesseract.js@5.1.1 tesseract.js-core@5.1.1 @tesseract.js-data/eng@1.0.0 >/dev/null
  for f in *.tgz; do d="x-${f%.tgz}"; mkdir "$d"; tar -xzf "$f" -C "$d"; done )
cp -r "$TMP"/x-zxing-wasm-*/package/dist/. "$OUT/zxing/"                                   # iife/reader/index.js + reader/zxing_reader.wasm (el lector deduce la ruta del .wasm desde el .js)
cp "$TMP"/x-tesseract.js-5*/package/dist/tesseract.min.js "$TMP"/x-tesseract.js-5*/package/dist/worker.min.js "$OUT/tesseract/"
cp "$TMP"/x-tesseract.js-core-*/package/*.js "$OUT/tesseract-core/"; cp "$TMP"/x-tesseract.js-core-*/package/*.wasm "$OUT/tesseract-core/" 2>/dev/null || true
cp "$TMP"/x-tessjs-data-eng-*/package/4.0.0_best_int/eng.traineddata.gz "$OUT/tesseract-lang/" 2>/dev/null || cp "$TMP"/x-*data-eng-*/package/4.0.0_best_int/eng.traineddata.gz "$OUT/tesseract-lang/"
for lic in "$TMP"/x-*/package/LICENSE*; do [ -f "$lic" ] && cp "$lic" "$OUT/LICENSE-$(basename "$(dirname "$(dirname "$lic")")" | sed 's/^x-//').txt"; done 2>/dev/null || true
( cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
echo "Listo: $OUT ($(du -sh "$OUT" | cut -f1)). Archivos:"; find "$OUT" -type f | sort
