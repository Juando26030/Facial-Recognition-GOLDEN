# Fase 0A · Estado de los 41 puntos pendientes contra `main`

Revisión del 30-oct-2026 sobre `origin/main` = `bc4a19d` (producción corre lo mismo, según Juan David en `/sistema`). `main` ya contiene `b36bf92` y 6 commits más, todos de impresión compartida (migración `0076`).
Esta versión **reemplaza** a las del 29-oct (numeración inferida) y del 30-oct (puntos 31–41 aún inferidos): **ya están los 41 textos reales** y no queda ninguna fila «inferida».

## Cómo leer este reporte (y qué NO está verificado)

1. **Numeración y textos reales de los 41 puntos**, según la lista de Juan David (antes del piloto): los puntos 31–41 los pegó en un segundo mensaje porque el primero llegó cortado en el 30.
2. «Verificado» = leí el código en `origin/main` (archivo y línea o prueba). La columna «Según Juan David» es lo que decía su lista (antes del piloto); «Hoy en `main`» es lo que encontré. Lo que vive en la nube (Neon, Cloud Run, Scheduler, buckets, Secret Manager) **no se pudo verificar**.
3. «Hecho y en main» no significa «probado en hardware».
4. Estados: **HECHO Y EN MAIN** · **HECHO PERO SIN INTEGRAR** (rama y commit) · **PARCIAL** (qué falta) · **POR HACER**.

## Tabla

### 1. Ficha del evento y estados

| # | Punto (lista de Juan David) | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 1 | Ficha del evento configurable por el admin (diseñador como el de formularios web, sin la parte pública) | Solo diseño (docs/18) | **POR HACER** | `Event` solo tiene columnas fijas (`app/models.py:209`); `EventFieldConfig` (`:377`) es el formulario de la PERSONA, no la ficha. Diseño en `docs/18 §3`. |
| 2 | Tipo de evento como lista ampliable por el admin | Solo diseño | **POR HACER** | No existe campo ni lista de tipo de evento (grep `event_type`/«tipo de evento» en `app`, `templates`, `static/js`, `alembic` = 0). |
| 3 | Jornada Full o Medio día, más hora de inicio y fin | Solo diseño | **PARCIAL** | Las horas existen (`event_time_start/end`, `setup_time_*` en `Event`); la jornada Full / Medio día no (grep `jornada` = 0). |
| 4 | Quitar «tipo de impresión» | Solo diseño | **POR HACER** (sin trabajo de código hoy) | «Tipo Impresión» es un campo de la ficha del software anterior (`docs/18 §1`); **no existe en el código actual** (grep = 0). Solo hay que no incluirlo cuando se construya la ficha (punto 1). |
| 5 | «Campos a capturar en registro» como lista o detalle libre; Habeas Data se ignora | Solo diseño | **POR HACER** | No hay ese campo a nivel de evento; lo más parecido son los campos de la persona de Parámetros (`FIELD_CONFIGS`), que es otra cosa. |
| 6 | Estados creados por el admin con reglas (cliente, estadísticas, temporales, ruleta, registro, inventario…) | Backend hecho en `producto/estados-evento`; faltan pantalla, selector, reglas restantes y exigencia de inventario categorizado | **PARCIAL** | **El backend ya está en `main`** (`45fd829` «Integra producto/estados-evento»): `EventState` (`models.py:300`), `app/routers/event_states.py`, `app/event_rules.py`, `Event.state_id` aceptado al crear y editar (`app/routers/events.py:103,375`), `tests/test_event_states.py`. **Falta:** pantalla en Configuración y selector en el evento (ninguna plantilla ni JS usa `event-states`/`state_id`; `eventos.html` solo filtra por los estados viejos); de las 9 reglas, el módulo mismo dice que solo 4 se hacen cumplir (`client_access`, `temp_digitadores_enter`, `registration`, `client_stats_download`) y `roulette`, `touch_registration`, `areas`, `inventory_control`, `certificates` están declaradas sin cablear; la exigencia de inventario categorizado para pasar a «en proceso» no existe. |
| 7 | Historial de cambios por campo | No hecho | **POR HACER** | Sin tabla ni código (grep `field_history`/`EventChange` = 0). |
| 8 | Calendario con más información al crear el evento, reflejada en todos los lugares | No hecho; espera datos | **POR HACER** | `app/routers/calendar.py` y `templates/calendario.html` existen (calendario básico, filtro por comercial); nada de lo pedido. Depende de los datos de Juan David y de la ficha (1). *(El 29-oct lo había puesto «parcial»; con el texto real queda por hacer.)* |

