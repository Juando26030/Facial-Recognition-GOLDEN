# Fase 0A · Estado de los 41 puntos pendientes contra `main`

Fecha de la revisión: 2026-10-29 (noche). `main` revisado: `bc4a19d` (`origin/main`). **Ojo:** el plan y el encargo hablan de `b36bf92`; `main` ya lo contiene y tiene 6 commits más, todos de impresión
compartida (A–E de `fix/impresion-compartida-29oct`, migración `0076`). Verificado con `git ls-remote`: `main` = `bc4a19d`, `corte/main` = `3a6207b`.

## Cómo leer este reporte (y qué NO está verificado)

1. **La lista original de 41 puntos de Juan David no vino adjunta** (solo el plan maestro). El único mapa disponible es el **Anexo A** del plan (rangos por tema) más `docs/16_BACKLOG_PRODUCTO.md` y
   `docs/18_EVENTO_CAMPOS_ESTADOS.md`. Los rangos 1–12, 13–16, 17–21, 27–30 y 33–38 se descompusieron en puntos individuales **por inferencia**; esa numeración interna es mía y **hay que confirmarla
   con la lista de Juan David** (columna «Texto del punto»: lo que asumí que dice). El estado de cada fila SÍ está verificado en código; lo que no se pudo verificar se marca «no verificado».
2. «Verificado» = leí el código en `origin/main` (archivo y línea o prueba). Nada de lo que vive en la nube (Neon, Cloud Run, Scheduler, buckets, Secret Manager) se pudo comprobar: no hay acceso, por diseño.
3. «Hecho y en main» no significa «probado en hardware»: lo físico (Brother, iPad, lector) se anota aparte.
4. Estados: **HECHO Y EN MAIN** · **HECHO PERO SIN INTEGRAR** (rama y commit) · **PARCIAL** (qué falta) · **POR HACER**.

## Tabla

