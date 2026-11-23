# Plan 08 · CSP estricta (política de seguridad de contenido)

Fecha: 23-nov-2026 · Rama `saas/revision-integral` · Es un PLAN (no hay código nuevo). Lo ejecuta otro desarrollador; lo que decide Juan David está al final.
Antecedentes: `docs/FASE_3_SEGURIDAD.md` §(f) y «CSP estricto: decisión del 8-nov-2026»; hallazgo 2 de `docs/revision_2026-11-22/03_seguridad_nube.md`; Fase 6, punto 5, de `docs/revision_2026-11-22b/00_PLAN_SEGUNDA_PASADA.md`.

## 0. En palabras sencillas (para Juan David)

- Una CSP es una lista que le dice al navegador: «solo ejecuta programas (scripts) que vengan de estos sitios y de esta manera». Si alguien lograra meter código malicioso en una página (XSS), una CSP estricta hace que el navegador **se niegue a ejecutarlo**. Es una segunda llave de seguridad.
- **Hoy la plataforma tiene la CSP en modo «solo avisar»** (no bloquea nada) y, además, esa política **permite scripts en línea (`'unsafe-inline'`)**, que es justo lo que un atacante necesitaría. Es decir: hoy la política protege contra sacar datos hacia sitios raros, pero **no frena un script inyectado**.
- Pasar a estricta requiere dos cosas: (1) quitar o «firmar» los **51 bloques de código en línea** que tienen las pantallas y (2) comprobar, midiendo, que nada de lo que la gente usa (imprimir escarapelas, leer cédulas, mapas, pagos) se rompe.
- El plan va por etapas, **midiendo primero sin bloquear**. Nada cambia en producción sin su autorización.

## 1. Cabeceras actuales (verificado)

### 1.1 En la aplicación: `app/main.py`, middleware `security_headers` (líneas 271-296)
| Cabecera | Valor | Nota |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Siempre. |
| `X-Frame-Options` | `SAMEORIGIN` | No se pone en `/f/*` ni en formularios públicos (se incrustan en el sitio del cliente a propósito). |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | |
| `Permissions-Policy` | `camera=(self), microphone=(), geolocation=(self), payment=(self)` | |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Solo con `IS_PRODUCTION`. |
| `Content-Security-Policy` (OBLIGATORIA) | `frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'` (sin `frame-ancestors` en formularios públicos) | **No restringe scripts.** Los SVG llevan `default-src 'none'; style-src 'unsafe-inline'; sandbox`. |
| `Content-Security-Policy-Report-Only` | La política completa del panel (`_CSP_PANEL`, líneas 242-245) o la del formulario público (`_CSP_PUBLIC_FORM`, líneas 246-250) | Encendida por omisión: `CSP_REPORT_ONLY` vale `"1"` si no se define (línea 241) y **no está en `deploy/gcp/env/common.yaml` ni en `.env.example`** (búsqueda hecha). **No tiene `report-uri`**: nadie recibe los avisos; solo salen en la consola del navegador. |

Política del panel en modo reporte (`_CSP_PANEL`): `default-src 'self'`; `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com`; `style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com`; `img-src 'self' data: blob: https://tile.openstreetmap.org https://cdnjs.cloudflare.com`; `font-src 'self' data:`; `media-src 'self' blob:`; `connect-src 'self' https://nominatim.openstreetmap.org https://storage.googleapis.com https://cdn.jsdelivr.net https://unpkg.com`; `frame-src 'self' blob:`; `worker-src 'self' blob:`; más `object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'`.
Política del formulario público (`_CSP_PUBLIC_FORM`): igual de abierta en scripts (`'unsafe-inline'`), con Wompi (`checkout.wompi.co`, `*.wompi.co`), Google Translate (`translate.google.com`, `translate.googleapis.com`, `www.gstatic.com`), sin `wasm-unsafe-eval` y sin `frame-ancestors`.
Ruta de prueba del lector de cédula: política propia en modo reporte (`_LECTOR_CEDULA_CSP`, línea 992; la respuesta está en la línea 1004).

