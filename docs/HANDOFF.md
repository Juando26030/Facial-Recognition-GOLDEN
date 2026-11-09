# Handoff — migración a Cloud Run + Neon (estado al 2026-09-29)

> ## ESTADO ACTUAL (9-nov-2026, noche) — léelo primero
> **Producción = Fase 4** (commit `2c8c4d7`, migración `0104`, desplegado el 9-nov con autorización de Juan David; `main` aún sin fusionar). **Fases 5 a 9 programadas en `f5/integracion`, sin probar con base ni desplegar** (Cloud Shell sin cuota hasta el 11-nov 14:05; GitHub Actions bloqueado por facturación). Migraciones nuevas `0105`–`0121` (sin 0117 ni 0120), cadena verificada por `tests/test_cadena_migraciones.py`.
> Revisión del 9-nov: [`REVISION_F5-9_PLAN_VS_CODIGO.md`](REVISION_F5-9_PLAN_VS_CODIGO.md) (plan contra código), [`seguridad/F5-9_RESUMEN.md`](seguridad/F5-9_RESUMEN.md) (ronda de seguridad y decisiones abiertas), [`ux/REVISION_VISUAL_F5-9.md`](ux/REVISION_VISUAL_F5-9.md). Configuración de nube ya hecha por Juan David el 9-nov: secretos `golden-onedrive-*`, `golden-backup-copy-encryption-key`, `golden-payment-keys-encryption-key`; retraso de destrucción de 7 días en las llaves; sitio SharePoint «Respaldos GoldenWeb» + app Entra «GoldenWeb copia semanal» (Sites.Selected, rol write). Al desplegar: `PUBLIC_FORMS_BASE_URL`, `ONEDRIVE_DRIVE_ID`, `GCP_BILLING_EXPORT_TABLE` (no son secretos pero no van en este repo público: están en el documento 43 del proyecto de Claude).
>
> ## ESTADO ANTERIOR (8-nov-2026, noche)
> **Fase 4 (Equipo del evento) CERRADA por Juan David** en `f4/integracion` (staging, despliegue 61). Resumen y pendientes: [`CIERRE_FASE_4.md`](CIERRE_FASE_4.md). Producción sigue en `main` sin Fase 2, 3 ni 4. **Siguiente: Fase 5 (Crear y configurar eventos).** Falta antes de producción: suite completa con base de datos sobre el SHA final (`scripts/pruebas_cloudshell.sh`, la corre Juan David) y su autorización del commit exacto. Migraciones nuevas de esta fase: `0100` a `0104`.
>
> ## ESTADO ANTERIOR (7-nov-2026, noche)
> **Fase 1 cerrada; Fase 2 entregada en staging; Fase 3 en curso.** Producción corre `main` (`1951bea`, 7-nov 02:16) y **no tiene nada de la Fase 2 ni de la Fase 3**. Resumen para Juan David: [`CIERRE_FASE_2.md`](CIERRE_FASE_2.md).
>
> | Qué | Estado |
> |---|---|
> | Rama `f2/integracion` | Integra la Fase 2 y la Fase 3 (oleadas 1 a 5 y modo tranquilo). Commit más reciente al escribir esto: `a34b6bc` (pulido visual del calendario); queda por delante lo que se fusione después: ver `git log f2/integracion`. En staging, sin fusionar a `main`. |
> | Migraciones en staging | `0087_event_templates`, `0088_archive_and_audit`, `0089_staff_archive`, `0090_event_archive`, `0091_people_forms_archive`, `0092_catalogs_archive`. Todas aditivas. La última a la fecha es la `0092`. |
> | Ramas de la Fase 3 en curso (NO fusionadas) | `f3b/docs-gastos` (migración `0093`), `f3b/crud-huecos` (migración `0094`), `f3b/seguridad` (alcance por cliente). Cada una sale de `f2/integracion`. Al fusionar, revisar que `0093` y `0094` queden en cadena (un solo extremo en Alembic). |
> | Rama de documentación | `f3b/cierre-fase2` (este cierre). |
> | Pendientes grandes | Prueba completa con base de datos en Cloud Shell (~47 min) sobre el SHA final; Strix y ZAP contra staging; `ENFORCE_STAFF_TENANT` (decide Juan David); CSP estricto; pantalla para restaurar colores y plantillas. Tablero en `FASE_3_AUDITORIA.md`. |
> | GitHub Actions | Bloqueado por facturación: se despliega a mano. |
>
> ### Desplegar a staging (lo corre Juan David en Cloud Shell)
> ```bash
> export REGION=us-east4
> export GOOGLE_CLOUD_QUOTA_PROJECT=goldenweb-staging
> git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN && cd Facial-Recognition-GOLDEN
> git checkout <rama o SHA>          # p. ej. f2/integracion
> nohup bash deploy/gcp/manual_deploy.sh staging <ID-del-proyecto-staging> > ~/deploy.log 2>&1 &
> tail -f ~/deploy.log               # el build de dlib puede tardar 20-60 min; si se corta, repetir el mismo comando
> ```
> Si el clon ya existe: `git fetch && git checkout <SHA>` y repetir el `nohup`. Producción usa el mismo script con `production`, solo con autorización explícita (ver `CIERRE_FASE_2.md` §5).
>
> ### Apagar y encender staging (`deploy/gcp/staging_power.sh`)
> ```bash
> bash deploy/gcp/staging_power.sh status   # solo lee
> bash deploy/gcp/staging_power.sh on       # SOLO mientras se prueba
> bash deploy/gcp/staging_power.sh off      # al terminar (por defecto staging queda apagado)
> ```
> Pausa la tarea horaria de staging y su alerta para que la base de Neon descanse. Se niega a tocar producción.
>
> Reglas que no cambian: nada a `main`, ni merge, ni despliegue a producción, ni migración en producción sin autorización explícita de Juan David para esa acción.


