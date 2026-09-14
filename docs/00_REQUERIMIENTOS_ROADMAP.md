# GoldenWeb 2.0 — Requerimientos y Roadmap de Producto

> Documento de trabajo para decidir, sesión a sesión, qué construye a continuación
> el agente de desarrollo (Claude Code) sobre `Facial-Recognition-GOLDEN`. Se
> actualiza a medida que aparecen nuevos hallazgos o requerimientos — este
> documento es la versión "producto/negocio"; el detalle técnico vive en
> `CLAUDE.md` dentro del repo.

## 1. El negocio

**Golden Eventos y Logística** presta logística de eventos; su servicio insignia
es **registro de asistentes y acreditación**: el asistente llega, se busca en la
base de datos del evento y, si corresponde, se acredita (sticker/manilla). La
empresa es reconocida sobre todo por la **velocidad** del registro — hoy, vía
lector de código de barras sobre la cédula colombiana. Cualquier rediseño tiene
que igualar o superar esa velocidad; es el estándar contra el que se mide todo.

## 2. Cómo funciona el sistema actual (a preservar o mejorar, no perder)

1. **Carga de base de datos del evento**: el cliente manda un Excel con los
   asistentes esperados; se carga a la plataforma y queda asociado al evento.
2. **Registro/acreditación en el punto**: se busca por cédula (lector de código
   de barras → autocompleta el número), por nombre o por empresa. Si la persona
   no estaba en la base pero está autorizada, se puede dar de alta como "nuevo"
   ahí mismo.
3. **Flujo de roles**: la *comercial* crea el evento en el sistema (fecha, hora,
   cliente, lugar, canal, etc.) → queda en "eventos creados" → el *coordinador*
   (rol intermedio, no super-admin) entra, gestiona el montaje/cliente y
   **activa** el evento → solo ahí se habilita el registro.
4. **Escarapelas**: al registrar, se imprime una escarapela con una plantilla
   editable (estilo mini editor de Word) donde se insertan variables (nombre,
   empresa, QR asociado al registro, etc.).
5. **Modo touch/iPad**: versión simplificada del registro, sin teclado físico,
   para módulos táctiles.
6. **Cierre de evento**: al terminar, el sistema guarda quién se inscribió,
   quién no, hora, variables del evento, y genera un informe descargable para
   el cliente.
7. **Formularios web propios** (no Google Forms): el cliente los envía a sus
   invitados, la gente se inscribe y esa inscripción arma directamente la base
   de datos del evento en el formato que Golden necesita (en vez de recibir un
   Excel en formato libre que hay que adaptar).

## 3. Estado actual del nuevo sistema (GoldenWeb 2.0)

Según la última sesión de desarrollo (rama `feature/auth-roles-events`, aún sin
mergear a `main`):

- Autenticación y roles reales: `super_admin`, `admin`, `coordinador`,
  `digitador` (temporal, atado a un evento), `cliente` (solo estadísticas y
  directorio, atado a un evento).
- Multi-tenant real: `Tenant` (cliente de Golden) y `Event` (evento puntual
  dentro de un tenant) son entidades con CRUD completo — ya no hay tenant
  hardcodeado.
- Ciclo de vida del evento: `creado → en_proceso → finalizado`, navegable con
  confirmación; el registro solo se habilita en `en_proceso` (bloqueado de
  verdad en la UI).
- Navegación: `/` panel (clientes → eventos), `/kiosk/{id}` selector de método
  de registro, `/kiosk/{id}/facial` kiosko real. **Solo el método facial está
  implementado**; QR es un placeholder de UI.
- Seguridad resuelta: credenciales rotadas, historial de git limpiado, rol de
  Postgres de mínimo privilegio, migraciones con Alembic (7 hasta ahora).
- CI/CD: runner self-hosted de GitHub Actions en la VM, despliega solo al
  mergear a `main`.
- Decisión de arquitectura (pendiente de ejecutar): reestructurar a monorepo
  (`apps/<módulo>/`) para que los módulos nuevos (QR, formularios, etc.) se
  agreguen sin fricción — exactamente el objetivo de "que sea fácil meter
  módulos nuevos" que se planteó para este rediseño.

**Lo que falta de paridad con el sistema viejo** (nada de esto existe todavía
en el nuevo sistema): carga de Excel del evento, registro por cédula/código de
barras, búsqueda por nombre/empresa, diseñador de escarapelas, modo touch,
informe final descargable, formularios web propios.

## 4. Backlog de requerimientos nuevos