### 1.2 En Firebase Hosting
- Aplicación (`deploy/firebase/make_config.py`, línea 39): la única cabecera que agrega es `Cache-Control: public, max-age=3600` para `/static/**`. **No agrega ninguna cabecera de seguridad**; todo lo anterior lo pone la aplicación (Cloud Run). Los archivos de `/static/**` los sirve Hosting directamente y por tanto **no llevan CSP** (no hace falta: no son documentos).
- Sitio corporativo (`deploy/sitio/firebase.json`): `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` (cámara, micrófono y geolocalización apagados). **No tiene CSP** (búsqueda hecha). Fuera del alcance de este plan, salvo la nota de la etapa 6.

### 1.3 Lo que fija hoy una prueba
`tests/test_seguridad_fase3b.py` (función `test_f_csp_enforced_has_form_action_and_report_only_has_script_src`) y `tests/test_csp_trinquete.py` (la deuda de JavaScript en línea solo puede bajar).

## 2. Inventario real (contado el 23-nov-2026 sobre `templates/` y `static/`)

Contado con un script de lectura (expresiones regulares sobre los archivos); coincide con el trinquete (51 y 1).

### 2.1 Scripts en línea
- **51 bloques `<script>` sin `src` en 30 plantillas** (los `application/json` no cuentan). Los que más pesan: `kiosk_registro.html` 8, `kiosk_parametros.html` 6, `_gw_head.html` 3 (esta se incluye en prácticamente todas las pantallas del panel), `badge_editor.html` 3, y 2 cada una `kiosk_estadisticas`, `kiosk_formulario_editor`, `kiosk_roster`, `kiosk_ruleta`, `kiosk_ruleta_visual`.
- Tamaño: `kiosk_formulario_editor.html` 163.158 caracteres en bloques en línea; `badge_editor.html` 68.794; `kiosk_parametros.html` 65.975; `_event_edit_modal.html` 43.006; `calendario.html` 40.460; `kiosk_roster.html` 40.601. Los demás son pequeños (por ejemplo `_gw_head.html`: 574, 130 y 121 caracteres; `_sidebar.html`: 2.370).
- **37 de los 51 bloques usan Jinja por dentro** (`{{ … }}` o `{% … %}`), en 26 plantillas; es decir, no se pueden cambiar a un archivo estático tal cual: sus datos hay que pasarlos por `data-*` o por un bloque `application/json`. Ejemplos: `_gw_head.html` (`{{ url_for('static', path='js/gw-carga.js') }}` y `request.session.get('tours_off')`), `badge_print.html` (`{{ event.id }}`, `{{ print_user_id_json | safe }}`, `{{ print_users_json | safe }}`), `form_public.html` (`{{ event_id }}`, `{{ slug }}`).
- **1 manejador en línea:** `templates/badge_print.html` (`onclick="window.close()"`).
- `eval(` y `new Function(` en `static/js`: **0** (búsqueda hecha). `javascript:` y `onclick=` dentro de textos de JavaScript: 0.

### 2.2 Estilos en línea
- **59 atributos `style="…"` en 7 plantillas**: `form_public.html` 36, `digital_badge.html` 13, `_legal_footer.html` 5, `certificate_public.html` 2, `aceptar.html` 1, `certificado_local.html` 1, más 1 en otra.
- **14 bloques `<style>` en 11 plantillas.**
- **Estilos creados por JavaScript:** 102 líneas con `style="` dentro de textos de JavaScript en 15 archivos de `static/js/` (los mayores: `variant-table-ui.js` 26, `field-render.js` 21, `form-render.js` 16, `clockpicker.js` 10, `certificate-link.js` 9, `shared-print.js` 8) y **9 archivos que crean elementos `<style>`** (`font-picker.js`, `analytics-dashboard.js`, `form-render.js`, `shared-print.js`, `rich-text.js`, `contingency.js`, `almacen-etiquetas.js`, `toast.js`, `event-transfer.js`).
- **La impresión de escarapelas y etiquetas escribe `@page` con JavaScript dentro de un `<style>`:** `static/js/badge-render.js` línea 163 (`pageStyle.innerHTML = '@page { size: …mm …mm; margin: 0; } @media print …'`), `static/js/label-compose.js` línea 94 (`pageCss`), `static/js/almacen-etiquetas.js` línea 39 (`st.textContent = '@page { size: 62mm …'`). **Esto es lo que impide quitar `'unsafe-inline'` de `style-src`** (ver §6).
- El servidor también escribe estilos: `app/main.py` `golden_logo_attrs()` devuelve un atributo `style` y `app/brandcolor.py` `css()` el contenido de un `<style>` con el color de marca de cada evento.

