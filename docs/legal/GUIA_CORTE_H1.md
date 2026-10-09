# Guía del corte, fase H1 (adelantar la infraestructura de producción SIN desplegar nada)

**Parte de** `docs/19_GUIA_PRODUCCION.md`, con cada comando verificado contra el repositorio (`deploy/gcp/bootstrap.sh`, `config.sh`, `scheduler.sh`, `cors.sh`, `scripts/create_staff_user.py`, `scripts/restore_test.sh`) y sin `<huecos>`: lo que solo tú sabes se pide con una pregunta en pantalla. Todo se ejecuta en **Cloud Shell** (shell.cloud.google.com) con tu cuenta de Google, salvo donde diga «consola».

**Qué hace H1 y qué no.** H1 deja lista la nube de producción (proyecto, facturación, base vacía, secretos, servicios con la imagen de relleno «hello», colas, Scheduler en pausa, sitio de Firebase, monitores) **sin** desplegar la aplicación, **sin** tocar el dominio y **sin** tocar `main` ni la VM actual. `CONTINGENCY_ENABLED` queda en `0`.

**Reversibilidad:** ✅ reversible sin consecuencias · ⚠️ reversible con trabajo o con efectos que quedan (se dice cuáles) · ⛔ no se puede deshacer.

**Qué encontré al verificar `docs/19` (y cómo queda aquí):**
1. `bootstrap.sh` **no muestra** la `FACE_ENCRYPTION_KEY` que genera (dice «generado al azar» y la guarda directo). Para copiarla al gestor de contraseñas hay un comando aparte (paso 13).
2. El bootstrap crea una alerta **activa** «/health no responde» que, con la imagen de relleno, dispararía correos. Se **desactiva** (paso 18) y se reactiva en el corte.
3. **`POLICY_VERSION=1.1` se escribía solo para staging.** Sin ese valor, producción mostraría la política 1.0 y la condición de la auditora para la contingencia («la huella del texto de la constancia coincide con la política vigente») no se cumpliría. **Ya está corregido en la rama `producto/politica-produccion`** (ahora vive en `deploy/gcp/env/common.yaml`, igual para staging y producción, con prueba); llega a `main` con el corte (paso 24).
4. Super administrador, evento de prueba, Scheduler en marcha, respaldos y `restore_test.sh` **necesitan la aplicación desplegada** (tablas creadas por la migración, imagen real). No pueden hacerse en H1: están en los bloques 4 y 5, detrás de la línea de parada.
5. Los pasos 1, 4 y 5 de `docs/19` (Environment de GitHub, deshabilitar «Deploy to production», variables, PR a `main`) **son el corte**, no H1.

---

## Bloque 1 · Proyecto, facturación, región y base de datos (7 pasos)

**Paso 1 — Abrir Cloud Shell y comprobar la cuenta.** ✅
```bash
gcloud auth list
gcloud config list
```
*Debes ver:* tu cuenta de Google marcada `ACTIVE`. Si es otra cuenta, cámbiala con `gcloud auth login` antes de seguir.

**Paso 2 — Crear el proyecto `goldenweb-prod`.** ⚠️ (se puede borrar con `gcloud projects delete goldenweb-prod`, pero el ID `goldenweb-prod` queda reservado y no se reutiliza)
```bash
PROJECT_ID=goldenweb-prod
gcloud projects create "$PROJECT_ID" --name="GoldenWeb"
```
*Debes ver:* `Create in progress … Operation … finished successfully`. **Si dice que el ID ya está en uso** («The project ID you specified is already in use by another project»), otra cuenta lo tiene (los ID de proyecto son globales): cambia SOLO la primera línea por la alternativa recomendada, `PROJECT_ID=goldenweb-prod-co` (o, si también estuviera tomada, `PROJECT_ID=golden-eventos-prod`), y repite este paso. No hay que cambiar nada más: el resto de la guía y los scripts leen el ID desde `gcloud config`. Reglas del ID: 6 a 30 caracteres, minúsculas, números y guiones, empieza con letra y no termina en guion. **Haz los pasos 2 a 5 en la misma ventana de Cloud Shell** (la variable `PROJECT_ID` vive en ella); si se reinicia a la mitad, vuelve a escribir la primera línea del paso 2 con el ID que usaste y sigue.

**Paso 3 — Encontrar la cuenta de facturación «Golden Logistics - GoldenWeb».** ✅
```bash
gcloud billing accounts list --format='table(name,displayName,open)'
BILLING=$(gcloud billing accounts list --filter="displayName~'GoldenWeb' AND open=true" --format='value(name)'); BILLING=${BILLING#billingAccounts/}; echo "Cuenta de facturación: $BILLING"
```
*Debes ver:* una fila «Golden Logistics - GoldenWeb … True» y, al final, un ID del tipo `XXXXXX-XXXXXX-XXXXXX`. Si salen dos IDs o ninguno, **detente**: no sigas hasta que quede una sola.