> **ESTADO ACTUAL (5-nov-2026): las Fases 0 y 1 (0A, 0B, 0C, 1A, 1B) están CERRADAS por Juan David** — ver [`CIERRE_FASES_0_1.md`](CIERRE_FASES_0_1.md). Producción corre en Cloud Run + Neon (`app.golden-eventos.com`), desplegada con el workflow manual `cloudrun.yml` (confirm=DESPLEGAR). Lo siguiente es la **Fase 2** (diseño y calendario; plan en `29_PLAN_MAESTRO…`). **Lo que sigue abajo es el estado de la migración al 29-sep-2026 y se conserva como historia: la VM y la rama `migra/fase1-2` ya no son el camino de producción.** Lo vigente: `CLAUDE.md`, `15_MIGRACION.md` (progreso), `13_RUNBOOK_PRODUCCION.md`, `19_GUIA_PRODUCCION.md`.

Documento para que una sesión nueva retome sin perder contexto. Complementa (no reemplaza) a [`docs/15_MIGRACION.md`](15_MIGRACION.md)
(progreso pieza por pieza), [`docs/13_ARQUITECTURA_ESCALABILIDAD.md`](13_ARQUITECTURA_ESCALABILIDAD.md) (plan, §15-§16 = decisiones
de la migración) y [`docs/14_FASE0_RESULTADOS.md`](14_FASE0_RESULTADOS.md) (carga y reconocimiento facial). Reglas técnicas del código:
[`CLAUDE.md`](../CLAUDE.md); historia detallada: [`docs/historial.md`](historial.md).

## 1. Dónde está todo