### 2.3 Orígenes externos
**En plantillas (`<script src>` / `<link>`):** 4 referencias, todas a `https://cdnjs.cloudflare.com` y todas con SRI (`integrity`): Chart.js 4.5.1 en `form_stats.html`, `kiosk_estadisticas.html` y `kiosk_formulario_editor.html`, y SheetJS (xlsx) 0.18.5 en `kiosk_roster.html`. Además: un enlace de texto a `https://wompi.statuspage.io` (no carga nada).
**Cargados desde JavaScript:**
| Origen | Quién | Para qué |
|---|---|---|
| `https://cdnjs.cloudflare.com` | `static/js/gw-map.js` (líneas 13-15, con SRI) | Mapa Leaflet 1.9.4 |
| `https://tile.openstreetmap.org`, `https://nominatim.openstreetmap.org` | `static/js/gw-map.js` líneas 16-17 | Mosaicos del mapa y búsqueda de direcciones |
| `https://cdn.jsdelivr.net` y `https://unpkg.com` | `static/js/cedula-readers.js` líneas 206-207 y 924-925 | `zxing-wasm` (lector PDF417) y `tesseract.js` con sus datos de idioma, con el segundo como respaldo del primero |
| `https://translate.google.com` (+ `translate.googleapis.com`, `www.gstatic.com`) | `templates/form_public.html` línea 102 | Traductor, solo si la persona lo activa |
| `https://checkout.wompi.co` | `app/wompi.py` línea 21 (`WIDGET_URL`) | Botón de pago |
| `https://storage.googleapis.com` | permitido en `connect-src` | Subida directa de archivos con URL firmada (uso no verificado en esta revisión) |
**Propios del repositorio (mismo origen, no necesitan permiso):** `static/vendor/` con html2canvas 1.4.1, jsPDF 2.5.1, JSZip 3.10.1, JsBarcode 3.12.3, qrcode-generator 1.4.4 y jsQR.

### 2.4 Lo que la política actual permite y no debería
- `script-src` admite `https://cdn.jsdelivr.net` y `https://unpkg.com`: son sitios que sirven **cualquier paquete de npm**; permitir su dominio entero permite a un atacante cargar un script suyo desde ahí. Es una vía conocida para saltarse una CSP. (Una afirmación de práctica común de seguridad web; no la probé en esta plataforma.)
- `cdnjs.cloudflare.com` hospeda muchas librerías antiguas; el riesgo es menor pero el mismo tipo.
- Se usan solo para el lector de cédula; la solución es llevar `zxing-wasm`, `tesseract.js` (y sus datos de idioma), Chart.js, SheetJS y Leaflet a `static/vendor/` con su licencia, como ya se hizo con las otras librerías.

## 3. Plan por etapas

Regla de todas las etapas: primero staging (`goldenweb-staging`; queda apagado por defecto, se enciende solo para probar, `bash deploy/gcp/staging_power.sh`), luego producción solo con autorización de Juan David para ESA acción. Las corridas de la suite completa de GitHub, una sola vez al final.

