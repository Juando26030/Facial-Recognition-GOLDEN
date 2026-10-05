# Guía de ejecución de producción — para Juan David

Qué es: el paso a paso para poner **la primera producción en Google Cloud** con el candidato actual (rama `migra/fase1-2`) y **`CONTINGENCY_ENABLED=0`** (no hay usuarios ni datos reales todavía). El modo sin conexión es **requisito del piloto y irá ENCENDIDO en producción**, pero lo enciende **Juan David** (una línea de `deploy/gcp/config.sh`, por PR) después de probarlo en dispositivos reales; `CONTINGENCY_ENABLED` queda como interruptor de emergencia. Claude no cambia ese valor. Todo lo de nube lo ejecuta Juan David; Claude Code
prepara ramas, flujos y scripts y no corre nada en la nube. Las mejoras (recarga sin red, B8, estados, 7a/7b…) llegan **después**, por PR normal a `migra/fase1-2`.
Reemplaza el orden de `docs/15` D2.4 y D2.5; los criterios y el porqué siguen allí (D2.5: ramas, neutralizar la VM, runners; D2.5f: respaldos y Scheduler; D2.5g: monitores).

**Cómo leer cada paso:** *Dónde* (consola o Cloud Shell) · *Qué hacer* (comando exacto) · *Debe verse* (si no, no sigas) · *Si falla*.
Convención: `<…>` = lo reemplazas tú. Los comandos son para **Cloud Shell** (shell.cloud.google.com) con el proyecto de producción ya elegido, salvo que diga otra cosa.
No pegues secretos en este documento ni en el chat: los pide el script a ciegas y van a Secret Manager.

---

## 0. Antes de empezar: qué decidir y qué preparar

| # | Qué | Decisión / cómo obtenerlo | Ejemplo / valor esperado |
|---|---|---|---|
| 0.1 | **ID del proyecto de GCP de producción** | `deploy/gcp/config.sh` **no fija ningún ID**: lo lee de `gcloud config get-value project` (nunca se escribe a mano). Lo que sí deriva de él: los buckets `<ID>-golden-app-us-east4` y `<ID>-golden-backups-us-east4` (nombre total ≤ 63 caracteres), el número de proyecto (para las URL de Cloud Run) y el sitio de Firebase `golden-app-<número>`. Recomendado: **`goldenweb-prod`** (como `goldenweb-staging`); 6-30 caracteres, minúsculas, dígitos y guiones. Lo creas tú (paso 1b) en la cuenta de facturación **Golden Logistics – GoldenWeb**. | `goldenweb-prod` (o el que elijas: ____________) |
| 0.2 | **Región** | Decidida: **us-east4** (junto a Neon en AWS us-east-1). | `us-east4` |
| 0.3 | **Dominio** | `app.golden-eventos.com`, DNS en Cloudflare (**solo DNS, nube gris**). El sitio de Firebase se llama `golden-app-<número del proyecto>` (lo calcula `config.sh`). | |
| 0.4 | **Base de datos Neon** | Cuenta de Neon **a nombre de la empresa**, plan **Launch**, **AWS us-east-1**, historial de restauración de **1 día**. Recomendado: un **proyecto NUEVO y vacío** `golden-production` (una *rama* de staging heredaría sus datos de prueba y los de la carga). Necesitas la cadena **directa** (host **sin** `-pooler`) del rol dueño. | `postgresql://…@ep-…us-east-1.aws.neon.tech/…` (la pegas a ciegas en el paso 3) |
| 0.5 | **Cuentas con acceso** | Google (propietario del proyecto), GitHub (administrador del repositorio: Environments y Actions), Cloudflare (DNS), Neon, Firebase (mismo Google), UptimeRobot, y un **correo para alertas** (`ALERT_EMAIL`). | |
| 0.6 | **Correo saliente** (escarapela digital, formularios, recuperar contraseña) | Se configura con Microsoft Graph (`azure-tenant-id`, `azure-client-id`, `azure-client-secret`, `graph-sender`). Si no los tienes ahora, el sistema funciona pero **no manda correos**: el piloto los necesita. | prepararlos antes del evento |
| 0.7 | **Pagos (Wompi)** | Para el corte basta el modo de pruebas (`wompi-sandbox-*`). Las llaves de producción se cargan cuando se activen los pagos. | opcional ahora |
| 0.8 | **Presupuesto** | **Ya existe a nivel de la cuenta de facturación y cubre todos los proyectos: no se crea ni se toca.** (`bootstrap.sh`, paso 11, lo detecta y solo lo informa.) | nada que hacer |
| 0.9 | **Llaves nuevas** | La VM no tiene datos reales, así que producción arranca con `SECRET_KEY` y `FACE_ENCRYPTION_KEY` **nuevas** (las genera el script con `FRESH_START=1`). **Copia `FACE_ENCRYPTION_KEY` a un lugar seguro**: perderla = perder los rostros que se registren. | |
| 0.10 | **VM** | Se detiene antes del corte (la dejas encendida si prefieres; lo importante es que **no tenga runner** y que `deploy.yml` no se dispare: paso 1). | |