**Paso 4 — Vincular la facturación al proyecto.** ✅ (se puede desvincular)
```bash
gcloud billing projects link "$PROJECT_ID" --billing-account "$BILLING"
gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
```
*Debes ver:* `billingEnabled: true` y luego `True`. Si falla por permisos necesitas el rol *Billing Account User* en esa cuenta. El presupuesto de la cuenta **ya cubre** todos los proyectos: no se crea nada.

**Paso 5 — Elegir el proyecto y la región.** ✅
```bash
gcloud config set project "$PROJECT_ID" && gcloud config set run/region us-east4
gcloud projects describe "$PROJECT_ID" --format='value(projectNumber,lifecycleState)'
```
*Debes ver:* un número largo (el número del proyecto) y `ACTIVE`. Anótalo, junto con el ID que usaste: se usan en nombres de Cloud Run y de Firebase. **Desde aquí, cada bloque lee el ID de `gcloud config`** (`PROJECT_ID=$(gcloud config get-value project)`): no hay que volver a escribirlo, ni siquiera si Cloud Shell se reinicia.

**Paso 6 — Crear la base de datos vacía en Neon (consola: console.neon.tech).** ⚠️ (el proyecto de Neon se puede borrar; los datos que luego se escriban no)
1. Con la cuenta de Neon **de la empresa** (plan Launch): **New project** → nombre `golden-production`, región **AWS US East (N. Virginia) / us-east-1**, Postgres **18** (la misma versión que staging).
2. **Settings → Storage → History retention (restore window): 1 día.**
3. En **Connection details**: rol dueño, **apaga «Pooled connection»**, copia la cadena (el host **no** debe contener `-pooler`). No la pegues en ningún chat.
*Debes ver:* el proyecto con una base `neondb` **sin tablas**, región `aws-us-east-1`, retención de 1 día.

**Paso 7 — Comprobar la conexión desde Cloud Shell sin mostrar la cadena.** ✅
```bash
read -rsp "Pega la cadena DIRECTA de Neon (no se ve): " NEON; echo
psql "$NEON" -c '\dt'; psql "$NEON" -tAc "select current_database(), version()" | cut -c1-80; unset NEON
```
*Debes ver:* `Did not find any relations.` y una línea con el nombre de la base y `PostgreSQL 18…`. Si dice «password authentication failed» o «could not translate host», la cadena está mal copiada.

---

## Bloque 2 · `bootstrap.sh production` y la llave de rostros (8 pasos)

**Antes de empezar el bloque, ten a mano** (el bootstrap pide varias cosas seguidas y no se puede pausar a mitad del paso 11):
1. La **cadena DIRECTA** de Neon (la del Bloque 1).
2. El **correo de alertas** (el que recibirá los avisos de Cloud Monitoring y de respaldos).
3. **Tres datos de Neon** para el precalentamiento automático (el paso 11, punto 8, explica dónde sale cada uno): la clave de API, el ID del proyecto y el ID del endpoint. Tómalos ahora en la consola de Neon.
4. El **gestor de contraseñas de la empresa abierto** (para el paso 13).
5. El navegador con la cuenta de Google del proyecto (el paso 8 abre un enlace de autorización).


**Paso 8 — Preparar la CLI de Firebase (la usa el paso 12 del bootstrap para crear el sitio).** ✅
```bash
firebase --version || sudo npm install -g firebase-tools
firebase login --no-localhost
```
*Debes ver:* una versión (p. ej. `13.x`) y, tras abrir el enlace que te muestra y pegar el código, `Success! Logged in as tu-correo`. Debe ser la cuenta con acceso al proyecto.

**Paso 9 — Traer el código. El repositorio es PRIVADO: primero se autentica Cloud Shell con GitHub (sin escribir tu contraseña).** ✅
```bash
gh auth status || gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
```
*Debes ver:* `gh auth login` muestra un **código de 8 caracteres** (`XXXX-XXXX`) y una dirección (`https://github.com/login/device`). Ábrela en el navegador donde tienes tu sesión de GitHub, escribe el código y autoriza. Termina con `✓ Logged in as tu-usuario` (si pregunta «Authenticate Git with your GitHub credentials?», responde `Y`). `gh auth setup-git` no imprime nada. El permiso queda guardado en Cloud Shell: al terminar el corte, `gh auth logout` lo borra.
```bash
PROJECT_ID=$(gcloud config get-value project); echo "Proyecto: $PROJECT_ID"
cd ~ && { [ -d Facial-Recognition ] || gh repo clone Juando26030/Facial-Recognition-GOLDEN Facial-Recognition; } && cd Facial-Recognition
git fetch origin && git checkout integracion/piloto-legal && git pull --ff-only && git log --oneline -1
```
*Debes ver:* `Proyecto: ` con el ID que creaste y el último commit de la rama **`integracion/piloto-legal`** (el arreglo del paso 5 del bootstrap vive ahí; cuando `migra/fase1-2` lo tenga también sirve esa rama; el bootstrap no depende de la rama).
*Si `gh` no existe en tu Cloud Shell:* crea un token de GitHub de **solo lectura de este repositorio** (GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token → *Only select repositories*: este → *Permissions → Contents: Read-only*) y úsalo así (el token queda en `.git/config`, por eso la última línea lo quita):
```bash
read -rsp "Token de GitHub (no se ve): " T; echo; git clone "https://x-access-token:$T@github.com/Juando26030/Facial-Recognition-GOLDEN.git" ~/Facial-Recognition; unset T
cd ~/Facial-Recognition && git remote set-url origin https://github.com/Juando26030/Facial-Recognition-GOLDEN.git
```
(luego bórralo en GitHub cuando termines; para actualizar el código tendrías que repetir el `clone`.)

