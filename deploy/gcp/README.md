# Cómo se despliega Orum (léelo ANTES de dar un comando de despliegue)

Lo ejecuta **Juan David en Cloud Shell**; ningún agente corre comandos de nube. Aquí está lo que ya salió mal alguna vez. Detalle y porqués: `docs/19_GUIA_PRODUCCION.md`, `docs/historial.md`.

## 1. Antes de dar el comando
- **Autorización:** nada a producción sin el «sí» explícito de Juan David para ESA acción (regla de CLAUDE.md). Staging se puede desplegar sin pedirla.
- **Qué se va a subir:** en Cloud Shell el repositorio es `~/gw-hosting`. Pídele que corra `git branch --show-current && git log --oneline -1` y confirma que es la rama/commit esperado. Pasó (17-nov-2026): producción salió con el commit de OTRA rama (Almacén) porque Cloud Shell no estaba donde se creía.
- **La rama debe contener TODAS las migraciones que ya corrieron en ese entorno.** Si la base ya está en una revisión (p. ej. `0148_almacen_unidades`, que subió otra rama) y la rama que se despliega no tiene ese archivo, el Job de migraciones falla con «Can't locate revision identified by '…'» y el despliegue se detiene (pasó en staging el 17-nov-2026). Antes de desplegar: `git ls-tree -r --name-only HEAD alembic/versions | tail -3` y compara con la última revisión que corrió en el entorno; si falta, une primero la rama que la trae.
- **Rama al día:** `git checkout <rama> && git pull`. Un despliegue sale de lo que hay en Cloud Shell, no de lo que acabas de empujar.
- **Identidad de git** (solo si va a hacer commit desde Cloud Shell): `git config user.name "Juan David" && git config user.email "noreply@golden-eventos.com"` (sin `--global`).

## 2. El comando (los dos argumentos son obligatorios)
```
bash deploy/gcp/manual_deploy.sh <staging|production> <ID-del-proyecto>
```
- Staging:    `REGION=us-east4 CLOUDSDK_CORE_PROJECT=goldenweb-staging bash deploy/gcp/manual_deploy.sh staging goldenweb-staging`
- Producción: `(FORCE=1 REGION=us-east4 CLOUDSDK_CORE_PROJECT=goldenweb-prod nohup bash deploy/gcp/manual_deploy.sh production goldenweb-prod > ~/deploy.log 2>&1 < /dev/null &) ; sleep 3; tail -f ~/deploy.log` (los valores no secretos salen de `~/.golden-production.env`, sección 6). **No pongas `&` al final de una cadena con `&&`**: manda TODA la cadena a segundo plano y Bash la detiene («Stopped») sin desplegar; el `tail` entonces muestra el log VIEJO. Por eso va entre paréntesis y con `< /dev/null`.
- Errores típicos: `Uso: …` (falta `staging|production`), `Falta el ID del proyecto` (falta el segundo argumento), «No existe golden-web-staging» (faltó `REGION`/`CLOUDSDK_CORE_PROJECT`).
- `FORCE=1` salta el congelamiento cuando hay eventos en curso; solo con autorización de Juan David y sabiendo que los servicios cambian de revisión.
- Un build largo (dlib) se corre con `nohup … &` y `tail -f`; no cerrar la pestaña. Si se corta, repetir el mismo comando.
- Termina con `== LISTO (<entorno>, commit <sha>)`. Se verifica en `/sistema` → «Versión desplegada» (el sha debe ser el esperado).

## 3. `ONEDRIVE_DRIVE_ID` (copia semanal a OneDrive, solo producción)
La copia semanal usa el sitio de SharePoint «Respaldos GoldenWeb»; el id de su biblioteca «Documentos» (empieza con `b!`, NO es secreto) llega al Job `golden-ops` por la variable `ONEDRIVE_DRIVE_ID`, y `deploy.sh` la copia **solo si está en el entorno del comando**. **Si un despliegue de producción no la lleva, el Job la pierde y /sistema vuelve a decir «copia semanal no configurada».** Se la pide a Juan David (o se saca de Graph Explorer, `docs/24_COPIA_SEMANAL_ONEDRIVE.md`); no se escribe en el repo. Si ya se perdió: `gcloud run jobs update golden-ops --region us-east4 --project goldenweb-prod --update-env-vars ONEDRIVE_DRIVE_ID=<id>`.

