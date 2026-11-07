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

## Oleada personas y formularios (migración `0091_people_forms_archive`)
Auditoría de borrados que existían: `DELETE /api/users/{id}` (coordinador+, borraba a la persona del evento y, si no estaba en otro, la fila `User` y su foto), `DELETE /api/events/{e}/forms/{f}` (coordinador+, borraba el formulario con inscripciones; solo frenaba con pagos aprobados/reembolsados) y `DELETE .../submissions/{id}` (coordinador+). Quedan sin tocar: `DELETE /api/attendees/{id}/purge-data`, la revocación y `app/privacy.py` (derecho del titular), y `audit_consent_logs` (inmutable).

| Acción | digitador | coordinador | comercial | admin | super_admin |
|---|---|---|---|---|---|
| Archivar / restaurar persona de un evento | - | - | - | sí | sí |
| Ver personas archivadas (`GET /users?archived=true`) | - | - | - | sí | sí |
| Borrar persona definitivo (`DELETE /users/{id}`) | - | - | - | - | sí (inscripción ya archivada) |
| Archivar / restaurar formulario | - | - | - | sí | sí |
| Ver formularios archivados (`?include_archived=true`) | - | - | - | sí | sí |
| Borrar formulario definitivo | - | - | - | - | sí (archivado y sin inscripciones ni pagos) |
| Borrar UNA inscripción de formulario | - | - | - | sí (antes coordinador) | sí |

- **Persona:** `event_attendees.archived_at/archived_by_id`. Archivar oculta a la persona del directorio de ESE evento (lista, total, incremental); no toca `users`, consentimientos, biometría ni registros de acceso. Quien solo tiene accesos (sin precarga) obtiene su inscripción al archivarla. Las estadísticas y la copia sin red no la excluyen (solo es ocultar del directorio).
- **Formulario:** `web_forms.archived_at/archived_by_id`. Archivar lo saca de la lista, lo cierra al público (404 como «finalizado»: ni página, ni estado, ni cotización, ni envíos), pasa «activo» a «cerrado» y apaga el calendario para que al restaurar NO se reabra solo, y no se puede editar ni cambiar su estado hasta restaurarlo. Se conservan inscripciones, archivos y pagos; el webhook de Wompi y la confirmación/estado de un pago ya iniciado siguen funcionando. El borrado definitivo exige archivado y cero inscripciones (las marcas «ya registrado» de la base no cuentan) y cero pagos. Borrar el evento completo sigue su camino de siempre.
- **Registro (`audit_actions`):** `attendee` (id de la inscripción y «evento N»; nunca cédula ni nombre), `form` (id y nombre del formulario) y `form_submission` (ids). Acciones `archive`, `restore`, `delete`.
- **UI:** directorio: «Archivar de este evento» (admin+, en «Más» y en «Editar») y chip «Ver archivados» con Restaurar (y «Eliminar definitivamente» para super_admin); formularios: «Archivar» en la tarjeta, casilla «Ver archivados» con Restaurar y, para super_admin, «Eliminar definitivamente».
- **Pendiente de decidir:** la ruta `DELETE /users/{id}/logs` (histórica, admin+, sin uso) no se tocó; las personas archivadas aún podrían acreditarse por cédula en la puerta (solo se ocultan del directorio).
