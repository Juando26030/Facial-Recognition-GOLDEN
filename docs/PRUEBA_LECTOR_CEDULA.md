# Prueba: lector de cédula por cámara (PDF417)

**Ruta:** `/pruebas/lector-cedula` (por ejemplo `https://app.golden-eventos.com/pruebas/lector-cedula`). Requiere sesión del personal (digitador o más).

**Qué es:** la página de un solo archivo entregada el 19-nov-2026 (versión 3), servida **tal cual** desde `app/pruebas/lector_cedula.html`
(`tests/test_lector_cedula_prueba.py` fija su huella SHA-256). Lee el PDF417 del reverso de la cédula colombiana con la cámara en vivo o con una foto y
muestra `cédula,nombre1,nombre2,apellido1,apellido2,AAAAMMDD`. **Todo se procesa en el navegador: no llama a ninguna API de la app, no guarda nada y no toca la base de datos.**

**Dependencia externa:** descarga `zxing-wasm@3.1.3` desde `cdn.jsdelivr.net` (respaldo `unpkg.com`). La ruta fija su propia política CSP «Report-Only» que lo permite;
si más adelante se quiere sin CDN, copiar `zxing_reader.wasm` y el JS a `static/` y cambiar las URLs en el archivo (y actualizar la huella del test).

**Cómo probar:** abrir la ruta en el celular (HTTPS, cámara permitida: la app ya envía `Permissions-Policy: camera=(self)`) y usar «Abrir cámara» o «Tomar foto» con la cédula física.

**Datos personales:** la cédula es dato personal. Esta prueba no registra nada; no se debe conectar a registros de personas sin la autorización y el consentimiento que exige el proyecto.
**Para retirarla:** borrar la ruta en `app/main.py`, `app/pruebas/` y `tests/test_lector_cedula_prueba.py`.


## Pestaña «Cédula nueva» (las 3 líneas de abajo) — 19-nov-2026
La página tiene dos pestañas: **Cédula vieja** (código de barras PDF417, el lector de siempre, sin cambios) y **Cédula nueva**. La nueva no usa el QR (va cifrado):
lee con OCR las **3 líneas de letras, números y «<»** del reverso (zona legible por máquina, formato TD1 de la OACI) y devuelve el mismo formato
`cédula,nombre1,nombre2,apellido1,apellido2,AAAAMMDD` (además muestra sexo, vencimiento y n.º de documento).

- **No depende de posiciones fijas:** la cédula es lo que sigue a `COL` en la línea 2 hasta el siguiente `<`; los nombres se separan por `<<` (apellidos | nombres) y `<`.
  Las líneas pueden llegar en cualquier orden y la cédula puede tener 6–11 dígitos.
- **Confiabilidad:** los dígitos de control (7-3-1) validan nacimiento, vencimiento, n.º de documento y el control general (que cubre la cédula). Los nombres no tienen control:
  se aceptan al verlos **iguales en dos cuadros** (o con confianza alta en uno). Si los controles no cuadran, el resultado sale como «aproximado, verifica».
- **Cámara:** recuadro guía fijo (3 renglones de ayuda), endereza la inclinación, separa las 3 líneas, enfoca por nitidez relativa y lee en cuanto está enfocado. Si la cédula está al revés, prueba girada 180°.
  «Diagnóstico» muestra las 3 líneas como las ve el OCR y el texto leído. «Tomar foto»/«Galería» localizan las 3 líneas en cualquier parte y orientación de la foto.
- **Dependencia externa:** `tesseract.js@5.1.1` y el idioma `eng` (`@tesseract.js-data/eng`) desde `cdn.jsdelivr.net` (respaldo `unpkg.com`); se descargan la primera vez (~5–10 MB) y quedan en caché del navegador.
  Un trabajador de OCR por línea, cada uno con su lista de caracteres permitidos (línea 2 solo dígitos y `MFCOLX<`; línea 3 solo letras y `<`).
- **Pruebas:** `node tests/js/mrz_parser_check.js` (parser, datos sintéticos). El OCR en sí se valida con cédulas físicas en el celular (no hay datos reales en el repo).


## Quiosco: Registro → «Escanear» (cédula vieja · cédula nueva · QR) — 19-nov-2026
El botón **Escanear** (junto a «Registrar nuevo» en `/kiosk/<evento>/registro`) abre la MISMA ventana de cámara de siempre (`static/js/qr.js`, `QrScanner.open`), ahora con un selector
**Cédula vieja · Cédula nueva · QR** (`modes`). El diseño no cambia; se recuerda el último modo elegido (`localStorage`, clave `gw_scan_mode`; por defecto QR).

- **QR:** exactamente lo de antes (QR de escarapela/dinámico, y el PDF417 por `BarcodeDetector` si el navegador lo trae; el botón «Foto del reverso» sigue ahí, solo en este modo).
- **Cédula vieja / nueva:** al elegirlas se carga `static/js/cedula-readers.js` (los mismos lectores de la página de prueba) con recuadro guía sobre el video. El resultado entra por el mismo camino que el PDF417 de siempre:
  `directorySearch.submitScannedCedula(cédula, {nombres, apellidos})`. La misma cédula quieta frente a la cámara no se envía dos veces (4 s) y tras cada lectura sigue con la siguiente persona.
  **Cédula nueva solo entrega lecturas VERIFICADAS** (dígitos de control en regla, incluido el general que cubre la cédula, y nombres confirmados): para acreditar a alguien no se acepta una lectura «aproximada».
- **Fuente única:** `static/js/cedula-readers.js` está GENERADO desde `app/pruebas/lector_cedula.html` (`python scripts/build_cedula_readers.py`); `tests/js/mrz_parser_check.js` falla si quedó desactualizado.
  Cualquier ajuste al lector se hace en la página de prueba y se regenera.
- **Sin CDN / sin internet (pendiente):** hoy zxing-wasm, tesseract.js y el idioma se bajan del CDN la primera vez (y quedan en caché del navegador). `scripts/vendor_cedula_readers.sh` (correr una vez con internet) deja
  una copia propia en `static/vendor/cedula/` que los lectores usan primero. **Ese script no se ha ejecutado** (el entorno de desarrollo no tiene red). Sin esa copia, el modo cédula necesita internet la primera vez en cada dispositivo;
  el modo QR sigue funcionando sin red como siempre.
- **CSP:** la política «Report-Only» del panel ahora lista `cdn.jsdelivr.net`/`unpkg.com` (script/connect) y `'wasm-unsafe-eval'`; no bloquea nada.
