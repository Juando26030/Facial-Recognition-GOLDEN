# 0C · D9 — Librerías de terceros sin `integrity` y traductor en el mismo origen

Estado al 2026-11-03 (rama `fix/0c-lote2-c`).

## Qué se hizo
- **JSZip 3.10.1**: ya no se pide a cdnjs. Se aloja en `static/vendor/jszip-3.10.1.min.js` (con `jszip-LICENSE.txt`), versión fijada, igual que el resto de `static/vendor/`. Lo usan `kiosk_certificados.html` y `kiosk_roster.html`.

## Pendiente (no se pudo calcular el hash)
El entorno de la sesión no tiene salida a `cdnjs.cloudflare.com`, `registry.npmjs.org`, `jsdelivr` ni `unpkg` (el proxy rechaza la conexión), y no hay copia local de estas dos librerías. **No se inventó ningún hash.** Siguen cargándose desde cdnjs SIN `integrity`:

| Página | Librería | URL fijada |
|---|---|---|
| `kiosk_roster.html` | SheetJS (xlsx) 0.18.5 | `https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js` |
| `kiosk_estadisticas.html`, `kiosk_formulario_editor.html` | Chart.js 4.5.1 | `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js` |

Cómo cerrarlo (desde una máquina con internet), cualquiera de las dos:
1. **Preferida:** descargar el archivo exacto, copiarlo a `static/vendor/<nombre>-<versión>.min.js` con su licencia y cambiar la etiqueta a `url_for('static', path='vendor/...')` (quitar la entrada de `EXTERNAL_SCRIPTS_ALLOWED` en `tests/test_fuentes_propias.py`).
2. Calcular el hash: `curl -s <URL> | openssl dgst -sha384 -binary | openssl base64 -A` y poner `integrity="sha384-<hash>" crossorigin="anonymous"` en la etiqueta (cdnjs sirve CORS). Quitar entonces la librería de `PENDIENTES_INTEGRITY` en `tests/test_seguridad_0c_lote2_c.py`.

Las dos solo se cargan en pantallas del PERSONAL autenticado (no en las de asistentes).

## Traductor de Google en `form_public.html`
`templates/form_public.html` inyecta `https://translate.google.com/translate_a/element.js` en el MISMO origen que el formulario público. Es una decisión de producto (política v1.2: botón «Translate», opcional por formulario, solo si el organizador lo deja activo). Riesgo: el script de Google corre con los mismos privilegios que la página (puede leer lo que la persona escribe en los campos, incluida la cédula) y no admite `integrity` porque Google lo cambia sin aviso. Mitigaciones actuales: el widget solo se carga cuando la persona pulsa «Translate»; los datos escritos en los campos no se envían a Google por la app.
No se aisló en un iframe porque el widget traduce el DOM de la página que lo contiene: aislarlo exigiría reemplazar el traductor (por ejemplo traducciones propias de los textos del formulario). Recomendación: tras el piloto, o bien traducciones propias, o bien una CSP que limite `script-src` a `'self'` y `translate.google.com`/`translate.googleapis.com`/`www.gstatic.com` en esa sola página.


## Cierre (3-nov-2026)
SheetJS 0.18.5 (`xlsx.full.min.js`) y Chart.js 4.5.1 (`chart.umd.min.js`) ya llevan `integrity="sha384-..."` + `crossorigin="anonymous"`. El hash se calculó en el navegador de Juan David y se contrastó con el sha512 que publica la API de cdnjs para esas mismas versiones (coinciden). Al subir de versión hay que recalcularlo. Pendiente: el traductor de Google del formulario público (riesgo descrito arriba).