| | Estado |
|---|---|
| `main` | `f3a7260`: Fase 0 de escalabilidad, **desplegada en la VM** (Gunicorn 3 procesos, migraciones hasta `0048`). `RECOGNITION_JITTERS=2` activo en producción (lo puso Juan David). |
| `migra/fase1-2` | Adelante de `main`, empujada, CI y workflow «Cloud Run» en verde. Migraciones nuevas `0049_form_atomic_reserve`, `0050_bulk_job_spec` (no aplicadas en producción). **No fusionar sin autorización.** |
| Nube | **Nada creado todavía.** `deploy/gcp/bootstrap.sh` está listo y revisado por Juan David; lo corre ÉL en Cloud Shell. |
| Neon | Proyecto `goldenweb` (AWS us-east-1, Postgres 18), base `golden_db`, dueño `golden_db_owner`, ramas `production` y `staging`. **Plan Launch** activo; Juan David creó una llave de API y conectó Neon a GitHub (esa integración no la usa nuestro flujo). |
| Rama `staging` de Neon | Tiene una copia del respaldo de producción del 26-sep (389 filas, 36 tablas) migrada a `0050`, con el rol `golden_app` creado. La contraseña de `golden_app` cambiará cuando se corra el bootstrap de staging (usa `--rotate`). |
| Este PC (Windows) | Python 3.13 en `C:\Users\USUARIO\AppData\Local\Programs\Python\Python313\python.exe` (el de PATH, 3.14, no tiene pytest). Docker Desktop funciona (`golden-app:local` construida con `pg_dump` 18). psql/pg_dump 18 por Docker (`postgres:18`). Postgres 17 local para `golden_test`. `.env.staging` (ignorado) con las cadenas de Neon staging: `DATABASE_URL` = `golden_app` por el pooler, `DIRECT_DATABASE_URL` = dueño directo. Fotos de prueba en `C:\JDRJ\Golden\fotos_prueba` (39 personas útiles; montar SIEMPRE en solo lectura). |

## 2. Hecho y probado
**Sesión 1 (código listo para Cloud Run + Neon):** cupo de formularios en una sola ida y vuelta (`form_reserve_slot`, pruebas de
concurrencia); `GcsStorage` (probado contra el emulador `fsouza/fake-gcs-server`); cola por Cloud Tasks (la tabla sigue mandando;
`/internal/jobs/run` vacía la cola dentro de la petición con presupuesto de 45 s); directorio por páginas + incremental cada 15 s (visto
por Juan David); subida directa de archivos grandes con URLs firmadas (Cloud Run corta a 32 MiB); Dockerfile multi-etapa (una imagen,
tres servicios, sin root) levantado con docker-compose contra Neon staging.

**Sesión 2 (infraestructura como código):** carga masiva con fotos como Cloud Run Job (el servicio web solo guarda tokens); Job horario
de operaciones `app/ops_runner.py` (respaldo cada hora + diario a las 3, purga biométrica a las 4, revisión de respaldos, barrido de la
cola, precalentamiento) — **probado desde el contenedor** contra Neon staging y el emulador, y el respaldo restaurado con conteos
idénticos; precalentamiento `app/warmup.py` (instancias mínimas + Neon) sin consultar la base a cada rato; rol `golden_app` en Neon
(`scripts/neon_app_role.py`, aplicado en staging, la app funciona con él); migración de la base VM→Neon (`scripts/migrate_db_to_neon.py`,
**probada con el respaldo real de producción contra staging: 389 filas idénticas**) y de archivos VM→GCS (`scripts/migrate_files_to_gcs.py`,
MD5, probado contra el emulador); `deploy/gcp/bootstrap.sh`, `deploy.sh`, `config.sh`; workflows `cloudrun.yml` (staging en cada push a
`migra/fase1-2`, producción con `if: false`) y `cloudrun-deploy.yml`; Firebase Hosting con rutas generadas desde `app/appmode.py`.

**Revisión de Juan David (R1-R4) + prueba facial:** permisos de despliegue a nivel de recurso y por rama; `/internal/*` solo con OIDC del
invoker (401/403); el bootstrap no duplica el presupuesto existente («GoldenWeb mensual», COP 160.000); retención biométrica (versiones
viejas en 1 día, sin soft delete, máximo 61 días por los respaldos diarios); reconocimiento facial con 39 personas (tabla en docs/14 §6.2).