## 4. Cosas de Bash que ya mordieron
- Un `!` dentro de comillas dobles lo toma Bash como historial («event not found»): no lo pongas en mensajes de `read -p`, `echo`, etc.
- Un rol de IAM recién creado tarda ~45 s en poder asignarse a un bucket («does not exist in the resource's hierarchy»): `sleep 45` y repetir.
- Un comando por mensaje, copiable tal cual; nada de secretos en el chat (los valores van a Secret Manager).

## 5. Después de desplegar
Verificar en el navegador (`/sistema` en verde, las pantallas tocadas) y avisar a Juan David. Migraciones: las corre el Job `golden-migrate` dentro del despliegue; revisa en el commit si trae `alembic/versions/*` nuevas ANTES de desplegar a producción y dilo.

## 6. Valores no secretos del despliegue: `~/.golden-<entorno>.env`
`manual_deploy.sh` carga, si existe, `~/.golden-production.env` (o `~/.golden-staging.env`) con líneas `CLAVE=valor`. Así `ONEDRIVE_DRIVE_ID` y `OFFSITE_FOLDER_URL` no dependen de que alguien las escriba delante del comando. Se crea UNA vez en Cloud Shell (el HOME de Cloud Shell persiste). Ejemplo (los valores los tiene Juan David; no van al repo):
```
ONEDRIVE_DRIVE_ID=b!...            # id de la biblioteca «Documentos» del sitio Respaldos GoldenWeb
OFFSITE_FOLDER_URL=https://goldenlogisticas.sharepoint.com/sites/RespaldosGoldenWeb/Documentos%20compartidos/Base%20de%20datos
```
Para Gastos (costos de infraestructura) el mismo archivo lleva `GCP_BILLING_EXPORT_TABLE=goldenweb-prod.billing_export.gcp_billing_export_v1_01D3FA_9264E8_E8058D` y `NEON_ORG_ID=<id de la organización en Neon>` (no son secretos; la llave de Neon va en el secreto `golden-neon-api-key`).
`OFFSITE_FOLDER_URL` alimenta Configuración › Copias de seguridad (botón «Abrir carpeta de copias», solo admin y super admin).

## Servidores locales: el paquete de actualización sale solo (18-nov-2026)
`manual_deploy.sh production` termina con el paso «5. PAQUETE DE ACTUALIZACIÓN»: construye `golden-local-update-<fecha UTC>.zip` (+ `.sha256` + `.commit`) del MISMO commit, lo sube a `system/local-update/` y comprueba que `/api/ops/update-manifest` lo anuncia. Si falla, el script avisa y sale con código 2 (el despliegue ya salió, pero los locales no verán la versión). El manifiesto anuncia el commit del paquete; si producción va adelante del paquete, dice «se está preparando» y no ofrece «Actualizar ahora». El instalador `.exe` sigue siendo manual (`deploy/windows/build_en_cloudshell.sh`) y solo hace falta para instalaciones nuevas.


## 7. Sitio web: «Pide tu cotización» (`QUOTE_TO_EMAIL`, `QUOTE_ALLOWED_ORIGINS`)
La ruta pública `POST /api/public/quote-request` (servicio `golden-publico`, sin sesión ni base nueva) manda por correo la solicitud del sitio corporativo. Juan David pone dos variables en cada entorno; Claude no las toca:
- `QUOTE_TO_EMAIL`: correo de una persona de Golden que recibe las solicitudes. Es un dato personal: va en **Secret Manager** (secreto `QUOTE_TO_EMAIL`, expuesto como variable de entorno al servicio `golden-web`, que es quien envía el correo desde la cola, y también a `golden-publico`, que la comprueba antes de aceptar), **nunca en el repo**. Sin ella la ruta responde 503 «No se pudo enviar ahora, escríbanos por WhatsApp».
- `QUOTE_ALLOWED_ORIGINS`: no es secreto; variable normal de Cloud Run (`golden-publico`), por ejemplo `https://golden-eventos.com,https://www.golden-eventos.com`. Vacía = solo mismo origen. Solo esta ruta acepta esos orígenes.
- En Firebase Hosting la regla de reescritura de `/api/public/**` hacia `golden-publico` sale sola de `deploy/firebase/make_config.py`. Límites: 5 intentos por IP cada 10 min (`QUOTE_IP_MAX_PER_10MIN`) y cuerpo de 8 KB.

**Cableado automático (23-nov-2026):** `config.sh`/`deploy.sh` ya ponen solos `QUOTE_ALLOWED_ORIGINS` (producción: `https://golden-eventos.com,https://www.golden-eventos.com`; staging: `https://golden-sitio-<número del proyecto>.web.app`) y conectan el secreto `golden-quote-to-email` (staging: `golden-quote-to-email-staging`; el nombre lleva el prefijo `golden-` y el sufijo del entorno, ver `secret_name` en `config.sh`) a `golden-web` y `golden-publico` SI EXISTE. Lo que falta es crear el secreto (con ESE nombre) y darle permiso de lectura a la cuenta de la app (una cuenta creada después del `bootstrap.sh` no lo tiene), una vez por proyecto, **sin escribir el correo en el historial** (el comando lo pide a ciegas):
```bash
# producción: S=golden-quote-to-email  P=goldenweb-prod  SUF=      staging: S=golden-quote-to-email-staging  P=goldenweb-staging  SUF=-staging
read -rsp "Correo de quien responde las cotizaciones: " Q; echo; printf %s "$Q" | gcloud secrets create $S --data-file=- --project $P; unset Q
for SA in golden-app golden-ops; do gcloud secrets add-iam-policy-binding $S --project $P --member "serviceAccount:${SA}${SUF}@$P.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --quiet | tail -1; done   # SUF=-staging en staging, vacío en producción; sin el permiso de golden-ops el despliegue falla en el Job de operaciones (pasó el 23-nov)
```
Después hay que volver a desplegar para que los servicios lo lean. **Staging nunca manda correos reales** (no lleva las credenciales de Microsoft). OJO (corregido 23-nov-2026): sin el secreto `quote-to-email` el formulario responde 503 también en staging (se comprobó); para ensayar el mensaje «Recibimos su solicitud» en staging hay que crear allí el secreto con una dirección inventada (p. ej. `staging@example.invalid`) y redesplegar; el correo no sale y la tarea falla tras sus reintentos, sin efecto. La entrega real solo se prueba en producción.