### 2. Correos e inventario

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 9 | Correo al editar un evento solo por campos clave; destinatarios: comercial, coordinador, encargado de almacén y rol «contabilidad» | No hecho; falta lista de campos clave | **POR HACER** | El texto «tuvo los siguientes cambios» no existe en `app/`; no hay campo de almacén ni rol «contabilidad» (grep = 0; `STAFF_ROLES` en `app/auth.py` no lo tiene). |
| 10 | Inventario inteligente: por cantidad (serie opcional), bodega principal en Bogotá, reserva con 1 día de anticipación en la misma ciudad, alerta de 1 semana en otra | Solo diseño | **POR HACER** | Existe otro módulo: control de entregas por evento (`InventoryItem`, `InventoryDelivery` en `models.py:753,764`, `app/routers/areas_inventory.py`, `templates/kiosk_inventario.html`, flag `inventory_enabled`). No es el inventario por cantidad ni las reservas por ciudad. *(El 29-oct lo había puesto «parcial».)* |
| 11 | Catálogo del inventario (computadores, impresoras QL/negras, pañoletas y corbatas por color, lectores bidimensionales, fundas 12/16 mm, cintas, cordones) con categorías por botones | Solo diseño | **POR HACER** | Sin catálogo (grep `catalog`/`pañoleta`/`corbata`/`fundas` en `app`, `templates`, `static/js`, `alembic`: sin resultados relevantes). |
| 12 | Regla de cuadre (suma de categorías = total exacto; «creado» puede quedar sin categorizar; «en proceso» todo categorizado) | Solo diseño | **POR HACER** | No hay regla de cuadre en `event_rules.py` ni en `events.py`. |

### 3. Impresión

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 13 | Imprimir en la QL-800 desde el celular por cable (WebUSB, Android + Chrome, rollo 62 mm), detectada sola al enchufar | Prototipo en `/impresion-usb`; no integrado al directorio ni al registro | **HECHO Y EN MAIN** | `static/js/ql-usb.js` (`getDevices()` reconoce la impresora sin preguntar de nuevo, `:301`), `templates/impresion_usb.html`; **integrado al directorio y al registro**: `shared-print.js` (`printUsb`, `usb.ok`) y detección al enchufar (`navigator.usb.addEventListener('connect', …)`, `shared-print.js:215`); `tests/js/ql_usb_check.js`, `tests/test_usb_print_page.py`. Hardware: la memoria del proyecto registra la QL-800 confirmada, **pendiente el giro horizontal y los textos de `739da4e`** (no verificado hoy). |
| 14 | Impresora compartida entre equipos | Solo diseño | **HECHO Y EN MAIN** | `app/routers/shared_print.py` (`print-jobs`, `print-devices/heartbeat`, `print-check`), `static/js/shared-print.js`, migraciones `0069`, `0071`, `0076`; pruebas `tests/js/shared_print_*_check.js`. Los 6 commits posteriores a `b36bf92` están en `main` y en producción (según Juan David). |
| 15 | Multiimpresión en Parámetros: el admin la activa y los usuarios activos eligen con qué equipo comparten; más de 2 pueden compartir | Solo diseño | **HECHO Y EN MAIN** (confirmado por Juan David el 30-oct) | Interruptor `PUT /events/{id}/shared-print` y tabla en Parámetros (`kiosk_parametros.html:148-150,848-869`, opción «En su propio equipo» o el equipo elegido); sin tope por impresora (`WARN_PER_PRINTER`, aviso con más de 6). Quien asigna a cada usuario su equipo es **coordinador o más** (`CONFIG = require_role_excluding("coordinador", …)`, `shared_print.py:39`); **Juan David confirmó (30-oct) que eso es lo correcto: los operadores no configuran nada.** |
| 16 | iPad imprime vía un celular Android «estación» con la impresora conectada | Solo diseño | **HECHO Y EN MAIN** (no probado en iPad físico) | El iPad usa la ruta `shared` del punto 14 hacia un equipo anfitrión con USB o «ventana de Chrome» (`_can_host`, `print_stations.py`, `print-jobs-next`, `tests/js/shared_print_station_check.js`). No hay prueba con un iPad real: **no verificado**. |

