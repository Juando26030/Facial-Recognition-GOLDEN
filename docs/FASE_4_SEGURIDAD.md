# Fase 4 — Ronda de seguridad (8-nov-2026)

Cinco revisores independientes (solo lectura) atacaron la rama `f4/integracion`: (1) borrado y archivo de cuentas, (2) credenciales y correo, (3) autorizar ingresos / «Autorizar a todos», (4) roles y permisos, (5) compromiso digital y formularios públicos. Cada hallazgo se verificó contra el código antes de corregirlo.

## Corregido en esta ronda
| Hallazgo | Corrección |
|---|---|
| Cuentas con rol **admin sumado** no se protegían como admin (se miraba solo el rol principal) | `_rank` y `_assert_can_manage` usan los roles efectivos; solo el Super Admin administra esas cuentas (correo, perfil, clave, desactivar, borrar, roles). |
| Cambiar/sumar/quitar roles dejaba la sesión abierta con permisos viejos | Se cierran las sesiones de la cuenta al cambiar roles. |
| Nombre de usuario comparado sin distinguir mayúsculas | Comparación `lower()` al editar el perfil. |
| «Autorizar a todos» podía aprobar peticiones que el coordinador no vio | El cuerpo exige la lista exacta de peticiones vistas (`reqs`); lo demás queda pendiente. |
| Importar por Excel reactivaba digitadores inactivos | Solo admin o superior puede reactivarlos. |
| Validadores de correo y de color demasiado permisivos | `_EMAIL` y `_HEX` ajustados. |
| El token del Camino B/C llevaba la cédula | Ya no. |
| Guard de «base archivada» sin las rutas nuevas | Rutas nuevas en la lista permitida y revisadas. |
| `/lookup` y `/check` del compromiso confirmaban si una cédula estaba en la base o ya inscrita | Responden siempre «no encontrada / no inscrita» en formularios de compromiso. |
| El permiso de «firmar de nuevo» no vencía y permitía liberar la cédula de una firma legítima | Vence a las 48 h (`pledge.RESIGN_WINDOW`). |

## Aceptado o diferido (con motivo)
- **Camino A (enlace público) firma en nombre de la cédula tecleada y crea la cuenta**: es el diseño aprobado (el enlace es el secreto, 144 bits, y el coordinador autoriza el ingreso antes de cualquier acceso). Mitigación futura: precarga de cédulas por el coordinador. Decisión de producto, no se cambia sin Juan David.
- **Spam de cuentas y límites en memoria por proceso**: tope por enlace (600/h) y por IP; un límite en base queda para la fase de seguridad.
- **`health_flags` en claro y `/pledge/state` sin auditoría**: guarda solo *cuáles* preguntas fueron «Sí», se purga a los 30 días; pendiente de la auditora (ver CIERRE_FASE_4 §5).
- **Skip descarta `audit_actions`**; **firma PNG opaca válida**; **supresión por titular y `person_id=NULL`**; **event_transfer y `sensitive_json`**: bajos o sin verificar; quedan para la fase de seguridad.
- `ENFORCE_STAFF_TENANT` / `ENFORCE_STAFF_EVENT_SCOPE` apagados (riesgo preexistente, decisión previa).

## Limpio
Token `pc` (firmado, 6 h, atado a la sesión), path traversal, XSS del documento firmado, carrera `release_stale`/cupo, acceso a salud (cifrada y auditada), cuentas privilegiadas o de otro tenant.

## Pendiente de verificar
La suite completa con base de datos sobre el SHA final (la corre Juan David en Cloud Shell).