**Paso 10 — Ejecutar el bootstrap de producción.** ⚠️ (casi todo lo que crea se puede borrar; lo que NO se deshace del todo está justo debajo del comando)
```bash
FRESH_START=1 bash deploy/gcp/bootstrap.sh production
```
*Debes ver primero:* `Proyecto: <tu ID> (número …) · Entorno: production · Región: us-east4 · Repositorio: Juando26030/Facial-Recognition-GOLDEN` y `¿Continuar? (escribe «si»):` → escribe `si`. Luego van apareciendo `== 1. APIs`, `== 2. Artifact Registry`, `== 3. Cuentas de servicio`, `== 4. Workload Identity Federation`, `== 5. Secret Manager (production)`… cada uno con `✓`.
**Qué NO se deshace del todo:** (a) convertir el proyecto en proyecto de Firebase (`projects:addfirebase`, paso 12 del bootstrap) no se revierte, y el nombre del sitio `golden-app-<número>` queda reservado aunque se borre; (b) los nombres de los buckets son globales y, si se borran, pueden tardar en poder reutilizarse; (c) un pool de Workload Identity borrado queda reservado 30 días. Todo lo demás (APIs, cuentas de servicio, colas, Scheduler, servicios y Jobs con la imagen «hello», monitores, secretos) se borra o se reemplaza sin consecuencias porque todavía no hay datos ni despliegue.

**Si ya corriste el bootstrap y se detuvo en el paso 5 con `relation "alembic_version" does not exist` (le pasó a la primera ejecución del 9-oct-2026):** la base de Neon estaba vacía y la comprobación final del rol `golden_app` suponía una base ya migrada. Está corregido en `integracion/piloto-legal` (con prueba). Qué quedó y qué no: ver `docs/legal/GUIA_CORTE_H1.md` → «Reintento»; en corto: **repite el paso 9** (autenticar y traer la rama) y **vuelve a correr el mismo comando del paso 10**; no se regenera ninguna llave.

**Paso 11 — Responder lo que pide el paso 5 (Secret Manager). Todo se escribe «a ciegas»: no se ve al teclear.** ⚠️ (los secretos se pueden desactivar y reemplazar)
En este orden:
1. `golden-direct-database-url` → pega la cadena DIRECTA de Neon (la misma del paso 7).
2. `golden-secret-key` → **Enter** (la genera).
3. `golden-face-encryption-key` → **Enter** (la genera; la copias en el paso 13).
4. `golden-ops-token` → **Enter** (la genera).
5. Los 8 de Wompi (`wompi-public-key`, `wompi-integrity-secret`, `wompi-events-secret`, `wompi-private-key` y los 4 `wompi-sandbox-*`) → **Enter** en cada uno (se cargan cuando se activen los pagos).
6. `golden-azure-tenant-id`, `golden-azure-client-id`, `golden-azure-client-secret`, `golden-graph-sender` → **Enter** en los cuatro (se cargan en el paso 16 con la función de lectura silenciosa).
7. `golden-alert-email` → escribe el correo que recibirá las alertas.
8. `golden-neon-api-key`, `golden-neon-project-id`, `golden-neon-endpoint-id` → **pega los tres** (recomendado). Con ellos, el Job horario enciende el precalentamiento de Neon durante un evento «En Proceso» o una apertura de formulario (nunca se apaga y mínimo 0,5 CU) y lo devuelve a lo normal después (`app/warmup.py`); **sin ellos se salta Neon** y la primera petición tras un rato de inactividad espera a que despierte. Dónde salen:
   - **ID del proyecto:** consola de Neon → tu proyecto → **Settings → General → Project ID** (algo como `quiet-cloud-12345678`).
   - **ID del endpoint:** **Branches → production → Computes**: el identificador `ep-…` (es la parte `ep-xxxx-xxxx` del host de la cadena, sin `-pooler` ni lo que sigue).
   - **Clave de API:** avatar → **Account settings → API keys → Create new API key** (nombre «goldenweb-precalentamiento»). Se muestra **una sola vez**: pégala aquí y no la guardes en otro lado. Si tu cuenta es una *organización* de Neon, crea una clave de **organización o de proyecto** en lugar de una personal (la personal puede administrar todos tus proyectos de Neon, incluido staging).
   Si prefieres no cargarlos ahora, **Enter** en los tres (la aplicación funciona igual; solo queda sin precalentar Neon). Para cargarlos después hay que volver a correr el bootstrap, que es idempotente y solo pregunta por lo que falta.