### 4. Personas nuevas

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 17 | Cédula nueva y vieja al crear digitadores o clientes temporales, para llenar nombre y cédula | No hecho; la lectura MRZ ya existía | **PARCIAL** | La lectura (MRZ, cédula vieja por código de barras) existe para ASISTENTES: `app/routers/cedula.py`, `directory.js`, `kiosk_registro.html`. `templates/staff.html` y `kiosk_usuarios.html` no la usan (grep `mrz` solo en `kiosk_registro.html` y `cedula.py`). Falta llevarla al alta de personal. |
| 18 | Autorregistro del cliente por enlace (usuario y contraseña = teléfono o correo; pantalla final con enlace de inicio de sesión; empresa y evento salen solos) | No hecho | **POR HACER** | Sin enlace de alta de personal (`app/routers/staff.py` sin enlaces; los `FormInvite` y `aceptar` son de formularios y consentimientos). |
| 19 | Autorregistro del digitador por enlace (cédula, celular, nombre, ciudad, barrio/zona, contacto de emergencia; coordinador, lugar y contacto de Golden heredados del evento) | No hecho | **POR HACER** | Igual que 18; depende del compromiso (20). |
| 20 | Compromiso digital de digitadores (desde el Word; aceptación por secciones; firma dibujada; PDF; vence a los 30 días y bloquea si está vencido) | No hecho | **POR HACER** | grep `compromiso` en `app/`, `templates/`, `static/js/` = 0. |
| 21 | Base de digitadores y clientes que solo un admin descarga | No hecho | **POR HACER** | Sin código; depende de 18–20. |

### 5. Cliente

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 22 | Informe del cliente con encuesta (5 preguntas, recomendar 0–10, «¿próximo evento? 2 %»); lo descarga solo si la comercial lo habilita y respondió; alerta por correo a la comercial | No hecho | **PARCIAL** | El informe final existe (`app/routers/event_report.py`, `Event.report_pdf_path`); no hay encuesta, ni habilitación por la comercial, ni alerta (grep `encuesta`/`survey` = 0). |
| 23 | Registro touch: sección nueva al lado de Registro y Ruleta, para pantallas táctiles, 16:9 y responsive | No hecho | **PARCIAL** *(confirmado por Juan David el 30-oct: el modo touch dentro del Registro cuenta como parcial; el pedido original se mantiene: sección aparte junto a Registro y Ruleta)* | Existe un modo «📱 Registro touch» **dentro de la pantalla de Registro** (interruptor por equipo, tres buscadores, «solo lector», tarjetas): `shared-print.js`, `directory.js:544`, commit `97c8509`, `tests/test_directorio_touch.py`. **No es una sección nueva** junto a Registro y Ruleta y no verifiqué 16:9. |

