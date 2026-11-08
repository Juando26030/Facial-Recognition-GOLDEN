# Fase 3: cierre de seguridad, lote b (alcance débil)

Rama `f3b/seguridad`. Pruebas: `tests/test_seguridad_fase3b.py` (las de «fuente» corren sin base; las demás usan el Postgres de pruebas). Nada de esto activa `ENFORCE_STAFF_TENANT`: sigue apagado por defecto; lo decide Juan David.

## Qué se cerró

| # | Hallazgo | Cambio | Prueba |
|---|---|---|---|
| a | `POST /api/colors` dejaba que un coordinador cambiara el tono de un color compartido por nombre | Crea si no existe. Si existe con **otro tono**: coordinador recibe **409** (mensaje claro); admin+ lo cambia y queda en `audit_actions` (`update saved_color`). Mismo tono = idempotente (200). Archivado sigue dando 400 | `test_a_*` |
| b1 | `POST /api/calendar/notes` (y listar, borrar, destinatarios) no filtraban por cliente | `CalendarNote` no tiene columna de cliente (y no se crean migraciones): **pertenece al cliente de quien la creó** (`created_by.tenant_id`). Con el interruptor encendido: la lista solo trae notas de su cliente (o dirigidas a él), no puede dirigir una nota a alguien de otro cliente (400, mismo mensaje que un destinatario inválido), `DELETE` de una nota ajena da 404 y `notifiable-staff` solo ofrece compañeros de su cliente | `test_b_calendar_*` |
| b2 | `POST /api/privacy-requests` (y listar/estado/bandera/claim) no filtraban por cliente | Solo admin+ (ya era así). Con el interruptor encendido: un evento de otro cliente da 404; sin evento la solicitud queda a nombre del cliente de quien la radica; la lista, el cambio de estado, la bandera y la consulta `claim/{cedula}` solo ven solicitudes de su cliente (`open_claim(..., tenant_id=)`) | `test_b_privacy_*` |
| c | Revisión de rutas con `get_event_for_staff` / `assert_event_tenant` | Ver sección siguiente. Se añadió `assert_event_tenant` a las dos rutas de `event_transfer.py` (exportar), que buscaban el evento a mano | `test_c_*` |
| d | `POST /api/ops/simulate-crash` | Confirmado: responde 404 salvo con `DEPLOY_ENV=staging` **y** `CHAOS_ENABLED=1` (y rol admin+ u OPS_TOKEN). Ningún archivo de `deploy/`, `.github/`, Dockerfile ni compose lo menciona; solo `docs/15` explica cómo Juan David lo pone a mano con `gcloud … --update-env-vars` y lo quita | `test_d_*` (de fuente) |
| e | `/api/ingreso/estado` y `/cancelar` sin dependencia | Ya tenían token de **un solo uso** (`consume_approved`, UPDATE condicional), **vencimiento de 5 min** (`REQUEST_TTL`), solo el SHA-256 en base y comparación en tiempo constante. Faltaba **tope de intentos**: ahora 429 (`Retry-After: 30`) a más de 60 preguntas por minuto por solicitud y 300 por IP, en memoria por proceso, sin tocar la base (la pantalla legítima pregunta 20 por minuto). La pantalla ignora el 429 y sigue preguntando | `test_e_*` |
| f | CSP | Solo documentado (abajo); producción no cambia | `test_f_*` |
| g | Leaflet sin SRI | Hecho el 8-nov-2026 (sha384 de `leaflet.js` y `leaflet.css` 1.9.4 en `static/js/gw-map.js`) | `test_g_*` |

## (c) Qué cambia al encender `ENFORCE_STAFF_TENANT=1`

Quien tiene `staff_users.tenant_id` queda limitado a ese cliente; `tenant_id` nulo (personal de Golden, super_admin) sigue viendo todo. No hay migración: es solo la variable de entorno.

Puntos de control (todos devuelven **404**, no 403, para no confirmar que el recurso existe):