Después el script crea solo el rol `golden_app` en Neon y la cadena `golden-database-url` (puede tardar 1 o 2 minutos).
*Debes ver:* `✓ … guardado` en los que escribiste (incluidos los tres de Neon si los pegaste), `(generado al azar)` en los tres generados y `(omitido)` en los demás. Más adelante pregunta `Correo para las alertas` si no guardaste `alert-email`.

**Paso 12 — Esperar el final del bootstrap y guardar el resumen.** ⚠️
*Debes ver al final, antes del resumen:* `== Estado de los secretos (production)` con una línea por secreto: `✓ golden-…: con versión`, `✗ golden-…: existe pero SIN versión` (si ves alguna `✗`, algo falló: no sigas) o `– golden-…: no existe (opcional omitido)`; nunca muestra valores. *Y al final:* `LISTO (production). Configura en GitHub → Settings → Environments → «production» → Variables` con cinco valores (`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOYER`, `FIREBASE_SITE`) y la URL de Cloud Run del servicio web. **No son secretos**: cópialos a tus notas (se vuelven a imprimir en el paso 22). Si algún paso mostró `⚠`, léelo: el script es idempotente, corrige y vuelve a correr **el mismo comando**; lo que ya existe no se toca. Si el sitio de Firebase no se creó, el mensaje trae el comando exacto.

**Paso 13 — Copiar la `FACE_ENCRYPTION_KEY` al gestor de contraseñas. Hazlo AHORA: antes de cargar cualquier dato real y antes del primer despliegue.** ✅
```bash
gcloud secrets versions access latest --secret golden-face-encryption-key; echo
```
*Debes ver:* una línea de unos 44 caracteres. Cópiala al gestor de contraseñas de la empresa con el nombre «GoldenWeb producción — FACE_ENCRYPTION_KEY», y después limpia la pantalla con `clear`. **Perderla = perder los rostros que se registren; no hay forma de recuperarla.** Comprueba que la copia es idéntica (sin mostrar nada):
```bash
gcloud secrets versions access latest --secret golden-face-encryption-key | tr -d '\n' | sha256sum | cut -c1-12
read -rsp "Pega la copia que guardaste en el gestor: " K; echo; printf '%s' "$K" | tr -d '\n' | sha256sum | cut -c1-12; unset K
```
*Debes ver:* **dos grupos de 12 caracteres idénticos.** Si difieren, repite el copiado. No sigas sin esta copia.

**Paso 14 — Comprobar lo creado.** ✅
```bash
PROJECT_ID=$(gcloud config get-value project)
gcloud run services list --region us-east4 --format='value(metadata.name)'
gcloud run jobs list --region us-east4 --format='value(metadata.name)'
gcloud scheduler jobs list --location us-east4 --format='table(name.basename(),schedule,state)'
gcloud secrets list --format='value(name)'
gcloud services list --enabled --filter=name:iamcredentials.googleapis.com --format='value(name)'
gcloud iam service-accounts get-iam-policy golden-app@$PROJECT_ID.iam.gserviceaccount.com --format='value(bindings.role)' | grep serviceAccountTokenCreator
```
*Debes ver:* los servicios `golden-biometria golden-publico golden-web`; los Jobs `golden-bulk golden-migrate golden-ops`; el Scheduler `golden-ops-hourly  5 * * * *  PAUSED`; los secretos `golden-alert-email golden-database-url golden-direct-database-url golden-face-encryption-key golden-ops-token golden-secret-key` (más `golden-neon-api-key`, `golden-neon-endpoint-id` y `golden-neon-project-id` si los pegaste en el paso 11); la API `iamcredentials.googleapis.com` y la línea `roles/iam.serviceAccountTokenCreator`.

**Paso 15 — Comprobar buckets, CORS, colas y que NO hay nada desplegado.** ✅
```bash
PROJECT_ID=$(gcloud config get-value project)
gcloud storage buckets describe gs://$PROJECT_ID-golden-app-us-east4 --format='yaml(location,cors_config)'
gcloud storage buckets describe gs://$PROJECT_ID-golden-backups-us-east4 --format='value(location)'
gcloud tasks queues list --location us-east4 --format='value(name.basename())'
gcloud run services describe golden-web --region us-east4 --format='value(spec.template.spec.containers[0].image)'
```
*Debes ver:* `US-EAST4`; en `cors_config`, el método `PUT` y exactamente tres orígenes (`https://app.golden-eventos.com` y los dos del sitio `golden-app-<número>`: `.web.app` y `.firebaseapp.com`) **sin ningún `run.app`**; en el segundo bucket `US-EAST4`; las colas `golden-faces` y `golden-jobs`; y la imagen `us-docker.pkg.dev/cloudrun/container/hello` (es decir, **la aplicación no está desplegada**).