### Etapa 1 · Que los avisos lleguen (4-6 h) — es el «Report-Only con endpoint de reporte»
1. **Ruta nueva `POST /api/csp-report`** (`app/routers/ops.py` o un router nuevo `app/routers/csp_report.py`), pública (el navegador la llama sin sesión), con estas reglas:
   - Cuerpo máximo 8 KiB: agregar la ruta a `limit_for` en `app/bodylimit.py` (ya hay un caso parecido para `/api/public/quote-request`, línea 32).
   - Límite por IP con `SlidingLimiter` (`app/ttlcache.py`, ya usado en `forms_public.py`); aceptar `application/csp-report` y `application/reports+json`; responder siempre 204.
   - **Privacidad:** nunca guardar el contenido tal cual. Del aviso conservar solo `violated-directive`/`effective-directive`, el **host** de `blocked-uri` (sin ruta ni parámetros; «inline» y «eval» tal cual) y de `document-uri` **solo el primer segmento de la ruta** (por ejemplo `/f`, `/aceptar`, `/kiosk`), porque las direcciones reales llevan el enlace personal de la persona (`/aceptar/<token>`, `?k=`) y eso es un dato personal que no puede ir a un log (regla de `CLAUDE.md`). No guardar `script-sample`, ni `source-file` con parámetros, ni `referrer`.
   - Descartar los avisos causados por extensiones del navegador (`chrome-extension:`, `moz-extension:`, `safari-extension:`, `edge:`).
   - **No escribir en la base de datos** (Neon debe poder dormirse; regla de costo): emitir **una línea de log estructurada** por combinación nueva (directiva + host + primer segmento), con una memoria en el proceso que evita repetir la misma más de una vez cada 10 minutos. Se consulta en Cloud Logging.
2. **Que la ruta no la bloqueen las compuertas existentes:**
   - `app/event_only.py`: una ruta global nueva queda **cerrada** para el coordinador temporal hasta agregarla a la lista de permitidos (regla de `CLAUDE.md`); agregar `/api/csp-report` a `API_ALLOWED_PREFIXES`/`API_ALLOWED_REGEX` con método POST.
   - `app/main.py` `_ALLOWED_WHEN_MUST_CHANGE` (línea 141): agregarla; si no, quien debe cambiar su clave recibe 403 en cada aviso (inofensivo, pero ruido).
   - CSRF por Origen (`csrf_and_password_gate`, líneas 144-163): el aviso lo manda el navegador desde el mismo sitio, así que debe pasar; **comprobar en staging** que detrás de Firebase Hosting (cabeceras `host`/`x-forwarded-host`) no devuelve 403 «Origen no permitido». Si lo hiciera, tratarla como la ruta de cotización (excepción acotada a esa sola ruta).
   - `app/appmode.py`: la ruta debe vivir en el servicio `web` (no está en `PUBLIC_PREFIXES`, por lo que `route_allowed` la deja en `web`; las páginas públicas servidas por `publico` mandan sus avisos por la dirección relativa `/api/csp-report`, y Firebase Hosting enruta `**` a `web`, `deploy/firebase/make_config.py` línea 28). Verificarlo en staging.
3. **Agregar `report-uri /api/csp-report`** a `_CSP_PANEL`, `_CSP_PUBLIC_FORM` y `_LECTOR_CEDULA_CSP`, detrás de una variable nueva `CSP_REPORT_ENDPOINT` (apagada por omisión; en staging encendida en `deploy/gcp/env/` del entorno de staging, no en `common.yaml`). Opcional después: `Reporting-Endpoints` y `report-to` (no todos los navegadores los usan igual).
4. **Pruebas de texto:** la ruta existe y responde 204; recorta `document-uri` al primer segmento; descarta extensiones; el tope de 8 KiB; las tres políticas contienen `report-uri` cuando la variable está encendida; con la variable apagada, idénticas a hoy (`tests/test_seguridad_fase3b.py` debe seguir verde).

### Etapa 2 · Medir (3-5 días de staging; 4 h de preparación)
1. Encender staging. Con Juan David (o con las pruebas E2E de `tests/e2e/test_staging.py`, hoy sin leer la consola del navegador: agregar la captura de errores de consola es un paso de 2 h) recorrer **esta lista fija de flujos**, cada uno con la consola abierta:
   - Panel: ingreso, registro con buscador, editar persona, Parámetros del evento (6 bloques en línea), diseñador de escarapela, estadísticas (Chart.js), carga de Excel con vista previa (SheetJS), calendario, inventario, almacén, configuración.
   - **Imprimir una escarapela por el cuadro de Chrome** y una etiqueta de almacén (ventana de impresión y `@page`); reimpresión.
   - **Leer cédula** (lector PDF417 con cámara; `zxing-wasm`; OCR de respaldo) y escanear QR (`static/js/qr.js`).
   - Mapa (Leaflet, OSM, Nominatim).
   - **Certificados** y escarapela digital (html2canvas, jsPDF, JSZip, JsBarcode, qrcode-generator).
   - Formularios públicos: inscripción, **pago con Wompi** (modo pruebas), traducir, subir foto o archivo grande (URL firmada).
   - `/aceptar` con selfie (cámara), certificado público, ruleta (`roulette_display`), página de turno y de contacto.
   - Quiosco con contingencia sin conexión (IndexedDB).
