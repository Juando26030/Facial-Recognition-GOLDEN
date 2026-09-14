# Product Backlog — GoldenWeb 2.0

> Backlog en formato Scrum, construido sobre la clasificación FURPS+
> (`02_CLASIFICACION_FURPS.md`) y el roadmap de fases (`REQUERIMIENTOS_ROADMAP.md`).
> Los épicos de la Fase A están refinados en historias de usuario listas para
> que el agente las tome; los de fases posteriores quedan a nivel de épico —
> se refinan cuando se acerque su turno (así se evita mantener detalle que
> puede cambiar antes de construirse).

## Definition of Ready (para que una historia entre a un sprint)

- Tiene criterios de aceptación escritos.
- Sus dependencias (columna "Depende de" en la clasificación FURPS+) ya están
  resueltas o entran en el mismo sprint.
- Si toca datos personales o biométricos, se revisó el impacto legal/privacidad.
- Juan David la priorizó explícitamente (no se empieza nada fuera de orden
  sin decisión consciente).

## Definition of Done

- Código en la rama de feature, con el runner de CI/CD en verde.
- Migración de Alembic incluida si cambia el modelo de datos.
- Probado manualmente en el flujo real (crear evento → activar → operar el
  módulo → cerrar evento) antes de mergear a `main`.
- `CLAUDE.md` actualizado si cambia arquitectura, estructura de archivos o
  quedan pendientes nuevos.
- Sin credenciales ni datos sensibles committeados (ver checklist de
  seguridad ya aplicada en el repo).

---

## Épico 1 — Núcleo de registro por cédula (Fase A · Must)

**Objetivo:** GoldenWeb 2.0 puede operar el flujo de registro que hoy hace el
sistema viejo: cargar la base del evento y acreditar gente por cédula.

### Historia 1.1 — Cargar la base de datos del evento

> Como coordinador, quiero subir el Excel de asistentes esperados de un
> evento, para que el equipo de registro pueda buscarlos el día del evento.

Criterios de aceptación:
- Se puede subir un `.xlsx`/`.csv` asociado a un evento en estado `creado` o
  `en_proceso`.
- El sistema mapea columnas de forma flexible (nombre/nombres,
  apellido/apellidos, cédula/identificación — como ya hacía `bulk_register`
  en el sistema anterior, ver `CLAUDE.md`).
- Errores de formato se reportan fila por fila, no se aborta toda la carga
  por un error puntual.
- Los registros cargados quedan visibles en el directorio del evento con
  estado "No registrado".

### Historia 1.2 — Registrar por cédula con lector de código de barras

> Como digitador, quiero escanear la cédula con el lector de código de
> barras, para acreditar a la persona sin escribir el número a mano.

Criterios de aceptación:
- El campo de entrada del kiosko interpreta la lectura del lector como si
  fuera tecleada y dispara la búsqueda automáticamente (sin submit manual).
- Si la cédula está en la base del evento: se acredita y pasa a "Registrado".
- Si no está pero se autoriza manualmente: se puede dar de alta como "Nuevo"
  sin perder el flujo (M1-3).
- Tiempo de respuesta percibido igual o mejor que el sistema actual (M1-1,
  categoría Performance — es el criterio de éxito #2 del documento de
  Visión y Alcance).

### Historia 1.3 — Buscar por nombre o empresa

> Como digitador, quiero buscar por nombre o empresa cuando no hay cédula a
> mano, para no bloquear el registro de alguien.

Criterios de aceptación:
- Búsqueda insensible a tildes y mayúsculas/minúsculas (M1-2).
- Muestra sugerencias mientras se escribe.
- Selecciona un resultado y sigue el mismo flujo de acreditación que 1.2.

### Historia 1.4 — Evitar y avisar registros duplicados

> Como digitador, quiero que el sistema me avise si alguien ya se registró,
> para no acreditarlo dos veces por error.

Criterios de aceptación:
- Alerta visible (no un `alert()` de navegador — seguir el patrón de
  notificaciones ya usado en el sistema, ver `CLAUDE.md` §"UX") al intentar
  registrar a alguien con estado "Registrado".
- El estado "ya registrado" es visualmente evidente en la tabla del
  directorio en vivo (M1-5).
- El botón "no registrado" filtra y muestra cuántos faltan (M1-6).

## Épico 2 — Escarapelas (Fase A · Must)

**Objetivo:** poder diseñar e imprimir la escarapela de cada evento sin
depender de un diseño fijo en código.

