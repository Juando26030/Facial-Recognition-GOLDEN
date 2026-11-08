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

## Pagos (formularios públicos con Wompi): auditoría con revisión cruzada, 8-nov-2026

Rama `f3e/pagos`. Hecho: D1 + R1 + R9 (no se descarta la inscripción pendiente de otra persona por teclear su cédula; solo el intento propio de la MISMA sesión y tras preguntar a Wompi; se recomprueba bajo candado), R2 (dos pendientes con la misma cédula no se confirman ambas: la segunda pasa a `refund_due`), D16, R3, R4, D8 y R8. Sin migraciones: `form_submissions.status` es texto libre (confirmar con `\d form_submissions` en Neon que no haya un CHECK que impida `refund_due`).

### D2 — antes pendiente; RESUELTO el 8-nov-2026 (ver «Decisiones del dueño», abajo; este esqueleto queda como contexto)

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


# Ronda de acceso (rama `f3e/acceso`): pertenencia persona/evento, base archivada y sesiones

Origen: auditoría con revisión cruzada (informes B1-B16, R2-x, A3, E4, E16/C9). Pruebas nuevas: `tests/test_pertenencia_persona_evento.py`, `tests/test_base_archivada_guard.py`, `tests/test_sesion_admin_b7.py`, `tests/test_safeeq.py`, `tests/test_acceso_fase3_menores.py` y casos añadidos a `test_roulette.py`, `test_observability.py`, `test_form_client.py`, `test_seguridad_cierre_sesion.py`. No se pudieron correr en el entorno de la rama (sin Postgres): validadas con `ruff` y `py_compile`; **correr la suite completa antes de integrar**.

## Qué se cerró

| ID | Cambio |
|---|---|
| P1 / B2 / R2-1 | `app/eventpeople.py` (`person_of_event`, `require_person_of_event`, `member_ids`; 404 con el mismo texto exista o no la persona en otro evento). Aplicado a `badge-print-data`, foto, `print-count`, `print-log`, las tres rutas de firma y a la ruta `cedula` de `access-logs/sync` (queda acotada al evento, igual que la de huella). `api._person_of_event` es ahora un alias. |
| P2 / B3 / B4 / D4 / D9 / R2-2 / R2-5 | `event_archive.require_data_open(event, staff)`: 403 con la base archivada salvo super_admin. Puesto en reporte Excel, `incomplete-registrations`, `local-roster`, bulk (preview, register, status), edición/borrado/estado de personas, `_carry_source_event`, formularios (envíos, pagos, archivos, reporte, analítica, invitaciones, personas, reembolsos), consentimientos y envío masivo de enlaces, puerta facial, áreas/inventario con personas, ruleta (candidatos, sorteo, historial, reporte), estadísticas, reimpresión, analítica y `sibling-check`. `_event_for_sync` rechaza evento archivado y base archivada para TODOS los roles. `set_status` de formularios no reabre con la base archivada. Enlaces públicos `/c/{token}` y `/b/{token}` (página, datos, foto, assets) devuelven 404 con el evento o su base archivados. |
| Red de seguridad | `test_every_route_with_event_access_decides_about_the_archived_base`: por AST, toda función de `app/routers` con `get_event_for_staff(` debe llamar `require_data_open` o estar en `ALLOW` (lista explícita y revisada, con las rutas de configuración, personal y privacidad). Una ruta nueva obliga a decidir. |
| A3 | `/b/{token}/data` ya no entrega teléfono ni correo; solo los campos que la plantilla pinta (misma regla que el certificado). **Efecto visible:** si una plantilla de escarapela digital usa la variable `phone` o `email`, ya no se pinta en la versión digital (la física no cambia). |
| B7 | `idle.start` marca `iat`; `idle_gate` expulsa a admin/super_admin a las `ADMIN_SESSION_MAX_HOURS` (12 por defecto, 0 = apagado) aunque la actividad renueve la cookie; cookies anteriores al cambio corren desde su primer uso. El logout de admin/super_admin sube `session_epoch` (invalida toda copia de la cookie; **también cierra sus otras sesiones**). Un cierre con cookie ya vencida no toca la época. |
| B15 | El `state` y el `spin` públicos de la ruleta no entregan la cédula del ganador (solo posición, nombre y entidad); `/r/{token}` deja de servir con el evento o su base archivados (se reabre al restaurar). |
| B6 | `login-state` expone un código corto de la solicitud vigente (`req`) y `login-request` lo compara si llega (409 si otra solicitud la reemplazó). `usuarios.js` lo manda. |
| B10 | `get_current_staff` da 401 a un cliente de formulario con el acceso vencido (sus propias rutas `/api/form-client/*` y `/mi-formulario` siguen respondiendo su 403 con mensaje). |
| B11 | `sibling-check` con tope por cuenta (`SIBLING_CHECK_MAX` = 300 cada 10 min). |
| B12 | `badge-assets`: 404 a cuentas de cliente de formulario y comprobación de cliente con `ENFORCE_STAFF_TENANT=1` (`auth.assert_tenant_id`). |
| E4 | `app/safeeq.safe_eq` (bytes UTF-8, nunca lanza) en `ops._ops_reader`, código y clave de pruebas de formularios públicos, checksum de Wompi y token de tiempos: texto no ASCII da 401/403, no 500. |
| E16 / C9 | `requestUrl` pasa por `mask_pii(mask_url(...))`; la query enmascara `id`, `email`, `q`, `cedula`, `documento`, `telefono`, `nombre`… y la ruta enmascara el segmento tras `/users/`, `/people/`, `/attendees/`, `/consent-status/`, `/web-acceptance/` (alfanumérico incluido; `users/changes` queda legible). `mask_pii` aplica lo mismo a cualquier mensaje. |

