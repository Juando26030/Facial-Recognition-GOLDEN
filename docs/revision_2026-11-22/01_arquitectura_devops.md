# 01 · Arquitectura y DevOps/SRE — revisión integral del 22-nov-2026

Roles: **Arquitecto de software** (pasada 1) e **Ingeniero DevOps/SRE** (pasada 2), y una tercera pasada en la que cada uno critica lo que escribió el otro. Rama `saas/revision-integral`, sin commit ni push. Todo lo que dice «comprobado» se leyó en el código o se corrió en esta máquina (pruebas de texto, `ruff`); nada se ejecutó en la nube.

---

## 1. Resumen en 5 líneas

1. **La plataforma está bien construida para lo que es hoy (una empresa, Golden):** una sola imagen que corre tres servicios y tres Jobs en Cloud Run, base Neon detrás de un pooler, cola de trabajos en Postgres, archivos solo por una interfaz, logs sin datos personales, secretos en Secret Manager, despliegue sin llaves, congelamiento automático si hay evento en curso. Es mejor que la media de empresas de este tamaño.
2. **Lo más grave para el SaaS:** la «empresa» no existe en el modelo de datos. Lo que el código llama *tenant* es **el cliente de Golden** (para quien se hace el evento), no la empresa de eventos que usaría la plataforma. 87 de las 119 tablas no tienen `tenant_id` (muchas se aíslan a través del evento, pero los catálogos, ajustes, impresoras, estados y notas no tienen ningún camino hacia una empresa), el aislamiento entre clientes vive detrás de **dos interruptores de entorno apagados** (`ENFORCE_STAFF_TENANT`, `ENFORCE_STAFF_EVENT_SCOPE`) y 8 funciones del negocio (CRM, Almacén, formulario de persona, contingencia, cuentas por servicio…) se encienden **desde los scripts de despliegue**, no desde la app. Eso contradice la decisión del 22-nov («nada se maneja desde código»).
3. **Lo más grave en operación:** el camino real de despliegue a producción es hoy **manual desde Cloud Shell con la cuenta dueña** (`manual_deploy.sh`), sin que corran las pruebas, mientras el camino seguro (GitHub Actions + identidad federada + pruebas) solo acepta la rama `main`. Y **nunca se ha ensayado una restauración con un respaldo real de producción**.
4. **Lo más valioso:** el diseño de la cola (`app/jobs.py`), los tres servicios de una imagen (`app/appmode.py` + `deploy/firebase/make_config.py`, UNA sola fuente de verdad para el reparto de rutas), el fallo cerrado al arrancar (sin llave de cifrado o sin manejadores no arranca) y el modo económico del Job horario que deja dormir a Neon. Es una base sólida para cobrar por ella.
5. **Qué se hizo hoy:** 4 cambios pequeños y seguros (tiempo máximo de espera de bloqueo en migraciones, tiempos límite en los flujos de GitHub, construcción de la imagen también en ramas `feat/` y `saas/`, y sección de recuperación ante desastre en Cloud Run en `docs/19`). Lo estructural (capa «empresa», aislamiento siempre encendido, planes y cuotas) va como plan exacto en §4 y el Anexo A; son 6-9 semanas de trabajo en `app/`.

---

## 2. Hallazgos