**Qué ya debe estar listo** (lo preparó Claude): `migra/fase1-2` con CI en verde; la rama `corte/main` con los cambios de flujos (paso 5); `deploy/gcp/scheduler.sh`, `move_region.sh` y `bootstrap.sh` con las comprobaciones de Scheduler; staging en la revisión del candidato.

**Qué NO se hace en esta guía:** migrar datos de la VM (no hay), encender la contingencia, tocar staging.

---

## 1. GitHub: dejar la VM fuera del camino (ANTES de fusionar nada)

*Dónde:* GitHub → repositorio `Juando26030/Facial-Recognition-GOLDEN`.
1. **Settings → Environments → New environment → `production`** → *Required reviewers*: tú. (Así el despliegue a producción espera tu clic aunque alguien fusione por error.) Las variables van en el paso 4.
2. **Actions → «Deploy to production» → ⋯ → Disable workflow.** (Es el que usa el runner de la VM; `main` está ~82 commits atrás y bajaría todo a la VM.)
3. **En la VM** (SSH): detener el runner → `cd ~/actions-runner && sudo ./svc.sh stop` (la carpeta puede variar; `sudo ./svc.sh status`). Opcional: `gcloud compute instances stop golden-biometrics-prod --zone us-central1-a`.

*Debe verse:* en Actions, «Deploy to production» con el aviso *This workflow is disabled*; el runner `self-hosted` en **Offline** (Settings → Actions → Runners).
*Si falla:* sin permisos de administrador no verás Environments; pide acceso antes de seguir.

---

## 1b. Crear el proyecto de GCP de producción (lo haces tú)

*Dónde:* Cloud Shell (o la consola: IAM y administración → Crear proyecto).
```bash
gcloud projects create goldenweb-prod --name="GoldenWeb"          # el ID (goldenweb-prod) es el que usarás en todo; el nombre puede ser el que quieras
gcloud billing accounts list                                       # copia el ID de «Golden Logistics – GoldenWeb» (formato XXXXXX-XXXXXX-XXXXXX)
gcloud billing projects link goldenweb-prod --billing-account <ID de la cuenta de facturación>
gcloud config set project goldenweb-prod && gcloud config set run/region us-east4
gcloud projects describe goldenweb-prod --format='value(projectNumber,lifecycleState)'
```
*Debe verse:* `…  ACTIVE` (con el número del proyecto) y, en `gcloud billing projects describe goldenweb-prod`, `billingEnabled: true`. El presupuesto de la cuenta ya cubre el proyecto: no hay que crear nada.
*Si falla:* sin permiso para vincular facturación necesitas el rol *Billing Account User* en esa cuenta.

---

## 2. Neon: la base vacía de producción

*Dónde:* console.neon.tech.
1. Con la cuenta de Neon de la empresa y plan Launch: **New project** → nombre `golden-production`, región **AWS US East (N. Virginia) / us-east-1**, Postgres **la misma versión que staging** (18).
2. **Settings → Storage / History retention: 1 día.**
3. Copia la **cadena de conexión DIRECTA** del rol dueño (en *Connection details*, apaga «Pooled connection»; el host NO debe contener `-pooler`). No la pegues en ningún chat.

*Debe verse:* proyecto con una base `neondb` (o la que elijas) **sin tablas**.
Prueba rápida (opcional, desde Cloud Shell, sin imprimir la cadena): `psql "$(read -rs u; echo $u)" -c '\dt'` → *Did not find any relations.*
*Si falla:* si el host trae `-pooler`, las migraciones fallarán: usa la cadena directa.