## Pendiente (no se hizo a medias)

1. **B1: consentimientos (`consents.py`) y `enroll_face`.** A la espera de la decisión de producto del dueño (el flujo de autorregistro y `aceptar.py`/`accept_link.py` registran la aceptación ANTES de la inscripción). Diseño: `consent_status` y `enroll_face` con `require_person_of_event`; en `record_consents`, calcular `members = member_ids(db, event, {uid de cada entrada})` una vez antes del bucle y contar como `unknown` a quien no esté (como una huella ajena). Con eso desaparece la cadena aceptación falsa → `maybe_enqueue` → foto sobrescrita y el borrado ajeno por un `reject` falso (`consents.py:105-106`). Riesgo a validar: que el «Creado nuevo» del quiosco inscriba a la persona antes de registrar el consentimiento.
2. **B6 (b) y (c).** El bloqueo de cuenta por 3 fallos desde cualquier origen (DoS en la puerta) y el 403 con mensaje propio para «bloqueada» (enumera cédulas de digitador) son una decisión de producto: unificar el mensaje deja al digitador legítimo sin saber que debe pedir el desbloqueo. Opción: mensaje genérico en `/login` y que el coordinador lo vea en «Usuarios del evento» (ya lo ve). Bloqueo por par usuario+IP. Contraseña inicial aleatoria entregada por el coordinador en lugar de la cédula (`events.py:675-677,780`): quita casi todo el alcance de B5 y B6.
3. **B5: reactivación por importación (`events.py` `import_event_staff`).** Diseño: si la cuenta está inactiva o archivada y quien importa no es admin+, agregar a `problems` («Esa cuenta fue desactivada o archivada por un administrador: pídele que la reactive») y `continue` antes de `EventStaffAuthorization`; si es admin, limpiar `archived_at`/`archived_by_id` y registrar `audit_actions.record(db, staff, "activate", "staff_user", ...)` sin la cédula. Prueba propuesta en `/tmp/revision_2.md` (P5).
4. **B8: `_require_page_role` confía en el rol de la cookie.** Cambiar a `_page_staff(request, db)` exige tocar la firma de cada página de `main.py` (añadir `db`). Solo cascarón HTML; las APIs ya verifican.
5. **B9 / R2-8: `DELETE /events/{id}/users/{uid}/biometrics`.** Usar `privacy.erase_person(..., "biometric")` (todas las versiones, `is_biometric_enabled=false`, revocación en `audit_consent_logs`, `record_system_event`) y decidir si el coordinador puede borrar a nivel cliente o pasa a ADMIN como `purge-data`.
6. **R2-3: `erase_person(scope="all")`** no limpia `bulk_jobs.result_json` (cédula, nombre, correo, teléfono en los mensajes de error), `roulette_draws.winners_json` ni `reprint_requests.user_id`. Mejor que suprimir: no guardar esos datos (mensajes de la carga con «Fila N» y columna; sorteos con posición y referencia).
7. **R2-4: `bulk_steps.purge_expired`** solo recorre cargas `running|queued`; las `done|error` cuyo `_drop` falló dejan `<tenant>/bulk_steps/<id>/prepared` para siempre (filtrar `updated_at` entre `cut - 1 día` y `cut` para no recorrer todo). Verificar que `delete_prefix` de un prefijo vacío sea idempotente en `LocalStorage` y `GcsStorage`.
8. **R2-6: `cedula-mrz-scan`** lee el archivo entero antes de validar y no usa `heavy.heavy_slot()`: `read(MAX+1)` con 413 y el OCR dentro del `with heavy.heavy_slot()`.
9. **R2-7: `print_settings.put_settings`** sin `audit_actions` y `{"settings": null}` restablece todo.
10. **B13 / B14 (latentes con `ENFORCE_STAFF_TENANT=1`):** `print_stations.release` y `PUT /settings/single-session` (global, debería ser por tenant con `AppSetting` `single_session:<tenant>`), `/staff/coordinators|commercials` sin filtro de cliente, plantillas guardadas y colores globales. Usar `auth.assert_tenant_id` (ya existe). Decisión de producto sobre la sesión única por cliente.
11. **B15 (resto):** vencimiento del enlace de la ruleta por fin de evento + gracia (no se aplicó el de 2 días tras finalizar: un sorteo posterior al cierre es plausible); poner `display_token = None` al archivar si se prefiere revocar en vez de bloquear.
12. **R2-2 (producto):** `/c/{token}/lookup` es una consulta por cédula sin segundo factor sobre un enlace compartido; mitigación barata: exigir apellido o las dos últimas cifras del teléfono, o devolver el nombre enmascarado hasta ese paso.
13. **D10 / D12 / D13:** `REVOKE UPDATE, DELETE, TRUNCATE ON audit_actions FROM golden_app` + trigger (migración nueva escrita a mano, id ≤ 32 caracteres) y `ALTER DEFAULT PRIVILEGES` revisado en `scripts/neon_app_role.py`; filtro `testperson` en `areas_inventory._delivered_by_item`, `door.py` y `event_report.py`; `delete_event` debe limpiar `web_acceptances`, `person_changes`, `accept_mail_log`.

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