Organizado por módulo. "Origen" = quién lo pidió en la ronda de reingeniería.
"Nota" marca si ya quedó resuelto por la nueva arquitectura, si es un bug del
sistema viejo a no repetir, o si necesita una decisión primero.

### M1. Registro y acreditación (núcleo del negocio)

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M1-1 | Registro por cédula vía lector de código de barras | Legado | **Crítico** — es el producto insignia, no existe aún en v2 |
| M1-2 | Búsqueda por nombre/empresa, sin tildes, todo mayúsculas, con sugerencias | JD | Optimización sobre la búsqueda del punto anterior |
| M1-3 | Alta de "nuevo" si no está en la base pero está autorizado | Legado | — |
| M1-4 | Alerta cuando alguien intenta registrarse 2+ veces | Juan Manuel | — |
| M1-5 | Aviso de "ya registrado" más evidente | JD | — |
| M1-6 | Botón "no registrado" funcional, que muestre el número | JD | — |
| M1-7 | Lectura de cédulas colombianas nuevas (formato distinto) | JD | Verificar si cambia el layout del código de barras |
| M1-8 | Detección/lectura de cédula por cámara (sin lector físico) | JD | Mayor esfuerzo — es visión por computador aparte del biométrico facial |
| M1-9 | Entrada con NFC del celular | JD | Marcado "revisarlo" por el propio JD — viabilidad incierta |
| M1-10 | Registro local si se desconecta, sync al reconectar | JD | Requiere diseño offline-first en el kiosko |

### M2. Kiosko / modo touch

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M2-1 | Modo touch/iPad simplificado (sin teclado) | Legado | — |
| M2-2 | Auto-registro en la pestaña touch | Juan Manuel | — |
| M2-3 | Módulos móviles (celular/tablet) + integración con "rompefila" de Jose | JD | **Pregunta abierta**: qué es exactamente el sistema de Jose |
| M2-4 | Ruleta integrada (gamificación) | JD | Baja prioridad de negocio, confirmar interés real |
| M2-5 | Modo simulación de evento (volúmenes/pruebas) | Juan Manuel | Útil para QA antes de un evento grande |

### M3. Escarapelas

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M3-1 | Diseñador de plantillas tipo editor (variables: nombre, empresa, QR) | Legado | — |
| M3-2 | Fondo de imagen + campos de texto superpuestos | Juan Manuel | — |
| M3-3 | Más fuentes / fuente personalizada | Juan Manuel | — |
| M3-4 | Escarapela virtual automática al inscribirse por formulario | Sergio | Depende de M5 (formularios) |
| M3-5 | Preferencias de impresión según navegador | JD | Bug/fricción operativa conocida |

### M4. Gestión de eventos

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M4-1 | Listado de personal asignable a cada evento | Gloria | — |
| M4-2 | Indicador visual de facturación en el calendario | Gloria | — |
| M4-3 | Planilla quincenal automática (eventos trabajados y pago por persona) | Gloria | Depende de M4-1 |
| M4-4 | Salones con muchas conferencias dejan de listarse | Juan Manuel | Bug del sistema viejo — validar que no se repita en v2 |
| M4-5 | Validaciones de fechas y campos obligatorios al crear evento | — | ✅ Ya implementado en v2 |

### M5. Formularios web

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M5-1 | Creador de formularios propio (alimenta directo la base del evento) | Legado | — |
| M5-2 | Personalización de tipografías y colores | Sergio | — |
| M5-3 | Adjuntar archivos (hoy solo 1 imagen jpg) | Sergio | Aplica a formularios, eventos e informes |
| M5-4 | Correo automático de confirmación al inscribirse | Sergio | — |
| M5-5 | Pasarela de pagos: PayU ya no se usa; descuentos son muy rígidos hoy | Sergio | **Pregunta abierta**: con qué pasarela se reemplaza |
| M5-6 | Soporte a otras plataformas de pago | Sergio | **Pregunta abierta**: cuáles son relevantes |
| M5-7 | Campos combo/check/radio con selección múltiple | Juan Manuel | Bug de UX del sistema viejo |
| M5-8 | Longitud de campos configurable (caracteres y ancho visual) | Juan Manuel | — |

### M6. Reportes, informes y estadísticas

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M6-1 | Informe final descargable por evento | Legado | — |
| M6-2 | Columnas del informe personalizables por evento | Juan Manuel | — |
| M6-3 | Repositorio de informes finales importados, asociados al evento por código | Juan Manuel | — |
| M6-4 | Estadísticas en tiempo real más fáciles/dinámicas | JD | Menciona "chat para cliente" — aclarar si es literal o es forma de decir "consulta conversacional" |
| M6-5 | Estadísticas personalizadas | JD | — |