Pruebas: 380 en verde (`python -m pytest -q`), 2 se saltan sin el emulador (pasan con él), `node tests/js/directory_paging_check.js`,
ruff limpio en lo tocado, shellcheck y actionlint limpios.

## 3. Decisiones y su porqué
- **Región `us-east4` (decidida el 2026-09-29).** Nivel 1 igual que us-east1; junto a Neon (Virginia). Sin valores fijos: `REGION` o `gcloud config set run/region`. Todo lo regional en la MISMA
  región (buckets nuevos `<proyecto>-golden-*-<región>`). Staging se traslada de us-east1 con `deploy/gcp/move_region.sh` (docs/15 «Mover a otra región»); producción nace en us-east4.
- **Neon (plan Launch)** en vez de Postgres en una VM: cobra por uso y se apaga solo. La app usa el pooler con `golden_app` (solo DML);
  migraciones, respaldos y restauraciones usan el dueño por conexión directa. Nada frecuente puede tocar la base (se mantendría despierta).
- **Firebase Hosting** para el dominio (el balanceador de Google cuesta fijo; el mapeo de dominios de Cloud Run no es para producción;
  Cloudflare gratis no reescribe `Host`). Límites verificados: 60 s por petición, solo pasa la cookie `__session`, respuestas privadas salvo
  `public`. Cloudflare Worker queda como plan B.
- **Staging en un proyecto de Google Cloud aparte (recomendado, pendiente de que Juan David decida):** Firebase Hosting solo da permisos a
  nivel de proyecto y solo reenvía a Cloud Run del mismo proyecto; un proyecto aparte aísla todo sin costo. Si se queda en el mismo
  proyecto, staging no tiene Firebase y su servicio web sirve la app completa (`app.main:app`).
- **Umbral 0,55 y `RECOGNITION_JITTERS=2`:** con 39 personas, 0,55 reconoce 97 % sin falsos positivos; 0,50 deja de reconocer 1 de cada 8-12
  sin ganancia medida. El margen es estrecho (impostor más cercano a 0,54): el riesgo real es alguien NO registrado parecido a alguien
  registrado. Propuestas (no implementadas): foto de registro en la tarjeta de confirmación y regla de «segundo más cercano».
- **Retención biométrica (desde la sesión 4):** 7 días después de que TODOS los eventos de la persona estén finalizados (tope 180 desde la captura); el encoding cifrado
  puede seguir hasta **30 días** en los respaldos diarios (antes 60). Ventana de historia de
  Neon: fijarla en 1 día (paso manual).
- **Una sola tarea de Cloud Scheduler** (cabe en las 3 gratis) reemplaza los 4 cron de la VM; en producción se crea EN PAUSA hasta el cambio.
- **Carga masiva como Cloud Run Job** (no cola dentro de la petición: hay cargas de horas y el tope por petición es 60 s).

- **Permisos de coordinador (decisión del dueño, 2026-11-04):** super_admin, admin y todos los coordinadores configuran cualquier evento y acceden a todos; comercial, digitador y cliente no. `ENFORCE_STAFF_EVENT_SCOPE` sigue APAGADO por defecto (no encenderlo sin que Juan David lo pida). Fijado en `tests/test_permisos_coordinador.py`; detalle en docs/15.

## 4. Reglas de trabajo (las de siempre)
- Rama `migra/fase1-2` para esta migración; se puede empujar. **Prohibido sin autorización explícita para ESA acción:** merge o push a
  `main`, desplegar en producción, correr migraciones en producción, crear recursos de nube (los crea Juan David), pruebas de carga
  contra producción.
- Commit + push por cada pieza terminada con sus pruebas en verde, y la lista de `docs/15_MIGRACION.md` al día en el mismo commit.
- Secretos y cadenas de conexión: nunca en el repo ni en el chat (solo nombres de variables). Nada de fotos, encodings ni resultados por
  persona en el repo, logs o commits. Si algo requiere un secreto, se pide que lo ponga Juan David en `.env.staging` o en el bootstrap.