## Decisiones del dueño, 8-nov-2026

Rama `f3f/decisiones`. Migración `0096_decisiones_dueno` (cadena `0095_super_events_archive` -> `0096_decisiones_dueno`), solo aditiva.

### D2 — un pago aprobado sin cupo no debe pasar nunca (el cupo es como un asiento de cine)
- **Regla.** Al hacer clic en «pagar» (el envío que crea el pago, antes de abrir el widget de Wompi), si en ese instante hay cupo, queda BLOQUEADO para esa persona aunque no haya terminado de pagar. Al aprobarse el pago se CONFIRMA. Si el pago no se completa (rechazado, error, anulado o abandonado) el cupo se LIBERA: al instante si Wompi informa el fallo, o solo a los **10 minutos**.
- **Un solo valor.** `FORM_HOLD_MINUTES` (por defecto 10; piso 2, techo 180) define `formsvc.PENDING_HOLD`, que gobierna `held_count`, los cupos por variable, los usos de códigos y el parámetro `hold_from` de `form_reserve_slot` (misma función SQL de la migración 0049; no hizo falta tocarla). Antes eran 15 min fijos; ya no hay renovación de la ventana.
- **(a)** Sin cupo (total, por variable o código agotado) no se entra (`cupo_lleno`) ni se crea el pago. **(b)** El re-chequeo atómico es `form_reserve_slot` bajo `FOR UPDATE` en el envío; si ya no hay cupo responde 409 con «Se agotaron los cupos de este formulario. No se cobró nada.» (`formsvc.FULL_MSG`) y no se crea ni inscripción ni pago. La respuesta con pago incluye `hold_minutes` y el formulario muestra «Tu cupo está reservado por N minutos mientras pagas.»
- **(d) Red de seguridad, sin sobreaforo.** `refund_due` y `admit_on_approval` quedan SOLO para el caso físico de un pago que Wompi aprueba DESPUÉS de vencida la reserva (dinero que se movió fuera de nuestro control). Con la reserva vigente no se revisa nada; vencida, se cuentan confirmadas + pagos en curso de otros y, si el cupo total, el de la variable o el código ya están llenos (o la cédula ya está inscrita), la inscripción pasa a `refund_due`, aparece en la lista de pagos con el aviso «reembolsa y avísale» y en «Estado del sistema» (`payment_refund_due`). Si el cupo sigue libre, se admite.
- Pruebas: `tests/test_decisiones_d2.py` (bloqueo al iniciar, confirmación al aprobar, liberación a los 10 min y al fallar/anular, dos personas por el último cupo, cupo por variable, vía rápida con caché vieja, aprobación tardía con y sin cupo). Se ajustó `test_seguridad_cierre_publico.py` (X6) a la constante.

