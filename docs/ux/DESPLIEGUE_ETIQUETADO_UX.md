# Ver el rediseño (rama `ux/fase1-visual`) en STAGING sin tocar la URL normal

La rama solo cambia **plantillas, CSS y JS de presentación** (nada de Python, migraciones ni endpoints). Se despliega **solo** al proyecto `goldenweb-staging`, como una **revisión etiquetada de Cloud Run sin tráfico** (`--tag ux-fase1 --no-traffic`): la URL normal de staging sigue con `migra/fase1-2`; la revisión etiquetada tiene su propia URL.

**Lo corres tú en Cloud Shell** (yo no ejecuto nada en la nube). No va a producción ni se mezcla con `corte/main`.

## 0. Condición previa (importante)
Las plantillas de esta rama usan funciones que llegan con los **ajustes del sábado 17** (`producto/ajustes-sabado17`: URL pública y aviso de la carga). Staging debe tenerlos **ya desplegados** (que `migra/fase1-2` los incluya) antes de montar la vista previa. Comprobación:
```bash
gcloud run services describe golden-web-staging --region us-east4 --project goldenweb-staging --format='value(spec.template.spec.containers[0].image)'
```
Debes ver una imagen `…/golden-staging/app:<hash>`; ese `<hash>` debe ser el de `migra/fase1-2` **con** los ajustes del sábado (pídemelo si dudas). Si no, la página de «Adjuntar Base de Datos» o la de Parámetros darán error en la vista previa.

## 1. Montar la vista previa (rápido: se superponen solo las plantillas y los estáticos sobre la imagen actual de staging)
```bash
set -e
PROJECT=goldenweb-staging; REGION=us-east4; SVC=golden-web-staging
cd ~/Facial-Recognition && git fetch origin && git checkout ux/fase1-visual && git pull origin ux/fase1-visual
BASE=$(gcloud run services describe $SVC --region $REGION --project $PROJECT --format='value(spec.template.spec.containers[0].image)')
echo "imagen base: $BASE"
D=$(mktemp -d); cp -r templates static "$D"/
printf 'FROM %s\nCOPY --chown=golden:golden templates /app/templates\nCOPY --chown=golden:golden static /app/static\n' "$BASE" > "$D/Dockerfile"
IMAGE=$REGION-docker.pkg.dev/$PROJECT/golden-staging/app:ux-fase1
gcloud builds submit "$D" --tag "$IMAGE" --project $PROJECT
gcloud run deploy $SVC --image "$IMAGE" --region $REGION --project $PROJECT --tag ux-fase1 --no-traffic
```
*Debes ver:* al final «Service [golden-web-staging] revision [golden-web-staging-0000N-xxx] has been deployed and is serving 0 percent of traffic» y una línea «The revision can be reached directly at https://ux-fase1---golden-web-staging-….run.app».

## 2. La URL etiquetada
```bash
gcloud run services describe golden-web-staging --region us-east4 --project goldenweb-staging --format=json | python3 -c "import json,sys; [print(t['url']) for t in json.load(sys.stdin)['status']['traffic'] if t.get('tag')=='ux-fase1']"
```
*Debes ver:* una sola dirección `https://ux-fase1---golden-web-staging-….run.app`. Ábrela e **inicia sesión de nuevo** (es otro dominio, la sesión no se comparte). Usa la misma base de datos de staging (no hay migraciones). **Las cargas directas de archivos grandes desde esa dirección pueden fallar** (el CORS del bucket no la conoce): para ver el diseño no importa.

## 3. Compara
- **Normal (sin etiqueta):** la URL de siempre de staging → `migra/fase1-2`.
- **Rediseño:** la URL etiquetada.
Pantallas para comparar: lista de eventos, menú del evento, Parámetros (6 pestañas), Adjuntar Base de Datos. Capturas ya hechas: `docs/ux/capturas/antes_*.png` y `despues_*.png`.

## 4. Borrarla después (en este orden)
```bash
set -e
PROJECT=goldenweb-staging; REGION=us-east4; SVC=golden-web-staging
UXREV=$(gcloud run services describe $SVC --region $REGION --project $PROJECT --format=json | python3 -c "import json,sys; print([t['revisionName'] for t in json.load(sys.stdin)['status']['traffic'] if t.get('tag')=='ux-fase1'][0])")
echo "revisión de la vista previa: $UXREV"
gcloud run services update-traffic $SVC --remove-tags ux-fase1 --region $REGION --project $PROJECT
gcloud run revisions delete "$UXREV" --region $REGION --project $PROJECT --quiet
gcloud run services update-traffic $SVC --to-latest --region $REGION --project $PROJECT
gcloud artifacts docker images delete $REGION-docker.pkg.dev/$PROJECT/golden-staging/app:ux-fase1 --project $PROJECT --quiet || true
```
*Debes ver:* la etiqueta quitada, la revisión borrada y «100 percent of traffic to LATEST». La URL normal de staging nunca dejó de servir `migra/fase1-2`.

## ⚠️ Una trampa de Cloud Run (por eso el orden de arriba)
Desplegar con `--no-traffic` deja el tráfico **fijado** a la revisión anterior. Mientras la vista previa exista, un despliegue normal a staging (un push a `migra/fase1-2`) crea su revisión pero **puede no recibir tráfico** hasta correr `update-traffic --to-latest`. Por eso el paso 4 borra primero la revisión de la vista previa y **después** hace `--to-latest` (si se hiciera antes, mandaría todo el tráfico a la vista previa, porque es la última creada). Si necesitas desplegar algo a staging mientras la vista previa existe, bórrala primero (paso 4) o dímelo.

## Alternativa sin esa trampa
Un servicio aparte (`golden-web-ux`, otra URL) no toca el tráfico del servicio de staging. Se borra con una sola orden (`gcloud run services delete golden-web-ux`). Si prefieres esa, te dejo los comandos.