- `get_event_for_staff` (decenas de rutas en `app/routers/*`: registro, reconocimiento, consentimientos, escarapelas, áreas, inventario, formularios, ruleta, puerta, estadísticas, reimpresión, etc.). El control de cliente va ANTES de la autorización del digitador/cliente: una cuenta temporal autorizada a un evento de otro cliente tampoco entra.
- `assert_event_tenant` directo en rutas que resuelven el evento a mano: `events.py` (editar, borrar, archivar/restaurar, devolver a Creado, historial de estados, cuentas temporales), `api._event_for_sync` (sincronización del quiosco sin red), `reprint.decision`, y ahora `event_transfer` (exportar).
- `scope_events_query`: listas de eventos (`/api/events`, `/events/search`, calendario) filtradas por cliente.
- `tenant_scope.assert_same_tenant` / `staff_tenant_enforced`: cuentas del personal (`staff.py`), clientes, supereventos y, desde este lote, notas del calendario y solicitudes de privacidad.

Queda **fuera** a propósito: colores, estados de evento, plantillas globales (`SavedColor` es global por diseño) y las rutas públicas por token (`/r/{token}`, `/f/…`, `/aceptar`, certificados), que no dependen de una cuenta.

Pruebas: `test_c_role_matrix_with_enforce_staff_tenant` (coordinador, comercial y admin limitados a `acme` contra 7 endpoints de un evento de `beta` y de uno propio, más el personal global y el interruptor apagado), `test_c_authorized_temp_accounts_*` (digitador y cliente autorizados a un evento ajeno), y las ya existentes `test_seguridad_cierre_permisos.py`, `test_seguridad_cierre_archivos.py` y `test_tenant_archive.py`. Para encenderlo: probar en staging con dos clientes y personal de ambos, y vigilar 404 inesperados del personal de Golden que tenga `tenant_id` puesto por error.

## (f) CSP: de «solo frame-ancestors» a `script-src` estricto

Estado actual (`app/main.py`, middleware `security_headers`): `frame-ancestors 'self'; object-src 'none'; base-uri 'self'` (sin `frame-ancestors` en `/f/*`, que se incrusta), y `default-src 'none'; style-src 'unsafe-inline'; sandbox` para SVG. **(Actualizado en la rama `f3e/xss`, ver «Rama f3e/xss» al final: ya existe la cabecera `Content-Security-Policy-Report-Only` con `script-src` y la política obligatoria suma `form-action 'self'`.)** Antes de esa rama no existían; Firebase Hosting no agrega cabeceras de seguridad propias (`deploy/firebase/make_config.py` no las define).

Lo que bloquearía un `script-src 'self'` (inventario hecho sobre `templates/`):

- 51 bloques `<script>` en línea en 30 plantillas: `_event_edit_modal`, `_gw_head` (3), `_sidebar`, `aceptar`, `badge_editor` (3), `badge_print`, `calendario`, `certificate_public`, `configuracion`, `digital_badge`, `eventos`, `form_public`, `impresion_usb`, `kiosk_areas`, `kiosk_certificados`, `kiosk_documentos`, `kiosk_estadisticas` (2), `kiosk_formulario_editor` (2), `kiosk_formularios`, `kiosk_inventario`, `kiosk_legalizaciones`, `kiosk_parametros` (6), `kiosk_registro` (8), `kiosk_roster` (2), `kiosk_rostro`, `kiosk_ruleta` (2), `kiosk_ruleta_visual` (2), `kiosk_select`, `kiosk_usuarios`, `roulette_display`.
- 1 manejador en línea: `badge_print.html` (`onclick="window.close()"`).
- Bloques `type="application/json"` (1 plantilla) NO se bloquean (no se ejecutan).
- Scripts externos permitidos hoy: `https://cdnjs.cloudflare.com` (Chart.js, SheetJS, Leaflet), Google Translate (`translate.google.com`, `translate.googleapis.com`, `www.gstatic.com`, solo en el formulario público, ver `docs/0C_d9_librerias_externas.md`). Otros orígenes de red (sin script): `nominatim.openstreetmap.org`, `tile.openstreetmap.org` (`connect-src`/`img-src`), `wompi.statuspage.io`.
- Estilos: 50 atributos `style="…"` y 9 plantillas con `<style>`: obligan a mantener `style-src 'unsafe-inline'` (no es el riesgo principal).
- No hay `eval()` ni `new Function` en `static/js`.