### D5 — aceptación web cuando la base no trae fecha de nacimiento (configurable)
- Ajuste del evento `events.accept_no_birth_mode`: `any` (comportamiento de siempre) | `require_personal_link` (sin el enlace personal del correo no se acepta con selfie: 403 «Para aceptar desde el celular usa el enlace personal que te llegó al correo…», antes de la cámara y sin guardar nada). Eventos existentes: `any`; eventos NUEVOS creados por la API: `require_personal_link`. El rechazo cuenta como fallo de esa cédula (mismo freno de 5 intentos / 15 min). No cambia nada para quien sí tiene fecha registrada ni para quien entra con enlace personal.
- Se edita en Parámetros -> Invitaciones («Si la base no trae la fecha de nacimiento», con ayuda) y por `PUT /api/events/{id}/biometric-setup` (clave `accept_no_birth_mode`). Código: `aceptar._check_birth(require_known=...)`. No se tocó `consents.py` más que la configuración, ni `enroll_face`. Pruebas: `tests/test_decisiones_d5.py`.

### D7 — repetir la entrega de inventario a la misma persona (configurable por ítem)
- `inventory_items.allow_repeat_delivery`: ítems existentes permiten (true); ítems NUEVOS por la API nacen sin permitir. Sin permiso, `deliver` responde 409 («ya se le entregó a esta persona y este ítem no se puede repetir…») y no entrega nada del combo; la comprobación ocurre después de bloquear los ítems `FOR UPDATE`, así doble clic o dos digitadores se turnan. Un `item_id` basura ahora es 400, no 500.
- Control en Parámetros -> Inventario (columna en la tabla y casilla en «Ítem nuevo»), y en el alta/edición de la API. Pruebas: `tests/test_decisiones_d7.py` (se ajustó el ayudante de `test_catalogs_archive.py`, que re-entrega al mismo).

### B9 — borrar el rostro de una persona
- `DELETE /events/{id}/users/{uid}/biometrics`: ahora solo admin y superior (antes coordinador). Usa `privacy.erase_person(..., "biometric")`: borra vector y foto (todas las versiones), pone `is_biometric_enabled=false` y registra la revocación en `audit_consent_logs`. Deja fila en `audit_actions` (`purge_biometrics`, evento, sin datos personales) y el evento de sistema. Los demás caminos que borran un rostro (`purge-data`, menores, rechazo) no cambian.
- La pantalla de Parámetros oculta el borrado de rostros al coordinador. Prueba: `tests/test_privacy.py` (el test que asumía coordinador ahora verifica el 403).