---

## 3. Cloud Shell: crear TODO lo de GCP para producción (`bootstrap.sh`)

*Dónde:* Cloud Shell.
```bash
git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN.git && cd Facial-Recognition-GOLDEN
git checkout migra/fase1-2 && git pull
gcloud config set project <ID del proyecto de producción>
gcloud config set run/region us-east4
FRESH_START=1 bash deploy/gcp/bootstrap.sh production
```
Qué pide (a ciegas, por teclado): cadena directa de Neon; `SECRET_KEY` y `FACE_ENCRYPTION_KEY` (**Enter = generar**); `ops-token` (Enter = generar); los opcionales (Wompi, Azure/Graph, `alert-email`: **pon el correo de alertas**) —Enter para omitir—; correo del canal de alertas; el presupuesto (si ya hay uno que cubra el proyecto, solo lo informa).
Crea: APIs, cuentas de servicio, Workload Identity (solo la rama `main` despliega producción), buckets nuevos en us-east4, cola de Cloud Tasks, 3 servicios y 3 Jobs con imagen de relleno, **la tarea de Cloud Scheduler `golden-ops-hourly` (en pausa)**, el chequeo de disponibilidad `golden-health` y 3 alertas, y el sitio de Firebase.

**Secretos** (todos en Secret Manager, `golden-<nombre>`; nunca en el repositorio ni en el chat): `direct-database-url` (Neon, dueño, directa) · `database-url` (la crea el script para el rol `golden_app`, por el pooler; no la tecleas) · `secret-key`, `face-encryption-key`, `ops-token` (Enter = generar con `FRESH_START=1`; **guarda `face-encryption-key` también en el gestor de contraseñas de la empresa**) · `alert-email` (correo de alertas) · opcionales ahora: `wompi-*` (+ `wompi-sandbox-*` para pruebas), `azure-tenant-id`, `azure-client-id`, `azure-client-secret`, `graph-sender` (correo saliente), `neon-api-key`, `neon-project-id`, `neon-endpoint-id`.
*Debe verse:* al final un bloque **«LISTO (production). Configura en GitHub → Settings → Environments → «production» → Variables»** con cinco valores (`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOYER`, `FIREBASE_SITE`) y la URL de Cloud Run del servicio web. **Cópialos** (paso 4).
Comprobación:
```bash
gcloud run services list --region us-east4 --format='value(metadata.name)'     # golden-biometria golden-publico golden-web
gcloud run jobs list --region us-east4 --format='value(metadata.name)'         # golden-bulk golden-migrate golden-ops
gcloud scheduler jobs list --location us-east4                                  # golden-ops-hourly … PAUSED
gcloud secrets list --format='value(name)' | grep -c .                          # ~15-20
```
*Si falla:* el script es idempotente: corrígelo (permiso, API, cadena de Neon) y vuelve a correr **el mismo comando**; lo que ya existe no se toca. Si el rol `golden_app` no se crea, la cadena de Neon no es la del dueño o es la *pooled*.

---

## 4. GitHub: las variables del Environment `production`

*Dónde:* GitHub → Settings → Environments → `production` → **Variables** (no son secretos). Pega los 5 valores del bloque «LISTO» del paso 3.
*Debe verse:* 5 variables con esos nombres. *(Si falta alguna, el flujo de despliegue se salta con un aviso «El Environment no tiene las variables de GCP» en vez de fallar.)*

---

## 5. El PR del corte y el primer despliegue

*Qué es:* la rama `corte/main` = `migra/fase1-2` + **un commit de flujos**: `deploy.yml` pierde el disparo por push a `main` (queda solo manual), y `cloudrun.yml` activa el job `production` para `main`. *La prepara Claude; no se fusiona sin tu confirmación.*

1. **GitHub → Pull requests → New → base `main`, compare `corte/main`.** Espera el CI en verde (pruebas + lint).
2. Revisa que en «Files changed» estén `deploy.yml` (sin `push`) y `cloudrun.yml` (producción con `if: github.ref == 'refs/heads/main'`).
3. **Merge** (tu autorización explícita). Se dispara el flujo **«Cloud Run»**.
4. En Actions → ese flujo → job **production** → *Review deployments → Approve* (tú).

