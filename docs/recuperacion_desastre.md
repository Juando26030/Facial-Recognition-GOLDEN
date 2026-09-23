# Recuperación ante desastre

Qué copias existen, dónde están y cómo se usan. Última verificación de una restauración real desde el bucket: 2026-09-23
(conteos idénticos a producción).

## Qué protege cada copia

| Copia | Qué contiene | Dónde | Frecuencia / retención | Sirve si... |
|---|---|---|---|---|
| **Snapshot del disco** | La máquina completa: sistema, Postgres, `data/`, `.env`, Nginx, certificados, cron, runner de GitHub | Snapshots de Compute Engine | Diario (02:00 Bogotá), 14 días | La VM o su disco se dañan |
| **Volcado de la base** | Solo la base `golden_db` (personas, eventos, accesos, cuentas, parámetros, encodings faciales) | `gs://golden-backups-analisis-de-imagen-id/db/AAAA/MM/` | Diario 03:00, 60 días (regla de ciclo de vida); además 7 días en `~/backups` de la VM | Se daña/borra algo en la base, o hay que armar una VM desde cero |
| **Archivos y `.env`** | `data/` (fotos, firmas, logos, plantillas de escarapela, informes, documentos) y el `.env` | `gs://<bucket-de-datos>/data/` y `/config/.env` (con versionado) | Diario 03:00, incremental | Armar una VM desde cero; recuperar un archivo puntual |
| **Código y configuración** | Código, migraciones, `requirements.txt` con versiones fijas, `deploy/nginx-golden.conf`, `deploy/facial-recognition.service`, scripts | GitHub | Cada push | Siempre |

Pérdida máxima de datos (RPO): lo ocurrido desde las 03:00 de ese día. Para bajarla, se puede correr `scripts/backup_db.sh` más seguido.

**Fuera de estas copias:** la cuenta/proyecto de Google Cloud. Si se pierde el proyecto (o alguien accede a la cuenta), los buckets y snapshots caen con él. Guarda además, fuera de Google: el `.env` en un gestor de contraseñas, y de vez en cuando baja un volcado a tu PC (`gcloud storage cp gs://.../golden_db_XXXX.sql.gz .`).

## Configuración inicial (una sola vez, en Cloud Shell)

Proyecto `analisis-de-imagen-id`, zona `us-central1-a`, VM y disco `golden-biometrics-prod`, IP reservada `golden-ip-fija`.

```bash
# 1) Snapshots diarios del disco (14 días de historial)
gcloud compute resource-policies create snapshot-schedule golden-diario --region=us-central1 \
  --max-retention-days=14 --on-source-disk-delete=keep-auto-snapshots --daily-schedule --start-time=07:00
gcloud compute disks add-resource-policies golden-biometrics-prod --zone=us-central1-a --resource-policies=golden-diario

# 2) Bucket de archivos (con versionado: si un archivo se sobrescribe o se borra por error, se puede recuperar la versión anterior)
B2=gs://golden-datos-analisis-de-imagen-id
gcloud storage buckets create $B2 --location=us-central1 --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update $B2 --versioning
gcloud storage buckets add-iam-policy-binding $B2 --member=serviceAccount:107562678730-compute@developer.gserviceaccount.com --role=roles/storage.objectAdmin
```
(El bucket de la base sigue con permiso solo de crear/leer: la VM no puede borrar volcados. El de archivos necesita poder sobrescribir, por eso `objectAdmin`, y lo compensa el versionado.)

Cron de la VM (`crontab -e`):
```
0 3 * * * GCS_BUCKET=gs://golden-backups-analisis-de-imagen-id GCS_DATA_BUCKET=gs://golden-datos-analisis-de-imagen-id bash /home/juando02603/Facial-Recognition/scripts/backup_db.sh >> /home/juando02603/backups/cron.log 2>&1
```

## Caso A — se daña o se borra algo en la base (la VM sigue viva)

1. Elegir la copia: `gcloud storage ls -r gs://golden-backups-analisis-de-imagen-id/db/` (la más reciente antes del problema).
2. `sudo systemctl stop facial-recognition`
3. Restaurar en una base NUEVA y comprobar conteos:
   `bash scripts/restore_db.sh gs://golden-backups-analisis-de-imagen-id/db/2026/09/golden_db_AAAAMMDD_HHMMSS.sql.gz golden_db_restaurada`
