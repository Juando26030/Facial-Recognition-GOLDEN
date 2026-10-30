# Fase 0A · Estado de los 41 puntos pendientes contra `main`

Revisión del 30-oct-2026 sobre `origin/main` = `bc4a19d` (producción corre lo mismo, según Juan David en `/sistema`). `main` ya contiene `b36bf92` y 6 commits más, todos de impresión compartida (migración `0076`).
Esta versión **reemplaza** a la del 29-oct, que usaba una numeración inferida.

## Cómo leer este reporte (y qué NO está verificado)

1. **Numeración real y textos: puntos 1–30.** Son los de la lista que Juan David pegó el 30-oct. **La lista llegó cortada en el punto 30** («…solo quien acreditó puede deshacer, hasta ~15 s, verificado en el»): **faltan los textos de los puntos 31–41**. Esas 11 filas conservan la numeración **inferida** del Anexo A del plan (marcadas «(inferido)») y hay que confirmarlas cuando llegue el resto de la lista.
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
| 15 | Multiimpresión en Parámetros: el admin la activa y los usuarios activos eligen con qué equipo comparten; más de 2 pueden compartir | Solo diseño | **HECHO Y EN MAIN** (con una diferencia a confirmar) | Interruptor `PUT /events/{id}/shared-print` y tabla en Parámetros (`kiosk_parametros.html:148-150,848-869`, opción «En su propio equipo» o el equipo elegido); sin tope por impresora (`WARN_PER_PRINTER`, aviso con más de 6). **Diferencia:** quien asigna es **coordinador o más** (`CONFIG = require_role_excluding("coordinador", …)`, `shared_print.py:39`), no cada usuario eligiendo el suyo. ¿Es lo pedido? |
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
| 23 | Registro touch: sección nueva al lado de Registro y Ruleta, para pantallas táctiles, 16:9 y responsive | No hecho | **PARCIAL** *(el 29-oct puse «hecho»: corregido)* | Existe un modo «📱 Registro touch» **dentro de la pantalla de Registro** (interruptor por equipo, tres buscadores, «solo lector», tarjetas): `shared-print.js`, `directory.js:544`, commit `97c8509`, `tests/test_directorio_touch.py`. **No es una sección nueva** junto a Registro y Ruleta y no verifiqué 16:9. |

### 6. Sin internet y lista local

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 24 | Servidor local sin internet con sincronización (laptop Windows, 5–6 equipos por router, hasta 2 laptops, sin hardware nuevo) | Solo diseño (docs/17) | **POR HACER** | Solo diseño en `docs/17_SERVIDOR_LOCAL.md`. |
| 25 | Modo sin conexión como requisito del piloto; encendido en producción; `CONTINGENCY_ENABLED` como interruptor de emergencia que cambia solo Juan David | Interruptor hecho; producción salía con 0 hasta ordenarlo | **HECHO Y EN MAIN** (valor en la nube no verificado) | `5ff752b` («Producción: modo sin conexión ENCENDIDO — `CONTINGENCY_ENABLED=1`»), `deploy/gcp/config.sh`. El valor actual en producción no lo puedo ver (nube). |
| 26 | B8: registro y edición completos sin red (bandeja de salida), cifrado WebCrypto, borrado tras sincronizar, caducidad de 7 días con avisos desde el día 3, cola visible | R1 hecha en `producto/piloto` sin integrar; R2–R5 sin hacer | **PARCIAL** | **R1 ya está en `main`**: `static/js/outbox.js`, `outbox-ui.js`, `POST /api/events/{id}/outbox/sync`, `tests/test_outbox_sync.py`, `tests/js/outbox_check.js`. **Defecto verificado:** el modal «Registrar nuevo» no abre sin red (`kiosk_registro.html:379-381`), así que R1 es inalcanzable desde la pantalla (ver `0A_fallos_autoimpresion_autorregistro.md` §5-F). Faltan R2 (foto y consentimiento), R3 (edición), R4 (PIN, exportación de emergencia), R5 (dos dispositivos). |
| 27 | Recarga sin red local-first: lista local en ≤3 s y franja de contingencia en ≤5 s | Hecho, sin integrar (`fix/offline-recarga`); faltan pruebas en dispositivos reales | **HECHO PERO SIN INTEGRAR** | Rama `fix/offline-recarga`, commit `2f256d2` (+216 líneas, incluye `tests/js/offline_reload_check.js`). **Sigue sin estar en `main`:** `git cherry` lo da como no aplicado, `FAST_HEALTH_TIMEOUT_MS`/`fastStart`/`LIST_HEAD_TIMEOUT_MS` = 0 en `contingency.js`, `directory.js` y `kiosk_registro.html`, y `offline_reload_check.js` no existe en `main`. Producción recarga sin red como describe `docs/15 D2.5h` (~34 s a ~1 min con red «colgada»). Tampoco están los otros 2 commits de la rama (`e5e5579`, `7169907`). |
| 28 | Lista local completa (todas las personas, buscables por cédula y nombre, 8.000 y 16.000, contador «LISTA LOCAL: N de N») | Hecho, sin integrar (`producto/piloto`); cédula solo por coincidencia exacta | **HECHO Y EN MAIN** *(la lista decía «sin integrar»: ya está)* | `directory.js:778-802` (modo `localMode`, contador «LISTA LOCAL: N de N», visto en pantalla en las pruebas), `contingency.js`, `tests/test_local_roster.py`, `tests/js/contingency_list_check.js`. Las pruebas de escala de 8.000/16.000 están en `fix/offline-recarga` (`7169907`, diagnóstico, no CI): no en `main`. |
| 29 | Filas por página por evento (10, 20, 50, 100, 200) en la tabla en vivo y la local; propuse 50 por defecto | Hecho, sin integrar (`producto/piloto`) | **HECHO Y EN MAIN** *(ya integrado)* | `Event.directory_page_size` con valor por defecto **50** (`models.py:263`), `app/routers/parametros.py:207`, selector en `kiosk_parametros.html:62`, `PAGE_SIZES = [10, 20, 50, 100, 200]` (`directory.js:665`), `tests/test_directory_page_size.py`, `tests/js/directory_paging_check.js`. |

