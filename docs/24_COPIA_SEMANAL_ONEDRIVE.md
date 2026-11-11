# Copia semanal de respaldo a OneDrive (guía para Juan David)

**Para qué sirve.** Los respaldos de la base viven en el mismo proyecto de Google que la plataforma. Si algún día se perdiera el proyecto (cuenta suspendida, borrado por error, facturación cortada), se perderían también los respaldos. Esta copia semanal deja un archivo **cifrado** en el OneDrive de la empresa, fuera de Google.

**Qué hace por sí sola, sin que nadie haga nada:** cada semana toma el respaldo más reciente, lo cifra antes de que salga de Google, lo sube a una carpeta de OneDrive y deja solo las últimas 8 copias. Lo ves en **/sistema → «Copia semanal fuera de Google»**. Si falla o pasan más de 10 días sin copia, llega un correo de alerta.

> Mientras no completes esta guía, la plataforma funciona igual: el paso dice «copia semanal no configurada» y no hace nada.

## Antes de empezar (5 minutos de decisión)
1. **¿Dónde caerán las copias?** Lo más limpio: una **carpeta en un sitio de SharePoint propio de respaldos** o en el OneDrive de **una cuenta de servicio** (no el de una persona). Si es el OneDrive de una persona y esa persona se va de la empresa, la copia se pierde con su cuenta.
2. **Quién puede entrar a esa carpeta:** pocas personas (tú y quien administre Microsoft 365).
3. Necesitas ser **administrador global** (o de aplicaciones) del Microsoft 365 de la empresa para los pasos 1–3.

## Paso 1 — Registrar la aplicación en Microsoft Entra
1. Entra a https://entra.microsoft.com con tu cuenta de administrador.
2. **Identidad → Aplicaciones → Registros de aplicaciones → Nuevo registro.**
3. Nombre: `GoldenWeb copia semanal`. Tipos de cuenta: **solo este directorio**. URI de redirección: déjalo vacío. **Registrar.**
4. En la pantalla que aparece copia dos datos (no son secretos, pero guárdalos): **Id. de aplicación (cliente)** y **Id. de directorio (inquilino)**. Son `ONEDRIVE_CLIENT_ID` y `ONEDRIVE_TENANT_ID`.

## Paso 2 — Permisos mínimos (importante)
Queremos que la aplicación pueda tocar **solo la carpeta de respaldos**, no todo el OneDrive de la empresa. Microsoft ofrece permisos «Selected» para eso (verificado en la documentación de Microsoft Graph: un permiso *Selected* no da acceso a nada hasta que un administrador asigna explícitamente el recurso y el rol, `read`, `write` u `owner`).

Opción recomendada (un sitio de SharePoint solo para respaldos):
1. En la aplicación: **Permisos de API → Agregar un permiso → Microsoft Graph → Permisos de la aplicación** → busca `Sites.Selected` → agrégalo.
2. Botón **Conceder consentimiento de administrador** para la empresa.
3. Un administrador debe **asignar el sitio** a la aplicación con rol `write` (se hace con una llamada a Graph `POST /sites/{id-del-sitio}/permissions`; si no sabes hacerla, dime y la hago yo desde el navegador contigo mirando).
4. El `ONEDRIVE_DRIVE_ID` es la biblioteca «Documentos» de ese sitio (también te ayudo a obtenerlo).

Alternativa (OneDrive de una cuenta de servicio): permiso `Files.ReadWrite.All` de aplicación. **Es más amplio**: la aplicación podría leer y escribir *todos* los OneDrive de la empresa. Úsalo solo si no hay más remedio y protege muy bien el secreto del paso 3. Si usas esta alternativa, en vez de `ONEDRIVE_DRIVE_ID` pones `ONEDRIVE_DRIVE_USER` = el correo de esa cuenta.

## Paso 3 — Crear el secreto de la aplicación
1. En la aplicación: **Certificados y secretos → Nuevo secreto de cliente** → descripción `copia semanal`, vence en **24 meses**.
2. Copia el **Valor** en ese momento (después no se vuelve a mostrar). Es `ONEDRIVE_CLIENT_SECRET`. **No lo pegues en el chat ni en el repositorio.**
3. Pon un recordatorio en tu calendario 1 mes antes del vencimiento: cuando venza, la copia deja de funcionar (te llegará la alerta, pero conviene anticiparse).

## Paso 4 — Crear la llave de cifrado
La llave convierte la copia en algo ilegible para cualquiera que no la tenga. **Si la pierdes, las copias de OneDrive no se pueden abrir nunca.** Se genera una sola vez (te la genero yo en Cloud Shell sin mostrarla, o con este comando):

    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Guarda esa llave en **dos sitios**: (a) Secret Manager (paso 5) y (b) **fuera de Google**, por ejemplo en el gestor de contraseñas de la empresa o impresa en un sobre en la caja fuerte. Es la misma lógica que `FACE_ENCRYPTION_KEY`.

## Paso 5 — Guardar los valores en Google Secret Manager (los crea Juan David, Claude no crea recursos de nube)
Nombres de los secretos (en producción llevan el sufijo habitual del entorno; en staging NO se crean, a propósito):

