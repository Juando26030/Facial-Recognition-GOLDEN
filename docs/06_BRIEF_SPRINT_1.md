# Brief para el agente de código — Sprint 1

> Para pegar como primer mensaje en la sesión de Claude Code sobre
> `Facial-Recognition-GOLDEN`. Referencia completa en `CLAUDE.md` (raíz del
> repo, rama `feature/auth-roles-events`) y en los documentos de este
> proyecto (`01_VISION_Y_ALCANCE.md` a `05_MODELO_DATOS.md`).

---

Vas a trabajar el **Épico 1 del backlog: núcleo de registro por cédula**
(Historias 1.1 y 1.2 de `03_PRODUCT_BACKLOG.md`). Es el hueco más crítico
del sistema hoy: GoldenWeb 2.0 tiene auth, roles, tenants y eventos, pero
todavía no puede hacer lo que hacía el sistema viejo — cargar la base de un
evento y acreditar gente por cédula. Sin esto no reemplaza al sistema actual
en ningún evento real.

## Antes de escribir código: resolver una decisión de modelado

`05_MODELO_DATOS.md` §3, pregunta 1: hoy `User` es por-tenant (no por-evento)
y `AccessLog.event_id` es lo único que ata un registro a un evento puntual.
Al implementar "cargar el Excel del evento", decide y documenta (actualiza
`CLAUDE.md`) uno de estos dos caminos, con tu criterio técnico:

- **(a)** Cargar el Excel crea/actualiza filas de `User` para el tenant del
  evento (reusa el patrón que ya tenía `bulk_register` en el sistema
  viejo, ver `CLAUDE.md` histórico si aplica). Más simple, pero mezcla
  "conocido para este cliente en general" con "esperado en este evento
  puntual".
- **(b)** Se agrega una tabla intermedia tipo `EventAttendee` que referencia
  a `User` + `Event`, para separar ambos conceptos.

Sea cual sea, tiene que sostener el estado "No registrado" / "Nuevo" /
"Registrado" que ya usa el directorio en vivo (`AccessLog.record_type`).

## Historia 1.1 — Cargar la base de datos del evento

Como coordinador, subo el Excel de asistentes esperados de un evento para
que el equipo de registro pueda buscarlos el día del evento.

Criterios de aceptación:
- Subir `.xlsx`/`.csv` asociado a un evento en estado `creado` o
  `en_proceso` (mismo criterio que ya usa `bulk_register` hoy: no exige
  `en_proceso`, es preparación previa).
- Mapeo de columnas flexible (nombre/nombres, apellido/apellidos,
  cédula/identificación — igual que la lógica ya existente en
  `bulk_register`, `app/routers/api.py`).
- Errores de formato se reportan fila por fila; un error puntual no aborta
  toda la carga.
- Los registros cargados quedan visibles en el directorio del evento en
  estado "No registrado".

## Historia 1.2 — Registrar por cédula con lector de código de barras

Como digitador, escaneo la cédula con el lector de código de barras para
acreditar a la persona sin escribir el número a mano.

Criterios de aceptación:
- El campo de entrada del kiosko interpreta la lectura del lector como si
  fuera tecleada y dispara la búsqueda automáticamente, sin submit manual
  (el lector envía los caracteres + Enter, como un teclado).
- Si la cédula está en la base del evento: se acredita y pasa a
  "Registrado" (mismo flujo de `AccessLog` que ya usa el registro facial).
- Si no está pero se autoriza manualmente: alta como "Nuevo" sin perder el
  flujo (igual que ya existe para el método facial).
- Usa `showToast`/`showConfirm` para cualquier aviso — no `alert()`/`confirm()`
  nativos (convención ya establecida en el proyecto).
- Sigue el patrón de navegación ya definido para métodos de registro:
  vive en su propia ruta `/kiosk/{event_id}/cedula`, escribe `AccessLog` con
  el mismo `event_id` que el método facial, para que Directorio en Vivo y
  Reporte sigan funcionando sin cambios (ver "Selección de método de
  registro" en `CLAUDE.md`).
- Habilita la tarjeta "Cédula" en `kiosk_select.html` (hoy solo Facial está
  habilitado, QR es placeholder).

## Fuera de alcance en este sprint (no lo toques todavía)

Búsqueda por nombre/empresa optimizada (Historia 1.3), alertas de doble
registro (Historia 1.4), escarapelas, modo touch. Van en el siguiente sprint.

## Flujo de trabajo a seguir

Rama nueva desde `feature/auth-roles-events` (o desde donde indiques) →
implementar → avisar cuando esté listo para que Juan David lo pruebe en su
entorno local → **no mergear a `main` sin su aprobación explícita**, aunque
el cambio se vea listo (regla ya establecida en `CLAUDE.md`).