### 7. Operación del evento (la lista llegó cortada en el 30; del 31 al 41, numeración inferida)

| # | Punto | Según Juan David | Estado hoy en `main` | Evidencia y qué falta |
|---|---|---|---|---|
| 30 | «✅ Acreditar» en todas las filas con «Deshacer» (~8 s en pantalla; solo quien acreditó puede deshacer, hasta ~15 s, verificado en el servidor) | (texto cortado) | **HECHO Y EN MAIN** | `directory.js:977` `acreditarFila`, `offerUndo` (`UNDO_MS = 8000`), `undoAccredit`; `POST /api/events/{id}/accreditations/undo` con `ACCREDIT_UNDO_WINDOW = 15 s` (`api.py:822,825`); `tests/test_accreditation_undo.py`, `tests/js/row_accredit_check.js`. |
| 31 (inferido) | Logo por defecto cambiable desde Configuración | — | **POR HACER** | No existe `/branding/logo` ni la sección en `configuracion.html`; el logo sigue en `static/img/logo-golden.png`. |
| 32 (inferido) | URL limpia para las inscripciones públicas | — | **POR HACER** | grep `public_slug` = 0; el formulario público sigue en `/f/{event_id}/{slug}`. |
| 33 (inferido) | Copias de la base a las 3 a. m. activas | — | **PARCIAL** | Código en `main`: `app/ops_runner.py`, `deploy/gcp/scheduler.sh`. Que estén ACTIVAS en producción: **no verificado** (nube). |
| 34 (inferido) | Alerta de borrado masivo en el bucket | — | **POR HACER** | `docs/15 D2.5j (c)(i)`: «Faltan… alerta de borrado masivo». |
| 35 (inferido) | Copia semanal fuera del proyecto | — | **POR HACER** | Sin código ni script (grep `semanal`/`offsite` = 0). |
| 36 (inferido) | Copia fuera de línea de la llave `FACE_ENCRYPTION_KEY` | — | **POR HACER** (acción de Juan David) | `docs/15 D2.5j (d)`; no verificable desde el repo. |
| 37 (inferido) | `--version-destroy-ttl=7d` en la llave (Secret Manager) | — | **POR HACER** (acción de Juan David, nube) | No se puede comprobar desde el repo. |
| 38 (inferido) | Restore-test de un respaldo real / historial de Neon a 1 día | — | **POR HACER** | `docs/15 D2.5j (b)`: solo se restauró uno de 17 KB contra el emulador. |
| 39 (inferido) | Política de privacidad v1.1 con el apartado 5-bis (registro sin red) | — | **PARCIAL** | v1.1 ratificada y activa (`docs/legal/POLITICA_v1.1.md`, `RATIFICACION_v1.1.md`); el 5-bis es un borrador sin integrar en `fix/legal-1-1-borrador` (`175e7b7`); el siguiente paso es `docs/legal/BORRADOR_POLITICA_v1.2.md` (no activo). |
| 40 (inferido) | Marcador de proveedores (confirmar Google, Neon, Microsoft) | — | **POR HACER** | `legal_privacidad_v11.html` no nombra a Neon/Microsoft/Google y no encontré el marcador en `main`: **no verificado**. |
| 41 (inferido) | Runbook y guía de producción | — | **HECHO Y EN MAIN** | `docs/19_GUIA_PRODUCCION.md`, `docs/runbook_evento.md`, `docs/13_RUNBOOK_PRODUCCION.md`, `docs/legal/RUNBOOK_CLOUD_SHELL.md`. |