| Secreto | Qué va dentro |
|---|---|
| `golden-onedrive-tenant-id` | Id. de directorio (paso 1) |
| `golden-onedrive-client-id` | Id. de aplicación (paso 1) |
| `golden-onedrive-client-secret` | Valor del secreto (paso 3) |
| `golden-onedrive-drive-user` | Correo de la cuenta de servicio (solo alternativa del paso 2) |
| `golden-onedrive-folder` | Nombre de la carpeta, por ejemplo `Respaldos GoldenWeb` |
| `golden-backup-copy-encryption-key` | La llave del paso 4 |

Si usas la opción del sitio de SharePoint, en vez de `drive-user` hace falta la variable `ONEDRIVE_DRIVE_ID` (id de la biblioteca); se puede poner como variable normal del Job (no es secreta). Después se vuelve a desplegar el Job `golden-ops` (`deploy/gcp/deploy.sh`), que ya sabe leer estos secretos si existen (`OPS_SECRETS` en `deploy/gcp/config.sh`).

## Paso 6 — Alerta por correo
Ya usa `ALERT_EMAIL` (el mismo de las otras alertas del Job). No hay nada más que configurar.

## Paso 7 — Probarla ya, sin esperar una semana
Desde Cloud Shell, con el Job configurado: ejecuta el Job `golden-ops` con la tarea `offsite-copy` (`gcloud run jobs execute golden-ops --args=-m,app.ops_runner,offsite-copy` — el mismo patrón que usas para las otras tareas sueltas). Debe responder «copia subida: golden_db_….gwbk». Revisa que el archivo aparece en la carpeta de OneDrive y que **/sistema** muestra «Copia semanal fuera de Google» en verde.

## Paso 8 — Prueba de que la copia SÍ sirve (hazla una vez, y luego cada 6 meses)
1. Descarga un archivo `.gwbk` de OneDrive.
2. En un computador con Python: `pip install cryptography`, y con el repositorio descargado:
   `python scripts/open_backup_copy.py golden_db_AAAAMMDD_HHMM.gwbk copia.sql.gz` (te pide la llave, escondida).
3. `gunzip -t copia.sql.gz` debe terminar sin errores. Restaurar es igual que con cualquier respaldo (`docs/recuperacion_desastre.md`).
Si el programa dice «Llave incorrecta o archivo alterado» o «Archivo truncado», avísame: es justo lo que esta prueba busca descubrir.

## Qué hacer si llega la alerta
- «HTTP 401/403 …»: el secreto venció o se borró el permiso → pasos 3 y 2.
- «HTTP 404 …»: la carpeta o la biblioteca cambió de nombre/id → revisa `ONEDRIVE_FOLDER` y `ONEDRIVE_DRIVE_ID`.
- «No hay respaldos en el bucket»: el problema es anterior (los respaldos horarios); mira /sistema → «Último respaldo».
- «Hace más de 10 días que no hay copia»: la copia lleva tiempo fallando; el correo trae el último motivo.

## Qué se verificó y qué falta verificar (honestidad)
- **Verificado en la documentación de Microsoft** (página «Overview of selected permissions in OneDrive and SharePoint»): los permisos *Selected* (Sites.Selected, Files.SelectedOperations.Selected…) requieren consentimiento del administrador **y** asignación explícita del recurso; la asignación rompe la herencia de permisos del elemento; los roles son `read`, `write`, `owner`, `fullcontrol`.
- **NO verificado desde este entorno** (las páginas de Microsoft Learn estaban bloqueadas): URL exacta del token (`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`, flujo `client_credentials`, alcance `https://graph.microsoft.com/.default`); subida simple `PUT /drives/{id}/root:/{carpeta}/{archivo}:/content` (hasta 4 MB); sesión de carga `POST …:/createUploadSession` y trozos con `Content-Range` en múltiplos de 320 KiB (se usan 10 MiB); listado `GET …/root:/{carpeta}:/children`; borrado `DELETE /drives/{id}/items/{id}`. Están implementados como los documenta Microsoft según lo conocido, con reintentos para 429/5xx. **Se confirman en el paso 7**; si alguno cambió, el error trae el código HTTP y se corrige en `app/offsite_copy.py` (clase `GraphClient`).
- Las pruebas automáticas simulan Graph; no prueban a Microsoft de verdad.

## Datos técnicos (por si alguien los pide)
- Variables: `ONEDRIVE_TENANT_ID`, `ONEDRIVE_CLIENT_ID`, `ONEDRIVE_CLIENT_SECRET`, `ONEDRIVE_DRIVE_USER` o `ONEDRIVE_DRIVE_ID`, `ONEDRIVE_FOLDER`, `BACKUP_COPY_ENCRYPTION_KEY`; opcionales `OFFSITE_KEEP_WEEKS` (8), `OFFSITE_HOUR` (6), `OFFSITE_EVERY_DAYS` (6), `OFFSITE_RETRY_HOURS` (6), `OFFSITE_ALERT_DAYS` (10).
- No se guardan datos personales ni secretos en el estado ni en los logs (los errores muestran solo el código HTTP y la ruta final).
- Cambiar la llave: las copias antiguas siguen necesitando la llave vieja; guarda la vieja mientras exista alguna copia con ella.