### 6. Sin internet y lista local

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 24 | Servidor local sin internet con sincronización (laptop Windows, 5–6 equipos por router, hasta 2 laptops, sin hardware nuevo) | Solo diseño (docs/17) | **POR HACER** | Solo diseño en `docs/17_SERVIDOR_LOCAL.md`. |
| 25 | Modo sin conexión como requisito del piloto; encendido en producción; `CONTINGENCY_ENABLED` como interruptor de emergencia que cambia solo Juan David | Interruptor hecho; producción salía con 0 hasta ordenarlo | **HECHO Y EN MAIN** (valor en la nube no verificado) | `5ff752b` («Producción: modo sin conexión ENCENDIDO — `CONTINGENCY_ENABLED=1`»), `deploy/gcp/config.sh`. El valor actual en producción no lo puedo ver (nube). |
| 26 | B8: registro y edición completos sin red (bandeja de salida), cifrado WebCrypto, borrado tras sincronizar, caducidad de 7 días con avisos desde el día 3, cola visible | R1 hecha en `producto/piloto` sin integrar; R2–R5 sin hacer | **PARCIAL** | **R1 ya está en `main`**: `static/js/outbox.js`, `outbox-ui.js`, `POST /api/events/{id}/outbox/sync`, `tests/test_outbox_sync.py`, `tests/js/outbox_check.js`. **Defecto verificado:** el modal «Registrar nuevo» no abre sin red (`kiosk_registro.html:379-381`), así que R1 es inalcanzable desde la pantalla (ver `0A_fallos_autoimpresion_autorregistro.md` §5-F). Faltan R2 (foto y consentimiento), R3 (edición), R4 (PIN, exportación de emergencia), R5 (dos dispositivos). |
| 27 | Recarga sin red local-first: lista local en ≤3 s y franja de contingencia en ≤5 s | Hecho, sin integrar (`fix/offline-recarga`); faltan pruebas en dispositivos reales | **HECHO PERO SIN INTEGRAR** | Rama `fix/offline-recarga`, commit `2f256d2` (+216 líneas, incluye `tests/js/offline_reload_check.js`). **Sigue sin estar en `main`:** `git cherry` lo da como no aplicado, `FAST_HEALTH_TIMEOUT_MS`/`fastStart`/`LIST_HEAD_TIMEOUT_MS` = 0 en `contingency.js`, `directory.js` y `kiosk_registro.html`, y `offline_reload_check.js` no existe en `main`. Producción recarga sin red como describe `docs/15 D2.5h` (~34 s a ~1 min con red «colgada»). Tampoco están los otros 2 commits de la rama (`e5e5579`, `7169907`). |
| 28 | Lista local completa (todas las personas, buscables por cédula y nombre, 8.000 y 16.000, contador «LISTA LOCAL: N de N») | Hecho, sin integrar (`producto/piloto`); cédula solo por coincidencia exacta | **HECHO Y EN MAIN** *(la lista decía «sin integrar»: ya está)* | `directory.js:778-802` (modo `localMode`, contador «LISTA LOCAL: N de N», visto en pantalla en las pruebas), `contingency.js`, `tests/test_local_roster.py`, `tests/js/contingency_list_check.js`. Las pruebas de escala de 8.000/16.000 están en `fix/offline-recarga` (`7169907`, diagnóstico, no CI): no en `main`. |
| 29 | Filas por página por evento (10, 20, 50, 100, 200) en la tabla en vivo y la local; propuse 50 por defecto | Hecho, sin integrar (`producto/piloto`) | **HECHO Y EN MAIN** *(ya integrado)* | `Event.directory_page_size` con valor por defecto **50** (`models.py:263`), `app/routers/parametros.py:207`, selector en `kiosk_parametros.html:62`, `PAGE_SIZES = [10, 20, 50, 100, 200]` (`directory.js:665`), `tests/test_directory_page_size.py`, `tests/js/directory_paging_check.js`. |