*Debe verse:* en Actions, el flujo «Cloud Run» con `test` ✓ → `production` ✓ (construye la imagen, corre el Job de migraciones —Neon vacío hasta `head`—, despliega los 3 servicios y los Jobs, y publica Firebase). **NO debe aparecer ninguna corrida de «Deploy to production»** (el de la VM).
*Si falla:* mira el job (logs); típicos: variables faltantes (paso 4), WIF que no acepta la rama (debe llamarse exactamente `main`), la migración (error de la cadena directa). **Aborto:** ver §14.

---

## 6. Verificar producción por la URL de Cloud Run (SIN tocar el dominio)

```bash
WEB=$(gcloud run services describe golden-web --region us-east4 --format='value(status.url)')
PUB=$(gcloud run services describe golden-publico --region us-east4 --format='value(status.url)')
BIO=$(gcloud run services describe golden-biometria --region us-east4 --format='value(status.url)')
for u in $WEB $PUB $BIO; do echo "== $u"; curl -fsS $u/health; echo; curl -fsS --max-time 60 $u/ready; echo; done
# la contingencia debe estar APAGADA:
gcloud run services describe golden-web --region us-east4 --format=json | python3 -c "import json,sys; e=json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env']; print([x for x in e if x['name']=='CONTINGENCY_ENABLED'])"
curl -s $WEB/kiosk/sw.js | head -3
```
*Debe verse:* `{"status":"ok"}` en `/health` de los tres; `/ready` → `"status":"ready"`; `[{'name': 'CONTINGENCY_ENABLED', 'value': '0'}]`; y el `sw.js` del quiosco que empieza con el comentario «Service worker del quiosco con el modo contingencia APAGADO».
*Si falla:* `/ready` en 503 = la base no responde (cadena `golden-database-url`) o el almacenamiento; mira `gcloud run services logs read golden-web --region us-east4 --limit 50`.

---

## 7. Crear el primer super administrador

La contraseña la pide el script por teclado (no queda en el historial). Se corre con la **imagen que ya está desplegada** (trae el script y todas las dependencias):
```bash
REGION=us-east4
IMAGE=$(gcloud run services describe golden-web --region $REGION --format='value(spec.template.spec.containers[0].image)')
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
docker run --rm -it \
  -e DATABASE_URL="$(gcloud secrets versions access latest --secret golden-database-url)" \
  -e SECRET_KEY="$(gcloud secrets versions access latest --secret golden-secret-key)" \
  "$IMAGE" python scripts/create_staff_user.py --username <usuario> --role super_admin \
  --full-name "<Nombre>" --email <correo> --phone <+57...>
```
*Debe verse:* se te pide «Contraseña:» y «Confirmar contraseña:» (mínimo 8 caracteres) y termina confirmando el usuario creado.
*Si falla:* «Ya existe un usuario…» = ya estaba; «relation … does not exist» = las migraciones no corrieron (paso 5).

---

## 8. Cloud Scheduler: crear las tareas, comprobarlas y verificar respaldos

La tarea `golden-ops-hourly` existe en **pausa** desde el paso 3. La reanudas y compruebas con el script (idempotente: también la corrige si algo difiere):
```bash
bash deploy/gcp/scheduler.sh production ensure --resume
gcloud scheduler jobs list --location us-east4
```
*Debe verse:* `estado: ENABLED` y, en la lista, una fila `golden-ops-hourly  5 * * * *  (America/Bogota)  … ENABLED`.

Ahora genera los primeros respaldos a mano (el Scheduler tardará hasta la hora y cinco) y comprueba todo:
```bash
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,backup" --wait
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,backup-daily" --wait
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,check-backups" --wait
bash deploy/gcp/scheduler.sh production check
bash deploy/gcp/scheduler.sh production alert
```
*Debe verse:* los tres Jobs terminan **«Execution … has successfully completed»**; `scheduler.sh … check` imprime solo líneas `OK` (tarea, horario `5 * * * *`, zona `America/Bogota`, destino, cuenta, estado ENABLED, «último respaldo horario hace … h», «hay un respaldo posterior al último despliegue») y termina con **«Scheduler y respaldos en orden.»**; `alert` dice «creada» (o «ya existe»).
**Una hora después** del paso, en la consola: Cloud Scheduler → `golden-ops-hourly` → *Last run* = Success, y `check` otra vez en verde (eso prueba que el Scheduler SÍ dispara).
*Si falla:* `FALTA la tarea…` → repite `ensure --resume`; `el último respaldo horario tiene N h` → el Job de respaldos falló: `gcloud run jobs executions list --job golden-ops --region us-east4` y mira los logs; **no relajes los umbrales** (la alarma de `check-backups` es la correcta).