**Reintento tras el error de `alembic_version` (solo si te pasó).** ⚠️
*Qué quedó creado antes del error:* APIs, Artifact Registry, cuentas de servicio y Workload Identity (pasos 1 a 4); los secretos con valor `golden-direct-database-url`, `golden-secret-key`, `golden-face-encryption-key`, `golden-ops-token` y `golden-alert-email`; el **contenedor** del secreto `golden-database-url` **sin ninguna versión**; y el rol `golden_app` en Neon, con sus permisos aplicados y sin privilegios de más, pero con una contraseña aleatoria que no se guardó en ninguna parte (no sirve; el reintento la reemplaza). *Qué NO se hizo:* la versión de `golden-database-url`, los permisos de lectura de los secretos y los pasos 6 a 12 (buckets, colas, servicios con la imagen «hello», Scheduler, monitores, presupuesto, Firebase).
*Antes de repetir*, anota las versiones de la llave de rostros (para comprobar después que no cambió):
```bash
gcloud secrets versions list golden-face-encryption-key --format='value(name,state,createTime)'
```
*Debes ver:* una sola fila, versión `1`, `enabled`. Repite el **paso 9** y luego el **paso 10**. *Debes ver ahora:* `golden-direct-database-url ya tiene valor`, `golden-secret-key ya tiene valor`, `golden-face-encryption-key ya tiene valor`, `golden-ops-token ya tiene valor` y `golden-alert-email ya tiene valor` (no te los vuelve a pedir); te pregunta otra vez por los opcionales que omitiste (Wompi, Microsoft y los tres de Neon: ahí puedes pegar los de Neon); restablece la contraseña de `golden_app` (la que nadie guardó) y guarda la cadena como la **primera versión** de `golden-database-url` (`Permisos de golden_app aplicados…`, sin error; si la versión no queda, el script se detiene con un mensaje) y continúa hasta `Estado de los secretos` y `LISTO (production)`. **Enter en los opcionales que omitiste es seguro:** no se crea nada y la siguiente corrida los vuelve a preguntar. *Después* repite el comando de arriba: **debe seguir siendo una sola fila, versión `1`, con la misma fecha**. El script nunca regenera una llave que ya tiene valor (solo lo haría si definieras la variable `ROTATE` con su nombre; no la definas).

---

## Bloque 3 · Correo, monitores, Firebase, DNS y ensayo de restauración (8 pasos)

**Paso 16 — Cargar los cuatro secretos de correo de producción (lectura silenciosa).** ⚠️ (cada valor se puede reemplazar con una versión nueva)
```bash
SUF=; PROJECT=$(gcloud config get-value project)
cargar() {  # nombre-corto
  local s="golden-$1${SUF}" v
  if gcloud secrets versions access latest --secret "$s" >/dev/null 2>&1; then echo "$s ya tiene valor (no se toca)"; return; fi
  if [ "$1" = graph-sender ]; then read -rp "$s (el buzón remitente): " v; else read -rsp "$s: " v; echo; fi
  [ -n "$v" ] || { echo "vacío: omitido"; return; }
  gcloud secrets describe "$s" >/dev/null 2>&1 || gcloud secrets create "$s" --replication-policy automatic >/dev/null
  printf '%s' "$v" | gcloud secrets versions add "$s" --data-file=- >/dev/null; unset v
  for sa in golden-app$SUF golden-ops$SUF; do gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:$sa@$PROJECT.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --quiet >/dev/null; done
  gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:golden-deployer$SUF@$PROJECT.iam.gserviceaccount.com" --role roles/secretmanager.viewer --quiet >/dev/null
  echo "$s guardado"
}
for n in azure-tenant-id azure-client-id azure-client-secret graph-sender; do cargar "$n"; done
```
*Debes ver, en orden:* `golden-azure-tenant-id:` (pegas el Id. de directorio), `golden-azure-client-id:` (pegas `2a1f1fb1-30eb-4c23-b355-5163e269a459`), `golden-azure-client-secret:` (pegas el valor del secreto «GoldenWeb producción» de Entra; no se ve) y `golden-graph-sender (el buzón remitente):` (escribes `soporteit@goldenlogisticas.com`), cada uno seguido de `… guardado`. La restricción RBAC de la aplicación ya cubre la cuenta (sección 11 del runbook).