2. Consultar los avisos en Cloud Logging (comando que pegará Juan David en Cloud Shell, un solo comando por mensaje, con el resultado esperado). Agruparlos por (directiva, host, primer segmento).
3. **Qué se espera ver (hipótesis, por confirmar midiendo):** avisos por cada bloque en línea una vez que la política pase a estricta (no hoy, porque hoy la permite), y posibles orígenes que falten. Hoy, en modo reporte con `'unsafe-inline'`, lo más probable es ver pocos avisos: ese silencio **no** demuestra que la política estricta funcione; por eso la etapa 4 repite la medición con la política objetivo.
4. **Criterio de salida:** una semana de uso real de staging (o un ensayo con los flujos de la lista completos) sin avisos propios sin explicar. Cada aviso restante queda como (a) arreglar el código, (b) agregar el origen (con razón escrita) o (c) aceptar y documentar.

### Etapa 3 · Quitar o firmar el JavaScript en línea (rama aparte; 40-60 h con archivos, o 8-12 h con `nonce` en el panel)
Hay dos caminos y **se recomienda el híbrido**:
- **A. Mover a archivo** (`static/js/<página>.js`), pasando los datos de Jinja con `data-*` en el `<body>` o con un `<script type="application/json" id="gw-data">` (los JSON no se ejecutan, no los bloquea la CSP). Es lo que ya dice el trinquete (`tests/test_csp_trinquete.py`) y la regla del proyecto («sin scripts en línea», `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md` §6). Obligatorio para las páginas **que la CDN guarda**: el cascarón del formulario público se sirve con `Cache-Control: public, max-age=30, s-maxage=60` (`app/routers/forms_public.py` línea 297); un `nonce` en una página guardada se **repetiría para muchas personas durante hasta 60 segundos**, lo que le quita la utilidad (un nonce debe ser distinto en cada respuesta). Por eso `form_public.html` (23.495 caracteres en línea, con `{{ event_id }}` y `{{ slug }}`) debe pasar a archivo sí o sí.
- **B. `nonce` por petición** para las páginas del panel (las páginas HTML llevan `Cache-Control: no-store`, `app/main.py` línea 306, así que el nonce no se reutiliza): el middleware crea `secrets.token_urlsafe(16)`, lo deja en una variable de contexto (como ya hace `idle.bind`) y lo expone a Jinja como `csp_nonce()`; cada `<script>` en línea pasa a `<script nonce="{{ csp_nonce() }}">`; el encabezado lleva `script-src 'self' 'nonce-…'`. Es rápido, pero **no baja el trinquete a 0**.
- **Recomendado (híbrido):** B para el panel (acelera todo lo demás), A para las páginas públicas, empezando por las más expuestas: `form_public` (1), `aceptar` (1), `certificate_public` (1), `digital_badge` (1), `roulette_display` (1), y luego, sin prisa, A para el resto hasta llegar a 0 y poder quitar el nonce.
- **Impresión (INAMOVIBLE):** `templates/badge_print.html` solo recibe el atributo `nonce` en su bloque y se reemplaza su único `onclick="window.close()"` por un oyente; **no se mueve ni se reescribe el script** (14.094 caracteres, con `print_users_json`), porque `tests/test_impresion_parametros_fijos.py` lee el texto de esa plantilla (línea 4) y de `label-compose.js` y `shared-print.js`. Verificar que ese test sigue verde sin editarlo y repetir la prueba física de la Brother QL-800 si se toca algo más (regla de `CLAUDE.md`).
- Cada plantilla migrada baja su número en `tests/test_csp_trinquete.py` (nunca lo sube).

