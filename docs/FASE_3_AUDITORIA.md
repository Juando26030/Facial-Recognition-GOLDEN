# Fase 3: auditoría de borrar / archivar / permisos

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
