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