### Etapa 4 · Política objetivo en modo reporte, junto a la actual (4-6 h)
Agregar una **segunda** cabecera `Content-Security-Policy-Report-Only` con la política objetivo (se permiten varias a la vez) para medir sin bloquear:
- Panel: `default-src 'self'; script-src 'self' 'nonce-…' 'wasm-unsafe-eval'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org; font-src 'self' data:; media-src 'self' blob:; connect-src 'self' https://nominatim.openstreetmap.org https://storage.googleapis.com; frame-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; report-uri /api/csp-report`. Es decir: **sin `cdnjs`, `jsdelivr` ni `unpkg`** en `script-src` y `connect-src` una vez que Chart.js, SheetJS, Leaflet, `zxing-wasm` y `tesseract.js` estén en `static/vendor/` (paso 5, 12-20 h con sus licencias; si no se hace, se dejan solo `https://cdnjs.cloudflare.com` y se **quitan** `jsdelivr`/`unpkg` cargando el lector de cédula desde `static/vendor/`).
- Formulario público (`/f/*`, sin nonce, con el script ya en archivo): `script-src 'self' https://checkout.wompi.co https://translate.google.com https://translate.googleapis.com https://www.gstatic.com`; el resto como hoy.
- Repetir la lista fija de la etapa 2. Criterio de salida: cero avisos propios sin explicar durante una semana.

### Etapa 5 · Pasar a bloquear (4 h + una semana de observación)
1. Variable nueva `CSP_ENFORCE` (apagada por omisión). Con `1`, la política objetivo se envía como `Content-Security-Policy` (la mínima actual de `frame-ancestors/object-src/base-uri/form-action` se fusiona con ella) y se conserva el reporte.
2. **Primero staging** una semana; luego producción solo con autorización explícita de Juan David para esa acción y ese commit, con aviso a los coordinadores y **nunca durante un evento en curso** (el despliegue normal ya respeta el congelamiento por eventos; `FORCE=1` no se usa).
3. **Reversa en minutos:** `CSP_ENFORCE=0` en las variables del servicio de Cloud Run y nueva revisión (o reutilizar la revisión anterior); no requiere tocar Firebase ni DNS.
4. Seguir mirando los avisos 30 días.

### Etapa 6 · Remates (opcional)
- `style-src`: **no se pretende** quitar `'unsafe-inline'` (ver §6). Opcional: separar `style-src-elem` y `style-src-attr` para endurecer solo lo posible.
- Sitio corporativo (`deploy/sitio/firebase.json`): agregar una CSP propia cuando se compile y se pueda medir (hoy «nunca se compiló», `00_PLAN_SEGUNDA_PASADA.md`).
- Subir `Strict-Transport-Security` con `preload` solo con decisión aparte.
- Considerar `Cross-Origin-Opener-Policy` y `Cross-Origin-Resource-Policy` (fuera de este plan).

### Resumen de horas
| Etapa | Horas |
|---|---|
| 1 Endpoint de reporte | 4-6 |
| 2 Medición en staging | 4 de preparación + 3-5 días de calendario |
| 3 JavaScript en línea (híbrido: nonce panel + archivos públicos) | 20-30 (solo archivos hasta 0: 40-60) |
| 4 Política objetivo en reporte + librerías propias | 16-26 |
| 5 Bloquear | 4 |
| **Total** | **≈ 50-70 h** (≈ 75-100 h si se llega a cero scripts en línea) |

## 4. Cómo medir y cuándo pasar a bloquear

- **Qué se mide:** número de avisos por (directiva, host, primer segmento de ruta) en Cloud Logging, separando propios de extensiones (ya filtradas). No se mide por persona: no hay datos personales.
- **Cuándo pasar de reportar a bloquear:** cuando se cumplan **las tres**: (1) la política objetivo en modo reporte lleva **7 días seguidos** sin avisos propios sin explicar, con al menos un ensayo completo de la lista de flujos de la etapa 2 incluido; (2) `tests/test_csp_trinquete.py` en cero para las páginas públicas y los nonces en las del panel; (3) la prueba de impresión (`tests/test_impresion_parametros_fijos.py` y una impresión física de una escarapela) pasó con la política en reporte.
- **Cuándo retroceder:** un solo reporte de una función que dejó de funcionar (impresión, lector, pago) en staging o producción → `CSP_ENFORCE=0` y analizar.

