# Fase 5 — Jornada (campo informativo calculado)

Decisión del dueño (8-nov-2026): la **jornada** es un campo más de la plantilla de evento. El administrador decide si lo agrega a la plantilla y si sale en la tarjeta del calendario. Se calcula sola y no se edita a mano.

## Regla
Duración del día de trabajo = hora de fin − hora de inicio del evento (`event_time_start` / `event_time_end`). Las fechas no cuentan: un evento de varios días tiene la misma jornada cada día. Si el fin es menor que el inicio, el día cruza la medianoche (22:00 → 04:00 = 6 h).

| Horas (tope superior inclusivo) | Clave | Etiqueta |
|---|---|---|
| 0 < h ≤ 6 | `media` | Media jornada |
| 6 < h ≤ 9 | `intermedia` | Jornada intermedia (entre media y completa) |
| 9 < h ≤ 12 | `completa` | Jornada completa |
| h > 12 | `extendida` | Jornada extendida |

Así 6, 9 y 12 h exactas caen en el tramo de abajo. Sin alguna hora, hora inválida o inicio = fin (no se sabe si son 0 h o 24 h): no hay jornada y se muestra «—».

## Dónde está
- `app/workday.py`: `compute_workday(start, end)` pura (devuelve `key`, `label`, `hours` decimal, `hours_text`) y `serialize(event)`. Espejo en `static/js/workday.js`.
- `app/event_template.py`: campo base `workday`, tipo `workday` (no creable, nunca obligatorio, sin columna ni valor guardado). De fábrica no está en ninguna vista; las plantillas ya guardadas lo reciben sin colocar (`merge_missing_base`).
- `GET /api/events*` y `/api/events/calendar`: agregan `workday_key`, `workday_label`, `workday_hours` (calculados al vuelo; no hay migración ni columna). Los filtros por jornada, si se piden, pueden calcularse en memoria o con una columna derivada en una fase posterior.
- Diseñador (`event-template-designer.js`): aparece como campo «Calculado · solo lectura» sin casilla de obligatorio. Ponerlo en la vista de creación lo activa en «Nuevo evento» y «Editar evento»; ponerlo en una zona del calendario es la opción «mostrar en calendario».
- «Nuevo evento»: control de solo lectura que se recalcula al digitar las horas (`EventFields.bindWorkday`). «Editar evento»: campo de solo lectura (`#eeWorkday`) visible si la plantilla lo incluye en la vista de creación o en el calendario. Tarjeta del calendario: insignia `gw-badge--info` (`.cal-card__wd-b`).

## Pruebas
`tests/test_jornada.py` (bordes 6/9/12, cruce de medianoche, sin horas, barrido de todos los minutos, plantilla, API), `tests/js/workday_check.js` (espejo, renderizador, tarjeta, en vivo) y `tests/js/event_template_default.json` regenerado.

## Decisiones ante ambigüedad
- Inicio = fin → sin jornada («—»), no 0 h ni 24 h.
- Se calcula al vuelo en vez de persistir: no hay migración (la `0109_event_workday` quedó sin necesidad).
- «Agregar a la plantilla» = colocarlo en la vista de creación; «mostrar en calendario» = colocarlo en una zona de la tarjeta.