4. Cambiar de base (con la app parada):
   ```bash
   sudo -u postgres psql -c "ALTER DATABASE golden_db RENAME TO golden_db_danada;" -c "ALTER DATABASE golden_db_restaurada RENAME TO golden_db;"
   ```
5. `cd ~/Facial-Recognition && venv/bin/alembic current` (debe coincidir con el head del código) y `sudo systemctl start facial-recognition`.
6. Verificar en el navegador. Cuando todo esté bien: `sudo -u postgres dropdb golden_db_danada`.

Recuperar solo unas filas borradas por error: restaurar la copia en una base aparte (paso 3) y copiar de ahí las filas necesarias con `psql`, sin tocar producción.

## Caso B — se pierde o daña toda la VM (la ruta rápida: snapshot)

1. Ver los snapshots: `gcloud compute snapshots list --filter="sourceDisk~golden-biometrics-prod" --sort-by=~creationTimestamp`
2. Si la VM vieja existe pero está mala, apágala/bórrala para liberar la IP: `gcloud compute instances delete golden-biometrics-prod --zone=us-central1-a` (¡solo si ya tienes el snapshot elegido!).
3. Crear el disco y la VM nueva desde el snapshot, con la misma IP fija y los mismos permisos:
   ```bash
   gcloud compute disks create golden-biometrics-prod --source-snapshot=NOMBRE_DEL_SNAPSHOT --zone=us-central1-a
   gcloud compute instances create golden-biometrics-prod --zone=us-central1-a --machine-type=TIPO_DE_LA_VM_ANTERIOR \
     --disk=name=golden-biometrics-prod,boot=yes,auto-delete=no --address=golden-ip-fija \
     --service-account=107562678730-compute@developer.gserviceaccount.com \
     --scopes=storage-rw,logging-write,monitoring-write,service-control,service-management,trace
   ```
   (El tipo de máquina: `gcloud compute instances describe` de la VM anterior, o la consola.)
4. Esperar ~2 min y abrir https://golden.juandajuzga.com. Todo debe estar como en el snapshot: si algo falta de las últimas horas, aplicar el Caso A (restaurar el volcado de la base más reciente) y `scripts/restore_data.sh` para los archivos.

## Caso C — reconstruir desde cero (sin snapshot utilizable)

1. VM nueva (Ubuntu, misma región) con la IP `golden-ip-fija`.
2. Paquetes: `sudo apt-get install -y postgresql nginx certbot python3-certbot-nginx tesseract-ocr build-essential cmake python3-venv python3-dev libpq-dev git`.
3. Código: `git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN.git ~/Facial-Recognition`, luego `python3 -m venv venv && venv/bin/pip install -r requirements.txt` (las versiones están fijas; `dlib` tarda en compilar).
4. Base: crear el usuario y la base (`sudo -u postgres psql -c "CREATE ROLE golden_app LOGIN PASSWORD '...';"` y `createdb -O golden_app golden_db`), restaurar el volcado (Caso A, pasos 1 y 3, con destino `golden_db`; usa `FORCE_PRODUCTION=1` porque es una base vacía nueva).
5. Archivos y secretos: `RESTORE_ENV=1 bash scripts/restore_data.sh gs://golden-datos-analisis-de-imagen-id` (revisa que `DATABASE_URL` del `.env` apunte a la base nueva).
6. Servicios: `sudo cp deploy/facial-recognition.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now facial-recognition`; Nginx: copiar `deploy/nginx-golden.conf` a `/etc/nginx/sites-enabled/golden` y emitir el certificado (`sudo certbot --nginx -d golden.juandajuzga.com`).
7. Permiso para el deploy y el cron: reglas de `sudoers` para `systemctl restart|is-active|status facial-recognition`, el cron de arriba, y volver a registrar el runner de GitHub Actions (GitHub → Settings → Actions → Runners → New self-hosted runner).
8. `venv/bin/alembic upgrade head` y verificar.

## Comprobar que las copias sirven (recomendado cada cierto tiempo)

- Restaurar el volcado más reciente en una base de prueba y comparar conteos: `scripts/restore_db.sh <copia> golden_restore_check` (y luego `dropdb`).
- Revisar que ayer hubo copia: `tail -20 ~/backups/cron.log` y `gcloud storage ls gs://golden-backups-analisis-de-imagen-id/db/$(date +%Y)/$(date +%m)/`.
- Revisar que hay snapshots recientes: `gcloud compute snapshots list --limit=3 --sort-by=~creationTimestamp`.