## 5. Qué se rompería (y cómo se evita)

| Qué | Por qué se rompe | Cómo se evita |
|---|---|---|
| Los 51 `<script>` en línea | Sin `'unsafe-inline'` no se ejecutan; el navegador solo ejecuta los que tengan el nonce correcto o vengan de un archivo | Etapa 3. Nunca activar el bloqueo antes de ella |
| `onclick="window.close()"` de `badge_print.html` | Los manejadores en línea se bloquean con `script-src-attr 'none'` | Reemplazarlo por un oyente (delegación de eventos, regla del proyecto) |
| Nonce en páginas guardadas por la CDN | El nonce se repetiría para muchos visitantes | No usar nonce en `/f/*`; mover ese script a archivo |
| `html2canvas` (certificados, escarapela digital) | Se sirve desde `static/vendor/` (mismo origen: no se bloquea el script), pero **su código crea un elemento `<style>` con `textContent`** (encontrado una vez en `static/vendor/html2canvas-1.4.1.min.js`) y clona la página para dibujarla | Mantener `style-src 'unsafe-inline'`. Si algún día se endurece `style-src`, habría que pasarle el nonce o probar con `ignoreElements`. **No verificado en un navegador** |
| QR (`qrcode-generator`, `qr.js`, jsQR) | Genera imágenes `data:` (permitidas en `img-src`) y usa la cámara (`media-src blob:`); si el lector crea trabajadores, necesita `worker-src blob:` | Ya están en la política del panel; confirmar en la medición. **No verificado** |
| Lector de cédula `zxing-wasm` | Compila WebAssembly: requiere `'wasm-unsafe-eval'` y carga el `.wasm` desde `jsdelivr`/`unpkg` | Mantener `'wasm-unsafe-eval'` en el panel (NO en el formulario público); llevar el `.wasm` a `static/vendor/` y apuntar `locateFile` ahí (`cedula-readers.js` línea 377) |
| **Impresión de escarapelas y etiquetas** | JavaScript escribe un `<style>` con `@page` (`badge-render.js` 163, `label-compose.js` 94, `almacen-etiquetas.js` 39); si `style-src` no permite estilos en línea, el tamaño de página (62 × 99,8 mm) se perdería | **No quitar `'unsafe-inline'` de `style-src`.** Es una decisión de diseño de este plan, para no tocar los parámetros INAMOVIBLES |
| Ventana de impresión (`window.open('about:blank')` en `badge-render.js` 376 y 392) | Una ventana `about:blank` hereda la política de quien la abre | Verificar en la medición; la política nunca debe bloquear el cuadro de impresión de Chrome (no pasa por la CSP) |
| Mapa (Leaflet), gráficos (Chart.js), Excel (SheetJS) | Hoy vienen de `cdnjs`; si se saca `cdnjs` de la política sin llevarlos a `static/vendor/`, dejan de cargar | Llevarlos a `static/vendor/` primero |
| Traductor de Google en el formulario público | Inserta scripts y estilos de Google | Se mantiene su política propia, solo en `/f/*`; no tocar el resto |
| Wompi (widget y marco) | `checkout.wompi.co` y `*.wompi.co` | Ya están en la política pública; probar el pago de punta a punta en modo pruebas |
| Estilos del color de marca y logo | `<style>` y `style=""` escritos por el servidor | Quedan permitidos por `style-src 'unsafe-inline'` |
| Avisos de la ruta de prueba `/pruebas/lector-cedula` | Tiene política propia | Agregarle el `report-uri` o retirarla cuando se retire la prueba |
| Servidor local (`LOCAL_SERVER=1`, sin internet) | Las librerías en CDN no cargan sin internet; hoy ya cae a sus plan B | Llevar las librerías a `static/vendor/` **mejora** la contingencia sin internet |

