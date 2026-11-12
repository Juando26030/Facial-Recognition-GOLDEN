# CRM · Etapa C1c + C2 + C3 + C4 — diseño (Paso 0, 12-nov-2026)

Un solo documento corto con todo lo que las cuatro piezas comparten: tablas, relaciones, migraciones, números reservados, reparto de archivos y decisiones por defecto. Si algo no cuadra con el código, manda el código; si cambia algo de aquí, se cambia aquí en la misma pieza.

**Rama:** `crm/c1c-c4` (desde `9b50cdc`, la última de C1b). **Producción:** `CRM_ENABLED=0`; nada a `main`, ningún merge, despliegue ni migración en producción sin autorización de Juan David para esa acción.

## 1. Orden de trabajo

| Lote | Piezas (en paralelo) | Migración | Qué entrega |
|---|---|---|---|
| Paso 0 (integrador) | modelos y migraciones 0131–0132, componentes Kanban, ganchos del arnés visual, este documento | 0131, 0132 | base compartida ya verificada con PostgreSQL real |
| 1 | **C2** embudos, oportunidades, leads, actividades, Kanban · **C1c-1** importador (cuentas, contactos, emparejamiento) | usa 0131 / 0132 | `STAGING_C2.md`, `STAGING_C1C.md` |
| 2 | **C3** productos, cotizaciones, proformas PDF, búsqueda global, filtros guardados, CSV · **C4** ganada → cliente + evento, «Mi día», tableros · **C1c-2** el importador carga también oportunidades, actividades, productos, cotizaciones y proformas | 0133 (C3), 0134 (reservada, solo si C4 la necesita) | `STAGING_C3.md`, `STAGING_C4.md` |

Cada pieza: su commit + push, `ruff` limpio, pruebas de texto (corren aquí), pruebas con base de datos escritas y marcadas «sin ejecutar» hasta que Juan David las corra, y su `docs/crm/STAGING_<pieza>.md` con criterios de éxito.

## 2. Reglas que no cambian (resumen operativo)
- **Ahorro (Neon):** cero sondeos, temporizadores, websockets; una consulta agregada por pantalla; paginación (50, «ver más»); sin N+1; mover una tarjeta = un UPDATE; recordatorios se calculan al abrir «Mi día». Cada pantalla anota sus consultas en `docs/crm/CONSULTAS_POR_PANTALLA.md`. La búsqueda global se dispara al pulsar Enter/«Buscar», no al teclear.
- **Ley 1581:** todo dato personal nuevo se suprime con el criterio de los contactos (adelanto, aviso, sin rastro). Texto libre = nunca en el historial (`history.FREE_TEXT`) y se cuenta en `review`. Nada de datos personales en logs, informes del importador ni filtros guardados.
- **Archivos:** solo `get_storage()` con prefijo `crm/`. **Trabajo pesado:** por la cola (`app/jobs.py`, el manejador procesa por tandas y se vuelve a encolar; idempotente) o Cloud Run Job; nunca un hilo.
- `def` (no `async def`), UTC, mensajes en español, identificadores en inglés, respuestas como dicts planos, `autoflush=False` (flush antes de filas dependientes), nada de `SET` de sesión/advisory locks. Visual: solo `--gw-*` y `.gw-*`; claro y oscuro; 1000/1100/1280/1500 y 390 px con `scripts/visual_harness`. Impresión inamovible: no se toca.

## 3. Tablas nuevas (todas `crm_*`, esquema `public`)

```
crm_pipelines 1──* crm_stages 1──* crm_opportunities *──1 crm_accounts 1──* crm_contacts
                                        │  └── primary_contact_id ──► crm_contacts (SET NULL)
                                        │  └── event_id ───────────► events        (SET NULL, único)
                                        └──* crm_activities *── (account | contact | lead | opportunity)
crm_leads ──(convertido)──► crm_accounts / crm_contacts / crm_opportunities (ids, SET NULL)
crm_import_runs 1──* crm_import_pairs ──► tenants
C3: crm_products · crm_terms · crm_doc_templates · crm_quotes 1──* crm_quote_lines · crm_proformas · crm_saved_filters
```

