# 09 · Purga local de eventos devueltos y escarapela de dependientes (Fase 6, puntos 4 y 6)

Fecha: 23-nov-2026 · Rama `saas/revision-integral` · Sin commits, sin nube, sin tocar `main`.

## TAREA 4 · Purga local de eventos devueltos

### Qué confirmé (leyendo el código)
- «Pasar a internet» en el servidor local es `node_sync.release_event` (lo llama `POST /api/node-sync/events/{id}/release`). Sube todo, llama a la nube (`POST /api/node/events/{id}/release`, que es `routers/nodes.py::node_release` → `event_lease.leave/release`) y, al final, solo hacía `event.cloud_event_id = None`.
- Es decir: **no se borraba nada**. Personas, ingresos, fotos (`known_people/…`), vectores (`face_encoding`) y marca de consentimiento seguían en el portátil. Lo decía `docs/17` § «Lo que NO se borra solo» («hasta que exista la purga automática…»).
- La purga de retención existente (`privacy.purge_expired`, paso `purge` del Job de ops) corre en la nube; un servidor local no ejecuta ese Job, así que tampoco cubría el portátil. `privacy.purge_event` existe pero es manual (administrador) y no se llama al devolver.
- El lado nube (`event_lease.release`) no toca datos: correcto, la nube es la dueña del evento.

### Qué implementé (acotado)
- `app/privacy.py`: `purge_returned_event(db, event)` + constante `RETURNED_PURGE_PENDING`. Borra foto (por `app/storage.py` vía `enroll.delete_photos`), vector y marca de consentimiento de las personas del evento con `_erase` (primero la foto; si falla, el vector queda y se reintenta). Respeta a quien sigue en OTRO evento todavía bajado de la nube (`cloud_event_id` no nulo). No toca `audit_consent_logs` (constancia inmutable). Fecha en UTC (`biometrics_purged_at`, solo si no hubo errores). Solo devuelve conteos; el log de error registra únicamente el tipo de excepción, sin `exc_info` (la ruta de la foto lleva la cédula).
- `app/node_sync.py`: `release_event` ahora llama a `purge_returned` DESPUÉS de que la nube confirmó y de limpiar `cloud_event_id`. Si la purga falla, no deshace la devolución: deja `sync_error = «Purga local pendiente»`. `retry_pending_purges` (llamada al inicio de cada ciclo de `_loop`) reintenta esos eventos. La respuesta de «Pasar a internet» trae `purge` con los conteos.
- `docs/17_SERVIDOR_LOCAL.md`: nota de la purga y ajuste de «Lo que sigue sin borrarse solo».
- `tests/test_purga_local_devuelto_texto.py`: 3 pruebas de texto (orden nube → `cloud_event_id=None` → purga; marca y reintento; reglas de `purge_returned_event`). Pasan con `python3 -m pytest -q --noconftest`.

### Plan de lo que falta (no implementado)
1. **Purgar también datos no biométricos del evento devuelto** (personas, ingresos, impresiones, formularios, dependientes, archivos del evento). Hoy el borrado definitivo vive dentro del endpoint `routers/events.py::delete_event` (no reutilizable). Pasos: extraer su cuerpo a `app/event_delete.py::delete_event_rows(db, event_id)` (el endpoint la llama), y desde `purge_returned` invocarla cuando `LOCAL_PURGE_RETURNED=full` (por defecto solo rostros, hasta que Juan David decida). Ojo: `delete_event` deja `AccessLog` huérfano (`event_id=None`); en local habría que borrarlos. Estimado: 4–6 h con pruebas con base de datos.
2. **Copias diarias locales** (`local_backup`) del evento ya devuelto siguen conteniendo los datos: definir retención corta (p. ej. 7 días) para copias de eventos devueltos. 2 h.
3. **Supresión de una persona hecha en la nube (Ley 1581)** no llega a un portátil sin internet ni a eventos aún no devueltos: ya está en `docs/17`; requiere cola de supresiones que el nodo baje en su ciclo. 4 h.
4. **Prueba con base de datos** de `purge_returned_event` (persona solo en el evento → borrada; persona en otro evento sincronizado → conservada; fallo de storage → `sync_error` pendiente y reintento). 1 h en CI.

