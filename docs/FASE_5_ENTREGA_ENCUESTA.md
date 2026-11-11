# Fase 5 (B) — Entrega al cliente: encuesta de satisfacción y descarga de la base final

Estado: construido en la rama `f5/b-encuesta`; migración `0106_survey_delivery` (down_revision `0104_pledge_health_flags`: el integrador la encadena después de las de las otras ramas).
Decisiones de Juan David: `docs/FASE_5_DECISIONES.md`. Las preguntas son las de la hoja «Encuestra de Satisfacción GEYL» (se corrigió el «suministtadas» de la pregunta 6).

## Flujo
1. El evento pasa a **Facturado** (rama A: `events.billed_at/billed_by_id`, regla de estado `client_delivery`) y el coordinador sube la **base final** (`events.final_db_key/final_db_name`, `app/storage.py`).
2. En «Editar evento» (comercial, admin, super_admin) aparece el bloque **Entrega al cliente**: enlace con **Copiar**, **Regenerar enlace** y la casilla **Enviar al correo del cliente** (desmarcada) con el botón **Enviar** (deshabilitado hasta marcarla). Al abrir un evento Facturado sin enlace, el bloque lo crea.
3. El cliente abre `/entrega/<token>` (sin sesión): saludo, empresa, evento y fecha precargados (no editables), «para descargar su base de datos, primero diligencie esta encuesta».
4. Al enviar la encuesta la misma página muestra **Descargar base de datos** (`GET /entrega/<token>/base`, `Content-Disposition: attachment`, `no-store`).

## Qué se lee de la otra rama (sin crear columnas) — `app/delivery.py`
| Función | Lee | Regla |
|---|---|---|
| `is_billed(event)` | regla `client_delivery` si existe en `event_rules.RULES`; si no, `status == 'finalizado'` y `getattr(event, 'billed_at', None)` | además es falso si el evento o su base están archivados (`archived_at`, `data_archived_at`) |
| `final_db(event)` | `getattr(event, 'final_db_key')`, `final_db_name` | `None` si no hay base subida |

**Para el integrador:** si la rama A usa otros nombres, solo se cambian estas dos funciones. Las pruebas simulan ambas con `monkeypatch`.

## Seguridad del enlace
- Token = HMAC-SHA256(`SECRET_KEY`, `"delivery-link|" + nonce`) en base64url (43 caracteres). En `event_delivery_links` queda `nonce` y `token_hash` (SHA-256); el token **no** se guarda, se vuelve a derivar para que el personal pueda volver a verlo. Cambiar `SECRET_KEY` mata los enlaces (se regeneran desde el bloque).
- Sin vencimiento. **Revocable** y **regenerable** (regenerar revoca el anterior). Desconocido, revocado o evento ya no Facturado responden lo mismo (404, sin confirmar nada).
- Límites: por IP (`security.limit_ip`, ventana de 10 min: página 60, envíos 10, descargas 20) y **por enlace y hora** (`DELIVERY_DOWNLOADS_PER_HOUR`, 5, contado en `audit_actions`, sirve entre instancias).
- Servicio `publico`: prefijo `/entrega/` agregado a `appmode.PUBLIC_PREFIXES` (y a `idle.EXEMPT_PREFIXES`, `obs._PATH_TOKEN` para enmascarar el token en logs). Las rutas del personal (`/api/events/{id}/delivery...`) quedan en `web`.
- Cada descarga queda en `audit_actions` (`delivery_download`, entidad `delivery_link`, detalle «descarga N»): sin correos, nombres ni cédulas.

## Validaciones del servidor (en cada petición)
Evento sigue Facturado y no archivado · enlace no revocado · para descargar: encuesta enviada y base final existente (mensajes claros en español en cada caso) · límite de descargas.

## Correo (cola `app/jobs.py`, tipo `delivery_mail`, módulo `app.delivery`)
- Solo se encola con `POST /api/events/{id}/delivery/send-email` y cuerpo `{"confirm": true}` (la casilla). Un correo por enlace y hora.
- Destinatario: `Tenant.contact_email` de la cuenta del evento; si no tiene, la primera cuenta de tipo `cliente` activa autorizada al evento con correo válido. Sin ninguno: 409 «no tiene un correo de contacto registrado» (el bloque lo avisa «sin correo de contacto registrado» y deshabilita la casilla).
- La cola **no** lleva el correo ni el token (`event_id`, `link_id`, `base`): el manejador los resuelve al enviar y no manda nada si el enlace se revocó/regeneró o el evento dejó de estar Facturado.
- Texto: el evento finalizó, agradecimiento, encuesta breve (menos de 3 minutos), al completarla se descarga la base; sin contraseñas ni datos personales.
- Nota para el integrador: `jobs.GENERAL_KINDS` y `jobs.HANDLER_MODULES` llevan `"delivery_mail"` (si otra rama también los edita, conservar ambas entradas).

## La encuesta (`app/survey_def.py`, `SURVEY_VERSION = 1`)
Son **datos versionados**: para cambiar preguntas se edita la lista y se sube la versión; el `id` de pregunta es estable. Cada respuesta guarda la versión.

| id | Pregunta | Tipo | Puntaje |
|---|---|---|---|
| `q1_experience` | 1. Experiencia con el servicio de registro | rating (Malo/Bueno/Excelente) | 1/2/3 |
| `q2_staff` | 2. Presentación y atención del personal | rating (Mala/Buena/Excelente) | 1/2/3 |
| `q3_coordinator` | 3. Presentación y atención del Coordinador | rating (Mala/Buena/Excelente) | 1/2/3 |
| `q4_commercial` | 4. Atención y servicio del Comercial | rating (Mala/Buena/Excelente) | 1/2/3 |
| `q5_speed` | 5. Agilidad y tiempos de espera | rating (Malos/Buenos/Excelentes) | 1/2/3 |
| `q6_badges` | 6. Calidad de escarapelas (solo si las suministró Golden) | rating + «No aplica» | 1/2/3 o NULL |
| `q7_nps` | 7. ¿Qué tan probable es que recomiende…? | 0–10 | el número |
| `q8_next_event` | 8. ¿Próximo evento? 2% de descuento (opcional) | Sí/No opcional | NULL |

