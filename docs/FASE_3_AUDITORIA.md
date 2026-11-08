# Fase 3: auditoría de borrar / archivar / permisos

## Estado de la Fase 3 (actualizado el 8-nov-2026)

| Estado | Pieza | Detalle |
|---|---|---|
| Hecho | Oleada 1: clientes | Archivar, restaurar, editar y borrado definitivo; registro de acciones (migración `0088`). |
| Hecho | Oleada 2: usuarios del personal y eventos | Archivar y restaurar cuentas (`0089`); archivar eventos finalizados y L7 (`0090`). |
| Hecho | Oleada 3: personas y formularios | Formularios: archivar, restaurar y borrado definitivo restringido (`0091`). Personas: revertido, se borran (ver «Personas: se borran, no se archivan»). |
| Hecho | Oleada 4-5: catálogos | Áreas, inventario, colores y plantillas de escarapela; tabla de auditoría de escrituras (`0092`). |
| Hecho | L7 corregido y modo tranquilo | Archiva solo la base del evento, una vez por semana; el Job horario deja descansar la base sin actividad. |
| Hecho | Decisión: respaldo cada 8 h | Ya aplicada: sin actividad, el respaldo corre a las 3, 4, 5, 11 y 19 h; con actividad, cada hora. La alerta de respaldo viejo pasó a 9 h. |
| Hecho | Documentos y gastos | Archivar y restaurar (coordinador+), borrado definitivo solo super_admin; migración `0093`. |
| Hecho | Huecos de CRUD, super eventos y pantallas | Estados de evento, plantillas de formulario, super eventos (`0094`, `0095`) y sus pantallas. |
| Hecho | Seguridad de alcance | Colores, calendario, exportaciones, límite de ritmo y SRI de Leaflet. |
| Hecho | Prueba completa en Cloud Shell | 8-nov-2026: 2.485 pasadas y 1 fallida (de prueba, ya corregida y verificada). |
| Pendiente | Strix y ZAP contra staging | Nunca contra producción. |
| Decidido | `ENFORCE_STAFF_TENANT` | Se queda apagado (decisión del 7-nov-2026). |
| Pendiente | CSP con `script-src` estricto | Hoy permite scripts en línea. |
| Hecho | Pantalla para restaurar colores y plantillas archivados | «Ver archivados» en la librería de colores y de plantillas. |

Cierre de la fase anterior: [`CIERRE_FASE_2.md`](CIERRE_FASE_2.md).

Decisiones de Juan David (7-nov-2026):
- **Archivar** = se oculta de listas y selectores y se puede restaurar. Nada se borra.
- **Clientes:** crea y edita comercial+; archiva y restaura admin+; borrado definitivo solo super_admin (cliente ya archivado y sin eventos), con registro.
- **Eventos finalizados:** se archivan a mano por admin+ (botón). 
- **L7 (aprobado por la auditora):** a los 90 días de cerrado un evento se ARCHIVA (no se borra); el super_admin lo desarchiva. Contrato con el cliente: poder entregar la base. La biometría sigue con su purga a los 7 días.

## Matriz (oleada 1: clientes)
| Acción | cliente | digitador | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|---|---|
| Ver clientes (activos) | - | - | sí | sí | sí | sí |
| Ver archivados | - | - | - | - | sí | sí |
| Crear / editar datos | - | - | - | sí | sí | sí |
| Archivar / restaurar | - | - | - | - | sí | sí |
| Borrar definitivo | - | - | - | - | - | sí (archivado, sin eventos) |

No se archiva un cliente con un evento «En Proceso». Un cliente archivado no recibe eventos nuevos ni se edita.

## Matriz (oleada 2: usuarios del personal)
| Acción | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|
| Ver cuentas archivadas | - | - | sí | sí |
| Archivar / restaurar | - | - | sí (cuentas por debajo de él y dentro de su alcance) | sí (también otro Super Admin, nunca el último) |
| Borrar definitivo | - | - | - | sí (cuenta archivada, sin eventos asignados) |

Archivar desactiva la cuenta y cierra su sesión (no inicia sesión; no sale en la lista ni en los selectores de coordinador, comercial o digitador/cliente). No se archiva a uno mismo, al último Super Admin ni a quien sea coordinador/comercial de un evento «En Proceso». Restaurar la deja DESACTIVADA: un administrador la reactiva aparte (`activate` rechaza las archivadas). Migración `0089_staff_archive` (`staff_users.archived_at/archived_by_id`). El borrado definitivo reemplaza al anterior (antes coordinador/admin borraban): el digitador temporal sigue limpiándose en bloque desde el evento. En el registro, el digitador se anota sin nombre (su usuario es la cédula).

## Registro de acciones
Tabla `audit_actions` (migración `0088_archive_and_audit`, solo INSERT): quién (id y rol), qué, entidad, id y nombre. Nunca valores personales (en ediciones solo los nombres de los campos).

## Oleada 2: eventos y L7 (archivo a los 90 días)
Migración `0090_event_archive` (columnas `events.archived_at` y `events.archived_by_id`; aditiva). Código en `app/event_archive.py`.

| Acción | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|
| Ver eventos activos | sí | sí | sí | sí |
| Ver archivados (`include_archived=true`) | - | - | sí | sí |
| Archivar (solo eventos FINALIZADOS) | - | - | sí | sí |
| Restaurar | - | - | sí (los archivados a mano) | sí (todos, incluidos los del Job) |
| Borrar definitivo (`DELETE /api/events/{id}`) | - | - | - | sí, solo de un evento ARCHIVADO; queda en `audit_actions` |

- **Qué es un evento archivado:** oculto de `/api/events`, `/api/events/search`, calendario y `my-events` (filtro `Event.archived_at IS NULL`); de solo lectura (`event_rules.ARCHIVED_OFF`: sin registro ni reconocimiento, sin acceso de cliente/digitador, sin ruleta ni registro touch, aunque su estado configurable diga otra cosa); no se edita ni se reabre (hay que restaurarlo primero); sus formularios públicos pasan a «finalizado» (el público recibe 404 y no se pueden reabrir mientras esté archivado). Al restaurar, los formularios siguen cerrados: se reabren a mano. **No se borra ningún dato.**
- **Interfaz:** «Archivar evento» en el menú «Más acciones» de cada evento finalizado (Clientes, Eventos y cuadro del calendario); «Ver eventos archivados» / «Ver archivados» (admin+) muestra los archivados con «Restaurar evento» y, para super_admin, «Eliminar definitivamente». El botón «Eliminar» directo desapareció.
- **Borrado definitivo:** antes era admin+ sobre cualquier evento; ahora super_admin y solo archivado (si no, 400). Las pruebas que borraban un evento (`test_forms`, `test_roulette`, `test_seguridad_cierre_archivos`) ahora lo finalizan, lo archivan y lo borran como super_admin.
- **L7 (decisión de la auditora: archivar está bien; el contrato exige poder entregar/restaurar la base):** el Job horario de ops tiene el paso `archive-events` (`ops_runner.archive_events`, también suelto: `--args=-m,app.ops_runner,archive-events`). Archiva los eventos `finalizado` con **90 días o más desde su cierre** (`EVENT_AUTO_ARCHIVE_DAYS`, 90 por defecto). **Fecha de cierre usada:** `events.finalized_at` (la estampa el listener al pasar a «finalizado»); si es NULL (eventos viejos), el final de `end_date`. Idempotente, un commit por evento, NUNCA borra, registra en `audit_actions` con actor NULL (`archived_by_id` NULL = lo archivó el sistema) y si un evento falla el paso falla (alerta) y se reintenta a la hora siguiente. Solo super_admin restaura lo que archivó el Job; un evento restaurado NO se vuelve a archivar solo hasta que se reabra y se vuelva a finalizar (se detecta con la marca `restore` posterior al cierre en `audit_actions`).
- **La purga biométrica de 7 días no se toca** (`app/privacy.py`); es independiente del archivo.
- **Pendiente / notas:** la caché del formulario público del servicio `publico` es por proceso; al archivar con el Job otro proceso tarda hasta que venza su caché en dejar de servirlo (al archivar a mano se limpia la del proceso que atiende). `sibling_attendance` (superevento) sigue contando los eventos archivados hermanos (son historial de la persona).

## Siguientes oleadas
usuarios del personal, personas, formularios, áreas, inventario, premios; L7 automático; cierre de seguridad (Strix + ZAP en staging, CSP, ENFORCE_STAFF_TENANT).
usuarios del personal, eventos (botón archivar + restaurar), personas, formularios, áreas, inventario, premios; L7 automático; cierre de seguridad (Strix + ZAP en staging, CSP, ENFORCE_STAFF_TENANT).

