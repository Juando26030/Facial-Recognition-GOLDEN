# Fase 5 (E): historial de cambios del evento por campo y correo de campos clave

Decisión del dueño (8-nov-2026): **campo clave = campo marcado OBLIGATORIO en la plantilla de evento** (`app/event_template.py`). Todo cambio queda en el historial; solo los de campos clave avisan por correo.

## Piezas
| Qué | Dónde |
|---|---|
| Tabla `event_change_log` (id, event_id FK CASCADE, field_key, field_label, old_value, new_value, changed_by_id FK SET NULL, changed_at UTC, source) | `app/models.py` (`EventChangeLog`), migración `alembic/versions/0108_event_change_log.py` (`down_revision = 0104_pledge_health_flags`; el integrador la encadena) |
| `snapshot(db, event)`, `diff_event(before, after, template)` (PURA), `record(...)`, `recipients(...)`, `render_mail(...)`, manejador `event_change_mail`, `history(...)` | `app/event_history.py` |
| Lectura: `GET /api/events/{id}/change-history?field=&page=&per_page=` | `app/routers/event_history.py` (registrado en `app/main.py`) |
| Panel «Historial de cambios» en Editar evento | `templates/_event_edit_modal.html` + `static/js/event-history-panel.js` |
| Pruebas | `tests/test_historial_evento.py` (+ entrada en `ALLOW` de `tests/test_base_archivada_guard.py`) |

## Puntos de guardado conectados (`before = snapshot` → cambiar → `record` → `commit` → `kick_after`)
* `PATCH /events/{id}` (`events.py: update_event`): campos, asignaciones, estado, pañoleta, superevento y campos personalizados. Las filas del estado salen con `source='state'`.
* `revert-to-created` (`source='state'`).
* Interruptores: Parámetros (rostro, certificados, escarapela digital), impresión compartida, áreas/inventario, paso guiado de biometría y `consent-config` (`source='switch'`).
* Al borrar un evento (`delete_event`) se borra su historial (y la FK es `ON DELETE CASCADE`).
* NO conectado: la confirmación de una importación de evento (`event_transfer.confirm_import`, `source='import'` queda reservado) porque `tests/test_event_transfer.py` compara el conteo de todas las tablas.

## Reglas
* **Qué se compara:** columnas del evento, asignaciones (por nombre de la persona), estado (nombre del estado configurable, o el estado base si no hay), pañoleta, interruptores (`sw_*`) y valores de `extra`. Vacíos equivalentes (`None`, `''`, espacios, `[]`, `{}`); `9:00` = `09:00`; fechas se guardan como `dd/mm/aaaa`; booleanos como Sí/No; valores a lo sumo 300 caracteres.
* **Privacidad:** solo campos DEL EVENTO; nunca asistentes. Los campos de tipo `contacto` se guardan como `[oculto]`. El trabajo en cola lleva solo ids; sin datos personales en logs.
* **Correo:** un guardado = un trabajo `event_change_mail` por destinatario (`dedupe_key = event_change_mail:<primera fila>:<destinatario>`), con todos los campos clave cambiados en ese guardado. Destinatarios: comercial y coordinador del evento (los de DESPUÉS del cambio), sin quien lo hizo, sin repetir (la misma persona con doble rol recibe uno), activos, no archivados y con correo válido; sin correo se omite sin error. Asunto: `Cambio en el evento <nombre>: <campo>` (o `N campos`). Cuerpo: campo, anterior → nuevo, quién, cuándo (hora de Colombia) y enlace `PUBLIC_BASE_URL/kiosk/<id>`.
* **Permisos de lectura:** `require_role("coordinador")` + `get_event_for_staff` (coordinador/comercial del evento, admin, super_admin; digitador y cliente reciben 403).

## Pendiente / a verificar con base de datos
* Correr `pytest tests/test_historial_evento.py tests/test_base_archivada_guard.py tests/test_trabajos_huerfanos.py tests/test_seguridad_cierre_permisos.py` y `alembic upgrade head` (no se pudo aquí: sin Postgres).
* Cambios hechos fuera de los puntos anteriores (p. ej. carga masiva, edición directa en base) no se registran.