### Historia 2.1 — Diseñador de plantilla de escarapela

> Como coordinador, quiero diseñar la plantilla de escarapela de un evento
> insertando variables (nombre, empresa, QR), para que cada evento tenga su
> propio diseño sin pedirle a un desarrollador que lo cambie.

Criterios de aceptación:
- Editor visual simple (arrastrar/soltar campos de texto e imagen sobre un
  lienzo del tamaño real de la escarapela).
- Variables disponibles: al menos nombre, apellido, empresa, cargo, QR/código
  del registro; extensible a los campos del evento a futuro.
- Permite fondo de imagen con los campos de texto superpuestos (M3-2).
- La plantilla se guarda asociada al evento, no es global.

### Historia 2.2 — Imprimir la escarapela al registrar

> Como digitador, quiero que al acreditar a alguien se envíe la escarapela a
> imprimir con sus datos ya rellenos, para no hacerlo manualmente.

Criterios de aceptación:
- Se dispara automáticamente después de un registro exitoso (Historia 1.2).
- Funciona de forma consistente entre navegadores (Chrome/Edge como mínimo)
  — cierra el hueco de M3-5.

## Épico 3 — Modo touch / kiosko simplificado (Fase A · Must)

> Como digitador operando un módulo táctil (iPad/touch), quiero una versión
> simplificada del registro sin teclado físico, para atender puntos de
> acceso sin computador tradicional.

Criterios de aceptación:
- Mismo flujo que el Épico 1, adaptado a pantalla táctil (botones grandes,
  sin depender de teclado físico para la búsqueda salvo un teclado en
  pantalla).
- Reutiliza la misma API de registro — no es un sistema paralelo.

## Épico 4 — Informe final del evento (Fase A · Must)

> Como coordinador, quiero descargar un informe del evento al cerrarlo, para
> entregarle al cliente el resultado (quién se registró, cuándo, quién no).

Criterios de aceptación:
- Disponible cuando el evento pasa a `finalizado`.
- Incluye como mínimo: identificación, nombre, empresa, estado, hora de
  registro.
- Formato Excel, igual que el sistema actual (`app/reports.py` ya tiene una
  base a adaptar, no partir de cero).

---

## Épico 5 — Formularios web propios (Fase B · Should)

Épico sin refinar todavía. Alcance de referencia (ver `02_CLASIFICACION_FURPS.md`
M5): creador de formularios que alimenta directo la base del evento,
selección múltiple en combo/check/radio (bug a corregir, M5-7), tipografía y
colores personalizables, adjuntar archivos, correo de confirmación
automático, escarapela virtual al inscribirse.

## Épico 6 — Portal de cliente (Fase C · Should)

Épico sin refinar. El rol `cliente` ya existe (construido en la sesión de
autenticación/roles); falta la superficie: estadísticas del propio evento,
encuesta de satisfacción post-evento.

## Épico 7 — Gestión de personal y facturación (Fase C · Should)

Épico sin refinar. Listado de personal asignable por evento, indicador de
facturación en el calendario, planilla quincenal automática de pago por
colaborador.

## Épico 8 — Pagos y adjuntos en formularios (Fase C · Should)

Épico sin refinar, bloqueado por decisión de negocio: qué pasarela reemplaza
a PayU (pregunta abierta en `REQUERIMIENTOS_ROADMAP.md` §5).

## Épico 9 — Acta de novedades digital (Fase C · Should)

Épico sin refinar. Captura de fotos/video y firma digital del cliente,
asociada al evento.

## Épico 10 — Exploración (Fase D · Could / Won't por ahora)

NFC, lectura de cédula por cámara, huella dactilar (bloqueado por legalidad),
sync offline/online completo, integración con "rompefila" de Jose (pendiente
de aclarar qué es), ruleta.

---

## Orden de sprints sugerido (a confirmar contigo)

1. **Sprint 1:** Historia 1.1 + 1.2 (carga de Excel + registro por cédula) —
   es el bloqueador de todo lo demás.
2. **Sprint 2:** Historia 1.3 + 1.4 (búsqueda y duplicados) + arranque del
   Épico 2 (diseñador de escarapelas).
3. **Sprint 3:** Cierre del Épico 2 + Épico 3 (modo touch) + Épico 4 (informe
   final) → con esto GoldenWeb 2.0 ya reemplaza al sistema viejo en un
   evento real.
4. A partir de ahí, Épicos 5-9 según lo que decidas de prioridad de negocio.