| # | Texto del punto (inferido del Anexo A / docs 16 y 18) | Fase del plan | Estado | Evidencia (archivo, commit o prueba) y qué falta |
|---|---|---|---|---|
| 1 | Ficha del evento configurable por el admin (campos, tipos, secciones, obligatorios, visibilidad) | 5 | **POR HACER** | `Event` tiene solo columnas fijas (`app/models.py:209`); `EventFieldConfig` (`models.py:377`) es el formulario de la PERSONA, no la ficha del evento. Diseño en `docs/18 §3`, sin código. |
| 2 | Tipo de evento ampliable y jornada Full / Medio día con hora de inicio y fin | 5 | **PARCIAL** | Existen `event_time_start/end` y `setup_time_*` en `Event`; no hay tipo de evento ampliable ni jornada Full/Medio día ni el cambio «sin tipo de impresión». |
| 3 | Estados de evento creados por el admin, con reglas (acceso del cliente, estadísticas, temporales, ruleta, registro, inventario) | 5 | **PARCIAL** | `EventState` (`models.py:300`), `app/routers/event_states.py`, `app/event_rules.py`, `tests/test_event_states.py`. **Solo API**: ninguna plantilla ni JS la usa (grep de `event-states` en `templates/` y `static/js/` = 0); no hay pantalla en Configuración ni selector en el evento. De las 9 reglas, el propio módulo dice que solo 4 se hacen cumplir hoy (`client_access`, `temp_digitadores_enter`, `registration`, `client_stats_download`); `roulette`, `touch_registration`, `areas`, `inventory_control`, `certificates` están declaradas pero sin cablear. |
| 4 | Historial de cambios por campo del evento | 5 | **POR HACER** | No hay tabla ni código de historial de campos (grep `field_history`, `EventChange` = 0). |
| 5 | Calendario con más información al crear el evento | 5 (visual en 2) | **PARCIAL** | `app/routers/calendar.py`, `templates/calendario.html` existen; la información nueva depende de la ficha (punto 1). |
| 6 | Calendario con filtros por cliente, ciudad, comercial y estado | 2 | **PARCIAL** | `calendario.html` filtra por comercial (`commercialFilter`) y tiene `.cal-filters`; no verifiqué cliente/ciudad/estado (no verificado). |
| 7 | Correo al editar un evento solo por campos clave | 5 | **POR HACER** | Sin código: el texto «tuvo los siguientes cambios» no existe en `app/`. Depende de la lista de campos clave (la entrega Juan David). |
| 8 | Destinatarios del correo: almacén (campo nuevo) y rol «contabilidad» | 5 | **POR HACER** | Ni el campo de encargado de almacén ni el rol existen (grep `contabilidad` = 0; `STAFF_ROLES` en `app/auth.py` sin ese rol). |
| 9 | Inventario por cantidad con catálogo categorizado | 5 | **PARCIAL** | `InventoryItem`/`InventoryDelivery` (`models.py:753,764`), `app/routers/areas_inventory.py`, `templates/kiosk_inventario.html`, flag `inventory_enabled`: es control de entrega por evento, no el catálogo por cantidad y ciudad de `docs/16 N5`. |
| 10 | Regla de cuadre del inventario (suma exacta; todo categorizado para pasar a «en proceso») | 5 | **POR HACER** | No hay regla de cuadre en `event_rules.py` ni en `events.py`. |
| 11 | Reserva con 1 día de anticipación en la misma ciudad y alerta de 1 semana en otra | 5 | **POR HACER** | Sin código. |
| 12 | «Recursos» por día de la ficha ↔ reservas de inventario | 5 | **POR HACER** | Sin código (`docs/18 §6` solo diseño). |
| 13 | Impresión directa por USB en la Brother QL-800 desde el celular/computador | hecho, verificar | **HECHO Y EN MAIN** | `static/js/ql-usb.js`, `templates/impresion_usb.html`, integrado en `static/js/shared-print.js` (`printUsb`, `usb.ok`); `tests/js/ql_usb_check.js`, `tests/test_usb_print_page.py`. Hardware: la memoria del proyecto registra la QL-800 confirmada (espejo y parámetros) pero **sigue pendiente el giro horizontal y los textos de `739da4e`** (no verificado en esta revisión). |
| 14 | Impresión compartida entre equipos (cola + anfitrión) | hecho, verificar | **HECHO Y EN MAIN** | `app/routers/shared_print.py` (`print-jobs`, `print-devices/heartbeat`), `static/js/shared-print.js`, migraciones `0069`, `0071`, `0076`; pruebas `tests/js/shared_print_*_check.js`. Los 6 commits posteriores a `b36bf92` (problemas A, B, D, E y C) ya están en `main`. |
| 15 | «Estación de impresión»: el equipo con la impresora atiende a los demás (Imprimir pendientes, Cola) | hecho, verificar | **HECHO Y EN MAIN** | `print-jobs-next`, `_claim_batch`, `print_stations.py`, `tests/js/shared_print_station_check.js`. |
| 16 | Impresión desde iPad/iPhone a través de un Android (o computador) con la impresora | hecho, verificar | **HECHO Y EN MAIN** (no probado en iPad físico) | El iPad usa la ruta `shared` del punto 14. No hay prueba con un iPad real en el repo: **no verificado**. |
| 17 | Lectura de cédula nueva y vieja al CREAR digitadores/clientes temporales | 4 | **PARCIAL** | La lectura (MRZ, cédula vieja por código de barras) existe para ASISTENTES: `app/routers/cedula.py`, `directory.js`, `kiosk_registro.html`. `templates/staff.html` / `kiosk_usuarios.html` no la usan (grep `mrz` solo en `kiosk_registro.html` y `cedula.py`). Falta llevarla al alta de personal. |
| 18 | Autorregistro por enlace — cliente (B3a) | 4 | **POR HACER** | Sin enlace de alta de personal (`staff.py` sin código de enlaces; los `FormInvite`/aceptar son de formularios y consentimientos). |
| 19 | Autorregistro por enlace — digitador (B3b) | 4 | **POR HACER** | Igual que 18; depende del compromiso (20). |
| 20 | Compromiso digital del digitador con firma y vigencia de 30 días (B4) | 4 | **POR HACER** | grep `compromiso` en `app/`, `templates/`, `static/js/` = 0. |
| 21 | Base de digitadores y clientes descargable solo por admin (B5) | 4 | **POR HACER** | Sin código; depende de 18–20. |
| 22 | Informe del cliente con encuesta y alerta por correo a la comercial (N3) | 7 | **PARCIAL** | El informe final existe (`app/routers/event_report.py`, `Event.report_pdf_path`); no hay encuesta ni bandera de liberación (grep `encuesta`/`survey` = 0). |
| 23 | Registro touch (N1c) | 7 | **HECHO Y EN MAIN** (primera versión; confirmar alcance) | Modo «📱 Registro touch» en `shared-print.js` (tres buscadores, «solo lector», tarjetas), `tests/test_directorio_touch.py`; commit `97c8509`. El plan lo lista para la Fase 7: hay que confirmar con Juan David si esta versión cumple o falta la versión 16:9/módulos touch de `docs/18 §7` (no verificado). |
| 24 | Servidor local sin internet con sincronización (B6) | 6 | **POR HACER** | Solo diseño en `docs/17_SERVIDOR_LOCAL.md`. |
| 25 | Modo sin conexión (contingencia) ENCENDIDO en producción | hecho, verificar | **HECHO Y EN MAIN** (valor de la nube no verificado) | `5ff752b` («Producción: modo sin conexión ENCENDIDO — `CONTINGENCY_ENABLED=1`»), `deploy/gcp/config.sh`. Que producción lo tenga prendido hoy: **no verificado** (nube). |
| 26 | Bandeja de salida: registro/edición completos sin red (B8 R2–R5) | 6 | **PARCIAL** | R1 está en `main`: `static/js/outbox.js`, `outbox-ui.js`, `POST /api/events/{id}/outbox/sync`, `tests/test_outbox_sync.py`. Faltan R2 (foto y consentimiento), R3 (edición), R4 (PIN, exportación de emergencia) y R5 (dos dispositivos). |
| 27 | Recarga sin red local-first | hecho?, verificar | **HECHO PERO SIN INTEGRAR** | Rama `fix/offline-recarga`, commit `2f256d2` («Recarga sin red LOCAL-FIRST…», +216 líneas, incluye `tests/js/offline_reload_check.js`). **No está en `main`**: `git cherry` lo da como no aplicado (`+`), `grep fastStart|LIST_HEAD_TIMEOUT_MS` en `contingency.js`/`directory.js` de `main` = 0 y `tests/js/offline_reload_check.js` no existe en `main`. Es decir, producción (con la contingencia encendida) recarga SIN red con el comportamiento lento descrito en `docs/15 D2.5h` (~34 s a ~1 min con red «colgada»). **Contradice la sospecha del encargo.** Los otros dos commits de la rama (`e5e5579` prueba intermitente, `7169907` diagnóstico de escala) tampoco están. |
| 28 | Lista local (el directorio funciona con la copia local sin red) | hecho?, verificar | **HECHO Y EN MAIN** | `directory.js` (`loadFromLocalCopy`, modo `localMode`, filas `__local`), `contingency.js`, `tests/test_local_roster.py`, `tests/js/contingency_list_check.js`. La mejora de arranque rápido es la del punto 27. |
| 29 | Filas por página del directorio configurable | hecho?, verificar | **HECHO Y EN MAIN** | `Event.directory_page_size`, `app/routers/parametros.py:207`, selector en `kiosk_parametros.html:62`, `tests/test_directory_page_size.py`, `tests/js/directory_paging_check.js`. |
| 30 | «✅ Acreditar» en todas las filas con «Deshacer» (7a) | hecho?, verificar | **HECHO Y EN MAIN** | `directory.js` (`acreditarFila`, `offerUndo`, `undoAccredit`), `POST /api/events/{id}/accreditations/undo` con `ACCREDIT_UNDO_WINDOW = 15 s` (`api.py:822`), `tests/test_accreditation_undo.py`, `tests/js/row_accredit_check.js`. |
| 31 | Logo por defecto cambiable desde Configuración (7b) | 7 | **POR HACER** | No existe la ruta `/branding/logo` ni la sección en `configuracion.html` (el logo sigue fijo en `static/img/logo-golden.png`). |
| 32 | URL limpia para las inscripciones públicas (N6) | 7 | **POR HACER** | grep `public_slug` = 0; el formulario público sigue en `/f/{event_id}/{slug}`. |
| 33 | Copias de la base a las 3 a. m. activas | 9 | **PARCIAL** | Código en `main`: `app/ops_runner.py` (horario, diario a las 3, purga, `check-backups`), `deploy/gcp/scheduler.sh`. Que estén ACTIVAS en producción (tarea del Scheduler reanudada): **no verificado** (nube). |
| 34 | Alerta de borrado masivo en el bucket | 9 | **POR HACER** | `docs/15 D2.5j (c)(i)`: «Faltan… alerta de borrado masivo». |
| 35 | Copia semanal fuera del proyecto | 9 | **POR HACER** | Sin código ni script (grep `semanal`/`offsite` en `app/ops*.py` y `deploy/gcp/*.sh` = 0). |
| 36 | Copia fuera de línea de la llave de cifrado (`FACE_ENCRYPTION_KEY`) | 9 | **POR HACER** (acción de Juan David) | `docs/15 D2.5j (d)`: «debe tener copia fuera de línea… hoy solo el bootstrap la imprime/pide a ciegas». No verificable desde el repo. |
| 37 | `--version-destroy-ttl=7d` en la llave (Secret Manager) | 9 | **POR HACER** (acción de Juan David, nube) | No se puede comprobar desde el repo. |
| 38 | Restore-test de un respaldo real (y historial de Neon a 1 día) | 9 | **POR HACER** | `docs/15 D2.5j (b)`: solo se restauró una vez un respaldo de 17 KB contra el emulador; la prueba con un respaldo real está propuesta, no hecha. La ventana de 1 día de Neon es un paso manual de Juan David (no verificado). |
| 39 | Política de privacidad v1.1 con el apartado 5-bis (registro sin red) | 9 | **PARCIAL** | La v1.1 está ratificada y activa (`docs/legal/POLITICA_v1.1.md`, `RATIFICACION_v1.1.md`, `POLICY_VERSION=1.1`). El 5-bis de la bandeja de salida es un BORRADOR sin integrar: rama `fix/legal-1-1-borrador`, commit `175e7b7`; el trabajo posterior es `docs/legal/BORRADOR_POLITICA_v1.2.md` (no activo). |
| 40 | Marcador de proveedores (confirmar Google, Neon, Microsoft) | 9 | **POR HACER** | Ni `legal_privacidad_v11.html` nombra a Neon/Microsoft/Google (grep = 0) ni encontré un marcador en el repo: **no verificado**; si existe vive fuera de `main`. |
| 41 | Runbook y guía de producción | hecho | **HECHO Y EN MAIN** | `docs/19_GUIA_PRODUCCION.md`, `docs/runbook_evento.md`, `docs/13_RUNBOOK_PRODUCCION.md`, `docs/legal/RUNBOOK_CLOUD_SHELL.md`. |