### Qué no pude comprobar
- Nada con base de datos ni FastAPI (no hay aquí): solo `py_compile` y las pruebas de texto. La consulta de «otro evento sincronizado» y el commit nunca se ejecutaron.
- Que un servidor local real (Windows, `LOCAL_SERVER=1`) borre las fotos de su storage local al devolver.
- Que `_erase` borre también las fotos pendientes (`photo_keys`) en ese storage: se confía en `enroll.delete_photos`.

---

## TAREA 6 · Impresión de escarapelas de dependientes (solo plan; no se tocó código)

### Qué confirmé
- `docs/25` §Pendiente: no hay ruta de escarapela de dependientes. En el código, `events.dependents_badge` (modelo `Event`, migración 0161) existe pero **ninguna línea lo usa** (solo la definición y la migración). No hay casilla en pantalla.
- Datos de un dependiente (`EventDependent`, tabla `event_dependents`): `uid` (estable, no cambia al copiar el evento), `holder_id` (cédula del titular), `person_key`, `name`, `doc_id`, `data_json` (columnas tal cual, incluidas producto/cantidad), `row_num`. Varias filas con el mismo `person_key` son el mismo dependiente con varios productos. **No es `User` ni `EventAttendee`**: no tiene rostro, ni categorías, ni apellidos separados, ni foto, ni código.
- La escarapela hoy se arma así: `templates/badge_print.html` pide `GET /api/users/{user_id}/badge-print-data?event_id=…` (`routers/badges.py::get_badge_print_data`), que exige persona del evento y registrada (`_require_printable`), y `BadgeRender.renderBadge` (`static/js/badge-render.js`) pinta la plantilla con `resolveVariable(variable, data)`. La plantilla (`BadgeTemplate`, por evento y categoría) y la composición/impresión (`label-compose.js`, `ql-usb.js`) no dependen del tipo de persona; todo lo que pasa por ahí queda igual.
- `print_logs.user_id` es un texto sin llave foránea (se podría guardar `d<uid>`, pero `print-count`, `require_person_of_event`, reimpresión, cola e informes asumen personas reales).

### Plan exacto
1. **Interruptor** (0,5 h): casilla «Imprimir escarapela a los dependientes» en Parámetros, visible solo si `dependents.has_dependents(db, event.id)`, guarda `events.dependents_badge` (la columna ya existe; sin migración).
2. **Datos** (2 h): `GET /api/events/{event_id}/dependents/{uid}/badge-print-data` en `routers/badges.py` (mismo permiso `require_role_excluding("digitador", ("comercial",))`, `get_event_for_staff`, `require_data_open`, y 404 si `dependents_badge` está apagado o el `uid` no es del evento). Devuelve el MISMO esquema que la de personas para no cambiar el renderizador: `id` = `d<uid>`, `first_name` = `name`, `last_name` = `""`, `role`/`entity` = los del titular (o columnas del `data_json` si Parámetros las mapea), `has_photo` = false (nunca foto: dependientes sin biometría, `docs/25` §3), `extra_fields` = `data_json`, `categories` = las del titular, `template_category` = la del titular (`template_category_for_user(event, db, holder_id)`), y SIN `code` ni `card_url` (el código y la tarjeta son de la persona). Exigir que el titular esté registrado (`dependents.is_registered`).
3. **Plantilla** (1 h): reutilizar la plantilla del titular. Decisión a tomar con Juan David: ¿misma plantilla del titular, o una por categoría «Dependiente»? Propuesta: la del titular, con un texto fijo opcional «Acompañante» si el diseñador lo pone (sin tocar el diseñador). `badge-render.js` no cambia: lo que no existe en los datos sale vacío; la foto (`image_variable` source photo) ya se omite sin `has_photo`.
4. **Ventana de impresión** (2 h): `templates/badge_print.html` ya recibe `USER_ID` y arma `/api/users/{id}/badge-print-data`; el cambio mínimo es que, si el id empieza por `d` + uid de dependiente (consulta `?dep=1`), llame a la ruta nueva. No tocar `PAGE_W`, `MAX_IMG_H`, `PAGE_H`, `@page`, `PAGE_LEFT_MM`, `#endMark` ni `label-compose.js`/`ql-usb.js` (`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`; `tests/test_impresion_parametros_fijos.py` debe seguir verde).
5. **Registro de la impresión** (2 h): nueva ruta `POST /api/events/{id}/dependents/{uid}/print-log` que escriba `PrintLog(user_id="d<uid>")` y nueva `print-count` equivalente; excluir `d…` de las consultas que asumen `User` (estadísticas, reimpresión `reprint.py`, cola de impresiones, sincronización local `node_sync._prints_query`, paquete de evento `event_transfer`). Aquí está el riesgo mayor: revisar cada consumidor de `print_logs`.
6. **Pantalla** (3 h): en «Editar persona»/tarjeta del titular, botón «Escarapelas de dependientes» (lista por `dependents.people_of`) con «Imprimir» por cada uno y «Imprimir todos» (reutiliza `printBatchUrl`, `?users=`). En Registro, opción de imprimir al titular y a sus dependientes juntos solo con el interruptor encendido.
7. **Servidor local y paquete** (1 h): `dependents_badge` ya viaja en `events` (revisar que `event_transfer` lo incluya) y el `uid` es estable; el nodo sube las impresiones de dependientes como `print_logs` normales (verificar que la nube las acepte con `user_id` `d…` sin exigir persona).
8. **Pruebas** (3 h): con base de datos (ruta apagada → 404; titular sin registrar → 403; dependiente de otro evento → 404; sin `code`/foto/tarjeta en la respuesta; `print-log` guarda `d<uid>`; el directorio/estadísticas/ruleta no lo cuentan) y de texto (`tests/test_impresion_parametros_fijos.py` intacto).

