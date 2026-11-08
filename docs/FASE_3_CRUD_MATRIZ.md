# Fase 3: matriz CRUD por entidad (7-nov-2026)

Una fila por cada tabla de `app/models.py` (61). Rol mínimo = el que declara la ruta (`require_role`; «sc» = «sin comercial»). **hecho** = existe y cumple el criterio de la Fase 3 (archivar y restaurar admin+, borrar definitivo solo super_admin y de lo archivado, todo en `audit_actions`); **hueco** = falta algo (se dice qué); **n/a** = no aplica a propósito (con el porqué).
Criterio: archivar = ocultar de listas y selectores y poder restaurar; nada se borra salvo super_admin sobre lo ya archivado. Lo de privacidad (`purge-data`, revocación, `audit_consent_logs`) es por derecho del titular y no se toca.

## Entidades de negocio

| Entidad (tabla) | Crear | Leer | Editar | Archivar | Restaurar | Borrar definitivo | Estado |
|---|---|---|---|---|---|---|---|
| Cliente (`tenants`) | comercial | coordinador | comercial | admin | admin | super_admin (archivado, sin eventos) | hecho |
| Personal (`staff_users`) | admin (coordinador/digitador temporal: coordinador) | coordinador | admin | admin | admin | super_admin (archivada, sin eventos) | hecho. Digitadores temporales: «Archivar los usuarios temporales» (antes borraba, ahora archiva) |
| Evento (`events`) | coordinador | coordinador | coordinador | admin (solo finalizados; el Job a los 90 días) | admin (super_admin los del Job) | super_admin (archivado) | hecho |
| Persona (`users`) | digitador | digitador | digitador | n/a (la persona es transversal) | n/a | coordinador+, vía la inscripción; se borra también la fila `User` si no queda en otro evento | hecho (vía inscripción). Excepción deliberada al criterio: las personas se borran, no se archivan |
| Inscripción de persona en un evento (`event_attendees`) | digitador | digitador | digitador | n/a (no se archiva; `archived_at` reservada sin uso) | n/a | coordinador+ (borra de verdad, con fila en `audit_actions`) | hecho. Lo que se archiva es la base del evento completa (L7) |
| Registro de acceso (`access_logs`) | digitador | digitador | n/a (inmutable) | n/a (es un registro) | n/a | deshacer 15 s: quien acreditó; «Revisar» (puerta): digitador; histórico de una persona (`DELETE /users/{id}/logs`): **solo super_admin** con confirmación (cédula) | hecho. Las tres rutas dejan `audit_actions` (sin cédula) |
| Cambios de la persona (`person_changes`) | automático | admin+ (historial) | n/a | n/a | n/a | solo con la persona (super_admin) | hecho (rastro propio) |
| Formulario web (`web_forms`) | coordinador | coordinador | coordinador | admin | admin | super_admin (archivado, sin inscripciones ni pagos) | hecho |
| Inscripción de formulario (`form_submissions`) | público | coordinador | coordinador | n/a (la cubre archivar el formulario) | n/a | admin (una); marcas «ya registrado» en bloque: coordinador, ahora con `audit_actions` | hecho |
| Código de descuento (`form_discount_codes`) | coordinador | coordinador | n/a | n/a | n/a | coordinador, solo si nunca se usó; ahora con `audit_actions` | hecho (configuración sin historial) |
| Pago (`form_payments`) / reembolso (`form_refunds`) | automático (Wompi) | coordinador | admin (reembolso) | n/a | n/a | n/a (registro financiero; solo se desvincula) | hecho a propósito |
| Eventos del formulario (`form_events`) | automático | coordinador | n/a | n/a | n/a | con el formulario | n/a (traza) |
| Acceso de cliente al formulario (`form_client_users`) | coordinador | coordinador | n/a | n/a | n/a | revocar: coordinador (desactiva la cuenta); ahora con `audit_actions` | hecho |
| Invitaciones (`form_invites`) / base del formulario (`form_persons`) | coordinador | coordinador | reemplazo | n/a | n/a | con el formulario / al reemplazar la base | n/a (datos operativos del formulario) |
| Plantilla de formulario (`saved_form_templates`) | coordinador | coordinador (admin: archivadas) | se sobrescribe por nombre | admin | admin | super_admin (archivada) | **hecho en 0094** (API; sin pantalla: ver pendientes) |
| Estado de evento (`event_states`) | admin | todos con sesión (admin: archivados) | admin | admin | admin | super_admin (archivado, sin eventos) | **hecho en 0094** (API; no existe pantalla en el proyecto) |
| Plantilla de escarapela del evento (`badge_templates`) | coordinador (sc) | coordinador (sc) | coordinador (sc) | n/a (una por evento y categoría) | n/a | con el evento | n/a |
| Plantilla de escarapela guardada (`saved_badge_templates`) | coordinador (sc) | coordinador (sc); archivadas: admin | n/a (copia) | admin | admin | super_admin (archivada) | hecho; **pantalla «Ver archivadas» en 0094** (Importar plantilla, en el editor) |
| Color de pañoleta guardado (`saved_colors`) | coordinador | coordinador; archivados: admin | coordinador (mismo nombre cambia el tono) | admin | admin | super_admin (archivado) | hecho; **pantalla «Ver archivados» en 0094** (junto al selector de color) |
| Zona (`event_areas`) / movimiento (`area_movements`) | coordinador (sc) / digitador (sc) | coordinador / digitador | coordinador (sc) | admin | admin | super_admin (zona archivada y sin movimientos) | hecho (movimiento: inmutable) |
| Ítem de inventario (`inventory_items`) / entrega (`inventory_deliveries`) | coordinador (sc) / digitador (sc) | idem | coordinador (sc) | admin | admin | super_admin (sin entregas) | hecho |
| Campo de evento (`event_field_configs`) | coordinador (sc) | coordinador (sc) | coordinador (sc) | borrar campo (escribe su nombre; queda en `person_changes`) | n/a | n/a | hecho (confirmación fuerte + rastro) |
| Plantilla del evento (`event_templates` / `event_template_revisions`) | admin | admin | admin (guarda revisión) | n/a (revisiones se podan solas) | n/a | n/a | n/a (global; las revisiones son la historia) |
| Super evento (`super_events`) | coordinador | coordinador (`include_archived`: coordinador+) | coordinador (solo el nombre; el cliente no cambia) | coordinador (decisión de Juan David 7-nov-2026: coordinadores y comerciales archivan) | coordinador | super_admin (archivado y sin eventos) | **hecho en 0095** (ventana «Administrar supereventos», junto al selector en «Editar evento» y «Nuevo evento») |
| Autorización de personal por evento (`event_staff_authorizations`) | coordinador | coordinador | n/a | n/a | n/a | revocar acceso: coordinador; ahora con `audit_actions` | hecho |
| Recordatorio del calendario (`calendar_notes`) | coordinador | coordinador (destinatarios) | n/a | n/a | n/a | el autor o admin+; ahora con `audit_actions` (sin el texto) | hecho (efímero a propósito) |
| Ruleta (`roulette_configs`) / sorteos (`roulette_draws`) | coordinador | coordinador | coordinador | n/a | n/a | los sorteos no se borran (auditoría de ganadores); solo se cancela la autorización de giro | hecho a propósito |
| Documentos del evento (`event_documents`) / gastos (`event_expenses`) | coordinador | coordinador | coordinador | **otro agente** | **otro agente** | **otro agente** | no tocado aquí (0093) |
| Carga masiva (`bulk_jobs`) | coordinador (sc) | coordinador (sc) | n/a | n/a | n/a | con el evento | n/a (traza técnica) |
| Cambios de estado del evento (`event_status_changes`) | automático | admin+ | n/a | n/a | n/a | con el evento | n/a (traza) |
| Enlaces de estadísticas (`stats_links`) | coordinador | coordinador | n/a | revocar (marca `revoked_at`) | n/a | n/a | hecho (ya es lógico) |