**Paso 17 — Comprobar los cuatro secretos sin ver valores.** ✅
```bash
for n in azure-tenant-id azure-client-id azure-client-secret graph-sender; do echo -n "golden-$n: "; gcloud secrets versions list "golden-$n" --format='value(name,state)' | head -1; done
```
*Debes ver:* cuatro líneas con la versión `1` en estado `enabled`.

**Paso 18 — Monitores: dejar creado el chequeo pero DESACTIVAR la alerta de `/health`.** ✅ (se reactiva con `--enabled` el día del corte)
```bash
gcloud monitoring uptime list-configs --format='table(displayName,monitoredResource.labels.host,period)'
gcloud monitoring policies list --format='table(displayName,enabled)'
POL=$(gcloud monitoring policies list --filter='displayName="Golden production: /health no responde"' --format='value(name)')
gcloud monitoring policies update "$POL" --no-enabled
gcloud monitoring policies list --filter='displayName:"/health"' --format='value(displayName,enabled)'
```
*Debes ver:* el chequeo `golden-health` (host `golden-web-<número>.us-east4.run.app`, período `60s`) y tres políticas activas («/health no responde», «un Job falló…», «errores 5xx»); tras el `update`, la de «/health no responde» con **`False`**. (La política «el Job horario no corre» se crea después, con `scheduler.sh … alert`.) Sin esto, la imagen «hello» —que no responde `/health`— enviaría correos de falla.

**Paso 19 — Comprobar el sitio de Firebase (sin agregar el dominio todavía).** ⚠️ (convertir el proyecto en proyecto de Firebase no se deshace, y el nombre del sitio queda reservado aunque se borre)
```bash
PROJECT_ID=$(gcloud config get-value project); PN=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
firebase hosting:sites:list --project "$PROJECT_ID"
```
*Debes ver:* una fila con el sitio `golden-app-<tu número de proyecto>` y la dirección `https://golden-app-<número>.web.app`. Si **no** aparece, créalo: `firebase hosting:sites:create "golden-app-$PN" --project "$PROJECT_ID" --non-interactive`. **No** hagas «Add custom domain» todavía: eso es el corte.

**Paso 20 — Cloudflare: bajar el TTL del registro SIN cambiar a dónde apunta.** ✅
Primero, en Cloud Shell, guarda cómo responde hoy el dominio:
```bash
dig +noall +answer app.golden-eventos.com
```
*Anota* las direcciones y el TTL que aparecen. Luego, en **dash.cloudflare.com → golden-eventos.com → DNS → Records**, busca el registro **`app`**:
- Si su estado es **«DNS only» (nube gris)**: **Edit → TTL = «1 min»** → **Save**. *No cambies el contenido ni el tipo.*
- Si es **«Proxied» (nube naranja)**: el TTL aparece como «Auto» y **no se puede cambiar**: no hagas nada (el cambio de la nube a gris se hará en el corte).
Pasado el TTL anterior, repite `dig +noall +answer app.golden-eventos.com`. *Debes ver:* **las mismas direcciones de antes** (el destino no cambió) y, si era «DNS only», un TTL de 60 o menos.

**Paso 21 — UptimeRobot: NO crear ni activar el monitor de `/health` todavía.** ✅
Si ya existe uno apuntando a `app.golden-eventos.com/health`, déjalo como está. El monitor definitivo apunta a `https://app.golden-eventos.com/health` (nunca a `/ready`) y se activa **después** de mover el dominio.

**Paso 22 — Reimprimir los cinco valores para GitHub y guardar el inventario.** ✅
```bash
PROJECT_ID=$(gcloud config get-value project); PN=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
echo "GCP_PROJECT_ID=$PROJECT_ID"; echo "GCP_REGION=us-east4"
echo "GCP_WIF_PROVIDER=projects/$PN/locations/global/workloadIdentityPools/github/providers/github-oidc"
echo "GCP_DEPLOYER=golden-deployer@$PROJECT_ID.iam.gserviceaccount.com"
echo "FIREBASE_SITE=golden-app-$PN"
gcloud run services describe golden-web --region us-east4 --format='value(status.url)'
```
*Debes ver:* los cinco pares y la dirección de Cloud Run del servicio web (`https://golden-web-<número>.us-east4.run.app`). Guárdalos con las notas del paso 12.

