#!/usr/bin/env bash
# Firma el instalador (.exe) con un certificado de firma de código para que Windows no muestre «Windows protegió su PC» (SmartScreen).
#   GW_SIGN_PFX=/ruta/certificado.pfx bash deploy/windows/firmar_instalador.sh build/windows/out/GoldenLocal-Setup-<v>.exe
# La contraseña del .pfx se pide en pantalla a ciegas (nunca va en el repo, en el chat ni en variables). Usa osslsigncode dentro de Docker.
# Certificado: de una autoridad reconocida (DigiCert, Sectigo, SSL.com…). Con uno EV (token/HSM en la nube) SmartScreen confía de inmediato; con uno OV
# la reputación se gana con las descargas. Ver docs/20_FIRMA_INSTALADOR.md.
set -euo pipefail
EXE="${1:?Uso: GW_SIGN_PFX=cert.pfx bash deploy/windows/firmar_instalador.sh <instalador.exe>}"
PFX="${GW_SIGN_PFX:?Falta GW_SIGN_PFX (ruta del certificado .pfx)}"
[ -f "$EXE" ] && [ -f "$PFX" ] || { echo "No encuentro el instalador o el certificado."; exit 2; }
read -r -s -p "Contraseña del certificado: " PW; echo
OUT="${EXE%.exe}-firmado.exe"
docker run --rm -e PW="$PW" -v "$(cd "$(dirname "$EXE")" && pwd):/in" -v "$(cd "$(dirname "$PFX")" && pwd)/$(basename "$PFX"):/cert.pfx:ro" ubuntu:24.04 bash -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq osslsigncode >/dev/null &&
  osslsigncode sign -pkcs12 /cert.pfx -pass "$PW" -n "Golden Local" -i "https://golden-eventos.com" -h sha256 \
    -ts http://timestamp.digicert.com -in "/in/'"$(basename "$EXE")"'" -out "/in/'"$(basename "$OUT")"'" &&
  osslsigncode verify -in "/in/'"$(basename "$OUT")"'" | tail -3'
unset PW
mv -f "$OUT" "$EXE"
echo "Firmado: $EXE"
