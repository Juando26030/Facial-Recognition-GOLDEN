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

## Registro de acciones
Tabla `audit_actions` (migración `0088_archive_and_audit`, solo INSERT): quién (id y rol), qué, entidad, id y nombre. Nunca valores personales (en ediciones solo los nombres de los campos).

## Siguientes oleadas
usuarios del personal, eventos (botón archivar + restaurar), personas, formularios, áreas, inventario, premios; L7 automático; cierre de seguridad (Strix + ZAP en staging, CSP, ENFORCE_STAFF_TENANT).
