# Eventos en curso — lista de lanzamiento y reversa (pista `producto/eventos-flujo`)

Documento para Juan David. **Nada de esto se ha ejecutado en staging ni en producción.** Estado: pista EN ESPERA (1-nov-2026). Orden acordado: (a) sale formularios a producción → (b) rebase de esta rama sobre `migra/fase1-2` → (c) prueba en staging con autorización de Juan David, repitiendo la medición de lotes de 200 con latencia real → (d) lanzamiento propio; la migración `0077` solo con **autorización escrita de Juan David para ESA acción**.

## 1. Qué trae la pista (pedidos A y B)
- **A — «Solo agregar personas nuevas»** a un evento en curso: nunca toca a quien ya existe; inscribe a quien ya está en el cliente; sin fotos, sin campos ni categorías nuevas; lotes de 200 filas con commit; vista previa que no escribe; informe con conteos. La carga normal no cambia.
- **B — «Devolver a Creado»** (`POST /api/events/{id}/revert-to-created`, solo admin y super_admin): solo cambia el estado, no borra nada, deja rastro (quién, cuándo, motivo, conteos); el quiosco sin red sigue pudiendo sincronizar lo anterior al cambio durante 7 días.
- **Arreglo asociado:** `POST /api/register` ya no responde 500 si otra petición crea la misma cédula entre su consulta y su INSERT.

## 2. Commits de la pista (de más antiguo a más nuevo, sobre `origin/migra/fase1-2` = `cf4d6c1`)
| Commit | Pieza |
|---|---|
| `ed58a00` | A1 — la regla de la carga distingue «solo agregar» |
| `5a34ac8` | A2 — lógica de «solo agregar» (`app/roster_append.py`), lotes de 200 |
| `73ca9ca` | A3 — vista previa (`POST /api/bulk_roster/preview`) |
| `29cc8d5` | A5 — pantalla y mensajes de los dos flujos |
| `8050d1d` | A6 — pruebas de concurrencia/choque; **arreglo del `IntegrityError` de `/api/register`** (revertible solo: `git show 8050d1d -- app/routers/api.py \| git apply -R`) |
| `7af53e7` | B1 — migración `0077` + modelos |
| `73e85d1` | B2 — `revert-to-created`, historial, mensaje del PATCH |
| `aed8acf` | B3 — sincronización sin red tras el retroceso (+ pruebas de B) |
| `8314be0` | B4 — botón «Devolver a Creado» y ventana de confirmación |
| (siguiente) | Consentimientos marcados aparte en `GET /status-changes`, botón en pantallas angostas, este documento |

CI de GitHub: `8050d1d` y `8314be0` en verde (`CI (pruebas)`). Suite local completa: 1501 pruebas en verde.

## 3. La migración `0077_event_status_changes` (`alembic/versions/0077_event_status_changes.py`)
`down_revision = 0076_print_mode`. **Solo aditiva** (el código anterior la ignora):
1. **Tabla nueva `event_status_changes`**: `id` (PK), `at`, `event_id` (indexado, `ix_event_status_changes_event_id`), `tenant_id`, `staff_user_id`, `staff_username`, `from_status`, `to_status`, `reason` (≤500), `attendees_count`, `access_logs_count` (con `server_default 0`). Sin llaves foráneas y sin datos personales.
2. **Columna nueva `access_logs.doubtful_reason`** (`VARCHAR(24)`, nullable, sin valor por defecto; vacía). `ADD COLUMN` nullable sin default es solo de catálogo (instantáneo en Postgres), pero toma un bloqueo exclusivo muy breve sobre `access_logs`: correrla en un momento sin picos de registro.
No toca `audit_consent_logs` (solo INSERT). Los consentimientos que hay que revisar se marcan aparte en `system_events` (`consent_sin_hora_valida` / `consent_after_revert`, con el UUID de la entrada; sin datos personales).
Verificado en local: `upgrade head` → `downgrade 0076_print_mode` → `upgrade head` sin errores.

**Para el rol de la aplicación (`golden_app`) en Neon/VM:** la tabla nueva es de INSERT/SELECT; confirmar que `scripts/neon_app_role.py` (o los privilegios por defecto) le dan acceso, igual que a las tablas de migraciones anteriores (ver cómo se hizo con `0074`/`0075`).

## 4. Procedimiento de reversa (NO ejecutado)
Regla de oro: **primero el código, después —y solo si hace falta— la migración**. El ORM del código nuevo lee `access_logs.doubtful_reason`: bajar la migración con el código nuevo vivo daría error en toda consulta de ingresos.

1. **Preferido: revertir solo el código** (servicio anterior vía `deploy.sh`/revisión previa de Cloud Run). La migración puede quedarse: es aditiva y el código anterior la ignora. No requiere tocar la base.
2. Antes de cualquier reversa de código, mirar si hay eventos devueltos a «Creado» con quioscos sin red: con el código anterior volverían a recibir 403 al sincronizar. Si los hay, reabrirlos («Creado» → «En proceso», PATCH normal) o esperar a que sincronicen.
3. **Si de verdad hay que bajar la migración** (solo con autorización escrita de Juan David para ESA acción), con el código anterior ya desplegado y en una hora sin registro:
   1. Copia de lo que se perdería (solo conteos y marcas, sin datos personales): `\copy event_status_changes TO …` y `\copy (SELECT id, event_id, client_id, doubtful_reason FROM access_logs WHERE doubtful_reason IS NOT NULL) TO …`. Además, el respaldo diario/horario de siempre.
   2. Con la conexión directa del dueño (`DIRECT_DATABASE_URL`, nunca la del pooler de la app): `alembic downgrade 0076_print_mode` (Job de migraciones). Quita la columna `access_logs.doubtful_reason` y la tabla `event_status_changes`.
   3. Consecuencia: se pierde el historial de retrocesos y las marcas «dudosas» (por eso la copia). Los eventos que estén en «Creado» siguen en «Creado» (el estado es dato del evento, no de la migración).
4. Alternativa a bajar la migración: restaurar la rama de Neon a un momento anterior (ventana de historia de 1 día) — pierde TODO lo escrito después; solo para un desastre.
5. Verificación tras la reversa: `/health`, un ingreso de prueba en un evento de prueba, y `SELECT version_num FROM alembic_version` = `0076_print_mode`.

## 5. Lista de comprobación del lanzamiento (a ejecutar solo con autorización)
1. Rebase sobre `migra/fase1-2` (hoy solo se prevé conflicto de texto en `docs/historial.md`, ambos agregan al final; no hay otra migración `0077`: si la sesión de formularios agrega una, renumerar la mía).
2. Staging: CI en verde, correr `0077` en staging, probar «Solo agregar» (resumen, informe, reintento = 0 creadas), medir latencia de pasos de 200 filas y del quiosco durante la carga, probar «Devolver a Creado» y la sincronización de un quiosco sin red.
3. Producción: respaldo previo; `0077` en una hora sin picos; desplegar; probar con un evento de prueba. No hay variables nuevas obligatorias (`SYNC_AFTER_REVERT_DAYS` = 7 y `BULK_APPEND_ROWS` = 200 son opcionales).