### 7. Operación del evento

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 30 | «✅ Acreditar» en todas las filas con «Deshacer» (~8 s en pantalla; solo quien acreditó puede deshacer, hasta ~15 s, verificado en el servidor) | (texto cortado) | **HECHO Y EN MAIN** | `directory.js:977` `acreditarFila`, `offerUndo` (`UNDO_MS = 8000`), `undoAccredit`; `POST /api/events/{id}/accreditations/undo` con `ACCREDIT_UNDO_WINDOW = 15 s` (`api.py:822,825`); `tests/test_accreditation_undo.py`, `tests/js/row_accredit_check.js`. |
| 31 | Logo por defecto cambiable desde Configuración (subir, previsualizar, restaurar; PNG/JPEG/WebP hasta 2 MB; ~512 px; ruta `/branding/logo?v=<hash>`; el logo del evento manda) | No hecho; aprobado | **POR HACER** | No existe `/branding/logo` ni la sección «Logo por defecto» en `templates/configuracion.html` (grep `branding` en `app`, `templates`, `static`, `scripts`, `deploy` sin resultados); el logo por defecto sigue fijo en `static/img/logo-golden.png` (`app/main.py:186` solo usa la altura del logo del evento). El diseño está en `docs/16` (pedido 7b). |
| 32 | URL limpia de inscripciones: `inscripciones.golden-eventos…/<nombre-del-evento>`, un solo host y certificado, nombres únicos, redirección al renombrar, palabras reservadas | Solo diseño; después del piloto | **POR HACER** | grep `public_slug` e `inscripciones.golden` = 0; el formulario público sigue en `/f/{event_id}/{slug}` (slug único solo por evento). Diseño en `docs/15 D2.5k` y `docs/16 N6`. |
| 33 | Copias de la base a las 3 a. m. y su alarma | Scripts y alerta hechos; falta activarlos en producción y crear la tarea en staging | **PARCIAL** | **En `main`:** `app/ops_runner.py` (`hourly` cada hora al minuto 05; a las `OPS_DAILY_HOUR` = 3 el diario; paso `check-backups`, con alerta por correo si falta o está viejo), `deploy/gcp/scheduler.sh` (`ensure`/`--resume` crea la tarea `golden-ops-hourly`). **Falta (nube, no verificable desde el repo):** que la tarea del Scheduler exista y esté reanudada en producción y en staging. |
| 34 | Prueba de restauración del último respaldo diario | Script hecho; la restauración real la corre Juan David | **PARCIAL** | **En `main`:** `scripts/restore_test.sh` y `scripts/restore_db.sh`. **Falta:** correrlo contra un respaldo real del bucket (`docs/15 D2.5j (b)`: hasta ahora solo se restauró uno de 17 KB contra el emulador). Lo ejecuta Juan David. |
| 35 | Llave de cifrado: copia fuera de línea y `--version-destroy-ttl=7d` | Aceptado, no hecho | **POR HACER** | grep `version-destroy-ttl` = 0 en `scripts`, `deploy`, `app` y `docs`; la copia fuera de línea es una acción de Juan David (`docs/15 D2.5j (d)`). |
| 36 | Alerta de borrado masivo de archivos | Aceptado, no hecho | **POR HACER** | No hay métrica ni política de alerta de borrados en `deploy/gcp/bootstrap.sh` (solo uptime, ejecuciones de Jobs y conteo de peticiones, líneas 292–306); `docs/15 D2.5j (c)(i)`: «faltan». |
| 37 | Copia semanal fuera del proyecto | Aceptado, para después del piloto | **POR HACER** | Sin código ni script (grep `semanal`/`weekly`/`offsite` = 0 fuera de `calendar.py`, que no tiene relación). |
| 38 | Bucket de respaldos accesible solo por la cuenta de operaciones | Corregido en `bootstrap.sh` en un commit local sin empujar | **HECHO Y EN MAIN** *(ya no es un commit local)* | `deploy/gcp/bootstrap.sh:185-201` en `main`: sobre el bucket de respaldos, la cuenta de operaciones tiene solo `objectCreator` y el rol propio `goldenBackupLister`; **ninguna cuenta puede descargar ni borrar**; a quien tuviera `objectViewer` de una versión anterior se lo quita (idempotente). **Matiz:** la cuenta de la app conserva el rol de *solo listar* (nombre, tamaño, fecha) para «Último respaldo» en `/sistema`; y en staging el bucket es uno solo con los archivos de la app. Que `bootstrap.sh` se haya vuelto a correr en la nube con esa corrección: **no verificado**. |
| 39 | Política de privacidad v1.0 con constancia de la auditora y borrador v1.1 del apartado 5-bis para el registro sin red | v1.0 hecha e integrada; borrador en `fix/legal-1-1-borrador` | **PARCIAL** | **En `main`:** v1.0 con constancia (`app/legal.py:14`), y además la v1.1 ratificada y activa (`docs/legal/POLITICA_v1.1.md`, `RATIFICACION_v1.1.md`, `POLICY_VERSION=1.1`). **Sin integrar:** el borrador del 5-bis (registro sin red) está en `fix/legal-1-1-borrador`, commit `175e7b7`; el paso siguiente es `docs/legal/BORRADOR_POLITICA_v1.2.md` (no activo). |
| 40 | Marcador de acuerdos con proveedores; se reduce a solo Wompi cuando Juan David confirme Google, Neon y Microsoft | Pendiente de confirmación | **PARCIAL** *(el 29-oct dije que no lo encontraba: sí existe, lo busqué mal)* | `templates/legal_privacidad.html:67` en `main`: `<span class="pending">[pendiente: confirmar los acuerdos de tratamiento de datos con cada proveedor]</span>` bajo la tabla de terceros (Wompi, Microsoft, Google Cloud, Neon, Cloudflare, Google traducción/fuentes, Organizador). **Falta:** la confirmación de Juan David y reducir el marcador a solo Wompi; el marcador no cuenta para la huella (`legal.py:15,26`). |
| 41 | Runbook de evento y guía de producción, con criterio para pasar al software de respaldo e iPad como PWA instalada | Hecho | **HECHO Y EN MAIN** | `docs/runbook_evento.md` (criterio concreto «P1. Cuándo se pasa al software de respaldo», línea 61; «los iPad se usan SIEMPRE como PWA», línea 83; «Añadir a pantalla de inicio», línea 52), `docs/19_GUIA_PRODUCCION.md`, `docs/13_RUNBOOK_PRODUCCION.md`, `docs/legal/RUNBOOK_CLOUD_SHELL.md`. Es un borrador del 5-oct en esa sección (el propio documento lo dice). |

## Conteos definitivos de los 41

| Estado | Puntos | Cantidad |
|---|---|---|
| **HECHO Y EN MAIN** | 13, 14, 15, 16, 25, 28, 29, 30, 38, 41 | **10** |
| **HECHO PERO SIN INTEGRAR** | 27 | **1** |
| **PARCIAL** | 3, 6, 17, 22, 23, 26, 33, 34, 39, 40 | **10** |
| **POR HACER** | 1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 18, 19, 20, 21, 24, 31, 32, 35, 36, 37 | **20** |
| **Total** | | **41** |

