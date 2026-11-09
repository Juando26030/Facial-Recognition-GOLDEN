# Fase 4: «Autorizar a todos los pendientes»

Pantalla «Usuarios temporales» de cada evento: botón que autoriza de una vez a todos los digitadores de ESE evento que esperan en la fila de ingreso (S1, `app/login_control.py`). Solo autorizar; no existe «bloquear a todos».

- **Endpoint:** `POST /api/events/{id}/staff-users/approve-all` (`app/routers/login_approval.py`, junto a `login-request`). Permisos del botón individual: coordinador o superior, nunca la comercial pura; evento propio (`get_event_for_staff`) y «en proceso» (400 si no).
- **Misma lógica que el individual:** ambos usan `_approve_one` (UPDATE condicionado a la MISMA solicitud pendiente, con el mismo hash y sin vencer; `login_control.approve_if_pending`) y dejan `audit_actions` `approve`/`login_request` por persona (solo ids y evento).
- **Carreras:** filas con `FOR UPDATE` en orden de id + UPDATE condicionado. Idempotente: la segunda llamada devuelve 0. Lo ya autorizado, no permitido, vencido o reemplazado no se toca.
- **Cuerpo (9-nov): `{"reqs": {"<id>": "<req visto>"}}`; solo se autorizan las solicitudes cuyo código sigue vigente (ronda de seguridad de la Fase 4); sin la lista responde 400.**
- **Respuesta:** `{approved, skipped, skipped_reasons:{motivo:n}, truncated, message}`. Motivos: «solicitud vencida», «cuenta bloqueada», «ya cambió su solicitud» y los del gancho.
- **Gancho para reglas nuevas:** `login_control.can_approve(db, event, target) -> (bool, motivo)`. Hoy devuelve `(True, "")`. Lo consultan el botón individual (409 con el motivo) y la masiva (omite con el motivo). Ahí se engancha «compromiso pendiente».
- **Límites:** `APPROVE_ALL_MAX = 500` por llamada (`truncated` avisa si quedan más) y `APPROVE_ALL_PER_MINUTE = 6` por usuario (`rate_limit_events`, kind `approve_all`; 429).
- **Auditoría:** una fila `approve_all`/`event_login_requests` (evento, autorizados, omitidos, quién).
- **Guard de base archivada:** no toca personas, respuestas ni pagos, así que `approve_all_pending` está en `ALLOW` de `tests/test_base_archivada_guard.py` (y `tests/test_autorizar_todos.py` comprueba que el escáner la ve).
- **Frontend:** `#approveAllBtn` (oculto sin pendientes; contador en la etiqueta; `showConfirm` con la cantidad; resumen en `showToast`), lógica en `static/js/usuarios.js`, sin JS inline. Reutiliza `.gw-usr__listhead` (ancho completo en celular).
- **Pruebas:** `tests/test_autorizar_todos.py`.