Total estimado: **15 h** de desarrollo y pruebas automáticas, más la prueba física.

### Qué habría que probar físicamente en la Brother QL-800 (Windows 11 + Chrome, 28-oct-2026 como línea base)
- Que la escarapela de un dependiente (sin foto, sin apellido, sin código) salga igual de centrada y completa en **vertical 62×100** y **horizontal 100×62**, con y sin recorte, sin textos de Chrome y con la marca de fin (la longitud de la tira no se acorta).
- Que una plantilla con elemento de foto no deje un hueco feo ni rompa la composición al faltar la imagen.
- Nombres largos de dependientes (ajuste de texto `fitText`) y nombre ausente (solo documento).
- Impresión por lote («Imprimir todos» del titular con 3–5 dependientes): una etiqueta por dependiente, sin cortes de más.
- Camino USB directo (`ql-usb.js`, WebUSB) y ventana normal de Chrome: ambas deben dar la MISMA etiqueta; recordar «Access denied» del controlador de Brother en Windows.
- Reimpresión: que imprimir dos veces al mismo dependiente avise (si se implementa `print-count`).
- Chrome siempre normal, con su cuadro de impresión: nunca `--kiosk-printing`.
- Como el código de impresión compartido no cambia, si SOLO se agrega la ruta de datos y el botón la repetición física puede limitarse a 2 etiquetas (vertical y horizontal); si se toca `badge_print.html` más allá de la URL de datos, repetir la prueba completa del documento de parámetros.

### Qué no pude comprobar
- Nada se ejecutó (solo lectura): el esquema exacto que consume cada plantilla real (`resolveVariable` para variables que un dependiente no tiene) y qué consumidores de `print_logs` romperían con un `user_id` `d<uid>`; hay que auditarlos antes del paso 5.
- Decisión de producto pendiente de Juan David: plantilla del titular vs. plantilla propia, y si el dependiente cuenta como «impresión» para informes.

## Límite conocido de la purga implementada (revisión del 23-nov-2026)
`purge_returned_event` conserva el rostro de quien sigue en OTRO evento que aún esté enlazado a la nube (`cloud_event_id` no nulo). Un evento creado solo en el portátil (sin enlace) y un evento ya devuelto se ven igual (`cloud_event_id` nulo), así que una persona que esté en un evento devuelto y a la vez en un evento solo-local activo perdería su rostro en el portátil. Es raro (los eventos del portátil suelen bajarse de la nube) y se corrige cuando se decida cómo distinguir «devuelto» de «solo-local» (por ejemplo, una marca `returned_at`). No se aplicó hoy para no inventar columnas sin migración. Se confirma en la prueba D (servidor local) de staging, con un evento devuelto y una persona repetida.