### 0131 `crm_pipeline_leads` (C2) — HECHA y verificada con PostgreSQL real
| Tabla | Para qué | Notas |
|---|---|---|
| `crm_pipelines` | embudos | sembrado «Eventos» (predeterminado) |
| `crm_stages` | etapas por embudo | `kind` open/won/lost, `probability` 0–100; sembradas 7 (Prospecto 10, Calificado 25, Propuesta de valor 50, Cotización enviada 65, Negociación 80, Ganada 100, Perdida 0) |
| `crm_leads` | clientes potenciales | datos personales; `status` nuevo/contactado/calificado/convertido/descartado; `converted_*_id` |
| `crm_opportunities` | oportunidad = posible evento | `code` único (contador `event`); `outcome` open/won/lost; `next_activity_at` copia para la alerta; `event_id` único |
| `crm_activities` | llamada/tarea/reunión/nota | cuelga de cuenta, contacto, lead u oportunidad; `result` lista cerrada; `contact_id`/`lead_id` CASCADE |

### 0132 `crm_import_runs` (C1c) — HECHA y verificada
`crm_import_runs` (corrida: modo sample/dry_run/apply, estado, conteos, cursor, informe) y `crm_import_pairs` (informe de emparejamiento: cliente de la plataforma ↔ cuenta de SuiteCRM; `bucket` seguro/dudoso/sin_pareja; `decision`). Solo conteos, números de fila y nombres de EMPRESAS.

### 0133 `crm_quotes` (C3) — por escribir al empezar el lote 2
- `crm_products`: sku, name, description, category, cost, price, currency, tax_percent (19 por defecto), active, legacy_sugar_id.
- `crm_terms`: condiciones comerciales elegibles (contado, 50-50, 30-70, N días…): name, body, position, archived_at.
- `crm_doc_templates`: plantilla de cotización/proforma: kind, name, header_text, greeting_text, footer_text, logo_key (almacenamiento `crm/templates/`), is_default.
- `crm_quotes`: number (contador nuevo `quote`), version, parent_quote_id, account_id, contact_id (SET NULL), opportunity_id (SET NULL), title, stage (borrador/enviada/negociada/aprobada/rechazada/vencida), approval_status, invoice_status, currency, valid_until, event_start, terms_id/terms_text, meeting_notes (texto libre), template_id, subtotal/discount_total/tax_total/total, pdf_key/pdf_generated_at/sent_at, owner_staff_id, legacy_sugar_id, archived_at.
- `crm_quote_lines`: quote_id (CASCADE), position, product_id (SET NULL), name, description (editable por línea), qty, unit_price, discount_percent, tax_percent, line_total.
- `crm_proformas`: number (contador nuevo `proforma`), quote_id, account_id, issued_at, due_at, status (no_pagado/pagado/anulado), event_name/city, total, pdf_key, legacy_sugar_id.
- `crm_saved_filters`: owner_staff_id (CASCADE), scope (cuentas/oportunidades/leads/cotizaciones), name, filters_json (**solo filtros estructurados; el texto de búsqueda libre NO se guarda**: podría ser el nombre de una persona), shared.
- `crm_counters`: dos filas nuevas `quote` y `proforma` (nacen NO listas; `COUNTERS` y `_TAKEN` en `app/crm/codes.py` se amplían; el importador sube los pisos con `bump_floor`).

### 0134 `crm_c4_extras` — RESERVADA
Solo si C4 descubre que necesita un índice o una columna (p. ej. para «Mi día»). Si no hace falta, el número queda sin usar y se anota aquí. **C4 (12-nov-2026): no hizo falta; la 0134 queda SIN USAR.** La numeración es lineal: 0131 → 0132 → 0133 → 0134; cada una con `down_revision` de la anterior, id ≤ 32 caracteres, escrita a mano, con reversa.