**Paso 23 — Ensayo de la restauración contra STAGING (no toca producción).** ✅ (opcional pero recomendado: el script nunca se ha probado con un respaldo real)
1. Consola de Neon, proyecto de **staging**: crea una rama temporal llamada `restore-test` y copia su cadena directa.
2. En Cloud Shell (el ID del proyecto de staging es `goldenweb-staging`; compruébalo con `gcloud projects list`):
```bash
PROD_ID=$(gcloud config get-value project); STAGING_ID=goldenweb-staging
gcloud config set project "$STAGING_ID"
cd ~/Facial-Recognition
python3 -m venv ~/venv && . ~/venv/bin/activate
grep -viE '^(face[-_]recognition|dlib)' requirements.txt > /tmp/req.txt && pip install -q -r /tmp/req.txt
read -rsp "Cadena DIRECTA de la rama restore-test de STAGING: " U; echo; printf 'DIRECT_DATABASE_URL=%s\n' "$U" > .env.restore; unset U
python scripts/neon_app_role.py --env-file .env.restore
BACKUP_BUCKET=$STAGING_ID-golden-staging-us-east4 TARGET_ENV_FILE=.env.restore bash scripts/restore_test.sh
rm -f .env.restore restore_test_dump.sql.gz
gcloud config set project "$PROD_ID"
```
3. Borra la rama `restore-test` en la consola de Neon.
*Debes ver:* `respaldo: gs://…/db/daily/…`, `gzip íntegro`, los conteos por tabla del volcado y del destino **iguales**, y al final `OK — duraciones en restore_test_AAAAMMDD.log`. Si el bucket de staging tiene otro nombre, el error trae el mensaje «No hay respaldos diarios en gs://…».

---

## ⛔ PARADA. De aquí en adelante NADA se hace sin tu orden escrita
Lo que sigue **despliega producción, migra la base, toca `main` y/o mueve el dominio**. H1 termina en el paso 23. Cuando des la orden por escrito («adelante con el despliegue de producción»), el orden es el de los bloques 4 y 5.

## Bloque 4 · El corte (requiere orden escrita) (6 pasos)

**Paso 24 — (Claude) Preparar `corte/main`.** ⚠️ Es una rama de trabajo: `migra/fase1-2` + un commit con tres cambios: `deploy.yml` sin disparo por push a `main`; `cloudrun.yml` con el job `production` para `main`; y `POLICY_VERSION: "1.1"` también en producción (ya hecho y probado en `producto/politica-produccion`: vive en `deploy/gcp/env/common.yaml`; se incorpora al corte). `CONTINGENCY_ENABLED` se queda en `0` (`deploy/gcp/config.sh`, línea 27). *Debes ver:* la rama con CI en verde y la lista de archivos tocados.

**Paso 25 — GitHub: dejar la VM fuera del camino.** ⚠️ (reversible: se vuelve a habilitar el flujo y el runner)
Settings → Environments → **New environment `production`** → *Required reviewers*: tú. Actions → «Deploy to production» → ⋯ → **Disable workflow**. En la VM: `cd ~/actions-runner && sudo ./svc.sh stop`. *Debes ver:* «This workflow is disabled» y el runner `Offline`.

**Paso 26 — GitHub: variables del Environment `production`.** ✅
Settings → Environments → `production` → Variables: pega los cinco valores del paso 22. *Debes ver:* cinco variables con esos nombres.

**Paso 27 — Fusionar y desplegar.** ⛔ (despliegue a producción y migración de una base vacía; solo se deshace con un `revert` y descartando lo escrito)
Pull request base `main`, compare `corte/main`; con el CI en verde y **tu autorización explícita**: Merge. En Actions → «Cloud Run» → job `production` → **Review deployments → Approve**. *Debes ver:* `test` ✓ → `production` ✓ (imagen, Job de migraciones hasta el último `head`, 3 servicios, Jobs, Firebase) y **ninguna** corrida de «Deploy to production».

**Paso 28 — Verificar por la dirección de Cloud Run (sin dominio).** ✅
```bash
WEB=$(gcloud run services describe golden-web --region us-east4 --format='value(status.url)')
PUB=$(gcloud run services describe golden-publico --region us-east4 --format='value(status.url)')
BIO=$(gcloud run services describe golden-biometria --region us-east4 --format='value(status.url)')
for u in $WEB $PUB $BIO; do echo "== $u"; curl -fsS $u/health; echo; curl -fsS --max-time 60 $u/ready; echo; done
gcloud run services describe golden-web --region us-east4 --format=json | python3 -c "import json,sys; e=json.load(sys.stdin)['spec']['template']['spec']['containers'][0]['env']; print([x for x in e if x['name'] in ('CONTINGENCY_ENABLED','POLICY_VERSION')])"
curl -s $WEB/privacidad | grep -c "Ratificada el 6 de octubre de 2026"
curl -s $WEB/kiosk/sw.js | head -3
```
*Debes ver:* `{"status":"ok"}` en `/health` y `"status":"ready"` en `/ready` de los tres; `CONTINGENCY_ENABLED` con valor `0` y `POLICY_VERSION` con valor `1.1`; un número mayor que cero en el `grep -c` (la política v1.1 publicada); y el `sw.js` que empieza con el comentario de «contingencia APAGADO».

**Paso 29 — Confirmar la última migración en la base de producción.** ✅
```bash
psql "$(gcloud secrets versions access latest --secret golden-direct-database-url)" -tAc "select version_num from alembic_version"
```
*Debes ver:* una sola línea, el último `head` del repositorio (hoy `0064_accept_link`; si hubo migraciones nuevas, esa).