---

## 9. Evento de prueba (humo funcional)

*Dónde:* el navegador, en la **URL de Cloud Run web** (paso 6), aún sin dominio.
1. Inicia sesión con el super administrador. **Estado del sistema** (`/sistema`) debe estar **en verde** (respaldo «hace 0 h», sin cola fallida).
2. **Clientes → nuevo cliente** `PRUEBA` · **Eventos → nuevo evento** «PRUEBA-CORTE» (coordinador = tú) · pasa el evento a **En proceso**.
3. Carga 3-5 personas de prueba (**Adjuntar BD** o alta manual) y regístralas: por **cédula escrita** y, si hay cámara, por **rostro** (consentimiento incluido). Mira el contador en vivo.
4. **Formulario web de prueba** con un correo tuyo: debe llegar el correo (si configuraste Graph) y, con el pago de **Wompi sandbox**, mostrar el resultado.
5. Abre `/kiosk/<id>/registro` en un celular: **no** debe aparecer la franja de «modo contingencia» y la página **no** debe registrar service worker (DevTools → Application → Service Workers: vacío).
*Debe verse:* todo sin errores 5xx; `/sistema` sigue en verde. *Si falla:* anota la pantalla y la hora; `gcloud run services logs read golden-web --region us-east4 --limit 100`.

---

## 10. Dominio: Firebase Hosting + Cloudflare

*Dónde:* Firebase console → Hosting → sitio `golden-app-<número>` → **Add custom domain** → `app.golden-eventos.com`. Firebase te da registros (un TXT de verificación y A/AAAA o CNAME).
*Cloudflare → DNS:* crea esos registros con la **nube GRIS (solo DNS)**. El registro viejo que apunta a la VM se **reemplaza**. Espera el certificado (puede tardar de minutos a unas horas).
*Debe verse:* en Firebase, el dominio en **«Connected»**; `curl -sI https://app.golden-eventos.com/health` → `HTTP/2 200` y `{"status":"ok"}`.
**Prueba de IP real (obligatoria):**
```bash
OPS=$(gcloud secrets versions access latest --secret golden-ops-token)
curl -s -H "X-Ops-Token: $OPS" https://app.golden-eventos.com/api/ops/client-ip
curl -s -H "X-Ops-Token: $OPS" -H "X-Forwarded-For: 1.2.3.4" https://app.golden-eventos.com/api/ops/client-ip
```
*Debe verse:* `x_forwarded_for` = `[tu IP real, una IP de Google]`, `hops: 2`, `google_infra: [false, true]` y `chosen_ip` = tu IP real; con la IP falsa, **descartada**. Cualquier otra entrada (104.x/172.64.x/162.158.x, una tercera IP) = Cloudflare está haciendo de proxy: apaga la nube naranja y repite.
*Si falla:* el certificado no sale en 1 h, o la prueba de IP no cuadra → **aborto** (§14, vuelta del DNS).

---

## 11. Monitores

Hay **dos capas** y ninguna «alimenta» a los Jobs: los Jobs los dispara solo Cloud Scheduler; los monitores solo observan. Tabla completa en `docs/15` D2.5g.
1. **Google Cloud Monitoring** (lo creó `bootstrap.sh`, paso 3). Comprobar:
```bash
gcloud monitoring uptime list-configs --format='table(displayName,monitoredResource.labels.host,period)'
gcloud monitoring policies list --format='value(displayName)'
```
*Debe verse:* `golden-health` (host = `golden-web-<número>.us-east4.run.app`, período 60 s) y 4 políticas: «Golden production: /health no responde», «…: un Job falló…», «…: errores 5xx» y «…: el Job horario no corre…» (esta última la creó el paso 8).
2. **UptimeRobot** (externo, con tu cuenta): el monitor HTTP(s) debe apuntar a **`https://app.golden-eventos.com/health`** (**NO** `/ready`: `/ready` toca la base y mantendría despierto el cómputo de Neon; `/health` no toca nada, comprobado en `tests/test_health_no_db.py`). Tipo HTTP(s), intervalo el del plan (gratis: 5 min), alerta a tu correo/teléfono. Hoy aparece caído porque la VM está apagada: **se pone en verde cuando el dominio ya apunta a Cloud Run** (paso 10).
*Debe verse:* tras el paso 10, UptimeRobot en **Up** y el chequeo de Google en verde (Monitoring → Uptime checks).