Severidad: **Crítica** = impide vender el SaaS o puede perder datos; **Alta** = incidente probable o incumplimiento claro; **Media** = deuda que cuesta cada mes; **Baja** = pulido.

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | **Crítica** | No existe la entidad «empresa que usa la plataforma» (organización). `tenants` = cliente final de Golden; `staff_users.tenant_id = NULL` significa «Golden, ve todo». 87 de 119 tablas no tienen `tenant_id`; de ellas, estas no tienen NINGÚN camino hacia un cliente o empresa (ni por evento): catálogos de inventario (`inventory_categories/products/units`), estados y tipos de evento (`event_states`, `event_types`), impresoras (`print_devices/stations`), `app_settings`, `alert_recipients`, `calendar_notes`, `saved_colors`, `payment_accounts`, `local_server_keys`, `local_nodes`, `notifications`, `event_templates`, `infra_costs`, todo `crm_*`. | `app/models.py` (clases `Tenant`, `StaffUser`, tablas listadas); `app/auth.py` | Dos empresas de eventos compartirían los mismos catálogos, impresoras, estados, notas de calendario y cuentas de cobro. No es «un hueco»: es que el modelo es de una empresa. | **Propuesto** (plan exacto en Anexo A, §A.3) |
| 2 | **Crítica** | El aislamiento entre clientes es opcional y está **apagado**: `ENFORCE_STAFF_TENANT=0` y `ENFORCE_STAFF_EVENT_SCOPE=0` por defecto; no se escriben en `deploy/gcp/env/common.yaml` ni en `deploy.sh`, así que producción corre sin él. Las 395 llamadas a `assert_event_tenant`/`get_event_for_staff`/`scope_events_query` están bien puestas (comprobado en `app/routers/events.py`, `api.py`, `inventory.py`, `downloads.py`, `tenants.py`), pero **todas** dependen de ese interruptor. | `app/auth.py` líneas 154-289, `app/tenant_scope.py` | En un SaaS el aislamiento no puede depender de una variable que alguien olvide poner (ya pasó con `ONEDRIVE_DRIVE_ID`, `deploy/gcp/README.md` §3). Hoy es aceptable solo porque todo el personal es de Golden. | **Propuesto**: quitar el interruptor (siempre encendido) + RLS en Postgres como segunda cerradura (Anexo A §A.4) |
| 3 | **Crítica** | Interruptores de negocio en los scripts de despliegue: `CRM_ENABLED`, `ALMACEN_ENABLED`, `CRM_IMPORT_APPLY`, `CRM_IMPORT_OWNER_USERNAME`, `PERSON_FORM_ENABLED`, `CONTINGENCY_ENABLED`, `SPLIT_SERVICE_ACCOUNTS`, `FIREBASE_DEPLOY`. Cambiar uno = redesplegar. | `deploy/gcp/config.sh` líneas 26-41, `deploy/gcp/deploy.sh` líneas 81, 106, 145 | Contradice la decisión del 22-nov: «cuentas, clientes, usuarios, planes, asistencia: todo dentro de la app». Un segundo cliente del SaaS no puede tener CRM apagado y Almacén encendido sin tocar `config.sh`. | **Propuesto**: tabla `org_entitlements` + pantalla «Planes» (Anexo A §A.5). Las variables quedan solo como tope de plataforma. |
| 4 | **Alta** | El despliegue real a producción es manual desde Cloud Shell con la **cuenta dueña del proyecto**: `deploy/gcp/README.md` §2 lo documenta como el comando normal, y `manual_deploy.sh` avisa que «las pruebas (CI) NO corren en este camino». El camino con identidad federada y pruebas (`cloudrun.yml`) solo acepta `main` y requiere escribir `DESPLEGAR`; staging por Actions solo desde `migra/fase1-2` (`config.sh` línea 25: `DEPLOY_REF`), rama que ya no es la de trabajo (`feat/`, `saas/`). | `deploy/gcp/manual_deploy.sh`, `deploy/gcp/config.sh`, `.github/workflows/cloudrun.yml` | Mínimo privilegio roto (la cuenta dueña despliega), sin pruebas antes de producción, y un error de rama ya mandó a producción el código de otra rama (17-nov, README §1). Estándar SRE: la máquina despliega, la persona aprueba. | **Propuesto** (§4, orden 2): ampliar `DEPLOY_REF` de staging a `feat/**`+`saas/**` con un segundo *binding* de WIF y volver a Actions; `manual_deploy.sh` solo como plan B escrito así. Cambio en `bootstrap.sh`+`cloudrun.yml`; lo corre Juan David. |
| 5 | **Alta** | Los tres servicios reciben **todos** los secretos (correo de Microsoft, llave PRIVADA de Wompi, llave de rostros) salvo con `SPLIT_SERVICE_ACCOUNTS=1`, que está en 0. El servicio `publico` es el que está abierto a internet. | `deploy/gcp/config.sh` líneas 53-62 y 132-147; `docs/20_CUENTAS_POR_SERVICIO.md` | OWASP ASVS V14 (configuración): un fallo en la parte pública expone credenciales que esa parte no necesita. El trabajo ya está hecho y probado en código; solo falta encenderlo (2 pasos, primero staging). | **Pendiente** (lo corre Juan David: `docs/20`, pasos 1-2) |
| 6 | **Alta** | Nunca se ha restaurado un respaldo real de producción (docs/15 D2.5j(b): solo uno de 17 KB contra un emulador, el 28-sep). `docs/recuperacion_desastre.md` describe la **VM** (snapshots, cron, `~/backups`), no Cloud Run + Neon. Los volcados llevan nombres y cédulas en claro dentro del bucket (cifrado solo en reposo por Google). | `docs/recuperacion_desastre.md`, `scripts/restore_test.sh`, `app/ops_runner.py` | «Una copia que nunca se restauró no es una copia». Sin un documento actual, el día del problema se improvisa. | **Corregido en parte**: sección «Recuperación ante desastre en Cloud Run + Neon» en `docs/19_GUIA_PRODUCCION.md` (tabla de copias, 4 caminos de vuelta, RPO/RTO). **Pendiente**: correr `scripts/restore_test.sh` una vez y anotar la fecha. |
| 7 | **Alta** | Una migración que espera un bloqueo (una exportación larga, una sesión colgada) retenía la base hasta 900 s con producción a medio desplegar: `alembic/env.py` no fija `lock_timeout` ni `statement_timeout`; solo 2 de 151 migraciones lo hacen (0077, 0079). | `deploy/gcp/deploy.sh` (Job `golden-migrate`), `alembic/env.py` | Un `ALTER TABLE` detrás de un bloqueo pone en cola a TODAS las consultas de esa tabla: la pantalla de registro se congela. | **Corregido**: `deploy.sh` pasa `PGOPTIONS="-c lock_timeout=10s -c statement_timeout=840s"` al Job de migraciones (`MIGRATE_LOCK_TIMEOUT` / `MIGRATE_STATEMENT_TIMEOUT` para ajustarlo). Si vence, el Job falla ANTES de tocar los servicios y se repite el despliegue. |
| 8 | **Alta** | Valores no secretos pero obligatorios del despliegue (`ONEDRIVE_DRIVE_ID`, `OFFSITE_FOLDER_URL`, `GCP_BILLING_EXPORT_TABLE`, `NEON_ORG_ID`) viven en `~/.golden-production.env` del HOME de Cloud Shell. `--env-vars-file` **reemplaza** todas las variables del servicio en cada despliegue. | `deploy/gcp/manual_deploy.sh` línea 24, `deploy/gcp/README.md` §3 y §6 | Google borra el HOME de Cloud Shell tras 120 días sin uso; un despliegue sin ese archivo pierde la copia semanal sin avisar hasta que `/sistema` lo diga. Configuración de entorno fuera de control de versiones (12-factor III roto a medias). | **Propuesto**: esos 4 valores a las *Variables* del Environment de GitHub (ya lo hace `cloudrun-deploy.yml` para 2 de ellos) y, en el SaaS, a `app_settings` por organización. |
| 9 | **Media** | Un despliegue manda el 100 % del tráfico a la revisión nueva de inmediato; no hay despliegue gradual ni comprobación automática de 5xx después (solo `curl /health` y `/ready`). La vuelta atrás existe y está documentada (`update-traffic`). | `deploy/gcp/deploy.sh` líneas 140-142, 163-166 | Con US$40/mes un *canary* real no cabe; pero una comprobación de «0 errores 5xx en 3 min» tras desplegar sí cuesta cero. | **Propuesto** (§4, orden 6) |
| 10 | **Media** | Observabilidad: logs JSON con `request_id` y PII enmascarada (bien), 3 alertas + alerta de ausencia del Job + chequeo `/health` cada minuto (bien). Faltan: alerta de **latencia** (p95 del servicio `web` > 2 s en 5 min), métrica de trabajos `failed` de la cola como alerta (hoy solo se ve en `/sistema`), y Error Reporting (los logs ya traen `stack_trace`, así que es gratis activarlo). | `deploy/gcp/bootstrap.sh` paso 10, `app/obs.py`, `app/ops.py` | Hoy te enteras de «lento» por el digitador, no por una alerta. | **Propuesto** (§4, orden 5; política JSON lista para `bootstrap.sh`) |
| 11 | **Media** | Dependencias y acciones sin fijar por huella: `python:3.14-slim-trixie` sin digest en `Dockerfile`; `actions/checkout@v4` y `@v7` mezclados; `setup-node@v4`/`@v7`; `upload-artifact@v4`; gitleaks por etiqueta. `pip-audit` y Semgrep son solo informativos. | `Dockerfile`, `.github/workflows/*.yml`, `seguridad.yml` | Cadena de suministro (ASVS V14.2, SLSA nivel 1-2): una etiqueta movida cambia lo que se construye sin cambiar el repositorio. | **Propuesto** (§4, orden 7). No se hizo hoy: cambiar versiones de acciones sin poder correr el flujo es riesgo sin prueba. |
| 12 | **Media** | Tope de costo: Cloud Run tiene máximo 10 instancias por servicio (código), pero el máximo de CU de Neon se fija **a mano en la consola** (docs/15 líneas 375-385) y no se comprueba en ningún `check`. Presupuesto con avisos al 50/90/100 % existe (avisa, no apaga). | `deploy/gcp/scheduler.sh check`, `app/warmup.py` | La regla «US$40 inamovible» depende de un valor que nadie verifica. | **Propuesto**: `scheduler.sh check` lee el endpoint por la API de Neon (`NEON_API_KEY` ya existe) y falla si `autoscaling_limit_max_cu > 4`. 2 h. |
| 13 | **Media** | Aislamiento de rendimiento entre empresas (vecino ruidoso): colas de Cloud Tasks, servicio `biometria` (concurrencia 2, máx. 10 instancias) y Job de carga masiva (1 tarea) son compartidos; no hay cuota por empresa ni por evento. | `deploy/gcp/bootstrap.sh` paso 7, `deploy/gcp/deploy.sh` línea 149, `app/bulk_jobs.py` | Una empresa cargando 50.000 personas con foto deja sin reconocimiento facial a otra en pleno evento. | **Propuesto**: cuotas por plan (`org_entitlements`: personas/evento, cargas simultáneas, facial sí/no) + una cola de Cloud Tasks por «prioridad» (evento en curso primero). Anexo A §A.5. |
| 14 | **Media** | Servidor local sin internet: la llave de producto (`local_server_keys`) y el manifiesto de actualización (`/api/ops/update-manifest`, `system/local-update/` del bucket) son globales; `PRODUCTION_URL` está fija en `deploy/windows/defaults.env`. | `app/models.py` `LocalServerKey`, `deploy/gcp/manual_deploy.sh` paso 5, `deploy/windows/defaults.env` | Para el SaaS cada instalación local debe nacer atada a una empresa; el paquete de actualización puede seguir siendo uno. | **Propuesto**: `local_server_keys.org_id` + el instalador recibe la URL y la llave (ya la pide) y de ahí deduce la empresa. Anexo A §A.3. |
| 15 | **Media** | Identidad legal y de marca fija por entorno: `COMPANY_NAME`, `COMPANY_NIT`, `LEGAL_*`, `PRIVACY_EMAIL`, `POLICY_VERSION`, remitente de correo (`GRAPH_SENDER`) y llaves de Wompi de Golden son variables de entorno; los textos legales son LITERALES de la auditora para Golden como responsable del tratamiento. | `deploy/gcp/env/common.yaml`, `app/legal_texts_data.py` (no se toca) | Otra empresa es OTRO responsable del tratamiento (Ley 1581): su nombre, NIT, correo de privacidad y política deben salir en sus pantallas y correos. No es solo técnico: la auditora debe decir cómo se parametriza el texto sin editarlo. | **Propuesto**: `organizations` guarda identidad, remitente y cuentas de cobro (el patrón ya existe en `payment_accounts`, cifrado con `PAYMENT_KEYS_ENCRYPTION_KEY`). Pregunta a la auditora en §4. |
| 16 | **Baja** | `ci.yml` construía la imagen solo en `integracion/`, `migra/` y `producto/`; `feat/` (la rama de la corrida final) y `saas/` no, así que un error del Dockerfile saltaba en pleno despliegue. Ningún job tenía `timeout-minutes` (6 h por defecto). | `.github/workflows/ci.yml`, `cloudrun-deploy.yml` | Minutos de Actions y un despliegue colgado bloqueando al siguiente (`concurrency` sin cancelación). | **Corregido** |
| 17 | **Baja** | Cadena de migraciones sana: 151 revisiones, **una sola cabeza** (`0161_inventario_por_base`), 2 uniones (`0141`, `0151`), ningún id > 32 caracteres, ninguna referencia rota (comprobado con un script sobre `alembic/versions`). Hueco: no hay prueba de «subir y bajar» automática en CI (solo `upgrade head` implícito en las pruebas). | `alembic/versions/`, `tests/test_cadena_migraciones.py` | Cada migración nueva se ensaya a mano (runbook 28/29-oct lo hizo bien). | **Propuesto**: paso en `ci.yml` `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` sobre la base de pruebas. 1 h. |
| 18 | **Baja** | Conexiones: `web` = 2 procesos × (10 + 10) = 40 conexiones por instancia × 10 instancias = hasta 400 conexiones de cliente al pooler de Neon, que las multiplexa sobre pocas conexiones reales. Correcto en modo transacción, pero `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` no están escritos en `deploy.sh` (valen los de `app/database.py`). | `app/database.py`, `deploy/gcp/deploy.sh` | Si alguien cambia el valor por defecto en código, cambia producción sin que el despliegue lo diga. | **Propuesto**: escribirlos explícitos en `deploy_service web … DB_POOL_SIZE=10 DB_MAX_OVERFLOW=10`. 10 min. |
| 19 | **Baja** | Dominio: una sola dirección (`app.golden-eventos.com`). Firebase Hosting **no admite dominios comodín** (`*.golden-eventos.com`), así que «un subdominio por empresa» no es gratis. | `deploy/firebase/make_config.py`, `docs/19` §10 | Decide el modelo de acceso del SaaS: una dirección con selector de empresa (gratis) o un dominio por empresa agregado a mano (gratis pero manual, y cada uno con su certificado). | **Propuesto**: slug de empresa en la ruta/sesión; dominio propio solo para planes altos, agregado a mano. |

