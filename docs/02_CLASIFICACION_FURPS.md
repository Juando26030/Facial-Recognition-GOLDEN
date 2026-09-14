# Clasificación de Requerimientos — Plantilla FURPS+

## 1. Por qué FURPS+

Para un sistema con tantos ángulos distintos (biometría, hardware de punto de
registro, pagos, formularios, reportes, portal de cliente) conviene un modelo
que obligue a mirar cada requerimiento desde más de un eje, no solo
"funciona / no funciona". FURPS+ (Hewlett-Packard, extendido) separa:

| Categoría | Pregunta que responde | Ejemplos en este proyecto |
|---|---|---|
| **F — Functionality** | ¿Qué hace el sistema? Funciones, capacidades, seguridad de negocio | Registrar por cédula, generar escarapela, crear formulario |
| **U — Usability** | ¿Qué tan fácil/consistente es de usar? | Búsqueda sin tildes, aviso de "ya registrado" más claro |
| **R — Reliability** | ¿Qué tan bien tolera fallos, se recupera, es predecible? | Registro offline con sync, no perder datos si se cae la red |
| **P — Performance** | ¿Qué tan rápido/con qué capacidad responde? | Velocidad de registro (el diferenciador histórico de Golden) |
| **S — Supportability** | ¿Qué tan fácil es mantener, configurar, extender, escalar? | Columnas de informe configurables, permisos granulares, arquitectura modular |
| **+ (constraints)** | Restricciones de diseño, implementación, interfaces externas, legales/físicas | Integración con lector de código de barras, legalidad de datos biométricos, dependencia de un proveedor externo |

Es más simple que IEEE 830 y más orientado a producto que Volere; para un
equipo chico que necesita decidir rápido qué construir primero, alcanza.

## 2. Estructura de la plantilla

Cada requerimiento se clasifica con estas columnas:

| Columna | Qué va ahí |
|---|---|
| **ID** | Identificador estable (ej. `M1-1`). No se reutiliza aunque el requerimiento se descarte. |
| **Módulo** | Área funcional (ver `REQUERIMIENTOS_ROADMAP.md` — M1 a M10) |
| **Requerimiento** | Descripción corta, en una línea |
| **Categoría FURPS+** | Una o dos categorías (el eje principal primero) |
| **Tipo** | Funcional / No funcional |
| **Prioridad (MoSCoW)** | Must / Should / Could / Won't (por ahora) |
| **Complejidad** | S / M / L / XL — estimación gruesa, no story points todavía |
| **Depende de** | IDs de los que debe existir antes |
| **Origen** | Quién lo pidió, o "Legado" si es paridad del sistema viejo |

**Prioridad MoSCoW** se define en el contexto de negocio, no en abstracto:
*Must* = sin esto GoldenWeb 2.0 no reemplaza al sistema actual en un evento
real; *Should* = mejora clara pedida por el equipo, no bloquea ir a producción;
*Could* = valor agregado, entra si sobra capacidad; *Won't (por ahora)* =
fuera del alcance hasta resolver una duda (legal, técnica, de negocio) o
hasta que se demuestre que vale la pena.

**Cómo clasificar los requerimientos viejos (tu tarea):** para cada ítem de
la lista de paridad legada, aplica las mismas ocho columnas. La única
diferencia es que en "Origen" casi todos dirán "Legado" — lo útil ahí es que
al ponerles Categoría FURPS+ y Prioridad vas a notar cuáles son en realidad
el mismo requerimiento que uno nuevo (por ejemplo, si "buscar por cédula" del
sistema viejo termina siendo literalmente `M1-1`, no crees un ID nuevo:
referencia el existente).

## 3. Clasificación de los requerimientos nuevos

### M1 — Registro y acreditación

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M1-1 | Registro por cédula (lector de código de barras) | F, P | Funcional | Must | M | Roster del evento (Excel) |
| M1-2 | Búsqueda por nombre/empresa sin tildes, sugerencias | U | No funcional | Must | S | M1-1 |
| M1-3 | Alta de "nuevo" si está autorizado pero no en la base | F | Funcional | Must | S | M1-1 |
| M1-4 | Alerta de doble registro | F | Funcional | Should | S | M1-1 |
| M1-5 | Aviso de "ya registrado" más evidente | U | No funcional | Should | S | M1-1 |
| M1-6 | Botón "no registrado" funcional, con número | F, U | Funcional | Should | S | M1-1 |
| M1-7 | Soporte a cédulas colombianas nuevas | F | Funcional | Should | M | M1-1 |
| M1-8 | Detección de cédula por cámara | F, P | Funcional | Could | L | M1-1 |
| M1-9 | Entrada por NFC del celular | + (interfaz HW) | Funcional | Could | L | M1-1 |
| M1-10 | Registro local offline + sync al reconectar | R | No funcional | Could | XL | M1-1 |

