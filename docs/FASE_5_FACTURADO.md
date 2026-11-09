# Fase 5 (A) — «Facturado», base de datos final y aviso a la comercial

Decisiones del dueño: [`FASE_5_DECISIONES.md`](FASE_5_DECISIONES.md). Migración: `0105_event_billed` (baja a `0104_pledge_health_flags`).

## Estado «Facturado»
- Es un estado configurable más (`event_states`), sembrado por la migración: nombre «Facturado», estado base **`finalizado`** (todo lo que compara `events.status == 'finalizado'` —retención biométrica `app/privacy.py`, `finalized_at`, conteos, reportes, archivar— sigue funcionando igual), color `#6f42c1`, posición = la última, y la regla nueva **`client_delivery`** encendida (`app/event_rules.py`; apagada en los demás estados). Esa regla declara «habilita la entrega al cliente»; el módulo de entrega (enlace + encuesta) la consultará con `event_rules.allowed(event, "client_delivery")`.
- **Quién lo pone:** solo una comercial (también quien tiene doble rol coordinador+comercial, por `effective_roles`) o admin/super_admin. Se hace cumplir en `PATCH /api/events/{id}` (403 «Solo una comercial o un administrador…»). El coordinador puede pasar a los demás estados como siempre. Lo mismo vale para **sacar** el evento de Facturado.
- «Estado de facturación» = el que tenga la regla `client_delivery` (`event_rules.is_billing_state`), no el nombre: renombrarlo no rompe nada.
- **Quién y cuándo:** `events.billed_at` y `events.billed_by_id` (FK `staff_users` ON DELETE SET NULL); además `audit_actions` `billed` / `unbilled` (entidad `event`). Al salir de Facturado se limpian `billed_*` y el historial queda en la auditoría. La edición del evento muestra «Facturado por X el <fecha y hora local>».
- Solo un evento **Finalizado** pasa a Facturado (400 si no).
- `default_state()` nunca elige un estado de facturación: cambiar solo `status` a `finalizado` no factura a nadie.
- `GET /api/event-states` ahora devuelve `billing` por estado y `can_set_billed` para quien consulta.

## Base de datos final
- Bloque propio en «Editar evento» (no es un campo de la plantilla: es una acción aparte con permisos y aviso, como el informe final, y no hay tipo de campo «archivo» en el motor).
- `POST /api/events/{id}/final-database` (coordinador o más; archivo `file` o `upload_token` de subida directa, propósito `final_database`, xlsx/csv, 50 MB) y `GET` para descargar. Se valida el contenido real (xlsx = zip con partes de hoja de cálculo; csv sin bytes nulos ni firmas de otros formatos).
- Clave en el almacenamiento: `<cliente>/final_database/<evento>/base_final.<ext>` (reemplaza; borra la anterior si cambió el formato). Columnas `events.final_db_key/name/uploaded_at/uploaded_by_id`. Auditoría `final_db_upload` / `final_db_replace` (sin el nombre del archivo).
- Respeta la base archivada (L7: 403) y el evento archivado (400). No viaja en el paquete de exportar/importar evento (se vuelve a subir).
- **Aviso:** al subir o reemplazar se encola `final_db_notice` (cola general; módulo `app/final_db.py`) a la comercial (`events.commercial_staff_id`): «Ya se subió la base de datos final del evento X. Revisa si ya se puede facturar el evento.», con enlace `/eventos?editar=<id>` (la página abre la edición de ese evento). Sin comercial o sin correo válido no se encola ni falla; el trabajo solo guarda el id del evento.

## Decisiones ante ambigüedad
- Estado de facturación identificado por la regla y no por el nombre; posición = última (después de Finalizado y de cualquier estado propio).
- Los selectores de estado de las tarjetas siguen siendo por estado base; «Facturado» se elige en «Editar evento» (el selector ahora lista los estados configurables activos).
- Un coordinador que no es comercial no puede sacar un evento de Facturado (consistente con no poder ponerlo).
- El borrado definitivo de un evento no limpia sus archivos (igual que el informe final hoy).
