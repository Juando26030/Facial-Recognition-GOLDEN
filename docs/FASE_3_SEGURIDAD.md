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

Estado actual (`app/main.py`, middleware `security_headers`): `frame-ancestors 'self'; object-src 'none'; base-uri 'self'` (sin `frame-ancestors` en `/f/*`, que se incrusta), y `default-src 'none'; style-src 'unsafe-inline'; sandbox` para SVG. **No existe** `Content-Security-Policy-Report-Only` ni `script-src`; Firebase Hosting no agrega cabeceras de seguridad propias (`deploy/firebase/make_config.py` no las define).

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

## Pagos (formularios públicos con Wompi): auditoría con revisión cruzada, 8-nov-2026

Rama `f3e/pagos`. Hecho: D1 + R1 + R9 (no se descarta la inscripción pendiente de otra persona por teclear su cédula; solo el intento propio de la MISMA sesión y tras preguntar a Wompi; se recomprueba bajo candado), R2 (dos pendientes con la misma cédula no se confirman ambas: la segunda pasa a `refund_due`), D16, R3, R4, D8 y R8. Sin migraciones: `form_submissions.status` es texto libre (confirmar con `\d form_submissions` en Neon que no haya un CHECK que impida `refund_due`).

### D2 — PENDIENTE de la decisión del dueño (esqueleto, NO aplicado)

**El problema.** El apartado de cupo es un reloj de 15 min (`formsvc.PENDING_HOLD`). Pasado ese tiempo el cupo se vuelve a vender, pero un pago que tarde en aprobarse (3DS, PSE, OTP) se confirma igual (`apply_result`) sin mirar el aforo, los cupos por variable (`quota_keys`) ni los usos de un código (`max_uses`): sobreventa. No requiere atacante.

**Pregunta al dueño.** Cuando un pago se aprueba y ya no hay cupo, ¿se admite igual (sobreaforo) o se reembolsa? El aforo, ¿es físico y duro?

**Opción recomendada (sin sobreventa; «quien pagó tiene prioridad sobre quien solo apartó»):** inscripción en estado `refund_due`, alerta y reembolso.

1. Ya existe el gancho: `formsvc.admit_on_approval(db, form, sub)` (hoy solo revisa el duplicado por cédula) y `form_payments._admit_or_flag`. Con el formulario BLOQUEADO (la misma fila que toma `form_reserve_slot`) se cuentan SOLO las confirmadas (`status == "confirmed"`, sin pruebas, sin la propia) y se devuelve un motivo:
   - `capacity`: `confirmadas >= form.capacity`;
   - `quota`: para cada regla de `quota_rules(form)` que cumple la inscripción (`sub.quota_keys` contiene `|firma|`), `confirmadas con esa firma >= formlib.rule_limit_now(regla, now_local())`;
   - `code`: `confirmadas con sub.discount_code_id >= code.max_uses`;
   - `duplicate` (ya hecho).
2. Si hay motivo: `sub.status = REFUND_DUE` (no cuenta como inscrita ni aparta cupo; ya se ve en la lista de pagos con el aviso «reembolsa y avisa» y en el KPI «Pagos por reembolsar»), `payment_refund_due` en «Estado del sistema» (ya hecho), y el administrador reembolsa por el flujo normal (`form_refunds.complete` ya pasa `refund_due` a `refunded`).
3. Opcional: para tarjeta, encolar `wompi.void_transaction` automático en `_admit_or_flag`; PSE/Nequi siguen manuales. Opcional: correo a la persona avisando del reembolso.
4. Pruebas a escribir al aplicarlo (propuestas en `/tmp/revision_1.md`): aprobación tardía sobre aforo 1 con apartado vencido (`created_at` del pago de hace 20 min) -> `{"b": "confirmed", "a": "refund_due"}`; cupo por variable agotado; código de un solo uso gastado por otra inscripción.
5. Si el negocio prefiere admitir con sobreaforo: cambiar `>= capacity` por un tope duro `capacity + N` (y documentar N).

Riesgos conocidos del diseño: el orden de candados es pago -> formulario; el único camino inverso es `purge_stale_pending` (llamado dentro de `_reserve_and_store` con el formulario bloqueado, 24 h de antigüedad): interbloqueo posible pero rarísimo, lo corta Postgres y el webhook se reintenta. Se elimina moviendo `purge_stale_pending` antes de `reserve_slot`. Un `lock_timeout` al aprobar responde 500 y Wompi reintenta; la conciliación (`reconcile`) también lo repite.

### Pendientes de esta auditoría que NO se tocaron aquí
D3/B1 (consentimientos: pertenencia de la persona y hash del texto), D5, D6, D7 (idempotencia de entrega), D17, D21, R5 (negarse a cobrar si `access == "activo"` y las llaves son de pruebas), R6, R7 (ventana de tiempo del webhook).
