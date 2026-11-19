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