**Cómo se prueba cada migración:** `docs/crm/verificacion_sql/correr_etapa.sh` convierte el archivo REAL de la migración a SQL (`alembic_a_sql.py`, sin SQLAlchemy), lo sube a un PostgreSQL temporal, corre `06_pruebas_etapa.sql` (cascadas, únicos parciales, RESTRICT, siembra), baja todo en orden inverso, comprueba que no queda ninguna tabla nueva y vuelve a subir. Correr así: `runuser -u pgtest -- bash docs/crm/verificacion_sql/correr_etapa.sh`. Además hay pruebas de texto de cada migración (ids ≤ 32, `down_revision`, reversa que borra todo) y la prueba con base de datos `alembic upgrade/downgrade` (sin ejecutar).

## 4. Regla de códigos de oportunidad y evento (DECISIÓN abierta — valor por defecto)
- **Se asigna al CREAR la oportunidad**, con `next_code(db, "event")`: así es en SuiteCRM («Código Proyecto» existe desde que nace la oportunidad). Una oportunidad perdida deja su número usado (sin reutilizar).
- **Al ganarla** nace el evento con `event_code = str(opportunity.code)` (mismo número). Si ya existiera un evento con ese código (caso raro: el contador se fijó mal), responde 409 con mensaje claro y no crea nada; `next_code` ya salta los ocupados al asignar.
- Los eventos viejos conservan su código; los nuevos creados a mano desde Eventos siguen pidiéndolo (no se toca ese flujo).
- El contador `event` debe fijarse **por encima** de todo código importado y de todo código de evento solo numérico (`scripts/crm_set_counter.py --name event --floor N --apply`). El orden de encendido de `docs/crm/CODIGOS.md` aplica también a él; el staging usa un piso de prueba (`800000`), nunca en producción.
- Formato: numérico simple. Si Juan David quiere prefijo o año, cambia en un solo sitio (`app/crm/opportunities.py::event_code_for`).

## 5. API y pantallas reservadas (para no pisarse)
| Pieza | Router (nuevo, propio) | Páginas | JS / CSS propios |
|---|---|---|---|
| C2 | `app/routers/crm_pipeline.py` → `/api/crm/pipelines`, `/stages`, `/opportunities`, `/leads`, `/activities` | `/crm/oportunidades` (Kanban + lista), `/crm/oportunidades/{id}`, `/crm/leads`, `/crm/leads/{id}`, `/crm/embudos` (admin) | `crm_kanban.js`, `crm_oportunidad.js`, `crm_leads.js`, `crm_embudos.js`, `p-crm-c2.css` |
| C1c | `app/routers/crm_import.py` → `/api/crm/import/*` | `/crm/importar` (admin, super_admin) | `crm_importar.js`, `p-crm-c1c.css` |
| C3 | `app/routers/crm_quotes.py`, `crm_tools.py` → `/api/crm/products`, `/quotes`, `/proformas`, `/terms`, `/search`, `/filters`, `/export`, `/import-csv` | `/crm/cotizaciones`, `/crm/cotizaciones/{id}`, `/crm/productos`, `/crm/buscar` | `crm_cotizaciones.js`, `crm_buscar.js`, `p-crm-c3.css` |
| C4 | `app/routers/crm_today.py` → `/api/crm/today`, `/dashboards`, `/opportunities/{id}/win` | `/crm/mi-dia`, `/crm/tableros` | `crm_midia.js`, `crm_tableros.js`, `p-crm-c4.css` |

Todos los routers repiten la puerta de C1b: `dependencies=[Depends(crm_router._require_crm_enabled)]` (404 con CRM apagado), `view_staff = require_platform_role("comercial")`, `admin_staff = require_platform_role("admin")`, `_run(db, fn)` para commit y errores en español (400 por textos largos, 409 por edición concurrente con `updated_at`). Cada campo de texto con tope valida con 400 en español (patrón de `tests/test_crm_limites.py`).

Navegación interna del CRM: `templates/_crm_nav.html` (barra de secciones; el integrador activa cada sección cuando su pieza se fusiona). Rutas de página y enlaces del menú: solo las agrega el integrador en `app/main.py`.