---

## 12. Presupuesto: nada que crear

El presupuesto mensual **ya existe a nivel de la cuenta de facturación y cubre todos los proyectos**; el bootstrap lo detecta y solo lo informa («ya hay presupuesto para este proyecto, no se crea otro»). Comprobación opcional (solo lee):
```bash
gcloud billing budgets list --billing-account <ID de la cuenta de facturación> --format='table(displayName,amount.specifiedAmount.units,amount.specifiedAmount.currencyCode)'
```
*Debe verse:* el presupuesto de la cuenta con sus avisos (50/90/100 %). Los avisos **no apagan nada**.

---

## 13. Después del corte

- **Etiqueta:** `git tag corte-AAAA-MM-DD` sobre `main` (la pone Claude cuando lo pidas).
- **Observación de 24 h:** `/sistema` en verde, UptimeRobot en Up, un respaldo por hora (`bash deploy/gcp/scheduler.sh production check`), y una pasada por el evento de prueba. La VM puede quedar detenida (sin runner) o borrarse más adelante.
- **Mejoras** (recarga sin red, B8, estados, 7a/7b…): ramas `producto/*` → PR a `migra/fase1-2` → staging → PR a `main`. El renombre de `migra/fase1-2` a `staging` es un paso aparte.

---

## 14. Abortar y volver atrás

**Aborta si:** (a) el CI está en rojo o el despliegue de producción falla en cualquier etapa (migración incluida); (b) algún `/health`/`/ready` no responde 200 o `/sistema` está en rojo; (c) falla el humo del paso 9; (d) tras mover el dominio, 5xx sostenidos (≥ 1 % durante 5 min), la prueba de IP no cuadra o el certificado no sale en 1 h.
**Qué hacer:**
- *Antes del paso 10* (dominio sin mover): no hay nada que deshacer fuera del repositorio; corriges y repites desde el paso 5. Si hay que retirar el merge: commit `revert` en `main` (la VM sigue neutralizada, nadie la redespliega).
- *Después del paso 10:* en Cloudflare vuelve el registro `app.golden-eventos.com` al de la VM; si la apagaste, `gcloud compute instances start golden-biometrics-prod --zone us-central1-a`. Como la VM no tiene usuarios reales, lo escrito en Neon se descarta.
- *Pausar los respaldos* si abortas del todo: `gcloud scheduler jobs pause golden-ops-hourly --location us-east4`.

---

## Resumen de una página (orden y responsable)
0. **J** Crear el proyecto `goldenweb-prod` y vincular la facturación (paso 1b).
1. **J** GitHub: Environment `production` + revisor, deshabilitar «Deploy to production», runner de la VM detenido.
2. **J** Neon: proyecto vacío, historia 1 día, cadena directa.
3. **J** `FRESH_START=1 bash deploy/gcp/bootstrap.sh production` → copiar las 5 variables.
4. **J** Variables en el Environment.
5. **Claude** prepara `corte/main` y el PR · **J** revisa, fusiona y aprueba el despliegue.
6. **J** Verifica por la URL de Cloud Run (`/health`, `/ready`, contingencia = 0).
7. **J** Crea el super administrador.
8. **J** `scheduler.sh production ensure --resume`, respaldos a mano, `check`, `alert`.
9. **J** Evento de prueba.
10. **J** Dominio (Firebase + Cloudflare gris) y prueba de IP.
11. **J** Monitores (Google ya creados; UptimeRobot a `/health`).
12. *(Presupuesto: ya existe a nivel de la cuenta; nada que hacer.)*