Todas con comentario opcional «¿Por qué? / Comentarios». Se guarda el texto que vio la persona (`choice_text`, con su forma gramatical) y el puntaje estable aparte. Sin nombre, cédula ni correo de quien responde.

## Modelo de datos para la analítica de gerencia (aparte de `form_submissions`, sin purga biométrica)
```
survey_responses  (una por evento: índice único uq_survey_responses_event)
  id, event_id → events, tenant_id, survey_version, submitted_at (UTC),
  nps_score (0-10), avg_score (promedio 1-3 de calidad, sin «No aplica»),
  delivery_link_id → event_delivery_links, comment_count, ip_hash (SHA-256 truncado de la IP; solo antiabuso)
survey_answers    (una fila por pregunta contestada)
  id, response_id → survey_responses (CASCADE), event_id, tenant_id, submitted_at, survey_version (repetidos a propósito: promediar sin joins),
  question_id, score (NULL si no aplica / sin puntaje), choice_text, comment
Índices: survey_responses(tenant_id, submitted_at), survey_answers(question_id, submitted_at), (event_id), (tenant_id, submitted_at), (response_id)
```
Decisión: **una respuesta por evento** (no por enlace): regenerar el enlace no obliga a repetirla ni permite duplicar el NPS. Reenviar se **bloquea** (409, «Ya recibimos…», conserva la primera) en vez de reemplazar, para que nadie altere una opinión ya entregada. Horas en UTC; para meses locales usar `AT TIME ZONE 'America/Bogota'`.

### Consultas de ejemplo
```sql
-- Promedio de satisfacción (1-3) por mes y por pregunta de calidad
SELECT date_trunc('month', submitted_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS mes, question_id,
       round(avg(score)::numeric, 2) AS promedio, count(score) AS n
FROM survey_answers WHERE question_id <> 'q7_nps' AND score IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;

-- Promedio general por evento (con su nombre) y NPS del evento
SELECT e.id, e.name, r.avg_score, r.nps_score, r.submitted_at
FROM survey_responses r JOIN events e ON e.id = r.event_id ORDER BY r.submitted_at DESC;

-- Promedio por cliente (tenant) y pregunta
SELECT t.name AS cliente, a.question_id, round(avg(a.score)::numeric, 2) AS promedio, count(a.score) AS n
FROM survey_answers a JOIN tenants t ON t.id = a.tenant_id
WHERE a.question_id <> 'q7_nps' AND a.score IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;

-- NPS por mes: %promotores (9-10) - %detractores (0-6)
SELECT date_trunc('month', submitted_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota') AS mes, count(nps_score) AS n,
       round(100.0 * (count(*) FILTER (WHERE nps_score >= 9) - count(*) FILTER (WHERE nps_score <= 6)) / NULLIF(count(nps_score), 0), 1) AS nps
FROM survey_responses GROUP BY 1 ORDER BY 1;

-- Comentarios de una pregunta (para leer lo que explica un puntaje bajo)
SELECT e.name, a.score, a.comment FROM survey_answers a JOIN events e ON e.id = a.event_id
WHERE a.question_id = 'q4_commercial' AND a.score = 1 AND a.comment IS NOT NULL;

-- Interesados en el 2% de descuento
SELECT t.name, e.name, a.comment FROM survey_answers a JOIN events e ON e.id = a.event_id JOIN tenants t ON t.id = a.tenant_id
WHERE a.question_id = 'q8_next_event' AND a.choice_text = 'Sí';
```
Al cambiar a la versión 2 de la encuesta, filtrar por `survey_version` o por `question_id` (los ids viejos no se reutilizan).

## Archivos
`app/survey_def.py`, `app/delivery.py`, `app/routers/delivery.py`, `templates/entrega.html`, `static/js/entrega.js`, `static/css/gw-entrega.css`, bloque en `templates/_event_edit_modal.html` (+ `static/css/gw-eventos.css`), modelos en `app/models.py`, `alembic/versions/0106_survey_delivery.py`, `tests/test_entrega_encuesta.py` (+ entrada en `ALLOW` de `tests/test_base_archivada_guard.py`).

## Pendiente / no verificado
No se corrió pytest ni la migración (sin base de datos aquí): verificado con `py_compile` y `ruff`. Falta probar en navegador el bloque del modal y la página pública en celular/tema oscuro. La rama A debe llamar (opcional) a `delivery.ensure_link(db, event, staff)` al marcar Facturado; si no, el modal crea el enlace al abrir el evento.

## Aviso «próximo evento» a la comercial (plan §12, revisión 9-nov-2026)
Si el cliente responde **«Sí»** a la pregunta 8 («¿Tienes próximamente un evento?… 2 % de descuento»), al guardar la encuesta se encola `next_event_mail` (cola general, módulo `app.delivery`) a la **comercial del evento** (`events.commercial_staff_id`), con el nombre del cliente, el evento, el comentario de la pregunta 8 (escapado) y el enlace a la edición del evento. Uno por evento (`dedupe_key`); la cola solo lleva el id del evento. Sin comercial activa con correo válido no se encola ni falla. Pruebas: `tests/test_entrega_encuesta.py::test_next_event_*`.