### Pendiente (no se tocó)
B1 / autorregistro (`consents.py`, `enroll_face`): depende de un texto legal que debe dar la auditora.

## Ronda de ataque 2 (8-nov-2026)
Segundo ataque de solo lectura sobre D2/D5/D7 (cupo, aceptación sin fecha, entrega repetida) y sobre color de marca y escarapela digital. Rama `f3g/ataque-nuevo`. Pruebas: `tests/test_ataque_ronda2.py`.

| Hallazgo | Estado | Qué se hizo / por qué |
|---|---|---|
| Cupo H1 (alto): aprobación tardía tras un rechazo entraba sin contar cupo | **Corregido** | `apply_result` (DECLINED/ERROR/VOIDED) adelanta el `created_at` de la inscripción pendiente (no de prueba) más allá de `PENDING_HOLD`; `admit_on_approval` ya no la ve como «apartado vigente» y cuenta confirmadas y pagos en curso: sin cupo queda `refund_due`. Efecto colateral bueno: cupos por variable y códigos se liberan al instante. |
| Cupo H2 (alto): tope por IP saltable con envíos paralelos; sin tope por cédula | **Corregido** | El tope por IP (`pending_from_ip`) se cuenta ahora DESPUÉS de `reserve_slot` (fila del formulario bloqueada), mismo 429 y mensaje. Nuevo tope por cédula: `FORM_PENDING_MAX_PER_PERSON` (defecto 3, 0 = sin tope; no cuenta la propia sesión). |
| Cupo H3 (alto/medio): renovar el apartado reenviando con el mismo `sid` sin límite | **Corregido** | `FORM_RENEWALS_MAX` (defecto 5) apartados por sesión en `PENDING_HOLD*3` (`rate_limit_events`, tipo `form_renewal_sid`); al superarlo, 429 sin crear apartado. |
| Cupo H4 (medio): `purge_stale_pending` O(N) bajo el candado del formulario; conciliación saturada | **Pendiente** | Cambio mayor (LIMIT, filtro SQL y job horario); H2/H3 ya frenan la fuente de pendientes basura. |
| D5 H5 (bajo/medio): el 403 distingue «inscrita sin fecha» (enumeración de cédulas) | **Aceptado** | Decisión del dueño (la pista del enlace personal es parte de D5); mitigado con 30 por IP / 10 min y 5 fallos por cédula / 15 min. |
| D5/D7 H6 (bajo): ajustes sin auditoría | **Corregido** | `accept_no_birth_mode` y `allow_repeat_delivery` registran `audit_actions` (valor anterior -> nuevo, sin datos personales) solo si cambian. |
| Cupo H7 (bajo): orden de candados contrario en el purgado perezoso (posible deadlock 40P01) | **Pendiente** | Raro, sin corrupción (responde 500); se resuelve junto con H4. |
| Cupo H8 (bajo): pagos de prueba fuera del cupo, `apply_list(hold=True)`, llamada a Wompi por reenvío, `update_item` sin FOR UPDATE | **Pendiente / aceptado** | Mala configuración o rol admin; la amplificación a Wompi queda acotada por H3. |
| Escarapela H1 (medio): apagar/encender sin auditoría y la selección de teléfono/correo sobrevive | **Corregido** | `set_digital_badge_enabled` audita (`event_digital_badge_enabled`) y al apagar pone `digital_badge_fields = NULL`. |
| Escarapela H2 (bajo): `/b/{token}/data` sin `Cache-Control` | **Corregido** | `private, no-store`. |
| Escarapela H3 (bajo): un coordinador decide exponer teléfono/correo sin confirmación del servidor | **Pendiente** | Pedir admin o `confirm_sensitive`; decisión de producto. |
| Color H4 (bajo): cambiar el color no invalidaba la caché pública del formulario | **Corregido** | `set_event_brand_color` llama `formsvc.invalidate_public_cache()` (solo este proceso; otros hasta ~5 s, y `s-maxage=60` del borde sigue). |
| Escarapela H5 (bajo): sin límite en `/b/{token}*` | **Aceptado** | Token de 144 bits: la enumeración no es viable; lo cubre Cloudflare. |