## Oleada personas y formularios (migración `0091_people_forms_archive`)
Auditoría de borrados que existían: `DELETE /api/users/{id}` (coordinador+, borraba a la persona del evento y, si no estaba en otro, la fila `User` y su foto), `DELETE /api/events/{e}/forms/{f}` (coordinador+, borraba el formulario con inscripciones; solo frenaba con pagos aprobados/reembolsados) y `DELETE .../submissions/{id}` (coordinador+). Quedan sin tocar: `DELETE /api/attendees/{id}/purge-data`, la revocación y `app/privacy.py` (derecho del titular), y `audit_consent_logs` (inmutable).

| Acción | digitador | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|---|
| Borrar persona del evento (`DELETE /users/{id}`) | - | sí | sí | sí | sí (ver sección final: no se archivan personas) |
| Archivar / restaurar formulario | - | - | - | sí | sí |
| Ver formularios archivados (`?include_archived=true`) | - | - | - | sí | sí |
| Borrar formulario definitivo | - | - | - | - | sí (archivado y sin inscripciones ni pagos) |
| Borrar UNA inscripción de formulario | - | - | - | sí (antes coordinador) | sí |

- **Persona:** ya no se archiva (ver «Personas: se borran, no se archivan», al final). Las columnas `event_attendees.archived_at/archived_by_id` de `0091` quedan sin uso.
- **Formulario:** `web_forms.archived_at/archived_by_id`. Archivar lo saca de la lista, lo cierra al público (404 como «finalizado»: ni página, ni estado, ni cotización, ni envíos), pasa «activo» a «cerrado» y apaga el calendario para que al restaurar NO se reabra solo, y no se puede editar ni cambiar su estado hasta restaurarlo. Se conservan inscripciones, archivos y pagos; el webhook de Wompi y la confirmación/estado de un pago ya iniciado siguen funcionando. El borrado definitivo exige archivado y cero inscripciones (las marcas «ya registrado» de la base no cuentan) y cero pagos. Borrar el evento completo sigue su camino de siempre.
- **Registro (`audit_actions`):** `form` (id y nombre del formulario) y `form_submission` (ids). Acciones `archive`, `restore`, `delete`.
- **UI:** formularios: «Archivar» en la tarjeta, casilla «Ver archivados» con Restaurar y, para super_admin, «Eliminar definitivamente».
- **Pendiente de decidir:** la ruta `DELETE /users/{id}/logs` (histórica, admin+, sin uso) no se tocó.
usuarios del personal, eventos (botón archivar + restaurar), personas, formularios; L7 automático; cierre de seguridad (Strix + ZAP en staging, CSP, ENFORCE_STAFF_TENANT). Documentos y legalizaciones de gastos del evento (ver hallazgos de abajo).

## Oleada catálogos (áreas, inventario, librerías de colores y de plantillas de escarapela)
Migración `0092_catalogs_archive` (aditiva: `archived_at` / `archived_by_id` en `event_areas`, `inventory_items`, `saved_colors`, `saved_badge_templates`). Mismo molde que clientes.

| Acción | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|
| Ver activos (zonas, ítems, colores, plantillas) | sí (comercial sin Parámetros) | - | sí | sí |
| Crear / editar | sí (igual que antes) | - | sí | sí |
| Ver archivados (`include_archived=true`) | - | - | sí | sí |
| Archivar / restaurar | - | - | sí | sí |
| Borrar definitivo | - | - | - | sí (archivado y SIN historial) |

Antes: coordinador+ borraba una zona CON todos sus movimientos, y un ítem sin entregas; coordinador+ borraba colores y plantillas de la librería. Ahora:
- **Zona archivada:** no se elige, no recibe movimientos ni se edita; sus movimientos siguen en `areas-report`. Borrado definitivo solo si no tiene movimientos.
- **Ítem archivado:** no se entrega ni se edita; el disponible y el reporte de inventario conservan sus entregas. Borrado definitivo solo si no tiene entregas.
- **Color / plantilla archivados:** salen de la lista y no se pueden importar; los eventos que ya los usaron guardan su copia y no cambian.
- Un nombre ya usado por un archivado se rechaza con el aviso de restaurarlo (no se duplica).
- Todo queda en `audit_actions` (entidades `event_area`, `inventory_item`, `saved_color`, `saved_badge_template`; acciones `archive`, `restore`, `delete`).
- UI: Parámetros del evento (checkbox «Ver zonas / ítems archivados» solo admin+, Archivar / Restaurar / Eliminar definitivamente con `showConfirm`); en la librería de colores y en la de plantillas, «Archivar» (solo admin+). Pendiente: pantalla para ver y restaurar colores y plantillas archivados (hoy solo por API: `GET ...?include_archived=true`, `POST .../restore`).
- **Premios / ruleta:** no existe un catálogo de premios en la base. La ruleta guarda su configuración (JSON por evento) y los sorteos ejecutados (`roulette_draws`, auditoría de ganadores) y NO tiene borrado de sorteos; lo único que se borra es la autorización de giro (`DELETE .../roulette/authorize`, efímera). No hay nada que archivar ahí: los premios entregados no corren riesgo.
- **No tocado a propósito:** estados de evento (`event-states`; ya tiene `is_active` y el borrado exige que ningún evento lo use), recordatorios del calendario (efímeros; solo el autor o admin+).

## Oleada documentos y legalizaciones del evento (migración `0093_docs_expenses_archive`)
Aditiva: `archived_at` / `archived_by_id` en `event_documents` y `event_expenses`. Código en `app/routers/event_docs.py`; pantallas `kiosk_documentos.html` y `kiosk_legalizaciones.html` (+ sus JS).

Auditoría de lo que existía: crear (`POST .../documents`, `POST .../expenses`, coordinador+), leer/listar, descargar (`.../download`, `.../evidence`), ZIP de documentos y reporte Excel de gastos (coordinador+) y borrar (`DELETE`, coordinador+, **borrado real del registro y del archivo, sin rastro**). **No existen endpoints de edición** (ni PUT ni PATCH): un documento o gasto mal cargado se archiva y se vuelve a crear; una prueba fija que siga así, y quien agregue edición debe rechazar los archivados. `delete_event_files` (borrar el evento completo, ya limitado a super_admin y a eventos archivados) no se tocó.

| Acción | coordinador / comercial | admin | super_admin |
|---|---|---|---|
| Crear, ver activos, descargar, ZIP, reporte | sí (igual que antes) | sí | sí |
| Ver archivados (`include_archived=true`) y descargar su archivo/evidencia | - | sí | sí |
| Archivar / restaurar | - | sí | sí |
| Borrar definitivo (`DELETE`) | - (antes sí) | - | sí, solo si está ARCHIVADO |

- **Archivado:** sale de la lista, del ZIP de documentos y del reporte Excel; en gastos **no suma al total** (ni en la lista con `include_archived`). El archivo (documento o evidencia) queda intacto en el almacenamiento y el registro conserva su historial; restaurar lo devuelve todo. Para coordinador/comercial un archivado responde 404 al intentar descargarlo.
- **Borrado definitivo:** super_admin y solo de lo ya archivado (si no, 400); borra la fila y después, ya confirmada la base, el archivo con `get_storage().delete` (misma API de `app/storage.py` que ya usaba el código). Antes lo hacía cualquier coordinador+.
- **Registro (`audit_actions`):** entidades `event_document` (nombre/referencia del documento) y `event_expense` (categoría del gasto), con `evento N`; acciones `archive`, `restore`, `delete`. Nunca el responsable, descripción, valor ni nombre del archivo.
- **UI:** casilla «Ver archivados» (solo admin+) en ambas pantallas; botones Archivar / Restaurar (admin+) y «Eliminar definitivamente» (super_admin, solo en archivados), todos con `showConfirm`. El contador y el total de la pantalla cuentan solo lo activo.
- **Paquete de evento (`event_transfer`):** los archivados viajan con su marca `archived_at`; `archived_by_id` se enlaza por nombre de usuario como los demás campos de personal.
- **Hueco de permisos (reportar, no cambiado):** documentos y gastos los crea hasta `comercial` (coordinador+ en `require_role`), aunque el docstring dice que no son módulos operativos; y con `ENFORCE_STAFF_EVENT_SCOPE` apagado cualquier coordinador ve los documentos y gastos de cualquier evento. Decisión pendiente de Juan David; no se tocó quién crea.

## Tabla de auditoría de escrituras y borrados
Generada con un recorrido estático (AST) de TODOS los `@router.post/put/patch/delete` de `app/routers/*.py` (212 rutas; `app/main.py` no define rutas de escritura propias). «Rol mínimo» es lo que declara la dependencia de la ruta (`require_role` = ese rol o superior; «sin comercial» = `require_role_excluding`). «Alcance de evento» = la ruta valida el evento/cliente con `get_event_for_staff`, `assert_event_*` o un ayudante que lo hace (revisado a mano en las que decían «vía helper»). La columna final marca lo que conviene revisar; **nada de esto se corrigió fuera de las oleadas**: es solo reporte.