- Ante una ambigüedad: decidir, documentar y seguir. Antes de cerrar una sesión o al acercarse al límite: commit, push y progreso al día.

## 5. Riesgos pendientes
1. `bootstrap.sh` y `deploy.sh` nunca han corrido contra el proyecto real: los permisos a nivel de recurso (`run.developer` sobre Jobs,
   esperar ejecuciones con `--wait`) y los comandos de Firebase/Monitoring siguen la documentación oficial pero se confirman en la primera
   corrida. Ambos scripts son idempotentes: se corrige y se vuelve a correr.
2. Producción necesita la `SECRET_KEY` y la `FACE_ENCRYPTION_KEY` ACTUALES de la VM; sin la llave de rostros, los rostros migrados no se leen.
3. Posición de la IP real en `X-Forwarded-For` detrás de Firebase (`XFF_CLIENT_INDEX`) sin verificar: hasta entonces los límites por IP se
   podrían esquivar. Se verifica con tráfico real en staging.
4. Margen estrecho del reconocimiento facial (ver §3): antes de un evento grande con registro automático, medir con más personas y con
   personas no registradas.
5. El respaldo horario despierta a Neon unos minutos por hora (~US$1-2/mes).
6. El precalentamiento de Neon (apagado/mínimo) necesita plan Launch: ya está.
7. Copias del mundo VM (`gs://<bucket-datos>/data/` con fotos, volcados viejos) siguen su propia retención hasta limpiarlas tras el cambio.

## 6. Siguientes pasos exactos (actualizado 2026-09-29, sesión 4)
**Hecho en la sesión 4 (rama `migra/fase1-2`, 414 pruebas en verde):** D.1 arreglos del Job de ops/bootstrap/Actions/distintivo STAGING; B retención biométrica de 7 días tras finalizar
(tope 180; migración `0051`; purga horaria; botón «Borrar fotos del evento»; respaldos a 30 días); A verificación del operador (foto de registro, confianza, «Ver 5 más cercanos», DUDOSO con
`MATCH_MARGIN`, recomendado 0,10); C textos de privacidad y consentimiento (marcados PENDIENTE DE REVISIÓN LEGAL); D.2 scripts y pasos (latencia/región, IP real, carga distribuida, simulacros,
runbook de cutover). Detalle: `docs/15_MIGRACION.md` «Sesión 4».

**Juan David, en este orden** (lista completa con comandos en docs/15 y en el resumen de la sesión):
1. Neon: historia de 1 día. Aplicar el ciclo de vida de 30 días al bucket de staging (comando en docs/15, B4). Borrar `C:\JDRJ\Golden\fotos_prueba`.
2. Revisión legal de los textos nuevos (`/privacidad` y consentimientos). Decidir `MATCH_MARGIN` (recomendado 0,10 ya en `common.yaml`).
3. Dejar que el push despliegue staging (corre la migración `0051`); correr `backup-daily` una vez; `bootstrap.sh staging` si se quiere recrear el paso 12 sin cuelgue.
4. D2.1: medir latencia desde us-east1 y us-east4 (Job temporal) y decidir región. D2.2: `/api/ops/client-ip` con tráfico real y fijar `XFF_CLIENT_INDEX`.
5. D2.3: `deploy/loadtest/run_phase4.sh build|seed|run|report|verify|cleanup` y los simulacros 1 y 2.
   Ronda 3 pendiente: desplegar, `scale-up` (máx 10), correr con `SERVER_TIMING=1` y ver dónde queda la latencia («[fuera de la app]» en el informe); D (`FORM_STATE_CDN_SECONDS=4`) se prueba en una corrida aparte; después, UNA variable por corrida (THREADPOOL_SIZE / DB_POOL_SIZE / concurrencia). Docs/15 «2.ª ronda».
6. Semana 3: runbook D2.4 (con autorización explícita para cada acción de producción).

**Pendientes de código:** regla DUDOSO en el Control de Áreas; cupo + INSERT en una sola función SQL si se queda us-east1; tabla de costos; Fase 3 (contingencia del kiosco).