Por bloque de la lista: 1–8 ficha y estados: 0 hechos, 2 parciales, 6 por hacer · 9–12 correos e inventario: 4 por hacer · 13–16 impresión: 4 hechos · 17–21 personas nuevas: 1 parcial, 4 por hacer · 22–23 cliente: 2 parciales · 24–29 sin internet y lista local: 3 hechos, 1 sin integrar, 1 parcial, 1 por hacer · 30–41 operación: 3 hechos (30, 38, 41), 4 parciales (33, 34, 39, 40), 5 por hacer (31, 32, 35, 36, 37).

*«Hecho y en main» no es «verificado en hardware» ni «activo en la nube»: lo que depende de la nube (33, 34, 38 y el valor de 25) no se pudo comprobar.*

## Qué cambió respecto a las versiones anteriores

- **29-oct → 30-oct (puntos 1–30 reales):** 23 pasó de «hecho» a «parcial»; 8 y 10 de «parcial» a «por hacer»; 4 y 5 «por hacer»; 3 y 6 «parcial»; 15 «hecho». Conteo 9 / 1 / 8 / 23 con 31–41 aún inferidos.
- **30-oct → hoy (puntos 31–41 reales):** **38 pasa a «hecho y en main»** (la corrección de `bootstrap.sh` ya está en `main`, no es un commit local); **34 pasa a «parcial»** (existe `scripts/restore_test.sh`); **40 pasa de «por hacer» a «parcial»** (el marcador sí existe en `legal_privacidad.html:67`; lo busqué mal el 29-oct); **35 y 36 quedan «por hacer»** (grep de `version-destroy-ttl` y de alertas de borrado en cero); 31, 32, 37 «por hacer»; 33 y 39 «parcial»; 41 «hecho».
- **Conteo definitivo: 10 / 1 / 10 / 20** (hecho y en main / sin integrar / parcial / por hacer). El conteo del 30-oct era 9 / 1 / 8 / 23.
- **Respuestas de Juan David (30-oct):** 15 confirmado (coordinador o más asigna); 23 sigue parcial (el pedido original es una sección aparte).
- **Lo que la lista (pre-piloto) daba por no integrado o por hacer y hoy ya está en `main`:** 13, 14, 15, 16 (impresión USB y compartida), 26-R1, 28, 29, 6 (backend), 38. **Lo único «hecho pero sin integrar» que queda:** 27 (`fix/offline-recarga`).

## Hallazgos que cambian el plan

1. **El punto 27 NO está en `main`** y producción recarga sin red con el comportamiento lento. Candidato natural para la Fase 1A (requiere prueba en dispositivos).
2. **El punto 26 (R1) está en `main` pero es inalcanzable** por el guardia de `openRegisterModal`.
3. **Estados con reglas (6):** el backend y el campo `state_id` ya están; faltan la pantalla, el selector y 5 reglas sin cablear.
4. **Ramas con trabajo no integrado** (para la limpieza de la Fase 0B): `fix/offline-recarga` (3 commits), `fix/legal-1-1-borrador` (1), `ux/fase1-visual` (8), `producto/impresion-ajustes` (9) y `producto/impresion-compartida` (6, probablemente reemplazadas por lo ya integrado; no verificado commit por commit), `producto/fecha-nacimiento-sin-rostro` (2, con sus revert).
5. **Lo que hay en `main` y no está en la lista:** exportar/importar eventos completo (`app/event_transfer.py`, `docs/18_EXPORTAR_EVENTOS.md`, migraciones `0074`–`0075`), puestos de impresión y sesiones por rol (`0072`), origen de carga (`0073`).

## Dudas para Juan David

- Punto 40: ¿cuándo confirma Google, Neon y Microsoft para reducir el marcador a solo Wompi? Es un cambio de texto de la política: según `app/legal.py` el texto marcado «pendiente» no cambia la huella, pero cualquier otro cambio sí exige nueva constancia de la auditora.
- Puntos 33, 34 y 38: ¿se pueden confirmar desde la nube (tarea del Scheduler reanudada, restore-test corrido, `bootstrap.sh` reaplicado)? No los puedo comprobar desde el repo.
- Punto 27 sigue sin integrar: ¿entra a la Fase 1A o se saca antes como parche aparte?