## Conteos (sobre las 41 filas de la tabla; ver advertencia 1 sobre la numeración inferida)

| Estado | Filas | Puntos |
|---|---|---|
| HECHO Y EN MAIN | 10 | 13, 14, 15, 16, 23, 25, 28, 29, 30, 41 |
| HECHO PERO SIN INTEGRAR | 1 | 27 |
| PARCIAL | 10 | 2, 3, 5, 6, 9, 17, 22, 26, 33, 39 |
| POR HACER | 20 | 1, 4, 7, 8, 10, 11, 12, 18, 19, 20, 21, 24, 31, 32, 34, 35, 36, 37, 38, 40 |
| **Total** | **41** | |

## Hallazgos que cambian el plan

1. **El punto 27 (recarga local-first) NO está en `main`.** Es el único «hecho pero sin integrar» del bloque que se sospechaba integrado. Está en `fix/offline-recarga` desde el 5-oct y nunca pasó a `main`.
   Con la contingencia encendida en producción, el arranque sin red sigue siendo el lento. Candidato natural para la Fase 1A o un parche aparte (requiere prueba en dispositivos).
2. **Estados con reglas (punto 3) tienen backend sin pantalla** y 5 de 9 reglas sin cablear: la Fase 5 no parte de cero, pero tampoco está cerrada.
3. **Lo que ya sobra en `main` sin estar en la lista:** exportar/importar eventos completo (`app/event_transfer.py`, `event_transfer_jobs.py`, `docs/18_EXPORTAR_EVENTOS.md`, migraciones `0074`–`0075`),
   puestos de impresión y sesiones por rol (`0072`), origen de carga (`0073`), registro touch con tres buscadores.
4. **Ramas con trabajo no integrado** (para la limpieza de la Fase 0B): `fix/offline-recarga` (3 commits), `fix/legal-1-1-borrador` (1), `ux/fase1-visual` (8; sistema visual de la Fase 2),
   `producto/impresion-ajustes` (9) y `producto/impresion-compartida` (6) — estas dos últimas probablemente reemplazadas por el trabajo ya integrado, no verificado commit por commit —,
   y `producto/fecha-nacimiento-sin-rostro` (2, con sus propios revert).

## Dudas para Juan David

- La lista exacta de los 41 puntos (para fijar la numeración de 1–12, 13–16, 17–21 y 33–38).
- ¿El «Registro touch» actual (punto 23) cumple lo que pidió, o falta la versión de `docs/18 §7`?
- ¿Existe en algún lugar el «marcador de proveedores» del punto 40? No lo encontré en `main`.