### M2 — Kiosko / modo touch

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M2-1 | Modo touch/iPad simplificado | U | Funcional | Must | M | M1-1 |
| M2-2 | Auto-registro en pestaña touch | F | Funcional | Should | S | M2-1 |
| M2-3 | Módulos móviles + integración "rompefila" de Jose | + (interfaz externa) | Funcional | Could | ? | Pendiente de aclarar qué es |
| M2-4 | Ruleta integrada | F | Funcional | Won't (por ahora) | S | — |
| M2-5 | Modo simulación de evento (volumen/pruebas) | R | No funcional | Should | M | — |

### M3 — Escarapelas

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M3-1 | Diseñador de plantillas (variables: nombre, empresa, QR) | F | Funcional | Must | L | — |
| M3-2 | Fondo de imagen + campos superpuestos | F | Funcional | Must | S | M3-1 |
| M3-3 | Más fuentes / fuente personalizada | U | No funcional | Should | S | M3-1 |
| M3-4 | Escarapela virtual automática al inscribirse | F | Funcional | Should | M | M3-1, M5-1 |
| M3-5 | Preferencias de impresión por navegador | + (constraint técnico) | No funcional | Should | M | M3-1 |

### M4 — Gestión de eventos

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M4-1 | Listado de personal asignable al evento | F | Funcional | Should | M | — |
| M4-2 | Indicador de facturación en el calendario | U | No funcional | Should | S | — |
| M4-3 | Planilla quincenal automática (eventos/pago por persona) | F | Funcional | Should | M | M4-1 |
| M4-4 | Bug: salones con muchas conferencias dejan de listarse | R | No funcional (defecto) | Must (no repetir) | S | — |

### M5 — Formularios web

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M5-1 | Creador de formularios propio | F | Funcional | Must | L | — |
| M5-2 | Personalización de tipografía/colores | U | No funcional | Should | M | M5-1 |
| M5-3 | Adjuntar archivos (no solo 1 jpg) | F | Funcional | Should | M | M5-1 |
| M5-4 | Correo automático de confirmación | F | Funcional | Should | S | M5-1 |
| M5-5 | Pasarela de pago (reemplazo de PayU) | F | Funcional | Should | L | Definir proveedor |
| M5-6 | Soporte a otras plataformas de pago | S | No funcional | Could | M | M5-5 |
| M5-7 | Combo/check/radio con selección múltiple | F | Funcional | Must (bug fix) | S | M5-1 |
| M5-8 | Longitud de campos configurable | S | No funcional | Should | S | M5-1 |

### M6 — Informes y estadísticas

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M6-1 | Informe final descargable por evento | F | Funcional | Must | M | — |
| M6-2 | Columnas del informe personalizables | S | No funcional | Should | M | M6-1 |
| M6-3 | Repositorio de informes importados por código de evento | F | Funcional | Should | M | — |
| M6-4 | Estadísticas en tiempo real, consulta más fácil | F | Funcional | Should | M | M8-1 |
| M6-5 | Estadísticas personalizadas | S | No funcional | Could | M | M6-4 |

### M7 — Actas y documentos

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M7-1 | Acta de novedades digital (foto/video + firma) | F | Funcional | Should | L | — |

### M8 — Portal / cuenta de cliente

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M8-1 | Cuentas de cliente funcionales (rol ya existe) | F | Funcional | Should | M | — |
| M8-2 | Encuesta de satisfacción post-evento | F | Funcional | Could | M | M8-1 |

### M9 — Transversal / plataforma

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M9-1 | Avisar antes de expirar la sesión | U | No funcional | Should | S | — |
| M9-2 | Sync bidireccional local/nube | R | No funcional | Could | XL | M1-10 |
| M9-3 | Permisos granulares por usuario | S | No funcional | Could | L | — |

### M10 — Legal

| ID | Requerimiento | FURPS+ | Tipo | Prioridad | Complej. | Depende de |
|---|---|---|---|---|---|---|
| M10-1 | Módulo de huella dactilar | + (legal) | No funcional (constraint) | Won't hasta resolver legalidad | — | Concepto jurídico (Ley 1581) |

*(No se listan aquí M4-5 y M9-4: ya están implementados — ver `REQUERIMIENTOS_ROADMAP.md` §3-4.)*
