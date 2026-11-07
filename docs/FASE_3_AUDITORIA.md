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

## Siguientes oleadas
usuarios del personal, eventos (botón archivar + restaurar), personas, formularios, áreas, inventario, premios; L7 automático; cierre de seguridad (Strix + ZAP en staging, CSP, ENFORCE_STAFF_TENANT).