## 6. Por qué se mantiene `style-src 'unsafe-inline'`
El riesgo principal de una CSP es el JavaScript inyectado, no el CSS. Quitar los estilos en línea exigiría reescribir 59 atributos de plantilla, 102 textos de JavaScript con `style="…"`, 9 archivos que crean `<style>` y, sobre todo, **el `@page` de la impresión**, que es parte de los parámetros INAMOVIBLES. El beneficio no compensa el riesgo de romper la impresión. La propia política actual lo documenta («no es el riesgo principal», `docs/FASE_3_SEGURIDAD.md`).

## 7. Qué decide Juan David

1. **Camino para los scripts en línea.** a) Híbrido (nonce en el panel + archivos en lo público), unas 20-30 h; b) Solo archivos, unas 40-60 h pero sin dependencia del servidor; c) No hacerlo por ahora. **Recomendación: (a)**: da la protección en pocas semanas y deja el camino hacia (b).
2. **¿Se llevan a la plataforma (copia propia) las librerías de CDN** (Chart.js, SheetJS, Leaflet, `zxing-wasm`, `tesseract.js`)? a) Sí, todas; b) Solo las que cargan desde `jsdelivr`/`unpkg`; c) No. **Recomendación: (a).** Quita orígenes de terceros, mejora el servidor local sin internet y evita un riesgo conocido. Implica 12-20 h y revisar sus licencias.
3. **¿Cuándo se enciende el bloqueo en producción?** Siempre con su autorización explícita y fuera de un evento en curso. **Recomendación:** después de una semana limpia en staging y del primer evento real sin incidentes con el modo reporte en producción.
4. **¿Se enciende el reporte en producción antes de bloquear?** a) Sí (solo registra); b) No, solo en staging. **Recomendación: (a)** con los avisos recortados a primer segmento y host (sin datos personales): es la única forma de ver el uso real.
5. **¿Cuánto tiempo de medición es suficiente?** a) 7 días; b) hasta el próximo evento grande. **Recomendación: (a) y repetir en el primer evento grande.**
6. **¿Qué hacer si un cliente grande pide una política aún más estricta (sin `'unsafe-inline'` en estilos)?** **Recomendación:** decir que no por ahora y explicarlo (§6): no se pone en riesgo la impresión INAMOVIBLE.
7. **Sitio corporativo.** ¿Se le agrega una CSP propia cuando se compile? **Recomendación: sí, después de la etapa 5.**

## 8. Qué no pude comprobar

- No abrí ningún navegador ni ejecuté la plataforma: todos los conteos salen de leer los archivos con búsquedas de texto y un script de lectura; **no hay mediciones de avisos reales** (no existe todavía el endpoint que los recibe).
- No comprobé en vivo que `html2canvas`, los QR, `zxing-wasm`, la impresión por `window.open('about:blank')` ni el traductor funcionen con la política objetivo. Lo escrito sobre ellos sale de leer su código; la tabla de §5 dice dónde no está verificado.
- No comprobé cómo Firebase Hosting entrega `host`/`x-forwarded-host` a la ruta nueva ni que su regla `**` la lleve al servicio `web`; hay que verlo en staging (etapa 1, paso 2).
- No verifiqué que `https://storage.googleapis.com` se use hoy en una subida directa (está en la política pero no encontré el uso en `static/js/`); no se debe quitar sin medirlo.
- No leí los 37 bloques con Jinja uno por uno; el conteo es mecánico (cualquier `{{` o `{%` dentro del bloque). El esfuerzo real de mover cada uno puede variar.
- Las horas son estimaciones mías según el tamaño de los bloques y piezas parecidas del proyecto; no hay medición.
- La afirmación de que `jsdelivr`/`unpkg` permiten saltarse una CSP es práctica común de seguridad web; no probé una explotación en esta plataforma ni contra su política.
- No revisé `docs/revision_2026-11-22b/05_ciberseguridad.md` por cambios recientes sobre la CSP (solo el reporte `docs/revision_2026-11-22/03_seguridad_nube.md`, hallazgo 2).