### M7. Actas y documentos del evento

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M7-1 | Acta de novedades digital: fotos/video + firma digital del cliente, asociada al evento | Juan Manuel | Mayor esfuerzo — incluye captura multimedia y firma |

### M8. Portal / cuenta de cliente

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M8-1 | Cuentas de cliente en GoldenWeb | JD | El rol `cliente` ya existe en v2 — falta construir las vistas/funciones propias |
| M8-2 | Encuesta de satisfacción post-evento | JD | Ligada al portal cliente |
| M8-3 | Usuario de cliente funcional (en el sistema viejo no servía) | Juan Manuel | Mismo punto que M8-1, confirmar que la nueva arquitectura ya lo resuelve |

### M9. Plataforma / transversal

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M9-1 | Avisar antes de que expire la sesión | Juan Manuel | — |
| M9-2 | Sync bidireccional de eventos (local/nube) | JD | Relacionado con M1-10 |
| M9-3 | Permisos granulares por usuario (hoy son 4-5 roles fijos) | — | Ya anotado como backlog en `CLAUDE.md` |
| M9-4 | Cada digitador con su propio usuario | Juan Manuel | ✅ Ya cubierto — rol `digitador` existe en v2 |

### M10. Seguridad / legal

| ID | Requerimiento | Origen | Nota |
|---|---|---|---|
| M10-1 | Módulo de huellas dactilares | JD | El propio JD marca "consultar legalidad" — revisar normativa de datos biométricos en Colombia antes de construir |

## 5. Preguntas abiertas (antes de poder planear con precisión)

1. **M2-3**: ¿qué es exactamente el sistema "rompefila" de Jose? ¿Es un
   proveedor externo a integrar, o un módulo interno que hay que reconstruir?
2. **M5-5 / M5-6**: ¿qué pasarela de pago reemplaza a PayU? ¿Cuáles de las
   "otras plataformas" mencionadas por Sergio son realmente prioritarias?
3. **M6-4**: el "chat para cliente" de JD — ¿literalmente un chat conversacional
   contra los datos del evento, o es una forma de decir "que las estadísticas
   se puedan consultar más fácil"?
4. **M10-1**: legalidad del tratamiento de datos biométricos de huella en
   Colombia (Ley 1581 de protección de datos) — falta resolver antes de
   construir nada ahí.
5. ¿Hay algún evento real con fecha próxima que obligue a priorizar un módulo
   en particular (por ejemplo, si ya hay un evento agendado que necesita
   registro por cédula sí o sí)?

## 6. Roadmap propuesto (a confirmar)

La lógica: primero recuperar la paridad con el sistema viejo en lo que es
*el negocio central* (sin esto, GoldenWeb 2.0 no puede reemplazar al sistema
actual en ningún evento real); después, capas de valor agregado.

**Fase A — Paridad del núcleo de registro**
1. Carga de la base de datos del evento (Excel → roster del evento).
2. Registro por cédula/código de barras + búsqueda por nombre/empresa (M1-1 a M1-6).
3. Escarapelas: diseñador de plantillas + impresión (M3-1, M3-5).
4. Modo touch/kiosko simplificado (M2-1).
5. Informe final descargable (M6-1).

**Fase B — Paridad de captación (formularios)**
6. Formularios web propios que alimentan el evento (M5-1, M5-7, M5-8).
7. Correo automático + escarapela virtual al inscribirse (M3-4, M5-4).

**Fase C — Capas nuevas de valor**
8. Portal/cuenta de cliente: estadísticas + encuesta (M8-1, M8-2).
9. Gestión de personal y facturación (M4-1 a M4-3).
10. Pasarela de pagos y adjuntos (M5-3, M5-5, M5-6) — depende de resolver la
    pregunta abierta #2.
11. Acta de novedades digital con firma (M7-1).

**Fase D — Exploración / mayor incertidumbre**
12. NFC, lectura de cédula por cámara, huella (M1-8, M1-9, M10-1), offline/sync
    (M1-10, M9-2), rompefila de Jose (M2-3), ruleta (M2-4).

En paralelo, sin bloquear lo anterior: terminar la reestructuración a monorepo
que ya se decidió, para que cada fase entre como su propio módulo.

---

*Este documento no reemplaza `CLAUDE.md` (detalle técnico/arquitectura del
repo) — es el mapa de producto que define, en conjunto con Juan David, qué le
toca construir al agente en cada sesión.*