Plan, sin tocar producción hasta el paso 4:

1. **Medir**: agregar la cabecera `Content-Security-Policy-Report-Only` con la política objetivo y un `report-uri` a una ruta propia (`/internal/csp-report`, sin datos personales, solo directiva y archivo) detrás de `CSP_REPORT_ONLY=1` (apagada por defecto). Encender solo en staging.
2. **Quitar lo inline**: mover cada bloque a `static/js/<pagina>.js`; los datos que hoy interpola Jinja pasan a un `<script type="application/json" id="gw-data">` (no bloqueado) o a `data-*`. Reemplazar el `onclick` de `badge_print.html` por delegación (regla del proyecto). Alternativa de menor esfuerzo: nonce por petición (`secrets.token_urlsafe(16)` en el middleware, `<script nonce="{{ csp_nonce }}">`), pero las páginas con `no-store` están bien y la caché del cascarón del formulario público (`form_public`) lo impide: ahí hay que sacar el script a archivo sí o sí.
3. **Política objetivo**: `default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://tile.openstreetmap.org https://*.googleusercontent.com; connect-src 'self' https://nominatim.openstreetmap.org https://wompi.statuspage.io; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'` (más los orígenes de Google Translate y Wompi SOLO para `/f/*`; `media-src blob:` y `worker-src 'self' blob:` por la cámara y el quiosco sin red). Verificar con ZAP y con el recorrido manual de las pantallas del quiosco.
4. **Activar**: cuando el informe esté vacío unos días con eventos reales de staging, pasar a la cabecera real por variable (`CSP_ENFORCE=1`), primero staging, luego producción con autorización de Juan David.

Decisión pendiente de Juan David: prioridad (el riesgo actual está acotado por el autoescape de Jinja, pero conviene revisar los `|safe` antes de decidir) y si se acepta nonce o se prefiere mover todo a archivos.

## (g) SRI de Leaflet

`static/js/gw-map.js` carga Leaflet **1.9.4** desde cdnjs (versión fija, ya con `crossOrigin`) pero sin `integrity`. En este entorno no hay red hacia el CDN, así que no se pudo calcular el hash y **no se agregó** (un hash mal puesto rompería el mapa, que hoy cae con gracia a una dirección de texto). Pendiente (SRI de Leaflet), 5 minutos con red:

```bash
for f in leaflet.js leaflet.css; do curl -s https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/$f | openssl dgst -sha384 -binary | openssl base64 -A | sed "s/^/$f sha384-/;s/$/\n/"; done
```

Luego en `loadLeaflet()` poner `js.integrity` / `css.integrity` con esos valores (y `crossOrigin = 'anonymous'`). Los demás scripts de CDN en plantillas (Chart.js 4.5.1, SheetJS 0.18.5) ya llevan SRI y `test_g_*` lo exige.


## CSP estricto: decisión del 8-nov-2026
No se activa en este despliegue. Se hace por etapas, sin esperar a la versión final:
1. **Ya (trinquete):** `tests/test_csp_trinquete.py` impide que crezca el JavaScript en línea; toda plantilla nueva nace sin él.
2. **Fase 4 y siguientes:** cada plantilla que se toque migra sus bloques a `static/js/` y baja su número en el trinquete.
3. **Cuando el contador llegue a 0:** cabecera `Content-Security-Policy-Report-Only` con `script-src 'self'` en staging, luego en producción, y por último la cabecera que bloquea.