---

## 3. Qué se cambió en el código

Cuatro archivos, todos del área permitida; verificados con `bash -n`, YAML válido, `ruff check .` (sin hallazgos) y las pruebas de texto que leen estos archivos (`tests/test_cutover_workflows.py`, `test_cadena_migraciones.py`, `test_deploy_faces_queue.py`, `test_dockerfiles.py`, `test_crm_c1b_texto.py`, `test_cobros_gastos_f10b_texto.py`, `test_bootstrap_secrets.py`, `test_bootstrap_iam_retry.py`: **88 pasan**).

| Archivo | Qué hace el cambio |
|---|---|
| `deploy/gcp/deploy.sh` | El Job de migraciones (`golden-migrate`) recibe `PGOPTIONS="-c lock_timeout=10s -c statement_timeout=840s"` (ajustable con `MIGRATE_LOCK_TIMEOUT` y `MIGRATE_STATEMENT_TIMEOUT`). libpq lo aplica en la conexión directa de Alembic. Una migración que espere un bloqueo más de 10 s falla antes de tocar los servicios (siguen con la versión anterior) y se repite el despliegue cuando la base esté libre. Comportamiento idéntico al de antes si las dos variables se dejan vacías. |
| `.github/workflows/ci.yml` | `timeout-minutes` en los 3 jobs (45 / 90 / 10) y el job `image` (construye la imagen sin subirla) corre también en ramas `feat/` y `saas/`: el Dockerfile se comprueba en la corrida final que aprueba Juan David, no en pleno despliegue. |
| `.github/workflows/cloudrun-deploy.yml` | `timeout-minutes: 120` en el job de despliegue (antes 6 h): un despliegue colgado no bloquea al siguiente. |
| `docs/19_GUIA_PRODUCCION.md` | Sección nueva «Recuperación ante desastre en Cloud Run + Neon»: tabla de copias (PITR 1 día, horario 3 días, diario 30, copia semanal cifrada en SharePoint, versiones del bucket, secretos), 4 caminos de vuelta con los scripts reales (`neon_app_role.py`, `migrate_db_to_neon.py`, `restore_test.sh`, `open_backup_copy.py`), RPO/RTO y la advertencia de que `docs/recuperacion_desastre.md` es de la VM. |