## Conteos

| Estado | Puntos 1–30 (numeración real) | Puntos 31–41 (inferidos) | Total 41 |
|---|---|---|---|
| HECHO Y EN MAIN | 8 (13, 14, 15, 16, 25, 28, 29, 30) | 1 (41) | **9** |
| HECHO PERO SIN INTEGRAR | 1 (27) | 0 | **1** |
| PARCIAL | 6 (3, 6, 17, 22, 23, 26) | 2 (33, 39) | **8** |
| POR HACER | 15 (1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 18, 19, 20, 21, 24) | 8 (31, 32, 34, 35, 36, 37, 38, 40) | **23** |
| **Total** | **30** | **11** | **41** |

## Qué cambió respecto a la versión del 29-oct

- **Antes** 10 hechos / 1 sin integrar / 10 parciales / 20 por hacer. **Ahora** 9 / 1 / 8 / 23.
- Con la lista real: **23 (Registro touch) pasa de «hecho» a «parcial»** (existe el modo touch dentro del Registro, no la sección nueva 16:9); **8 (calendario) y 10 (inventario inteligente) pasan de «parcial» a «por hacer»** (lo existente no es lo pedido); 4 y 5 quedan «por hacer» (el campo «tipo de impresión» no existe en el código actual y «campos a capturar en registro» a nivel de evento tampoco). 3 y 6 quedan «parcial». El 15 queda «hecho» con una diferencia que debe confirmar Juan David.
- **Estados que se mantienen:** 13, 14, 16, 25, 28, 29, 30, 41 (hechos y en `main`), 27 (sin integrar), 17, 22, 26, 33, 39 (parciales) y 24, 18–21, 31, 32, 34–38, 40 (por hacer).
- **Lo que la lista de Juan David daba por «sin integrar» y ya está en `main`:** 13 (integrado al directorio y al registro), 26-R1, 28 y 29 (`producto/piloto`), 6 (backend, `producto/estados-evento`). **Lo que sigue sin integrar:** solo 27 (`fix/offline-recarga`).
- Los puntos 31–41 siguen inferidos hasta que llegue el resto de la lista.

## Hallazgos que cambian el plan

1. **El punto 27 NO está en `main`** y producción recarga sin red con el comportamiento lento. Candidato natural para la Fase 1A (requiere prueba en dispositivos).
2. **El punto 26 (R1) está en `main` pero es inalcanzable** por el guardia de `openRegisterModal`.
3. **Estados con reglas (6):** el backend y el campo `state_id` ya están; faltan la pantalla, el selector y 5 reglas sin cablear.
4. **Ramas con trabajo no integrado** (para la limpieza de la Fase 0B): `fix/offline-recarga` (3 commits), `fix/legal-1-1-borrador` (1), `ux/fase1-visual` (8), `producto/impresion-ajustes` (9) y `producto/impresion-compartida` (6, probablemente reemplazadas por lo ya integrado; no verificado commit por commit), `producto/fecha-nacimiento-sin-rostro` (2, con sus revert).
5. **Lo que hay en `main` y no está en la lista:** exportar/importar eventos completo (`app/event_transfer.py`, `docs/18_EXPORTAR_EVENTOS.md`, migraciones `0074`–`0075`), puestos de impresión y sesiones por rol (`0072`), origen de carga (`0073`).

## Dudas para Juan David

- Reenviar el resto de la lista (puntos **31–41**), que llegó cortada.
- Punto 15: ¿basta con que coordinador o más asigne a cada usuario su equipo de impresión, o debe elegir cada usuario?
- Punto 23: ¿el modo touch dentro del Registro cumple o quiere la sección aparte (16:9)?
- Punto 40: ¿existe el «marcador de proveedores» en algún lado? No lo encontré en `main`.