## 6. Ley 1581 — qué cubre la supresión en esta etapa
La supresión de un contacto (`app/crm/erase.py`) se amplía (la hace el integrador al fusionar cada pieza, con el criterio ya probado en C1b):
| Dato | Qué pasa al suprimir al contacto |
|---|---|
| actividades con `contact_id` | se borran (CASCADE) y se cuentan en el adelanto |
| oportunidades con `primary_contact_id` | se desvincula (SET NULL); su `description`/`next_step`/actividades de texto libre se cuentan en `review` |
| leads que coinciden con su correo/teléfono/nombre | se borran con sus actividades e historial (`erase_lead`); se cuentan |
| cotizaciones dirigidas a él | `contact_id` pasa a NULL; los PDF guardados (`pdf_key`) se borran del almacenamiento y la cotización queda regenerable sin su nombre; notas de reunión se cuentan en `review` |
| `crm_change_log` de lead/oportunidad/cotización | filas con sus valores se borran (los campos de texto libre ya no guardan valor) |
| importador | los archivos subidos se borran al terminar la corrida; informes sin datos personales |
Un lead se puede suprimir por sí solo (admin, super_admin) con la misma ventana de adelanto.

## 7. Reparto de archivos
**Solo el integrador (yo) toca:** `app/models.py`, `app/main.py`, `templates/_sidebar.html`, `templates/_crm_nav.html`, `static/css/design-system.css`, `docs/ux/guia_visual.html`, `docs/ux/ESTANDARES_VISUALES.md`, `docs/15_MIGRACION.md`, `app/crm/__init__.py`, `app/crm/history.py`, `app/crm/codes.py`, `app/crm/erase.py`, `app/jobs.py`, `deploy/gcp/*`, `ruff.toml`, `tests/crm_helpers.py`, `tests/conftest.py`, `scripts/visual_harness/{pages,mocks,server,shoot}.py`. Si una pieza necesita un cambio ahí, lo pide en su nota de entrega (`docs/crm/entregas/<pieza>.md`: qué cambio, por qué, el texto exacto).

**Cada pieza crea solo archivos nuevos propios** (tabla de la sección 5, más `app/crm/<módulo>.py`, `tests/test_crm_<pieza>*.py`, `docs/crm/STAGING_<pieza>.md`, `scripts/visual_harness/pages_<pieza>.py` y `mocks_<pieza>.py`). Cada pieza trabaja en su propio árbol de trabajo (`git worktree`) y su propia rama (`crm/c2`, `crm/c1c`, `crm/c3`, `crm/c4`); el integrador las fusiona en `crm/c1c-c4` y vuelve a correr todo.

## 8. Decisiones abiertas y su valor por defecto
| Decisión | Valor por defecto (marcado `DECISIÓN` en el código/pantalla) |
|---|---|
| Estado «masivo» de una cuenta | se conserva como está (`ACCOUNT_STATUSES`); sin lógica especial hasta saber qué significa |
| Listas cerradas (plazo de pago, tipos, toma de contacto, resultado de actividad) | tipos y fuentes como texto con sugerencias de lo ya usado; resultado de actividad con lista corta propia (`activities.RESULTS`) |
| Etapas del embudo | las 7 de fábrica (editables en `/crm/embudos` sin migración) |
| Plantillas PDF de cotización y proforma | plantilla sencilla con encabezado, saludo, tabla de líneas, totales, condiciones y pie (texto editable en `crm_doc_templates`); sin logo hasta que Juan David lo entregue |
| Word (.docx) además de PDF | **no se construye en esta etapa** (no hay librería; se evalúa con Juan David); el PDF se genera sin dependencias nuevas (`app/crm/pdfdoc.py`, solo biblioteca estándar) |
| Texto de «Suprimir sus datos» | el actual de C1b |
| Código de evento automático | sección 4 |
| Importador real | `CRM_IMPORT_APPLY` = 1 solo en staging; 0 en producción hasta que Juan David diga y se envíe el aviso a la auditora |

## 9. Medición
Cada pantalla nueva anota en `docs/crm/CONSULTAS_POR_PANTALLA.md` cuántas consultas hace y cómo se midió (contador de sentencias de SQLAlchemy en una prueba con base de datos, «sin ejecutar» hasta que se corra). Objetivo: Kanban = una consulta de totales por columna + una de tarjetas por columna visible acotada (50); «Mi día» = tres consultas; búsqueda global = una por tipo, solo al enviar.