**Nada en `app/`** (otro agente). Lo que haga falta allí está en el Anexo A con archivo, función y cambio.

---

## 4. Qué queda pendiente y por qué (horas y orden recomendado)

| Orden | Qué | Por qué en este orden | Horas | Quién |
|---|---|---|---|---|
| 1 | **Ensayo de restauración** con `scripts/restore_test.sh` (rama temporal de Neon) y anotar fecha y duración en `docs/19`. | Es lo único de esta lista que puede costar la empresa si falla, y cuesta 1 h. | 1-2 | Juan David con Claude |
| 2 | **Volver el despliegue a GitHub Actions**: en `bootstrap.sh` paso 4, un segundo *binding* de WIF para staging con `attribute.ref` de `refs/heads/feat/*` y `refs/heads/saas/*` (hoy solo `migra/fase1-2`); en `cloudrun.yml`, `push: branches: [migra/fase1-2, "feat/**", "saas/**"]` para staging; producción sigue siendo manual con `DESPLEGAR` desde `main`. `manual_deploy.sh` queda como plan B documentado como tal en `README.md` §2. | Quita la cuenta dueña del camino diario y hace que las pruebas corran antes de cada staging. | 3 (+ 15 min de Juan David en Cloud Shell) | Claude prepara; Juan David corre `bootstrap.sh` |
| 3 | **Encender cuentas por servicio** (`SPLIT_SERVICE_ACCOUNTS=1`): `docs/20`, pasos 1-2, primero staging. | Saca el correo y la llave privada de Wompi del servicio público. Ya está construido. | 1 (+ 30 min Juan David) | Juan David |
| 4 | **Variables no secretas a GitHub**: `OFFSITE_FOLDER_URL`, `GCP_BILLING_EXPORT_TABLE`, `NEON_ORG_ID` como `vars` del Environment y leídas en `cloudrun-deploy.yml` (igual que `ONEDRIVE_DRIVE_ID`); `README.md` §6 pasa a «solo para el plan B». | Deja de depender del HOME de Cloud Shell. | 1 | Claude |
| 5 | **Alertas que faltan** en `bootstrap.sh` paso 10: latencia p95 de `golden-web` > 2 s durante 5 min; trabajos `failed` de la cola (métrica por log sobre `golden.jobs` «falló en el intento»); activar Error Reporting (ya salen `stack_trace`). | Hoy «lento» no avisa. Costo cero (alertas gratis hasta 2027 según `bootstrap.sh`). | 3 | Claude prepara; Juan David corre `bootstrap.sh` |
| 6 | **Comprobación post-despliegue** en `deploy.sh`: tras los 3 servicios, leer durante 3 min la métrica de 5xx de las revisiones nuevas y, si pasa de 5, imprimir el comando exacto de vuelta atrás y salir con 1. | Sustituto barato del *canary*. | 3 | Claude |
| 7 | **Cadena de suministro**: `Dockerfile` con `python:3.14-slim-trixie@sha256:…`, acciones de GitHub fijadas por SHA (`actions/checkout`, `setup-python`, `setup-node`, `docker/*`, `google-github-actions/*`, `upload-artifact`), misma versión mayor en todos los flujos; `pip-audit` bloqueante para severidad alta. | Un flujo que no se puede correr aquí no se cambia a ciegas; se hace cuando haya una corrida completa programada. | 3 | Claude, en la rama `feat/` de la próxima corrida final |
| 8 | **Prueba subir/bajar migraciones** en `ci.yml` y tope de Neon verificado en `scheduler.sh check` (#12, #17). | Cierra dos huecos chicos con costo cero. | 3 | Claude |
| 9 | **Capa «empresa» (organización)** en `app/`: tablas, migración, sesión, filtros, RLS, pantalla de administración de empresas, planes y cuotas. Plan exacto en el Anexo A. | Es la obra grande del SaaS. No tiene sentido antes de 1-3 (seguridad de lo que ya hay) ni sin la decisión de la auditora sobre textos legales por empresa. | **160-220** (6-9 semanas de una persona) | Agente de `app/` + Claude; decisiones de Juan David y la auditora |

**Pregunta para la auditora (bloquea el orden 9, parte legal):** otra empresa de eventos es otro *responsable del tratamiento*. ¿Puede el mismo texto literal de la política 1.1 servir con nombre, NIT y correo de privacidad **parametrizados** por empresa, o cada empresa necesita su propia política aprobada? La plataforma puede guardar una política por empresa con su versión y hash (como hoy con `POLICY_VERSION` y `docs/legal/POLITICA_v1.1.md`), pero el contenido no lo decide el código.

---

## 5. Qué NO se pudo comprobar

- **Nada en la nube**: no se vio la configuración real de Cloud Run, Neon, Secret Manager, colas, Scheduler ni alertas. Todo lo dicho sobre «producción» es lo que el código y los scripts harían; si alguien cambió algo en la consola, aquí no se ve (el propio runbook 28-oct §4 avisa de lo mismo).
- **No se corrió la suite completa de pruebas** (344 archivos): esta máquina no tiene `sqlalchemy`/`fastapi` instalados y no hay red para instalarlos. Solo se corrieron las pruebas que leen archivos de texto (88 en verde) y `ruff check .` (limpio). Las 4 que fallan en `tests/test_contingency_flag.py` fallan por la falta de `fastapi`, no por los cambios.
- **El flujo de GitHub Actions no se ejecutó** (está prohibido disparar corridas hasta la final); el YAML se validó como YAML y contra `tests/test_cutover_workflows.py`.
- **`PGOPTIONS` con Neon directo**: libpq lo manda como parámetro `options` de arranque y Neon lo acepta en conexiones directas (es el mismo mecanismo que Neon documenta para `options=endpoint=…`); no se pudo probar contra una base real desde aquí. Por eso se dejaron las dos variables para desactivarlo (`MIGRATE_LOCK_TIMEOUT= MIGRATE_STATEMENT_TIMEOUT=` vacías) si el primer despliegue de staging mostrara algo raro en el log del Job.
- **Costos reales** (facturas de Google y Neon): no se vieron; solo las reglas que los limitan.
- **Consultas sin filtro de cliente**: se revisaron las 80 búsquedas directas `db.query(Event).filter(Event.id ==` en `app/routers/` y las 67 de `query(User)`; todas las que atienden a personal pasan por `assert_event_tenant`/`get_event_for_staff` o son rutas públicas por token. **No** se revisaron una a una las ~2.000 consultas restantes: el método correcto para eso es RLS (Anexo A §A.4), que convierte «¿olvidé un filtro?» en «la base no lo deja».

---

## 6. Consejo en corto y veredicto

- **Contrario:** «No conviertas esto en SaaS todavía: una empresa, un cliente, cero incidentes de aislamiento. Primero vende el servicio con tu gente operando la plataforma (lo que ya haces) y mete la capa empresa cuando haya un segundo cliente firmado.»
- **Primeros principios:** «Un SaaS es una llave de empresa en cada fila y una base que la exige. Todo lo demás (planes, pantallas, dominios) se construye encima. Si la llave no está, nada de lo demás vale.»
- **Expansionista:** «La misma imagen ya corre en la nube y en una laptop sin internet: eso es un producto raro y valioso. El SaaS debería vender las dos cosas: nube + servidor local por evento.»
- **Forastero:** «Vengo de otra industria y me asusta que la seguridad entre clientes dependa de una variable apagada y que producción se despliegue desde la consola del dueño. Eso se arregla en una semana y debería ser lo primero.»
- **Ejecutor:** «Esta semana: restaurar un respaldo, despliegue por Actions, cuentas por servicio. Cuatro horas de Claude y una de Juan David. Después, la capa empresa por piezas, empezando por la tabla y el filtro, nunca por las pantallas.»

**Veredicto:** la plataforma es sólida y barata para una empresa; para venderla a otras le falta la pieza central (la empresa como entidad) y hay tres riesgos operativos baratos de cerrar. **UN siguiente paso:** correr el ensayo de restauración (`scripts/restore_test.sh`, orden 1 de §4) esta semana y anotar el resultado en `docs/19`; sin eso, cualquier plan de SaaS descansa sobre una copia que nunca se probó.

---

## Anexo A · Pasada 1: Arquitecto de software

### A.1 Arquitectura real hoy (leída del código)

```
                          Internet
                             │
              Cloudflare (solo DNS, gris)  app.golden-eventos.com
                             │
                   Firebase Hosting (CDN /static; rutas → servicios; solo cookie __session; 60 s)
            ┌────────────────┼────────────────────┐
            ▼                ▼                    ▼
   Cloud Run `publico`   Cloud Run `web`     Cloud Run `biometria`
   /f /inscripciones     panel del personal  /api/recognize /api/register
   /b /aceptar /webhooks /api/* /sistema     /api/bulk_register /internal/faces/run
   1 CPU 1 GiB c=40 máx10  1 CPU 1 GiB c=40 máx10   2 CPU 2 GiB c=2 máx10 (dlib)
   sin dlib              sin dlib            FACE_PROCESSES=2
            └────────────────┼────────────────────┘
                      UNA imagen (Dockerfile), APP_MODE decide las rutas (app/appmode.py)
                             │
     ┌───────────────────────┼──────────────────────────┐
     ▼                       ▼                          ▼
 Neon Postgres 18       Cloud Storage               Cloud Tasks
 (pooler, modo        bucket app (versiones)       cola general → web:/internal/jobs/run
  transacción;        bucket respaldos (nadie      cola faces  → biometria:/internal/faces/run
  rol golden_app)     borra; solo ciclo de vida)   (token OIDC de golden-invoker)
     ▲                                                  ▲
     │  tabla `jobs` = fuente de verdad (app/jobs.py)   │
     │                                                  │
 Cloud Run Jobs: golden-migrate (alembic, directo, dueño) · golden-bulk (carga masiva, 2 CPU 4 GiB, 24 h)
                 golden-ops (hourly: respaldo, purga, cola, precalentamiento, db-health) ◄── Cloud Scheduler :05
 Secret Manager (golden-*): referenciados por nombre; GitHub Actions por Workload Identity (sin llaves)
 Servidor local (deploy/windows, deploy/local): MISMA imagen en modo `web` + Postgres 16, LOCAL_SERVER=1, sube a la nube cada ~30 min
```

Lo que está bien y hay que conservar: una imagen y un reparto de rutas con una sola fuente (`appmode.py` alimenta a `make_config.py`); fallo cerrado al arrancar (`crypto.assert_ready`, `jobs.assert_handlers`); cola transaccional con arriendo y `SKIP LOCKED`; archivos solo por `Storage`; `/health` sin base; configuración solo por entorno; `hide_parameters=True` en el motor; PII enmascarada en logs; `/internal/*` solo con OIDC.

### A.2 Diagnóstico para el SaaS multiempresa

El modelo actual es **una empresa operadora con muchos clientes finales**:

```
Golden (implícito: staff_users.tenant_id = NULL)
 └── tenants (clientes de Golden: la empresa para la que se hace el evento)
      └── events ── event_attendees ── users (personas; llave compuesta id+tenant_id)
 catálogos, impresoras, estados, tipos, ajustes, CRM, almacén, llaves locales: GLOBALES
```

Para vender a otras empresas de eventos hace falta un nivel arriba y que lo global baje a ese nivel:

```
PLATAFORMA (Golden como operador del SaaS; rol platform_admin)
 ├── organizations (empresa de eventos: Golden, Empresa B, Empresa C…)  ← NUEVO
 │    ├── identidad legal y marca (nombre, NIT, correo privacidad, política + versión + hash, logo, remitente)
 │    ├── org_entitlements (plan: módulos encendidos, cuotas, facial sí/no, servidor local sí/no)  ← NUEVO
 │    ├── staff_users.org_id (TODO el personal pertenece a una empresa; platform_admin aparte)
 │    ├── tenants.org_id (sus clientes finales)  →  events (ya llevan tenant_id)  →  personas
 │    ├── catálogos, estados, tipos, impresoras, ajustes, notas, colores, cuentas de cobro, llaves locales: org_id
 │    └── CRM: SOLO Golden (decisión 22-nov) → módulo con entitlement `crm` que solo la plataforma concede
 └── infraestructura compartida (pooled): misma base, mismos servicios, mismas colas
      + RLS en Postgres (segunda cerradura) + cuotas por plan (vecino ruidoso)
```

**Modelo elegido: *pooled* (base compartida, columna `org_id` + RLS).** Un proyecto de Neon por empresa (*silo*) costaría US$19+/mes por empresa y rompería el tope de US$40; un esquema por empresa complica Alembic y el pooler. *Pooled* es lo que usan la mayoría de SaaS de este tamaño y cabe en el presupuesto: el costo marginal de una empresa más es casi cero hasta que su carga lo justifique.

### A.3 Plan exacto en `app/` (para el agente de `app/`; archivo → función → cambio)

Orden de piezas (cada una desplegable sola, sin que nada cambie para Golden):

1. **Migración `0162_organizations`** (`alembic/versions/`): tabla `organizations(id serial, slug unique, name, nit, legal_address, legal_phone, privacy_email, policy_version, policy_hash, sender_email, brand_color, logo_key, created_at, archived_at)`; fila 1 = Golden (valores de `common.yaml`). Columna `org_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations` en: `staff_users`, `tenants`, `events` (desnormalizada para RLS barata), `event_states`, `event_types`, `inventory_categories`, `inventory_products`, `inventory_units`, `print_devices`, `print_stations`, `print_routes`, `app_settings` (pasa a llave compuesta `org_id,key`), `alert_recipients`, `calendar_notes`, `saved_colors`, `payment_accounts`, `local_server_keys`, `local_nodes`, `notifications`, `event_templates`, `badge_templates`, `saved_badge_templates`, `saved_form_templates`, `super_events`, `infra_costs`, `jobs` (para cuotas y diagnóstico). `DEFAULT 1` deja todo lo existente en Golden y la migración es aditiva (bloqueo de milisegundos; patrón ya usado en 0073). Después, en una segunda migración, quitar el `DEFAULT`.
2. **`app/models.py`**: clase `Organization`; `org_id` en las clases anteriores; `StaffUser.role` admite `platform_admin` (nuevo valor por encima de `super_admin`; `super_admin` pasa a ser «admin de SU empresa»). `STAFF_ROLES` no cambia de orden para no tocar 395 llamadas; `platform_admin` se trata en `effective_roles`.
3. **`app/auth.py`**: `get_current_staff` carga `staff.org_id`; nueva `assert_org(obj, staff)`; `assert_event_tenant` y `scope_events_query` **dejan de leer `ENFORCE_STAFF_TENANT`** y filtran siempre por `org_id` (y por `tenant_id` cuando el usuario lo tiene). `require_platform_role` pasa a exigir `platform_admin`. Las pruebas que hoy ponen la variable a 1 (`tests/test_tenant_*`) quedan como pruebas normales.
4. **`app/database.py` + `app/main.py`**: dependencia `get_db` que, dentro de la transacción de cada petición, ejecuta `SET LOCAL app.org_id = :id` (es `SET LOCAL`, de transacción: compatible con el pooler en modo transacción; la regla de CLAUDE.md prohíbe `SET` de **sesión**). Para las rutas públicas (`/f/`, `/b/`, `/aceptar/`…) el `org_id` sale del recurso (formulario, token), nunca del cliente.
5. **Migración `0163_rls`**: `ALTER TABLE … ENABLE ROW LEVEL SECURITY` + política `USING (org_id = current_setting('app.org_id', true)::int)` en las tablas con `org_id`; rol `golden_app` sin `BYPASSRLS`; el dueño (migraciones, respaldos) lo conserva. Con esto, una consulta sin filtro **devuelve vacío** en vez de datos ajenos. Se enciende tabla por tabla, primero en staging, con la prueba `tests/test_rls.py` (dos empresas, mismo `event_id`, 404).
6. **`app/org_settings.py`** (nuevo): lee identidad/remitente/política de `organizations` con caché por proceso (60 s); `app/legal.py`, `app/mailer.py`, `templates/base.html` y los correos pasan de `os.getenv("COMPANY_NAME")` a `org_settings.current()`. Las variables de `common.yaml` quedan como valores de la fila 1 en la migración y como **respaldo** si la fila no tiene valor.
7. **`app/entitlements.py`** (nuevo) + tabla `org_entitlements(org_id, key, value, updated_at)`: `enabled(org, "crm")`, `quota(org, "people_per_event")`. `app/almacen.py:48`, `app/inventory.py:243`, `app/routers/crm.py` y el formulario de persona leen primero el entitlement y, si no existe, la variable de entorno (compatibilidad). `crm` solo lo concede `platform_admin`.
8. **`app/routers/platform.py`** (nuevo, solo `platform_admin`): CRUD de empresas, planes, cuotas, llaves de servidor local por empresa, «entrar como» con auditoría (`audit_actions`). Pantalla `templates/plataforma.html` con tokens `--gw-*`.
9. **`app/bulk_jobs.py`, `app/jobs.py`**: `enqueue` escribe `org_id`; `bulk_jobs.start` rechaza si la empresa ya tiene `quota("bulk_concurrent")` cargas en curso; `jobs._claim` ordena por «evento en proceso primero» (ya guarda `run_at`; agregar `priority`).
10. **`app/server_keys.py`, `app/node_sync.py`**: la llave nace con `org_id`; el nodo local recibe `org_id` al activarse y lo manda en cada subida; la nube rechaza paquetes de otra empresa.
11. **`app/storage.py`**: claves con prefijo de empresa `org/<id>/<tenant>/…` para lo nuevo (`key_of`), manteniendo la lectura de las claves viejas de Golden (ya tolera `data/`).

Estimación: piezas 1-5 (seguridad) 60-80 h; 6-8 (identidad, planes, pantalla) 60-80 h; 9-11 (cuotas, local, archivos) 40-60 h. Total 160-220 h.

### A.4 Por qué RLS y no «revisar cada consulta»

Hay ~2.000 consultas en 86 routers. Revisar una a una encuentra el 95 % y deja el 5 % que cuesta un incidente. RLS hace que la base **no devuelva** filas de otra empresa aunque la consulta lo olvide; el filtro en SQLAlchemy sigue existiendo (rendimiento e índices), RLS es la red de seguridad. Costo: una política por tabla y `SET LOCAL` por transacción (microsegundos). Es el estándar de multi-tenant *pooled* en Postgres (y lo que Neon recomienda).

### A.5 Planes y cuotas (lo que hoy está en `config.sh`)

| Hoy (variable de entorno) | Mañana (entitlement por empresa) |
|---|---|
| `CRM_ENABLED` | `crm` (solo Golden) |
| `ALMACEN_ENABLED` | `almacen` |
| `PERSON_FORM_ENABLED` | `person_form` |
| `CONTINGENCY_ENABLED` | `kiosk_offline` |
| (no existe) | `facial` (sí/no por empresa: hay empresas que no quieren biometría ni su carga legal) |
| (no existe) | `local_server`, `max_events_in_progress`, `people_per_event`, `bulk_concurrent`, `forms_payments` |

Las variables de entorno quedan solo como **tope de plataforma** (p. ej. `FACIAL_PLATFORM_ENABLED=1`): si la plataforma lo apaga, ninguna empresa lo tiene.

---

## Anexo B · Pasada 2: Ingeniero DevOps/SRE

### B.1 Contra 12-factor

| Factor | Estado | Evidencia |
|---|---|---|
| I Código base, II Dependencias | ✓ | un repo; `requirements.txt` fijo; ruedas compiladas en la etapa 1 del `Dockerfile` |
| III Configuración | ◐ | todo por entorno, pero parte vive en `~/.golden-*.env` de Cloud Shell (#8) y los interruptores de negocio en `config.sh` (#3) |
| IV Servicios de respaldo | ✓ | `DATABASE_URL`, `STORAGE_BACKEND`, `JOBS_BACKEND` intercambiables (local/VM/nube) |
| V Construir-publicar-correr | ◐ | imagen por commit (`app:<sha>`), pero el camino manual construye en Cloud Shell (#4) |
| VI Procesos sin estado | ✓ | `STORAGE_LOCAL_DIR=/tmp` en la imagen; matriz facial en memoria se reconstruye |
| VII Puerto, VIII Concurrencia | ✓ | Gunicorn/uvicorn por `PORT`; procesos por `WEB_CONCURRENCY`, instancias por Cloud Run |
| IX Desechabilidad | ✓ | `lifespan` detiene cola y marca cargas interrumpidas; `graceful_timeout=10` = lo que da Cloud Run |
| X Paridad dev/staging/prod | ◐ | misma imagen; staging sin Wompi/correo por diseño; `FIREBASE_DEPLOY=0` en staging cambia el reparto de rutas (sirve TODO desde `web`) |
| XI Logs como flujos | ✓ | JSON a stdout, `request_id`, trace, PII enmascarada (`app/obs.py`) |
| XII Tareas administrativas | ✓ | Jobs de Cloud Run con la misma imagen (`golden-migrate`, `golden-ops`) |

### B.2 Contra prácticas SRE

- **SLI/SLO:** no definidos. Propuesta mínima y gratis: disponibilidad `/health` ≥ 99,5 % mensual (ya se mide con el chequeo de uptime), latencia p95 de `web` < 2 s durante eventos en curso, 0 trabajos `failed` sin revisar en 24 h. Con eso las 3 alertas actuales + 2 nuevas (#10) cubren los SLO.
- **Alertas:** `/health` caído (2 min), Job fallido, > 20 5xx en 5 min, ausencia del Job horario (2 h). Falta latencia y cola fallida.
- **Runbooks:** `docs/13_RUNBOOK_PRODUCCION.md` (dos cortes, muy buenos), `docs/runbook_evento.md`, `deploy/gcp/README.md`. Falta uno de **incidente** (quién mira qué en 5 min; hoy es «mandarle la tabla a Claude»). 2 h.
- **Capacidad:** probada (docs/14, docs/15 Fase 4, prueba «rush» 19-nov). Topes: 10 instancias por servicio; Neon máx. CU manual (#12).
- **Cambios:** congelamiento automático con eventos (`/api/ops/deploy-allowed`), migraciones antes que servicios, vuelta atrás por revisiones. Falta comprobación automática post-despliegue (#9).
- **Postmortems:** `docs/historial.md` cumple ese papel (causa raíz y arreglo). Bien.
- **Toil:** `manual_deploy.sh` + `~/.golden-*.env` + «un comando por mensaje» es trabajo manual repetido en cada despliegue; el orden 2 y 4 de §4 lo quitan.

### B.3 Contra OWASP ASVS (nivel 1-2, solo lo arquitectónico)

| Área | Estado |
|---|---|
| V1 Arquitectura: separación público/privado | ✓ servicio `publico` aparte sin dlib; `BodyLimitMiddleware` en rutas públicas |
| V2/V3 Autenticación y sesión | ✓ bcrypt, sesión firmada, sesión única, bloqueo del digitador, `must_change_password`; cookie `__session` |
| V4 Control de acceso | ◐ roles sólidos; aislamiento por cliente **opcional** (#2) |
| V6 Criptografía | ✓ rostro con Fernet y rotación por lista de llaves; secretos en Secret Manager; llaves de cobro cifradas |
| V7 Registro | ✓ PII enmascarada; `audit_actions`, `audit_consent_logs` solo INSERT |
| V12 Archivos | ✓ claves normalizadas (`..` rechazado); nunca `FileResponse` sobre `data/` |
| V13 API | ✓ CSRF por `Origin`; `/internal/*` con OIDC; límites de tasa (`rate_limit_events`) |
| V14 Configuración | ◐ docs/openapi apagados en producción; imágenes y acciones sin fijar por huella (#11); todos los secretos en los 3 servicios (#5) |

### B.4 Costo y escalabilidad (con la regla de US$40)

- **Estructura de costo actual** (lo que el código limita): Cloud Run por uso con `min-instances` 0 salvo precalentamiento con actividad real (`app/warmup.py`); Neon dormido sin actividad (`suspend_timeout` 0 = 5 min; modo tranquilo del Job: respaldo cada 8 h sin actividad); staging apagado por defecto; sin balanceador ni VM. Coherente con «típico US$22-35».
- **Lo que puede romper el tope:** máx. CU de Neon puesto a mano (#12); 10 instancias × 3 servicios en un pico largo (es el tope correcto: ~US$1,5/h en el peor caso, se acaba cuando acaba el evento); cargas masivas con foto de 24 h en `golden-bulk` (2 CPU 4 GiB ≈ US$0,20/h).
- **Para el SaaS:** el costo marginal por empresa es ~0 hasta que su carga lo exija; el riesgo no es el costo sino el **vecino ruidoso** (#13). Las cuotas por plan son la herramienta, no más infraestructura. Si una empresa grande lo justifica, se le vende su propio entorno (otro proyecto de Google + Neon, mismo `bootstrap.sh`): el diseño ya lo permite sin cambiar código.

### B.5 Límites de Cloud Run / Neon que el diseño respeta (y los que hay que vigilar)

Respetados: 60 s por petición detrás de Firebase (lo largo va a Jobs); 10 s de gracia al apagar; rutas que terminan en «z» reservadas; una sola cookie detrás de Hosting; pooler en modo transacción (sin `SET` de sesión, sin temporales, sin `LISTEN`); migraciones por conexión directa; respaldos con `pg_dump` 18 (cliente oficial en la imagen). A vigilar: `max_connections` reales del cómputo de Neon frente a 400 conexiones de cliente posibles (#18; el pooler lo absorbe, pero una consulta larga ocupa una conexión real); Firebase Hosting sin dominios comodín (#19); Cloud Tasks 5 despachos/s (suficiente: la tarea es «despierta», no «un trabajo por tarea»).

---

## Anexo C · Pasada 3: crítica cruzada

**El DevOps critica al Arquitecto:**
- «Tu plan de `org_id` + RLS está bien, pero 160-220 h sobre una base en producción con eventos cada semana es un riesgo de cambio enorme. Exige: una migración por pieza, cada una aditiva con `DEFAULT 1`, desplegada a staging y a producción por separado, y RLS encendido tabla por tabla con una prueba automática de dos empresas por tabla. Nada de un *big bang*.» → **Aceptado**: así quedó escrito en A.3 (pieza 1 con `DEFAULT 1`, pieza 5 tabla por tabla).
- «`SET LOCAL` por transacción: CLAUDE.md prohíbe `SET` de sesión; `SET LOCAL` es válido con PgBouncer en modo transacción, pero hay que probarlo contra el pooler de Neon en staging **antes** de escribir una sola política.» → **Aceptado**: es la primera prueba de la pieza 4.
- «Pones planes y cuotas en la base y dejas las variables como tope: bien, pero entonces `config.sh` y `deploy.sh` deben dejar de escribir `CRM_ENABLED`/`ALMACEN_ENABLED`, y `tests/test_crm_c1b_texto.py` los exige. Cambia las pruebas en la misma pieza.» → **Aceptado**, anotado en A.5.

**El Arquitecto critica al DevOps:**
- «Tu hallazgo #4 (despliegue manual con cuenta dueña) es correcto, pero la causa no es `manual_deploy.sh`: es que el *binding* de identidad federada solo acepta `migra/fase1-2` y la gente trabaja en `feat/`. Arregla la causa (ramas permitidas) y el síntoma desaparece.» → **Aceptado**: así está en §4 orden 2.
- «Pediste `lock_timeout` en el Job de migraciones y lo pusiste en `deploy.sh`. Bien como parche; el sitio correcto es `alembic/env.py` (`connect_args={"options": …}`), para que valga también en el servidor local y en desarrollo. Déjalo en el plan de `app/`.» → **Aceptado**: pieza adicional para el agente de `app/`: `alembic/env.py`, `run_migrations_online`, `connect_args={"options": os.getenv("MIGRATE_PGOPTIONS", "-c lock_timeout=10s -c statement_timeout=840s")}`; cuando esté, `deploy.sh` solo pasa `MIGRATE_PGOPTIONS`.
- «Tus alertas nuevas (#10) están bien, pero la métrica de latencia de Cloud Run mide hasta la respuesta del contenedor, no lo que ve el digitador detrás de Firebase. Súmale el tiempo `took_ms` que ya guarda `access_logs` (0079) como SLI de negocio en `/sistema`.» → **Aceptado**, 2 h adicionales en el orden 5.
- «En el hallazgo #19 dices "slug en la ruta". No: el slug en la ruta obliga a tocar 86 routers y `event_only.py`. La empresa va en la **sesión** (y en `app.org_id` de la transacción); la ruta no cambia.» → **Aceptado**, A.3 pieza 4 lo dice así.

**Lo que los dos coinciden en NO hacer:** un esquema o una base por empresa; subdominios comodín; un segundo proveedor de nube «por si acaso»; reescribir la cola o el almacenamiento (están bien).
