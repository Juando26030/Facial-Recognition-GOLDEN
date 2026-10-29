# 13 · Runbook de producción — paso del 28-oct-2026 (staging → producción)

Lo ejecuta **Juan David**; Claude no corre nada en la nube. **Producción queda como staging el 28-oct-2026**: el código de `79348da` (rama `migra/fase1-2`), probado por Juan en su Brother QL-800 (vertical y horizontal). Sin funciones nuevas ni arreglos extra. **Única diferencia de código/configuración frente a `79348da`:** `CONTINGENCY_ENABLED=1` en producción (orden explícita de Juan David, 28-oct-2026, 14:46).
Los parámetros de impresión son **inamovibles** ([`IMPRESION_PARAMETROS_INAMOVIBLES.md`](IMPRESION_PARAMETROS_INAMOVIBLES.md); los fija `tests/test_impresion_parametros_fijos.py`).

> **Nada de esto se ejecuta hasta que Juan David escriba exactamente «DESPLIEGA PRODUCCIÓN».** Armar el paquete (esta rama y este documento) no despliega nada.

## 0. Qué hay hoy en producción y qué cambia

| Pieza | Hoy | Después |
|---|---|---|
| `main` | `b225a2d` (PR #1 «corte/main»: producción en Cloud Run) | el candidato `candidato/produccion-28oct` (avance directo: `b225a2d` es su ancestro) |
| Código de los 3 servicios y los Jobs | el de `b225a2d` | el de `79348da` (el candidato solo agrega documentación y scripts) |
| Base de datos | `0068_door_liveness` | `0073_attendee_origin` (migraciones 0069–0073, solo aditivas) |
| `CONTINGENCY_ENABLED` | `0` | **`1`** (orden de Juan David del 28-oct-2026: el modo sin conexión va ENCENDIDO; `deploy/gcp/config.sh`, línea 27) |

**Comprobar el estado real de producción antes de tocar nada** (solo lectura, en Cloud Shell, proyecto `goldenweb-prod`, región `us-east4`):

```bash
bash deploy/produccion_28oct/anotar_estado_previo.sh
```
Anota la revisión de `golden-web`, `golden-publico` y `golden-biometria`, la imagen de los Jobs y la versión de Firebase Hosting, y escribe `vuelta_atras.sh` con esos valores. **Guarda una copia de `estado_previo_*.txt` fuera de Cloud Shell.** Comandos sueltos equivalentes:

```bash
P=goldenweb-prod; R=us-east4
for s in golden-web golden-publico golden-biometria; do
  echo "$s -> $(gcloud run services describe $s --project $P --region $R --format='value(status.traffic[0].revisionName)')  código: $(gcloud run services describe $s --project $P --region $R --format=json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((e.get("value","") for e in d["spec"]["template"]["spec"]["containers"][0].get("env",[]) if e["name"]=="APP_COMMIT"),"?")[:7])')"
done
for j in golden-bulk golden-ops golden-migrate; do echo "$j -> $(gcloud run jobs describe $j --project $P --region $R --format='value(spec.template.spec.template.spec.containers[0].image)')"; done
```
En el repositorio: `git ls-remote origin refs/heads/main` debe dar `b225a2d…`. La versión de la base se lee en la consola SQL de Neon: `SELECT version_num FROM alembic_version;` → `0068_door_liveness` (lo comprueba también `verificar_antes.sh`).

## 1. Antes de desplegar (en este orden)

1. **Verificación previa** (solo lectura): `bash deploy/produccion_28oct/verificar_antes.sh`. Todo en ✅ (o ⚠️ explicados). Si hay ❌, **no sigas**: mándale la tabla a Claude.
2. **Sin eventos en curso ni por abrir** en las próximas 3 h (el despliegue se congela solo: `/api/ops/deploy-allowed`).
3. **Respaldo: rama de Neon `antes-produccion-28oct`** (Neon → proyecto de producción → Branches → *Create branch* → «Current point in time» → nombre `antes-produccion-28oct`). Es el punto de restauración de la base. No la borres hasta pasada la primera semana.
4. **Ensayo de migraciones en una rama de Neon aparte** (opcional, recomendado; ver §3): crea la rama `ensayo-0073` desde producción, apunta una `DIRECT_DATABASE_URL` a ella y corre `alembic upgrade head` desde el Job o desde Cloud Shell con la imagen del candidato; luego borra la rama de ensayo.
5. **Fusionar el PR candidato → `main`** (§6). Fusionar NO despliega.

## 2. Despliegue (manual, con confirmación)

GitHub → Actions → **«Cloud Run (staging y producción)»** → *Run workflow* → rama **`main`** → en **confirm** escribe `DESPLEGAR` (en mayúsculas); `force` **sin marcar**.
El flujo corre las pruebas, construye la imagen y ejecuta `deploy/gcp/deploy.sh production`: **migraciones (Job) → 3 servicios → Jobs → Firebase Hosting**. Si la migración falla, se detiene antes de tocar los servicios.

Después: `bash deploy/produccion_28oct/verificar_despues.sh <hash de main>` (comprueba `/health`, que cada servicio corra ese código, rutas nuevas, hosting y errores de los últimos 30 min) y las **pruebas de humo** ([`deploy/produccion_28oct/PRUEBAS_DE_HUMO.md`](../deploy/produccion_28oct/PRUEBAS_DE_HUMO.md)).

## 3. Migraciones 0069 → 0073 (ensayo local del 28-oct-2026, datos ficticios)

Ensayo: copia de la base de demostración (9 037 personas), bajada a `0068_door_liveness`, subida a `0073_attendee_origin`.

| Verificación | Resultado |
|---|---|
| `upgrade head` desde 0068 | sin errores, **1,3 s** |
| Conteos de todas las tablas que ya existían, antes vs. después | **idénticos** (ninguna cambió) |
| Datos previos de `events`, `staff_users`, `event_attendees`, `users`, `access_logs`, `bulk_jobs` (sin las columnas nuevas) | **idénticos** (huella igual) |
| Reescritura de tablas (`relfilenode` de `events`, `staff_users`, `event_attendees`, `users`, `access_logs`) | **ninguna** (las columnas nuevas son solo metadato) |
| Segunda subida | sin cambios |
| Bajar a 0068 y volver a subir | limpio; conteos iguales |
| Sesiones esperando locks durante el ensayo | 0 |

Qué hace cada una:

| Rev. | Cambio | Riesgo |
|---|---|---|
| 0069 | `events.shared_print_enabled` (false) + tablas nuevas `print_devices`, `print_routes`, `print_jobs` | aditiva; la impresión compartida **viene apagada** en cada evento |
| 0070 | `events.print_settings_json` (NULL = valores de fábrica) | aditiva |
| 0071 | `print_jobs.prefs_json` | aditiva (tabla nueva) |
| 0072 | tablas nuevas `print_stations`, `app_settings`, `session_audit`; `staff_users.print_station` (false) y `staff_users.session_token` (NULL) | aditiva; **no toca ninguna tabla de sesión existente** (no existe una: la sesión es una cookie firmada). Solo agrega 2 columnas a `staff_users`, sin reescribirla. **Nadie pierde su sesión**: sin `session_token` la sesión sigue válida |
| 0073 | `event_attendees.origin` + **relleno** (`UPDATE` de `origin`) con lo que se deduzca (manual / autoregistro / base / NULL) | la única que **escribe datos existentes**, solo la columna nueva. En el ensayo: 9 001 «base» y 36 sin rastro (NULL «Desconocido»); no cambia estado ni otras columnas |

Bloqueos: los `ADD COLUMN` con valor constante toman un bloqueo breve (milisegundos) sobre `events`, `staff_users` y `event_attendees`; el `UPDATE` de 0073 bloquea por filas solo `event_attendees`. Por eso se despliega **sin evento en curso** (el congelamiento ya lo exige). **Ninguna es insegura; no hace falta alternativa.** Vuelta atrás de datos: la rama de Neon `antes-produccion-28oct`; las bajadas (`downgrade`) de las 5 existen y se probaron.

El código anterior (`b225a2d`) ignora las columnas y tablas nuevas, así que **volver a las revisiones anteriores de Cloud Run NO exige bajar la base**.

## 4. Diferencias de configuración staging ↔ producción (código y flujos, sin ver la nube)

Origen: `deploy/gcp/config.sh`, `deploy/gcp/deploy.sh`, `deploy/gcp/env/common.yaml`, `.github/workflows/*`.

| Qué | Staging | Producción | ¿Afecta lo que Juan probó? |
|---|---|---|---|
| `CONTINGENCY_ENABLED` | 1 | **1** (era 0 hasta el 28-oct-2026; cambiado por orden explícita de Juan David en un commit propio, `deploy/gcp/config.sh`) | **Ahora igual en los dos**: el quiosco de producción trae la copia local de la lista y el service worker `/kiosk/sw.js`. Apagarlo = volver la línea a `=0` y redesplegar |
| Rama que puede desplegar (Workload Identity) | `migra/fase1-2` (cada push) | **solo `main`, solo manual** con `confirm=DESPLEGAR` | No |
| Congelamiento de despliegue | no | **sí** (`/api/ops/deploy-allowed`; `force` solo emergencias) | No |
| `DEPLOY_ENV` / avisos | `staging`: distintivo STAGING y correos con prefijo `[STAGING]` | `production`: sin distintivo ni prefijo | Cosmético |
| Dominio y hosting | `staging.golden-eventos.com` (sitio de Firebase de staging) | `app.golden-eventos.com`, sitio `golden-app-<nº de proyecto>`; `FIREBASE_DEPLOY=1` | No |
| Nombres de servicios, Jobs, colas, secretos, cuentas | con sufijo `-staging` | sin sufijo | No |
| Buckets | uno solo (app + respaldos) | `…-golden-app-us-east4` y `…-golden-backups-us-east4` | No |
| CORS del bucket | incluye las URL `run.app` | solo dominio y Firebase | No |
| Instancias y límites | los de `deploy.sh`: web 1 CPU/1 GiB, concurrencia 40, máx. 10; público igual; biometría 2 CPU/2 GiB, concurrencia 2, máx. 10; **mínimo de instancias no fijado en el código (0)** | **los mismos (mismo script)** | Idénticos en código. **Si en la consola de Cloud Run alguien los cambió a mano en cualquiera de los dos, no se ve aquí: compáralos** (comando abajo) |
| `CHAOS_ENABLED` / simulacro de caos | solo staging (triple candado, `DEPLOY_ENV=staging`) | imposible | No |
| `SINGLE_SESSION` (variable) | no definida en el código | no definida | **Ojo, §5:** la sesión única viene ENCENDIDA por defecto en ambos |
| Impresión compartida | apagada por defecto en cada evento nuevo; Juan la enciende por evento | igual | Lo probado: compartida APAGADA (USB/ventana normal) y barra amarilla de Windows |
| Política de privacidad `POLICY_VERSION` y textos legales | 1.1 (igual) | 1.1 (igual) | No |

**Comparar a mano las configuraciones reales de Cloud Run** (por si alguien las tocó en la consola; solo lectura):
```bash
P=goldenweb-prod; R=us-east4
for s in golden-web golden-publico golden-biometria; do gcloud run services describe $s --project $P --region $R --format="value(metadata.name,spec.template.metadata.annotations)" ; done
# y lo mismo con -staging en el proyecto de staging; mira: autoscaling.knative.dev/minScale, maxScale, containerConcurrency, cpu, memory
```

## 5. Lo que CAMBIA para el operador al subir esta versión (ver las notas de la versión)

- **Sesión única** (encendida por defecto en cuanto existe `app_settings`): los roles que no son admin/super_admin solo pueden tener **una** sesión; entrar en otro equipo cierra la anterior. Las **cuentas de puesto de impresión** rechazan un segundo inicio mientras estén en uso. Se apaga en Configuración (o con la variable `SINGLE_SESSION=0`). Los admin no tienen límite. Nadie pierde su sesión al desplegar.
- **Modo sin conexión (contingencia) ENCENDIDO:** el quiosco descarga una copia local de la lista del evento (con huellas) y registra un service worker; sin red se puede registrar y al volver la red se sincroniza. Probarlo en cada dispositivo antes de un evento (pruebas de humo, paso 12). Requisitos legales ya cubiertos por la política 1.1 (sección 8; `docs/legal/CONTINGENCIA_PRODUCCION_LISTA.md`).
- **Impresión** (ver `IMPRESION_PARAMETROS_INAMOVIBLES.md`).

## 6. PR candidato → main (NO fusionar hasta DESPLIEGA PRODUCCIÓN)

Texto y línea `[skip ci]` en [`deploy/produccion_28oct/PR_CANDIDATO.md`](../deploy/produccion_28oct/PR_CANDIDATO.md). **Fusionar a `main` no despliega producción**: `cloudrun.yml` solo se dispara con push a `migra/fase1-2` o a mano (`workflow_dispatch`); un push a `main` solo corre `ci.yml` (y `deploy.yml`, el de la VM, es solo manual). Lo comprueba `tests/test_cutover_workflows.py`.
El repositorio es **público**: los runners de GitHub no consumen el presupuesto de minutos. Las dos fallas «de 3 segundos sin runner» del 28-oct fueron del lado de GitHub y se resolvieron re-ejecutando.

## 7. Plan de vuelta atrás (por revisiones; no se borra la anterior)

**Antes de desplegar** (§0) quedan anotadas las revisiones actuales de cada servicio y `vuelta_atras.sh` las trae escritas. Orden:

1. Tráfico de los 3 servicios a las revisiones anteriores (pide escribir `VOLVER ATRAS`):
   ```bash
   bash deploy/produccion_28oct/vuelta_atras.sh
   ```
   (equivale a `gcloud run services update-traffic <servicio> --region us-east4 --to-revisions=<revisión anterior>=100` por cada servicio; las revisiones nuevas NO se borran).
2. Jobs (`golden-bulk`, `golden-ops`) a su imagen anterior (el script lo pregunta).
3. Firebase Hosting: consola → Hosting → «Historial de versiones» → la versión anotada → ⋮ → *Revertir*.
4. La base **se queda en 0073** (el código anterior la ignora). Solo si hubiera datos dañados: restaurar desde la rama de Neon `antes-produccion-28oct` (decisión aparte, con Claude).
5. `bash deploy/produccion_28oct/verificar_despues.sh b225a2d`.

**Criterio para volver atrás:** no se puede iniciar sesión, falla el registro o la impresión, errores 5xx sostenidos, o `/health` distinto de 200.

## 8. Archivos de este paquete

`deploy/produccion_28oct/`: `comun.sh`, `verificar_antes.sh`, `anotar_estado_previo.sh` (genera `vuelta_atras.sh`), `verificar_despues.sh`, `NOTAS_DE_LA_VERSION.md`, `PR_CANDIDATO.md`, `PRUEBAS_DE_HUMO.md`.


---

# Paso del 29-oct-2026 — exportar/importar eventos y arreglo de impresión (staging `d53498e` → producción)

Lo ejecuta **Juan David**; Claude no corre nada en la nube. Producción queda **igual que staging el 29-oct-2026**: el código de `d53498e` (rama `migra/fase1-2`, probado en staging: CI y Cloud Run en verde, `/health` 200). El candidato es `candidato/produccion-29oct` (solo agrega documentación y scripts). Paquete: [`deploy/produccion_29oct/`](../deploy/produccion_29oct/). Parámetros de impresión inamovibles: [`IMPRESION_PARAMETROS_INAMOVIBLES.md`](IMPRESION_PARAMETROS_INAMOVIBLES.md).

> **Nada de esto se ejecuta hasta que Juan David escriba exactamente «DESPLIEGA PRODUCCIÓN».** Armar el paquete no despliega nada.

## A. Qué hay hoy en producción y qué cambia

| Pieza | Hoy | Después |
|---|---|---|
| `main` | `6c71cc3` (PR #2: producción del 28-oct) | el candidato `candidato/produccion-29oct` (avance directo: `6c71cc3` es su ancestro) |
| Código de los 3 servicios y los Jobs | el de `6c71cc3` | el de `d53498e` |
| Base de datos | `0073_attendee_origin` | `0075_transfer_jobs` (migraciones 0074 y 0075, solo aditivas) |
| `CONTINGENCY_ENABLED` | `1` | `1` (sin cambios) |
| Configuración staging ↔ producción | ver §4 de este runbook | **sin diferencias nuevas** |

**Qué trae (para el operador):** exportar e importar eventos (solo super_admin) y el arreglo de impresión (página fija de 62 × 99,8 mm, imagen de máximo 96 mm, horizontal centrada). Notas completas: `deploy/produccion_29oct/NOTAS_DE_LA_VERSION.md`.

**Comprobar el estado real de producción antes de tocar nada** (solo lectura, Cloud Shell, proyecto `goldenweb-prod`, región `us-east4`): `bash deploy/produccion_29oct/anotar_estado_previo.sh` (anota revisiones de `golden-web`, `golden-publico` y `golden-biometria`, imagen de los Jobs y versión de Firebase Hosting, y escribe `vuelta_atras.sh`). `git ls-remote origin refs/heads/main` debe dar `6c71cc3…`; en la consola SQL de Neon, `SELECT version_num FROM alembic_version;` debe dar `0073_attendee_origin`.

## B. Migraciones 0074 y 0075 (ensayo local, datos sintéticos)

Ensayo: copia de la base de demostración (9 037 personas, evento de 8 000), subida desde `0073_attendee_origin` a `0075_transfer_jobs`.

| Verificación | Resultado |
|---|---|
| `upgrade head` desde 0073 | sin errores |
| Conteos de todas las tablas que ya existían, antes vs. después | **idénticos** |
| Tablas nuevas | `event_transfer_log`, `event_import_actors` (vacías) |
| Columnas nuevas | `form_payments.origin` (NULL) y, en `event_transfer_log`: `stage`, `progress`, `result_json`, `file_key`, `finished_at` |
| Segunda subida | sin cambios |
| Bajar a 0073 y volver a subir | limpio; conteos iguales |

Ninguna toca datos existentes ni tablas de sesión; `ADD COLUMN` sobre `form_payments` es de metadato (bloqueo de milisegundos). El código anterior (`6c71cc3`) ignora lo nuevo: **volver a las revisiones anteriores de Cloud Run NO exige bajar la base.**

## C. Pasos (en este orden)

1. `bash deploy/produccion_29oct/verificar_antes.sh` — todo en ✅. Si hay ❌, no sigas.
2. **Sin eventos en curso ni por abrir** en las próximas 3 h (el despliegue se congela solo).
3. **Respaldo: rama de Neon `antes-produccion-29oct`** (Neon → Branches → *Create branch* → «Current point in time»).
4. **PR candidato → `main`** (texto y `[skip ci]` en `deploy/produccion_29oct/PR_CANDIDATO.md`). Fusionar NO despliega.
5. Actions → **«Cloud Run (staging y producción)»** → *Run workflow* → rama **`main`** → `confirm` = `DESPLEGAR`; `force` **sin marcar**. Corre las pruebas, migra (Job), despliega los 3 servicios y los Jobs y publica Firebase Hosting.
6. `bash deploy/produccion_29oct/verificar_despues.sh <hash de main>` y las pruebas de humo (`deploy/produccion_29oct/PRUEBAS_DE_HUMO.md`, incluye exportar e importar con un evento ficticio).

## D. Vuelta atrás (por revisiones; no se borra la anterior)

1. `bash deploy/produccion_29oct/vuelta_atras.sh` (pide escribir `VOLVER ATRAS`): tráfico de los 3 servicios a las revisiones anotadas; opcionalmente los Jobs a su imagen anterior.
2. Firebase Hosting: consola → Hosting → «Historial de versiones» → versión anotada → ⋮ → *Revertir*.
3. La base **se queda en 0075** (el código anterior la ignora). Solo si hubiera datos dañados: restaurar desde la rama de Neon `antes-produccion-29oct` (decisión aparte).
4. `bash deploy/produccion_29oct/verificar_despues.sh 6c71cc3`.

**Criterio para volver atrás:** no se puede iniciar sesión, falla el registro o la impresión, errores 5xx sostenidos, o `/health` distinto de 200.

## E. Riesgos

- Es un cambio grande (≈ 2 700 líneas, 24 archivos) y **exportar/importar no se probó en staging por una persona** antes de este paso (sí con 28 pruebas automáticas, la prueba de oro y el asistente en un navegador con 8 000 personas sintéticas). Recomendación: probarlo en staging con un evento de prueba antes de la frase de despliegue.
- Hoy es la **víspera del piloto del 29-oct**: decide el momento (antes o después del piloto).
- El paquete exportado contiene datos personales (descarga de 5 min y borrado a las 24 h); la biometría es opcional, solo super_admin y cifrada.
- Tu Chrome de impresión debe ser el normal (sin `--kiosk-printing`).