## Rama f3e/xss (8-nov-2026): inyección, denegación de servicio y cabeceras
Hecho, con sus pruebas (los IDs son de la revisión cruzada):
- **C1/C2 (XSS en confirmaciones):** `showConfirm(msg, {text})` escapa `opts.text`; los nombres de color, de plantilla, el usuario de cliente, el radicado y la cédula se escapan en cada llamada. El servidor rechaza `<`/`>` en el nombre del color (400) y en el de la plantilla (422, tope de 80). Solo cubre escrituras nuevas: para lo ya guardado, consulta de control `SELECT id, name FROM saved_colors WHERE name ~ '[<>]'` (y lo mismo en `saved_badge_templates`); el escape del cliente es el arreglo real para esas filas.
- **R3-01 (ReDoS):** `richtext._FORMAT_RE` con `+` en el valor sin comillas, y `has_format` no evalúa textos de más de 20000 caracteres.
- **C3/R3-07 (cuerpo sin tope):** `app/bodylimit.py` (ASGI puro): 413 por `Content-Length` y corte al contar bytes sin él. Topes: `submit` 36 MiB (`MAX_BODY_PUBLIC_BYTES`), resto de `/f/` 256 KiB, webhook 256 KiB, `/api/aceptar` 10 MiB, login/olvidé/restablecer 64 KiB. Nginx de la VM: 40M para esas rutas (el resto queda en 500M por la carga masiva). Pendiente de Juan David: aplicar `deploy/nginx-golden.conf` en la VM y medir la memoria del servicio `publico` en Cloud Run.
- **R3-08:** `limit`/`offset` de `/api/users` validados (422), `badge-assets` con `..` da 404, contraseñas de más de 72 bytes (bcrypt 5) rechazadas con mensaje claro en `password_problem`.
- **C6/C11:** el asunto del correo se limpia de controles y el armado del mensaje queda dentro del manejo de errores; el gasto rechaza `Infinity`, `NaN` y valores que no caben en `Numeric(14, 2)`.
- **E6:** `TRUST_CF_CONNECTING_IP` vale `0` por defecto. **La VM debe tener `TRUST_CF_CONNECTING_IP=1` en su `.env` ANTES de desplegar esto** (agregar la línea, nunca reemplazar el archivo); si no, los límites por IP pasan a usar `X-Forwarded-For`. `app/obs.py:166` usa la cabecera sin condición (otro corrector).
- **E1 (CSP):** la política obligatoria suma `form-action 'self'`. Además `Content-Security-Policy-Report-Only` con dos políticas (panel y `/f/*`: Wompi y Google Translate solo allí; sin `frame-ancestors` en `/f/*`). Mantiene `'unsafe-inline'` en `script-src`/`style-src` mientras haya bloques en línea. `CSP_REPORT_ONLY=0` la apaga.
  - Verificación manual en staging (no hecha): con la consola abierta, imprimir una escarapela, subir un Excel, abrir el mapa, pagar con Wompi y traducir un formulario; anotar los orígenes que falten.
  - Diseño del endpoint de reportes (NO implementado): `POST /api/csp-report` público, cuerpo máximo 8 KiB (ya cubierto por `bodylimit` si se agrega la ruta), límite por IP, guardar solo `violated-directive` y `blocked-uri` sin query ni fragmento, y agregar `report-uri /api/csp-report` a ambas políticas.

No hecho en esta rama (por tamaño o porque lo hace otro corrector): C7 (adjunto del informe final: quitar `.xls`, validar el `.xlsx` con `safe_limits.check_zip`), C8 (paquete de evento: lista blanca de extensiones, `iterations` entre 100.000 y 2.000.000, `MIN_PASSPHRASE = 12`), E4/R3-02 (`security.safe_eq`), R3-03 a R3-06, E7, E8, E9, E12.