## Impresión, privacidad, sistema

| Entidad (tabla) | Crear | Leer | Editar | Archivar / restaurar | Borrar definitivo | Estado |
|---|---|---|---|---|---|---|
| Historial de impresión (`print_logs`) | digitador (sc) | coordinador | n/a | n/a | con la persona (super_admin) | n/a (traza) |
| Trabajos de impresión (`print_jobs`), equipos (`print_devices`), rutas (`print_routes`), puestos (`print_stations`) | automático / coordinador (sc) | coordinador (sc) | coordinador (sc) | n/a | quitar ruta o puesto: coordinador (configuración, sin datos personales) | n/a (configuración operativa) |
| Reimpresión (`reprint_requests`, `reprint_links`, `reprint_audit`) | digitador (sc) | coordinador | admin (decisión) | n/a | con la persona | n/a (traza) |
| Aceptación web (`web_acceptances`), consentimientos (`audit_consent_logs`), envíos de aceptación (`accept_mail_logs`) | persona / automático | admin+ | n/a (inmutables) | n/a | **no se tocan** (derecho del titular y retención legal; `app/privacy.py`) | n/a por diseño |
| Solicitudes de privacidad (`privacy_requests`, `privacy_request_counters`, `suppressed_persons`) | admin | admin | admin | n/a | `purge-data` por derecho del titular | n/a por diseño |
| Registro de acciones (`audit_actions`) | automático | admin+ (BD) | n/a | n/a | nunca (solo INSERT) | hecho |
| Sesiones auditadas (`session_audit`), límites (`rate_limit_events`), tokens de contraseña (`password_reset_tokens`), tareas (`jobs`), eventos del sistema (`system_events`) | automático | ops | n/a | n/a | poda técnica automática (vencidos) | n/a (limpieza técnica, fuera de alcance) |
| Ajustes (`app_settings`) | admin / super_admin | admin | admin / super_admin | n/a | n/a | n/a (valores únicos) |
| Traslado de eventos (`event_transfer_logs`, `event_import_actors`) | super_admin | super_admin | n/a | n/a | n/a | n/a (traza) |

