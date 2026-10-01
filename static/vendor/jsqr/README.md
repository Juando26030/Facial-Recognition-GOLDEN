# jsQR (copia propia, sin CDN)

- Paquete: `jsqr` 1.4.0 del registro npm (https://registry.npmjs.org/jsqr/-/jsqr-1.4.0.tgz), repositorio https://github.com/cozmo/jsQR
- Archivo: `jsQR.js` = `package/dist/jsQR.js` TAL CUAL (sin modificar; byte a byte igual al del paquete). `LICENSE` = el del paquete.
- Integridad del paquete (npm): `sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==`
- SHA-256 de `jsQR.js`: `bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859` (lo comprueba `tests/test_local_roster.py`).
- **Licencia: Apache-2.0** (campo `license` del paquete y texto de `LICENSE`; NO es MIT). Al redistribuirlo se conserva el `LICENSE` y no se modifica el archivo; el paquete no trae archivo NOTICE.
- Uso: `static/js/qr.js` lo carga bajo demanda desde `/static/vendor/jsqr/jsQR.js` cuando el navegador no tiene `BarcodeDetector` (Safari/iPad); el service worker del quiosco lo guarda en la primera visita.
- Para actualizar: bajar la nueva versión con `npm pack jsqr`, reemplazar `jsQR.js` y `LICENSE`, y actualizar la versión (`QrScanner.JSQR_URL` en `qr.js`), este archivo y el hash de la prueba.