| Método | Ruta | Rol mínimo | Qué hace | Alcance de evento | Marca |
|---|---|---|---|---|---|
| `POST` | `/api/aceptar/{code}` | ninguno (público / token) | submit | sí | Público a propósito (código del evento / token de aceptación) |
| `POST` | `/api/aceptar/{code}/check` | ninguno (público / token) | B2e: la fecha de nacimiento se valida ANTES de mostrar el texto y de abrir la cámara. Un menor  | sí | Público a propósito (código del evento / token de aceptación) |
| `DELETE` | `/api/attendees/{user_id}/purge-data` | admin+ | Supresión individual (Habeas Data). Solo admin y super_admin. `scope=biometric` = revocación (v | sí |  |
| `POST` | `/api/bulk_jobs/{job_id}/step` | coordinador+ (sin comercial) | Procesa el siguiente grupo de filas de una carga por pasos (idempotente; ver app/bulk_steps.py) | n/a |  |
| `POST` | `/api/bulk_register` | coordinador+ (sin comercial) | Carga masiva de la base del evento (ver `_bulk_register_impl` para las reglas). Con `background | sí |  |
| `POST` | `/api/bulk_roster` | coordinador+ (sin comercial) | Carga de SOLO la base (Excel/CSV, sin fotos). Es la misma carga que `bulk_register`, pero esta  | n/a |  |
| `POST` | `/api/bulk_roster/preview` | coordinador+ (sin comercial) | Vista previa de «solo agregar personas nuevas» (app/roster_append.py): lee y valida la hoja y c | sí |  |
| `POST` | `/api/bulk_timing` | coordinador+ (sin comercial) | Tiempos de una carga medidos EN EL NAVEGADOR (preparación, firma de la subida, subida, POST, pr | n/a | Sin evento: solo números del navegador al log; sin datos personales. |
| `POST` | `/api/calendar/notes` | coordinador+ | create calendar note | n/a | REVISAR: tablero global sin alcance por cliente/evento; coordinador+ avisa a cualquier personal notificable. |
| `DELETE` | `/api/calendar/notes/{note_id}` | coordinador+ | Solo el autor del recordatorio o admin+ puede borrarlo — es un tablero compartido, pero no | n/a | Solo el autor o admin+ (se valida en el cuerpo); borrado real de un recordatorio (efímero, sin archivar a propósito). |
| `POST` | `/api/checkin-cedula` | digitador+ | Acreditación por cédula (lector de código de barras o MRZ de la cédula nueva) — mismo | sí |  |
| `POST` | `/api/colors` | coordinador+ | Crea un color; si ya existe uno con ese nombre, le cambia el tono (así "Rojo Golden" es siempre | n/a | REVISAR: coordinador crea o SOBRESCRIBE el tono de un color compartido por toda la organización (mismo nombre). |
| `DELETE` | `/api/colors/{color_id}` | super_admin+ | Borrado DEFINITIVO: solo super_admin y de un color ya archivado (no hay otras dependencias: los | n/a |  |
| `POST` | `/api/colors/{color_id}/archive` | admin+ | Archivar = quitarlo de la lista de colores guardados. Los eventos que ya lo usan guardan su pro | n/a |  |
| `POST` | `/api/colors/{color_id}/restore` | admin+ | restore saved color | n/a |  |
| `POST` | `/api/door-face` | digitador+ | `file` = un fotograma. Sin prueba de vida (decisión del dueño del producto, 2026-10-16): la val | sí |  |
| `POST` | `/api/event-states` | admin+ | create state | n/a |  |
| `DELETE` | `/api/event-states/{state_id}` | admin+ | delete state | n/a | REVISAR: admin borra un estado configurable (ya exige que no haya eventos en él y otro activo con el mismo estado base). Existe `is_active` para desactivar; sin registro en audit_actions. |
| `PATCH` | `/api/event-states/{state_id}` | admin+ | update state | n/a |  |
| `PUT` | `/api/event-template` | admin+ | Guarda la plantilla completa. Cuerpo: {version, fields, creation_layout, calendar_layout}. 400  | n/a |  |
| `POST` | `/api/event-transfer/export/start` | super_admin+ | export start | n/a |  |
| `POST` | `/api/event-transfer/import` | super_admin+ | import event | sí |  |
| `POST` | `/api/event-transfer/import/dry-run` | super_admin+ | import dry run | n/a |  |
| `POST` | `/api/event-transfer/import/inspect` | super_admin+ | import inspect | n/a |  |
| `POST` | `/api/event-transfer/import/start` | super_admin+ | import start | n/a |  |
| `POST` | `/api/event-transfer/imports/{import_id}/confirm` | super_admin+ | confirm import | n/a |  |
| `POST` | `/api/event-transfer/upload` | super_admin+ | Subida de un paquete CHICO por la propia aplicación (sin tocar el bucket desde el navegador, as | n/a |  |
| `POST` | `/api/event-transfer/upload-url` | super_admin+ | Subida directa del paquete (URL firmada al almacenamiento; en local, un PUT firmado a la app):  | n/a |  |
| `POST` | `/api/events` | coordinador+ | Crear eventos: coordinador+. Historia: antes del 16-sep-2026 era coordinador+; ese día pasó a | sí |  |
| `DELETE` | `/api/events/{event_id}` | admin+ | Borrado permanente — solo admin+ (coordinador+ avanza el estado del evento vía PATCH status, | sí | REVISAR: admin borra un evento completo en cascada. Oleada eventos. |
| `PATCH` | `/api/events/{event_id}` | coordinador+ | update event | sí |  |
| `POST` | `/api/events/{event_id}/accept-mail/resend` | coordinador+ (sin comercial) | accept mail resend | sí |  |
| `POST` | `/api/events/{event_id}/accept-mail/start` | coordinador+ (sin comercial) | accept mail start | sí |  |
| `POST` | `/api/events/{event_id}/accept-mail/stop` | coordinador+ (sin comercial) | accept mail stop | sí |  |
| `POST` | `/api/events/{event_id}/accept-mail/test` | coordinador+ (sin comercial) | Envío de prueba: el correo aprobado, solo a la dirección indicada. | sí |  |
| `POST` | `/api/events/{event_id}/access-logs/sync` | digitador+ | Sincronizacion por LOTES de ingresos que un kiosco guardo mientras no tenia conexion (base del  | sí (vía helper) |  |
| `POST` | `/api/events/{event_id}/accreditations/undo` | digitador+ | Deshace una acreditación recién hecha con el botón «✅ Acreditar» de la fila (docs/16, 7a). Regl | sí |  |
| `POST` | `/api/events/{event_id}/areas` | coordinador+ (sin comercial) | create area | sí |  |
| `DELETE` | `/api/events/{event_id}/areas/{area_id}` | super_admin+ | Borrado DEFINITIVO: solo super_admin, de una zona ya archivada y SIN movimientos (con historial | sí |  |
| `PATCH` | `/api/events/{event_id}/areas/{area_id}` | coordinador+ (sin comercial) | update area | sí |  |
| `POST` | `/api/events/{event_id}/areas/{area_id}/archive` | admin+ | Archivar = ocultar la zona (ya no se elige ni recibe movimientos). Los movimientos registrados  | sí |  |
| `POST` | `/api/events/{event_id}/areas/{area_id}/movement` | digitador+ (sin comercial) | Entrada/salida por cédula o QR (el QR trae el ID). `direction`: in / out / auto (alterna). | sí |  |
| `POST` | `/api/events/{event_id}/areas/{area_id}/movement-face` | digitador+ (sin comercial) | Entrada/salida por reconocimiento facial (solo eventos con biometría). | sí |  |
| `POST` | `/api/events/{event_id}/areas/{area_id}/restore` | admin+ | restore area | sí |  |
| `PUT` | `/api/events/{event_id}/badge-bio-photo` | super_admin+ | Interruptor de seguridad (A1): permitir imprimir la foto BIOMÉTRICA en la escarapela (física y  | sí |  |
| `PUT` | `/api/events/{event_id}/badge-mode` | coordinador+ (sin comercial) | Ítem 14: `per_category` False = una plantilla para todas las categorías; True = una distinta | sí |  |
| `PUT` | `/api/events/{event_id}/badge-template` | coordinador+ (sin comercial) | update badge template | sí |  |
| `POST` | `/api/events/{event_id}/badge-template/import/{saved_id}` | coordinador+ (sin comercial) | 'Importar plantilla': copia el diseño de una SavedBadgeTemplate al BadgeTemplate de ESTE | sí |  |
| `POST` | `/api/events/{event_id}/badge-template/save-as` | coordinador+ (sin comercial) | 'Guardar como plantilla': copia el diseño actual del evento a una fila nueva de la | sí |  |
| `POST` | `/api/events/{event_id}/badge-template/upload-image` | coordinador+ (sin comercial) | Sube una imagen (fondo, o un image_static suelto como un logo) y devuelve el storage_path | sí |  |
| `PUT` | `/api/events/{event_id}/biometric-setup` | coordinador+ (sin comercial) | Guarda el paso guiado de una vez y validado EN EL SERVIDOR (esto es lo que protege; la pantalla | sí |  |
| `POST` | `/api/events/{event_id}/biometrics/purge` | admin+ | Borra los datos biométricos del evento (irreversible; solo admin+). Exige `confirm_name` = nomb | sí |  |
| `PUT` | `/api/events/{event_id}/categories` | coordinador+ (sin comercial) | Categorías del evento (ítem 14, reunión 2026-09-21): la lista de la que se eligen las de cada | sí |  |
| `POST` | `/api/events/{event_id}/cedula-mrz-scan` | digitador+ | Lee por OCR la zona MRZ del reverso de la cédula colombiana nueva (Sprint 2 Parte 2, | sí |  |
| `PUT` | `/api/events/{event_id}/certificates-enabled` | coordinador+ (sin comercial) | Activa/desactiva el módulo de certificados (ítem 5, reunión 2026-09-21). Al activarlo aparece | sí |  |
| `POST` | `/api/events/{event_id}/certificates/public-link` | coordinador+ (sin comercial) | Genera el enlace público para que cada persona descargue su certificado. Si ya existe se devuel | sí |  |
| `POST` | `/api/events/{event_id}/consent-click` | digitador+ | CAMINO 2 (un clic y rostro): la persona pulsó «Acepto…» en la pantalla del quiosco. Devuelve un | sí |  |
| `PUT` | `/api/events/{event_id}/consent-config` | coordinador+ (sin comercial) | Quién es el Responsable del evento (golden / tercero + datos del organizador) y cada cuánto se  | sí |  |
| `POST` | `/api/events/{event_id}/consents` | digitador+ | Registra decisiones de la persona: {entries: [{id (UUID del dispositivo), user_id O h (huella d | sí (vía helper) |  |
| `PUT` | `/api/events/{event_id}/digital-badge-enabled` | coordinador+ (sin comercial) | Activa/desactiva la escarapela digital (ítem 17): agrega el campo de correo corporativo y, al | sí |  |
| `PUT` | `/api/events/{event_id}/digital-email` | coordinador+ (sin comercial) | Guarda la plantilla (saneada). Vacía o `reset` = vuelve a la de siempre. | sí |  |
| `POST` | `/api/events/{event_id}/digital-email/preview` | coordinador+ (sin comercial) | preview digital email | sí |  |
| `POST` | `/api/events/{event_id}/digital-email/test` | coordinador+ (sin comercial) | Envía el correo con datos de ejemplo a UNA dirección que escribe quien edita (para verlo como l | sí |  |
| `POST` | `/api/events/{event_id}/digital-email/upload-image` | coordinador+ (sin comercial) | upload email image | sí |  |
| `PUT` | `/api/events/{event_id}/directory-page-size` | coordinador+ (sin comercial) | Filas por página de la tabla del directorio de ESTE evento (en vivo y lista local sin red): 10, | sí |  |
| `POST` | `/api/events/{event_id}/documents` | coordinador+ | El archivo llega en la petición o ya subido directo al almacenamiento (`upload`, ver app/upload | sí |  |
| `DELETE` | `/api/events/{event_id}/documents/{doc_id}` | coordinador+ | delete document | sí (vía helper) | SOSPECHOSO: coordinador borra definitivamente documentos del evento (archivo incluido), sin archivar ni registro. Candidato a la siguiente oleada. |
| `POST` | `/api/events/{event_id}/door-face/revert/{log_id}` | digitador+ | «Revisar»: el personal deshace una entrada por rostro que no le cuadra. Queda en el rastro de c | sí |  |
| `POST` | `/api/events/{event_id}/enroll-face` | digitador+ | CAMINO A: la persona ya aceptó en la pantalla y se captura su rostro en vivo. Guarda la foto ci | sí |  |
| `POST` | `/api/events/{event_id}/expenses` | coordinador+ | add expense | sí |  |
| `DELETE` | `/api/events/{event_id}/expenses/{expense_id}` | coordinador+ | delete expense | sí (vía helper) | SOSPECHOSO: coordinador borra legalizaciones de gastos (registro contable y su soporte) sin archivar ni registro. |
| `PUT` | `/api/events/{event_id}/facial-enabled` | coordinador+ (sin comercial) | Interruptor manual (2026-09-27, pedido explícito: "si me equivoqué y ya no quiero facial no pue | sí |  |
| `PUT` | `/api/events/{event_id}/field-configs/{field_key}` | coordinador+ (sin comercial) | upsert field config | sí |  |
| `DELETE` | `/api/events/{event_id}/fields/{field_key}` | coordinador+ (sin comercial) | Borra un campo de ESTE evento (también uno que vino en la base original). Hay que escribir su n | sí |  |
| `POST` | `/api/events/{event_id}/final-report` | coordinador+ | upload final report | sí |  |
| `DELETE` | `/api/events/{event_id}/form-templates/{template_id}` | coordinador+ | delete template | sí | REVISAR: borrado real de plantilla de formulario (coordinador). Oleada formularios. |
| `POST` | `/api/events/{event_id}/forms` | coordinador+ | Crea un formulario nuevo (con campos de partida) o, con `template_id`, a partir de una plantill | sí |  |
| `POST` | `/api/events/{event_id}/forms-import` | admin+ | Crea la copia: todo o nada (si algo falla, se borran las imágenes ya subidas y no queda nada en | sí |  |
| `POST` | `/api/events/{event_id}/forms-import/preview` | admin+ | Vista previa: valida y cuenta lo que se crearía. No escribe NADA. | sí |  |
| `POST` | `/api/events/{event_id}/forms-upload-image` | coordinador+ | upload image | sí |  |
| `DELETE` | `/api/events/{event_id}/forms/{form_id}` | coordinador+ | delete form | sí | REVISAR: coordinador borra un formulario con pagos, reembolsos e inscripciones en cascada. Oleada formularios. |
| `PUT` | `/api/events/{event_id}/forms/{form_id}` | coordinador+ | Guarda nombre, dirección (slug), diseño y/o configuración. El diseño se valida completo en el s | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/align-to-base` | admin+ | Lleva un campo con cupos de las inscripciones al valor que la BASE DEL EVENTO tiene para esa pe | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/client-access` | coordinador+ | Crea el usuario y la contraseña temporal (se muestran UNA sola vez). Misma regla que las cuenta | sí (vía helper) | REVISAR: coordinador entrega acceso de cliente al formulario (valida evento con _form_for). |
| `DELETE` | `/api/events/{event_id}/forms/{form_id}/client-access/{staff_id}` | coordinador+ | revoke client access | sí (vía helper) |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/discount-codes` | coordinador+ | Crea códigos para un descuento «con código»: `shared` = UN código válido `max_uses` veces (ej.  | sí |  |
| `DELETE` | `/api/events/{event_id}/forms/{form_id}/discount-codes/{code_id}` | coordinador+ | delete code | sí | REVISAR: borrado real de un código de descuento (coordinador). Oleada formularios. |
| `POST` | `/api/events/{event_id}/forms/{form_id}/duplicate` | coordinador+ | duplicate form | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/feed-now` | coordinador+ | Carga a la base del evento todas las inscripciones reales aún no cargadas (quedan «No registrad | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/invites/send` | coordinador+ | Genera el enlace personal de cada persona de la fuente y lo manda por correo (a quien tenga cor | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/payments/{payment_id}/refund` | admin+ | Body: `reason` (obligatorio), `amount` (COP; por defecto el saldo), `manual` (true = ya se devo | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/payments/{payment_id}/refunds/{refund_id}/{action}` | admin+ | Un reembolso `pending` (Wompi lo aceptó pero no confirma): `check` lo vuelve a consultar y lo c | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/people` | coordinador+ | Sube (Excel/CSV) la base que pre-llenará SOLO este formulario (fuente «base subida aparte»); re | sí |  |
| `DELETE` | `/api/events/{event_id}/forms/{form_id}/registered` | coordinador+ | «Quitar todas las marcas»: borra las marcas «ya registrado» de este formulario (liberan el cupo | sí | REVISAR: coordinador vacía la base de registrados del formulario. Oleada formularios. |
| `POST` | `/api/events/{event_id}/forms/{form_id}/registered` | coordinador+ | Carga o recarga la lista de «Personas ya registradas» de ESTE formulario (cédula, o el campo id | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/registered/preview` | coordinador+ | Antes de cargar: qué columnas del archivo corresponden a campos del formulario, cuáles de ellas | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/save-as-template` | coordinador+ | save template | sí |  |
| `PUT` | `/api/events/{event_id}/forms/{form_id}/status` | coordinador+ | Estado manual, calendario por fechas y cupo (editable en caliente: no se pierde ninguna inscrip | sí |  |
| `DELETE` | `/api/events/{event_id}/forms/{form_id}/submissions/{submission_id}` | coordinador+ | delete submission | sí | SOSPECHOSO: coordinador borra una inscripción (puede tener pago) sin archivar. Oleada formularios. |
| `POST` | `/api/events/{event_id}/forms/{form_id}/unify-values` | admin+ | Unifica un campo que define cupos en las inscripciones ya guardadas: «Bogota», «BOGOTÁ» y los a | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/variant-table/parse` | coordinador+ | Lee un .xlsx subido y lo empareja con la tabla; devuelve las celdas y los problemas SIN guardar | sí |  |
| `POST` | `/api/events/{event_id}/forms/{form_id}/variant-table/template` | coordinador+ | Genera el .xlsx (hojas «Tabla», «Instrucciones» y «Valores válidos») de la tabla de variantes q | sí |  |
| `PUT` | `/api/events/{event_id}/idle-minutes` | coordinador+ (sin comercial) | Minutos sin uso tras los que se cierra la sesión del personal que trabaja en ESTE evento (5 a 6 | sí |  |
| `POST` | `/api/events/{event_id}/inventory` | coordinador+ (sin comercial) | create item | sí |  |
| `POST` | `/api/events/{event_id}/inventory/deliver` | digitador+ (sin comercial) | Entrega uno o varios ítems (combo) a una persona: `{cedula, items: [{item_id, qty}]}`. Todo o | sí |  |
| `DELETE` | `/api/events/{event_id}/inventory/{item_id}` | super_admin+ | Borrado DEFINITIVO: solo super_admin, de un ítem ya archivado y SIN entregas (con entregas solo | sí |  |
| `PATCH` | `/api/events/{event_id}/inventory/{item_id}` | coordinador+ (sin comercial) | update item | sí |  |
| `POST` | `/api/events/{event_id}/inventory/{item_id}/archive` | admin+ | Archivar = ocultar el ítem (ya no se entrega). Las entregas hechas y el reporte se conservan; u | sí |  |
| `POST` | `/api/events/{event_id}/inventory/{item_id}/restore` | admin+ | restore item | sí |  |
| `PUT` | `/api/events/{event_id}/last-name-required` | coordinador+ (sin comercial) | Fase 2: «Apellido obligatorio». `mode`: «auto» (según la base cargada), «required» u «optional» | sí |  |
| `PUT` | `/api/events/{event_id}/logo` | coordinador+ (sin comercial) | `mode`: 'default' (logo de Golden), 'hidden' (sin logo) o 'custom' (el propio ya subido). Opcio | sí |  |
| `POST` | `/api/events/{event_id}/logo/upload` | coordinador+ (sin comercial) | upload event logo | sí |  |
| `PUT` | `/api/events/{event_id}/modules` | coordinador+ (sin comercial) | Switches por evento: `areas_enabled` / `inventory_enabled` (solo se cambian los que vengan). | sí |  |
| `POST` | `/api/events/{event_id}/optional-fields` | coordinador+ (sin comercial) | Agrega un campo opcional nuevo directamente desde Parámetros del Evento (2026-09-16, | sí |  |
| `POST` | `/api/events/{event_id}/outbox/sync` | digitador+ | Sincroniza la BANDEJA DE SALIDA de un quiosco (docs/16, B8): operaciones hechas sin red, hasta  | sí | digitador+: valida el evento con _event_for_sync (ventana de 7 días tras finalizar). |
| `PUT` | `/api/events/{event_id}/person-form` | admin+ | put person form | sí |  |
| `PUT` | `/api/events/{event_id}/precalculo-autorizado` | super_admin+ | Solo super_admin. Para activarlo: evento de un tercero y referencia + fecha (AAAA-MM-DD) del an | sí |  |
| `POST` | `/api/events/{event_id}/print-devices/heartbeat` | digitador+ (sin comercial) | El equipo dice que sigue ahí y si tiene la impresora conectada. Responde dónde imprime este usu | sí |  |
| `POST` | `/api/events/{event_id}/print-jobs` | digitador+ (sin comercial) | create job | sí |  |
| `POST` | `/api/events/{event_id}/print-jobs/release` | digitador+ (sin comercial) | La persona cerró o canceló la ventana: los trabajos que seguían «enviados» a este puesto vuelve | sí |  |
| `POST` | `/api/events/{event_id}/print-jobs/result-batch` | digitador+ (sin comercial) | Los resultados de una tanda, DESPUÉS de que la ventana de impresión terminó. Cada trabajo se co | sí |  |
| `POST` | `/api/events/{event_id}/print-jobs/{job_id}/result` | digitador+ (sin comercial) | job result | sí |  |
| `PUT` | `/api/events/{event_id}/print-settings` | coordinador+ (sin comercial) | Reemplaza los valores del evento por los enviados (lo omitido o `null` vuelve al valor de fábri | sí |  |
| `PUT` | `/api/events/{event_id}/print-stations/{staff_id}` | coordinador+ (sin comercial) | Guarda la configuración del puesto (`settings`; `null` o `{}` la borra: vuelve a lo de siempre) | sí |  |
| `PUT` | `/api/events/{event_id}/registro-gear-digitadores` | coordinador+ (sin comercial) | Plan 7: «Mostrar configuración del registro a digitadores». Solo decide si el digitador VE el e | sí |  |
| `PUT` | `/api/events/{event_id}/reprint-mode` | admin+ | Reimpresión del evento: habilitada (por defecto) o deshabilitada. SOLO admin o super_admin. | sí |  |
| `POST` | `/api/events/{event_id}/reprint-requests` | digitador+ (sin comercial) | Pide permiso para reimprimir. Solo si la reimpresión está deshabilitada, la persona ya se impri | sí |  |
| `POST` | `/api/events/{event_id}/reprint-requests/use` | digitador+ (sin comercial) | Gasta el permiso aprobado ANTES de imprimir en el propio equipo (USB o ventana de Chrome). La i | sí |  |
| `POST` | `/api/events/{event_id}/revert-to-created` | admin+ | Devuelve un evento «en curso» a «creado» (solo admin y super_admin). NO borra nada (ni personas | sí |  |
| `DELETE` | `/api/events/{event_id}/roulette/authorize` | coordinador+ | cancel authorization | sí |  |
| `POST` | `/api/events/{event_id}/roulette/authorize` | coordinador+ | El operador AUTORIZA un giro: se valida ahora (para que los errores salgan aquí y no frente al  | sí |  |
| `PUT` | `/api/events/{event_id}/roulette/behavior` | coordinador+ | save behavior | sí |  |
| `POST` | `/api/events/{event_id}/roulette/display-link` | coordinador+ | Enlace de la pantalla de visualización (para el proyector): sin login, con código secreto. Se c | sí |  |
| `POST` | `/api/events/{event_id}/roulette/execute` | coordinador+ | Ejecuta el sorteo YA (sin esperar el botón de la pantalla pública). La interfaz normal usa `aut | sí |  |
| `POST` | `/api/events/{event_id}/roulette/reset-round` | coordinador+ | Modo «todos»: empieza una ronda nueva (vuelven a poder salir todos). | sí |  |
| `PUT` | `/api/events/{event_id}/roulette/style` | coordinador+ | save style | sí |  |
| `POST` | `/api/events/{event_id}/roulette/upload-image` | coordinador+ | upload image | sí |  |
| `PUT` | `/api/events/{event_id}/shared-print` | coordinador+ (sin comercial) | set enabled | sí |  |
| `PUT` | `/api/events/{event_id}/shared-print/route` | coordinador+ (sin comercial) | set route | sí |  |
| `POST` | `/api/events/{event_id}/staff-users` | coordinador+ | Crea una cuenta digitador o cliente y la autoriza para ESTE evento en un solo paso — no | sí |  |
| `POST` | `/api/events/{event_id}/staff-users/assign-existing` | admin+ | Autoriza una cuenta digitador/cliente YA existente (de otro evento) para ESTE evento — | sí |  |
| `POST` | `/api/events/{event_id}/staff-users/import` | coordinador+ | Asigna digitadores a este evento desde un Excel (Identificación, Nombres, Apellidos). Cédula nu | sí |  |
| `POST` | `/api/events/{event_id}/staff-users/purge-temporary` | coordinador+ | Borra de una vez TODAS las cuentas digitador asignadas a este evento (lo mismo que «Borrar perm | sí |  |
| `DELETE` | `/api/events/{event_id}/staff-users/{staff_id}` | coordinador+ | Revoca el acceso de un digitador/cliente a ESTE evento y SOLO a este (E-N1, 0C). Su cuenta, su  | sí | REVISAR: coordinador desvincula/borra personal del evento (borrado real de autorizaciones/puestos). |
| `POST` | `/api/events/{event_id}/staff-users/{staff_id}/login-request` | coordinador+ | decide login | sí (vía helper) |  |
| `POST` | `/api/events/{event_id}/staff-users/{staff_id}/unlock` | coordinador+ | unlock account | sí (vía helper) |  |
| `POST` | `/api/events/{event_id}/stats-links` | coordinador+ | Crea un enlace. `scope`: «event» (estadísticas del evento) o «form» (con `form_id`). `days`: 1  | sí |  |
| `DELETE` | `/api/events/{event_id}/stats-links/{link_id}` | coordinador+ | revoke link | sí |  |
| `DELETE` | `/api/events/{event_id}/users/{user_id}/biometrics` | coordinador+ (sin comercial) | Derecho de supresión de una persona: borra su rostro (foto y encoding). Conserva su identidad y | sí |  |
| `DELETE` | `/api/events/{event_id}/users/{user_id}/signature/{field_key}` | digitador+ | delete signature | sí (vía helper) |  |
| `PUT` | `/api/events/{event_id}/users/{user_id}/signature/{field_key}` | digitador+ | put signature | sí (vía helper) |  |
| `PATCH` | `/api/events/{event_id}/users/{user_id}/status` | digitador+ | Cambia manualmente el estado de registro de una persona en este evento (2026-09-16, nuevo; | sí |  |
| `POST` | `/api/events/{event_id}/web-acceptance/{user_id}/verify` | digitador+ | El personal confirma, con el documento físico o el QR de la persona, que quien aceptó desde el  | sí |  |
| `POST` | `/api/ingreso/cancelar` | ninguno (público / token) | waiting cancel | n/a | Sin dependencia: igual que /ingreso/estado. |
| `POST` | `/api/ingreso/estado` | ninguno (público / token) | `pending` (con `expires_in`), `approved` (con `redirect`: la sesión ya quedó creada), `denied`  | n/a | Sin dependencia: parte del flujo de ingreso (token de la solicitud de login). Revisar que el token sea de un solo uso y con límite de intentos. |
| `PUT` | `/api/me/tours-auto-off` | cualquier sesión | «Deshabilitar demos automáticas»: se guarda en la cuenta (así vale en el celular y en el comput | n/a |  |
| `POST` | `/api/ops/simulate-crash` | _ops_reader | Simulacro 1 de la Fase 4 («matar una instancia» mientras hay carga). Triple candado: solo con D | n/a | REVISAR: se abre con un token estático OPS_TOKEN además de admin+; solo opera con CHAOS_ENABLED=1 en staging (404 en otro caso). Confirmar que CHAOS_ENABLED nunca está en producción. |
| `POST` | `/api/print-stations/{staff_id}/release` | admin+ | Un admin libera la cuenta de un puesto (por ejemplo, cambió de computador): la sesión anterior  | n/a |  |
| `POST` | `/api/privacy-requests` | admin+ | create request | n/a | admin+ sin alcance de cliente (el evento es opcional): aceptable, pero cualquier admin ve/crea de cualquier cliente. |
| `PUT` | `/api/privacy-requests/{request_id}/claim-flag` | admin+ | Activa o quita la bandera «reclamo en trámite» sobre el dato de la persona (máximo 2 días hábil | n/a |  |
| `PUT` | `/api/privacy-requests/{request_id}/status` | admin+ | set status | n/a |  |
| `POST` | `/api/recognize` | digitador+ | Sprint 2.2 Fase B (2026-09-16): un match facial YA NO acredita solo por defecto — antes | sí |  |
| `POST` | `/api/recognize/candidates` | digitador+ | «Ver 5 más cercanos»: los candidatos siguientes del MISMO reconocimiento (los guarda el token:  | n/a |  |
| `POST` | `/api/recognize/person` | digitador+ | El registro (fila del directorio) del candidato elegido, para abrir el modal «Editar»: desde ah | n/a |  |
| `POST` | `/api/recognize/photo` | digitador+ | Foto de registro de un candidato del reconocimiento (`index` 0 = la persona principal). Solo la | n/a |  |
| `POST` | `/api/register` | digitador+ | file es OPCIONAL: el alta manual la puede disparar tanto el flujo facial (con foto, para | n/a |  |
| `POST` | `/api/reprint-requests/{request_id}/decision` | coordinador+ (sin comercial) | decision | sí | Alcance por assert_event_tenant + reprint.can_decide (no usa get_event_for_staff): correcto, anotado por ser distinto al patrón. |
| `DELETE` | `/api/saved-badge-templates/{saved_id}` | super_admin+ | Borrado DEFINITIVO: solo super_admin y de una plantilla ya archivada. | n/a |  |
| `POST` | `/api/saved-badge-templates/{saved_id}/archive` | admin+ | Archivar = sacarla de la librería (ya no se ofrece para importar). Los eventos que la importaro | n/a |  |
| `POST` | `/api/saved-badge-templates/{saved_id}/restore` | admin+ | restore saved badge template | n/a |  |
| `POST` | `/api/session/touch` | ninguno (público / token) | La persona hizo algo (clic, teclas, toque, scroll): el middleware ya renovó la sesión; aquí se  | n/a | Sin dependencia propia: lee la sesión del navegador; renueva la actividad. |
| `PUT` | `/api/settings/golden-logo-height` | super_admin+ | Alto del logo de Golden para TODO el sistema (6-nov-2026): solo el super administrador. | n/a |  |
| `PUT` | `/api/settings/single-session` | admin+ | put single session | n/a |  |
| `POST` | `/api/staff` | admin+ | create staff | n/a |  |
| `DELETE` | `/api/staff/{staff_id}` | coordinador+ | Borrado PERMANENTE (no desactivación) — cada rol solo puede borrar lo que tiene | n/a | REVISAR: coordinador borra cuentas de personal (acotado por DELETABLE_ROLES_BY y _assert_can_manage). Borrado real; oleada usuarios. |
| `PATCH` | `/api/staff/{staff_id}/activate` | admin+ | activate staff | n/a |  |
| `PATCH` | `/api/staff/{staff_id}/deactivate` | admin+ | deactivate staff | n/a |  |
| `PATCH` | `/api/staff/{staff_id}/email` | admin+ | Completa/corrige el correo de una cuenta (las creadas antes de que existiera el campo no lo tie | n/a |  |
| `PUT` | `/api/staff/{staff_id}/password` | coordinador+ | Restablece la contraseña de una cuenta que `staff` puede administrar (un coordinador, las de di | n/a |  |
| `PATCH` | `/api/staff/{staff_id}/role` | admin+ | Cambia el rol de una cuenta ya creada (Sprint 4). Solo entre los roles que se crean desde Confi | n/a |  |
| `PATCH` | `/api/staff/{staff_id}/secondary-role` | admin+ | Sprint 2.4 Fase 15 (2026-09-17, pedido explícito): "hay coordinadores que también pueden | n/a |  |
| `POST` | `/api/super-events` | coordinador+ | create super event | sí |  |
| `POST` | `/api/tenants` | comercial+ | Sprint 2.4, 2026-09-16 (pedido explícito): crear clientes pasó a ser comercial+ — antes | n/a |  |
| `DELETE` | `/api/tenants/{tenant_id}` | super_admin+ | Borrado DEFINITIVO: solo super_admin, solo de un cliente ya archivado y sin eventos, y queda re | n/a |  |
| `PATCH` | `/api/tenants/{tenant_id}` | comercial+ | update tenant | sí |  |
| `POST` | `/api/tenants/{tenant_id}/archive` | admin+ | Archivar = ocultar de las listas y de los selectores. No borra nada: sus eventos y bases siguen | n/a |  |
| `POST` | `/api/tenants/{tenant_id}/restore` | admin+ | restore tenant | n/a |  |
| `POST` | `/api/uploads` | digitador+ | `{purpose, event_id, filename, size, content_type}` → `{url, method, headers, token}`. | sí |  |
| `PUT` | `/api/uploads/local/{token}` | ninguno (público / token) | Receptor del PUT cuando el almacenamiento es local (desarrollo y la VM): hace lo que en la nube | n/a | Sin sesión a propósito: la autoriza el token firmado de la subida (solo almacenamiento local, no en la nube). |
| `DELETE` | `/api/users/{user_id}` | coordinador+ | Borra a la persona de ESTE evento por completo (2026-09-16, pedido explícito: "Eliminar" | sí | REVISAR: coordinador borra a la persona, sus registros de acceso y su foto (borrado real, sin archivar). Oleada personas. |
| `PATCH` | `/api/users/{user_id}` | digitador+ | update user | sí |  |
| `PUT` | `/api/users/{user_id}/cedula` | admin+ | Corrige la cédula (User.id) de una persona ya registrada (2026-09-16, pedido explícito: a | sí |  |
| `DELETE` | `/api/users/{user_id}/logs` | admin+ | Histórico (2026-09-21 en adelante) — ya NO se usa desde el frontend, quedó reemplazado por | sí | REVISAR: admin borra el historial de accesos de una persona. Oleada personas. |
| `POST` | `/api/users/{user_id}/print-log` | digitador+ (sin comercial) | Registra una impresión de escarapela — se llama justo antes de abrir la ventana de | sí |  |
| `POST` | `/cambiar-contrasena` | ninguno (público / token) | change submit | sí |  |
| `POST` | `/f/{event_id}/{slug}/beacon` | ninguno (público / token) | Marcas de uso para la analítica: `view` (abrió), `start` (empezó a llenar). Sin datos personale | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/f/{event_id}/{slug}/check` | ninguno (público / token) | Aviso temprano «Ya estás inscrito» mientras la persona escribe su identificador (cédula u otro  | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/f/{event_id}/{slug}/gate` | ninguno (público / token) | gate | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/f/{event_id}/{slug}/lookup` | ninguno (público / token) | Autoservicio por cédula: si la persona está en la base elegida, se pre-llenan y bloquean sus da | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/f/{event_id}/{slug}/pay/confirm` | ninguno (público / token) | El navegador avisa que el widget se cerró (con el id de la transacción, si la hay). No se le cr | n/a (público) | Público a propósito (Wompi sin sesión); webhook con checksum SHA-256 |
| `POST` | `/f/{event_id}/{slug}/quote` | ninguno (público / token) | Monto a pagar según lo que la persona lleva escrito (para mostrar el total en vivo). Solo lee;  | n/a (público) | Público a propósito (Wompi sin sesión); webhook con checksum SHA-256 |
| `POST` | `/f/{event_id}/{slug}/submit` | ninguno (público / token) | Lee el cuerpo (lo unico asincrono) y pasa el resto —consultas, cupo, insercion— a un hilo: el b | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/f/{event_id}/{slug}/upload` | ninguno (público / token) | Firma la subida directa de un archivo del formulario (ver app/uploads.py): `{fid, filename, siz | n/a (público) | Público a propósito (formulario web); protegido por límites de uso y cupo |
| `POST` | `/internal/faces/run` | token OIDC de Google | Cola APARTE de los cálculos faciales (vector tras la aceptación): corre en el servicio de biome | n/a |  |
| `POST` | `/internal/jobs/run` | token OIDC de Google | Ejecuta la cola dentro de ESTA petición (en Cloud Run con facturación por petición la CPU se re | n/a |  |
| `POST` | `/login` | ninguno (público / token) | login submit | sí |  |
| `POST` | `/logout` | ninguno (público / token) | logout | n/a |  |
| `POST` | `/olvide-contrasena` | ninguno (público / token) | Manda un enlace de un solo uso al correo de la cuenta. La respuesta es SIEMPRE la misma (exista | sí |  |
| `POST` | `/r/{token}/spin` | ninguno (público / token) | El botón «Girar» de la pantalla de visualización: solo funciona si el operador AUTORIZÓ un giro | n/a | Pantalla pública por token (/r/<token>) |
| `POST` | `/reimpresion/{token}` | ninguno (público / token) | La decisión (POST; el Origin lo revisa el middleware CSRF). El enlace se gasta primero con un U | n/a |  |
| `POST` | `/restablecer/{token}` | ninguno (público / token) | reset submit | n/a |  |
| `POST` | `/webhooks/wompi` | ninguno (público / token) | Eventos de Wompi (`transaction.updated`). Lee el cuerpo (lo único asíncrono) y procesa en un hi | n/a | Público a propósito (Wompi sin sesión); webhook con checksum SHA-256 |

### Hallazgos de la auditoría (resumen)
1. **Ninguna ruta de escritura con sesión carece de rol:** toda ruta sin dependencia es pública a propósito (`/f/*` formularios, `/api/aceptar/*`, Wompi, pantalla de ruleta, enlaces `/ver`, `/reimpresion/<token>`, login/logout) o se autoriza por token (`PUT /api/uploads/local/{token}`, `/internal/*` con OIDC de Google).
2. **Borrados reales por coordinador, sin archivar ni registro** (lo más delicado): `DELETE /api/users/{user_id}` (persona + accesos + foto), `DELETE .../documents/{id}` y `.../expenses/{id}` (documentos y legalizaciones con su soporte), `DELETE .../forms/{id}` y `.../submissions/{id}` (formularios y sus pagos), `DELETE /api/staff/{id}` y `.../staff-users/{id}`. Las de personas, formularios, usuarios y eventos están en las otras oleadas; **documentos y gastos del evento no están en ninguna**: candidatos a la siguiente.
3. **Borrado real por admin:** `DELETE /api/users/{id}/logs`, `DELETE /api/events/{id}`, `DELETE /api/event-states/{id}` (este último sin registro en `audit_actions`).
4. **Alcance por cliente/evento más débil:** `POST /api/colors` (color compartido que cualquier coordinador sobrescribe por nombre), `POST /api/calendar/notes` (tablero global), `POST /api/privacy-requests` (admin sin alcance de cliente). Con `ENFORCE_STAFF_TENANT` apagado (valor por defecto), `get_event_for_staff` no aísla por cliente al personal que tiene `tenant_id`: revisar ese interruptor en el cierre de seguridad.
5. **`POST /api/ops/simulate-crash`** se abre con un token estático (`OPS_TOKEN`) además de admin+; responde 404 salvo `CHAOS_ENABLED=1` (staging). Verificar que esa variable no exista en producción.
6. **`POST /api/ingreso/estado` y `/cancelar`** no tienen dependencia (flujo de ingreso por token): confirmar que el token es de un solo uso y tiene límite de intentos.
7. Roles inconsistentes entre pares: `PUT /api/staff/{id}/password` y `DELETE /api/staff/{id}` son coordinador+ pero se acotan dentro del cuerpo (`_manageable_roles`, `DELETABLE_ROLES_BY`, `_assert_can_manage`); correcto, pero el control está en el cuerpo y no en la dependencia: un cambio descuidado lo abriría.


## L7 corregido (7-nov-2026, pedido de Juan David)
- El Job **ya no archiva el evento**: el evento sigue en todas las listas. Archiva **solo la base de datos** (`events.data_archived_at`): el personal deja de ver las personas del evento (directorio) y sus formularios públicos se cierran; un super_admin la desarchiva (`POST /api/events/{id}/restore-data`, menú «Desarchivar base de datos»). Nada se borra.
- **Una vez por semana**: domingo a las `OPS_WEEKLY_HOUR` (5 a. m., hora de Bogotá), dentro del Job horario ya existente (sin tarea nueva de Scheduler). El resto de la semana ese paso no toca la base.
- Archivar el evento completo (ocultarlo de las listas) sigue siendo solo manual, admin+.

## Qué despierta la base de Neon (revisión de todo el código)
Fuera del uso normal de las pantallas, lo único que corre solo es el Job horario (`app/ops_runner.py`, Cloud Scheduler `5 * * * *`). El monitor de disponibilidad pega a `/health`, que no toca la base; las pantallas solo consultan mientras alguien las usa (se pausan en reposo).
| Paso del Job | Cada | Toca la base |
|---|---|---|
| respaldo (pg_dump) | hora | sí |
| respaldo diario / purga biométrica | día (3 a. m. / 4 a. m.) | sí |
| revisión de respaldos | hora | no (solo el bucket) |
| cola pendiente (`sweep`) | hora | sí |
| borrar reportes y paquetes vencidos | hora | sí |
| precalentamiento (`warmup`) | hora | sí |
| archivar bases a los 90 días (L7) | **semana** | sí |
Pendiente de decisión: el respaldo, la cola, los reportes vencidos y el precalentamiento siguen cada hora (el respaldo horario es la protección durante un evento; la purga biométrica debe seguir diaria por el plazo de 7 días de la política).

## Modo tranquilo del Job horario (7-nov-2026, decisión de Juan David)
`app/ops_state.py`: la app anota actividad en `ops/active.json` (almacenamiento, sin consultar la base) cuando entra el primer ingreso/envío tras un rato inactivo o cambia el estado de un evento o formulario (`warmup.kick`). El Job horario lee ese archivo al arrancar: con actividad en las últimas 3 h (`OPS_ACTIVE_WINDOW_H`) corre completo cada hora; sin actividad solo corre completo a las 3, 4, 5, 11 y 19 h (`OPS_IDLE_HOURS`: respaldo diario, purga biométrica, paso semanal y respaldos cada 8 h) y en las demás horas sale sin abrir la base. Si no puede leer el archivo, corre completo. La alerta de «respaldo horario viejo» pasa a 9 h (`BACKUP_HOURLY_MAX_AGE_H` en `common.yaml`); con actividad, un fallo del respaldo avisa directo.

## Cierre de huecos de CRUD (migración `0094_crud_gaps`, 7-nov-2026)
Detalle y matriz por entidad en [`FASE_3_CRUD_MATRIZ.md`](FASE_3_CRUD_MATRIZ.md). Resumen: estados de evento y plantillas de formulario se archivan/restauran (admin+) y se borran solo super_admin si están archivados; `DELETE /users/{id}/logs` es solo super_admin con confirmación y por evento; «Eliminar los usuarios temporales» ahora archiva; recordatorios del calendario, deshacer acreditación, «Revisar» de la puerta, firmas, accesos de cliente, accesos de personal, códigos de descuento y marcas del formulario dejan `audit_actions`; pantallas «Ver archivados» para colores y plantillas de escarapela.

## Personas: se borran, no se archivan (decisión de Juan David, 7-nov-2026)
- **Qué cambia:** en el registro de un evento, quitar a una persona (p. ej. alguien creado por error) vuelve a BORRAR de verdad, como antes de la Fase 3. `DELETE /users/{id}` es otra vez de coordinador+ y no exige archivado. Se eliminaron `POST /users/{id}/archive|restore`, el parámetro `archived` de `GET /users` y los filtros de «archivadas» del directorio, el total y el ETag; en la pantalla desaparecieron «Archivar de este evento», el chip «Ver archivados» y su ventana. El botón vuelve a ser «Eliminar de este evento» (coordinador+), con la confirmación «se elimina a X del registro de este evento».
- **Por qué:** lo que se archiva es LA BASE DE DATOS del evento completa (L7, a los 90 días: `events.data_archived_at`), no personas sueltas. Archivar a una persona por error de captura dejaba datos personales que nadie pensaba usar, y obligaba a pasos extra (archivar, luego un super_admin borrar) para algo que el operador ya hacía bien.
- **Se conserva el rastro:** cada borrado deja una fila en `audit_actions` (acción `delete`, entidad `event_attendee`, id de la inscripción y «evento N»; nunca cédula ni nombre).
- **Intacto:** `purge-data`, la revocación, `app/privacy.py`, `audit_consent_logs` (inmutable) y `suppressed_people`.
- **Columnas sin uso:** `event_attendees.archived_at/archived_by_id` (migración `0091`, ya aplicada en staging) se dejan en el modelo y la migración, marcadas «sin uso: reservado»; ningún código las lee ni las escribe. No se crea migración para quitarlas.
## Super eventos: editar, archivar, restaurar y borrar (migración `0095_super_events_archive`, 7-nov-2026)
- `PATCH /api/super-events/{id}` (coordinador+, con `assert_same_tenant`): solo el nombre; el cliente no se puede cambiar (400); nombre repetido en el cliente, 400; uno archivado no se edita.
- `POST /api/super-events/{id}/archive` y `/restore` (coordinador+; decisión de Juan David: coordinadores y comerciales archivan, digitador y cliente no). `GET /api/super-events?tenant_id=..&include_archived=true` tambien coordinador+. Los archivados no salen en listas ni selectores.
- `DELETE /api/super-events/{id}`: solo super_admin, solo de uno archivado y sin eventos asociados (400 «tiene eventos asociados»). Todo deja `audit_actions` (entidad `super_event`; el cambio de nombre registra solo «campos: name»).
- **Qué pasa con los eventos y la asistencia hermana:** archivar NO toca los eventos (conservan `super_event_id`; no se archivan ni se borran). `sibling_attendance` no mira el estado del superevento, así que el aviso «ya asistió a un evento hermano» sigue funcionando. Sí se impide ASIGNAR un superevento archivado a un evento (crear o editar); conservar el que ya tiene no estorba, y el modal de edición lo muestra como «(archivado)» para que guardar no lo quite.
- UI: no había pantalla propia; se agregó la ventana «Administrar supereventos» (`static/js/gw-super-eventos.js`) con Editar, Archivar, Restaurar, «Ver archivados» y «Eliminar definitivamente» (super_admin, con `showConfirm`), abierta con el botón «Administrar» junto a «Nuevo» en «Editar evento» y en «Nuevo evento».
- Pruebas: `tests/test_super_events_crud.py`. Pendiente: correr `pytest` y `alembic upgrade head` en un entorno con SQLAlchemy/Postgres (aquí solo ruff, py_compile y node --check).
## Cambio de roles: coordinador y comercial archivan
Decisión de Juan David (7-nov-2026). Antes solo admin+ archivaba, restauraba y veía «Ver archivados»; ahora lo hace **coordinador+** (`require_role("coordinador")` cubre coordinador, comercial, admin y super_admin; digitador y cliente siguen sin poder y reciben 403).
- **Cambia:** formularios y plantillas de formulario (`forms.py`, constante `ARCHIVE`), zonas e ítems (`areas_inventory.py`, `ARCHIVE_ROLE`), colores (`events.py`), plantillas de escarapela (`badges.py`), documentos y gastos (`event_docs.py`, `ARCHIVE_ROLE`). `include_archived=true` ya no exige admin; un archivado lo descarga cualquiera que llegue al endpoint (coordinador+).
- **No cambia:** archivar clientes y cuentas de personal (admin+), eventos (admin+, solo finalizados), estados de evento (admin+), personas/directorio, desarchivar la base de un evento (super_admin). El **borrado definitivo** sigue siendo solo super_admin, de lo archivado y sin dependencias.
- **Acceso al evento:** cada endpoint conserva su puerta (`get_event_for_staff`, alcance por evento/cliente y las exclusiones de «comercial sin Parámetros/Escarapelas»). Por eso un comercial puro archiva y restaura (zonas, ítems, plantillas de escarapela) por la API, pero no llega a las pantallas de listado de Parámetros ni del diseñador de escarapelas, que le siguen vetadas.
- **Pantallas:** Archivar, Restaurar y «Ver archivados» visibles para coordinador+ (Formularios, Documentos, Legalizaciones, Parámetros, librería de colores, importar plantilla de escarapela); «Eliminar definitivamente» solo super_admin. Textos de ayuda: «un coordinador o superior puede restaurarlo».
- **Pruebas:** `test_catalogs_archive.py`, `test_docs_expenses_archive.py`, `test_people_forms_archive.py` y `test_crud_gaps.py` afirman 200 para coordinador y comercial y 403 para digitador y cliente.
## Pantallas de estados y plantillas (7-nov-2026)
Rama `f3c/pantallas-archivados`, sin migraciones ni cambios de servidor. Qué se construyó y dónde:
- **Estados de evento** viven en Configuración (pestaña nueva, solo admin+): `templates/configuracion.html`, `static/js/event-states-admin.js`, estilos mínimos en `static/css/p-configuracion.css` (punto de color por la variable `--gw-estado-color`, solo si el color es `#RRGGBB`). Usa `GET/POST/PATCH /api/event-states`, `archive`, `restore` y `DELETE`. Se carga al abrir la pestaña (no antes). Renombrar usa `showPrompt`; archivar y eliminar, `showConfirm`; los rechazos del servidor salen con `showToast`.
- **Plantillas de formulario:** gestión dentro del bloque «Empezar desde una plantilla» de `templates/kiosk_formularios.html` + `static/js/kiosk-formularios.js` (coordinador+ ve la lista con Archivar/Restaurar y «Ver archivadas»; super_admin además «Eliminar definitivamente»). El selector de creación solo ofrece las no archivadas.
- `static/js/archive-rules.js`: quién ve cada botón (estados admin+, plantillas coordinador+, borrado super_admin). Solo oculta botones; el servidor decide.
- Pruebas: `tests/test_fase3_pantallas_archivados.py` (fuente: sin diálogos nativos ni `onclick`, `url_for('static')`, sin colores/tamaños sueltos; pestaña solo para admin) y `tests/js/archive_rules_check.js`.
- Dependencia: hoy el servidor exige admin+ para archivar/restaurar/ver archivadas de plantillas; mientras el otro agente lo pasa a coordinador+, un coordinador vería el aviso de «Solo un administrador…» al marcar «Ver archivadas».