## Cierre de huecos (rama `f3b/crud-huecos`, migración `0094_crud_gaps`)
1. **Colores y plantillas de escarapela archivados:** «Ver archivados» (admin+) en la librería de colores y en la ventana «Importar plantilla»; Restaurar (admin+) y «Eliminar definitivamente» (super_admin, con `showConfirm`).
2. **Estados de evento:** `POST /event-states/{id}/archive` y `/restore` (admin+); `DELETE` pasa a super_admin y solo de un estado archivado y sin eventos. Archivar sigue las reglas de desactivar (sin eventos en el estado y otro activo con el mismo estado base). `GET /event-states?include_archived=true` es de admin+.
3. **Histórico de accesos de una persona** (`DELETE /users/{id}/logs`): solo super_admin, exige `confirm` = identificación de la persona y ahora borra solo ESE evento (antes todo el cliente, bug conocido). `audit_actions` entidad `access_logs` (cuántos; nunca la cédula).
4. **Recordatorios del calendario:** ya eran del autor o admin+; ahora quedan en `audit_actions` (fecha y autor, no el texto).
5. **Otros borrados encontrados y corregidos:**
   - `POST /events/{id}/staff-users/purge-temporary` («Eliminar los usuarios temporales», coordinador+) borraba cuentas de digitador de verdad. Ahora las **archiva** (sin acceso, sin sesión, sin tocar impresiones ni cargas) y deja un registro; el botón dice «Archivar…».
   - Plantillas de formulario (`saved_form_templates`): coordinador+ las borraba. Ahora archivar/restaurar (admin+) y borrado definitivo super_admin.
   - Con `audit_actions` (sin cambiar permisos): deshacer acreditación (15 s), «Revisar» de la puerta (`door-face/revert`), borrar firma, revocar acceso de cliente de formulario, revocar acceso de personal al evento, borrar código de descuento y «Quitar todas las marcas».
   - Revisados y dejados igual: `delete_field` (ya pide escribir el nombre y deja `person_changes`), `roulette/authorize` (permiso efímero), rutas y puestos de impresión (configuración), `stats-links` (ya es una revocación lógica), `formsvc.discard_submission` (limpieza de inscripciones nunca confirmadas), `sessions`/`security`/`event_template_svc` (podas técnicas).

## Pendientes
- Pantalla de archivar/restaurar para **estados de evento** y **plantillas de formulario** (hoy solo API; el proyecto no tiene pantalla de estados y la de plantillas solo las ofrece al crear un formulario).
- **Super eventos:** resuelto en 0095 (ver `FASE_3_AUDITORIA.md`).
- Documentos y gastos: otro agente (0093). Alcance por cliente: otro agente.
- `usuarios.js` («Borrar permanente» de una cuenta, super_admin) debería ofrecer primero «Archivar» por cuenta si no lo hace ya (revisión de la oleada 2).