## Bloque 5 · Administrador, humo, respaldos y restauración (requiere el bloque 4) (7 pasos)

**Paso 30 — Primer super administrador.** ✅
```bash
REGION=us-east4
IMAGE=$(gcloud run services describe golden-web --region $REGION --format='value(spec.template.spec.containers[0].image)')
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
read -rp "Usuario: " SU; read -rp "Nombre completo: " SN; read -rp "Correo: " SE; read -rp "Celular (+57…): " SP
docker run --rm -it \
  -e DATABASE_URL="$(gcloud secrets versions access latest --secret golden-database-url)" \
  -e SECRET_KEY="$(gcloud secrets versions access latest --secret golden-secret-key)" \
  "$IMAGE" python scripts/create_staff_user.py --username "$SU" --role super_admin --full-name "$SN" --email "$SE" --phone "$SP"
```
*Debes ver:* «Contraseña:» y «Confirmar contraseña:» (mínimo 8 caracteres; no se ve) y la confirmación del usuario creado. «Ya existe un usuario…» = ya estaba; «relation … does not exist» = la migración no corrió (paso 27).

**Paso 31 — Entrar y revisar el sistema.** ✅
En el navegador, en la dirección de Cloud Run del servicio web (paso 28): inicia sesión con ese usuario → **Estado del sistema** (`/sistema`). *Debes ver:* todo en verde. (El respaldo aparecerá recién en el paso 33.)

**Paso 32 — Evento de prueba (humo).** ✅
Sigue `docs/legal/GUIA_PRUEBAS_NO_TECNICA.md`, puntos 0, 1, 2 y 6 (evento «PRUEBA-CORTE», carga de 5 personas, sin biometría, aceptación en el celular y en la puerta). *Debes ver:* todo sin errores 5xx; en el quiosco, **ninguna** franja de modo contingencia y ningún service worker (DevTools → Application → Service Workers: vacío).

**Paso 33 — Scheduler en marcha y primeros respaldos.** ✅
```bash
bash deploy/gcp/scheduler.sh production ensure --resume
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,backup" --wait
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,backup-daily" --wait
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,check-backups" --wait
bash deploy/gcp/scheduler.sh production check
bash deploy/gcp/scheduler.sh production alert
```
*Debes ver:* `estado: ENABLED`; los tres Jobs terminan con «Execution … has successfully completed»; `check` imprime solo líneas `OK` y termina con **«Scheduler y respaldos en orden.»**; `alert` dice «creada» o «ya existe». **Una hora después**, `check` otra vez en verde (prueba que el Scheduler dispara). **No relajes los umbrales** si falla.

**Paso 34 — Reactivar la alerta de `/health`.** ✅
```bash
POL=$(gcloud monitoring policies list --filter='displayName="Golden production: /health no responde"' --format='value(name)')
gcloud monitoring policies update "$POL" --enabled
gcloud monitoring policies list --format='table(displayName,enabled)'
```
*Debes ver:* las cuatro políticas con `True`. Haz esto cuando la aplicación ya responda `/health` (paso 28).

**Paso 35 — Prueba de restauración con un respaldo REAL de producción.** ✅ (no toca la base viva: la lee solo para comparar)
1. Consola de Neon, proyecto `golden-production`: rama temporal `restore-test` (vacía) → copia su cadena directa.
```bash
cd ~/Facial-Recognition && . ~/venv/bin/activate
read -rsp "Cadena DIRECTA de la rama restore-test de PRODUCCIÓN: " U; echo; printf 'DIRECT_DATABASE_URL=%s\n' "$U" > .env.restore; unset U
python scripts/neon_app_role.py --env-file .env.restore
read -rsp "Cadena DIRECTA de la base VIVA de producción (solo lectura, para comparar): " V; echo; printf 'DIRECT_DATABASE_URL=%s\n' "$V" > .env.live; unset V
BACKUP_BUCKET=$(gcloud config get-value project)-golden-backups-us-east4 TARGET_ENV_FILE=.env.restore LIVE_ENV_FILE=.env.live bash scripts/restore_test.sh
rm -f .env.restore .env.live restore_test_dump.sql.gz
```
2. Borra la rama `restore-test` en la consola de Neon.
*Debes ver:* `respaldo: gs://<tu ID>-golden-backups-us-east4/db/daily/…`, `gzip íntegro`, conteos del volcado y del destino **iguales**, los conteos vivos **no menores** que los del respaldo, y `OK — duraciones en restore_test_AAAAMMDD.log` (anota las duraciones: son el RTO real).

**Paso 36 — Dominio (SOLO con una segunda orden escrita: es el cambio de DNS).** ⛔→ reversible en minutos si el TTL es de 1 min: sigue `docs/19` §10 (Firebase «Add custom domain», registros en Cloudflare con la **nube gris**, prueba de IP real) y §11 (UptimeRobot a `/health`). No se ejecuta en esta guía.
