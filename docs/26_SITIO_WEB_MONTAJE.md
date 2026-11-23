# 26 · Montaje del sitio web corporativo en golden-eventos.com

**Fecha:** 22-nov-2026 · **Estado:** todo PREPARADO en el repositorio; **nada ejecutado** (ni nube, ni DNS, ni publicación). Lo ejecuta Juan David, paso a paso, cuando lo decida.
**Decisión que implementa:** `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md` §9 (22-nov): el sitio se monta tal cual bajo **golden-eventos.com**, la plataforma sigue intacta en `app.golden-eventos.com`, la gente llega por `goldenlogisticas.com` o por `golden-eventos.com`, prioridad a salir en Google sin pagar, y el bot del sitio debe poder seguir cambiándolo.

## Cómo queda armado (en una imagen)

```
golden-eventos.com ─────────┐
www.golden-eventos.com ─301─┤→ Firebase Hosting, sitio «golden-sitio-<nº>»  (archivos estáticos del sitio web)
goldenlogisticas.com ───301─┘        ▲
                                     └─ deploy/sitio/deploy_sitio.sh: golden-sitio-web @ deploy/sitio/VERSION + deploy/sitio/parche → npm run build → firebase deploy

app.golden-eventos.com ────→ Firebase Hosting, sitio «golden-app-<nº>» → Cloud Run   (la plataforma: NO se toca)
```

- **Dos sitios de Hosting en el mismo proyecto** (`goldenweb-prod`): el de la plataforma y el del sitio web. Son independientes: publicar uno no cambia el otro.
- **Costo:** cero en la práctica. Firebase Hosting regala 10 GB guardados y ~10 GB de tráfico al mes por proyecto; el sitio pesa menos de 1 MB por visita. Sin balanceador, sin servidor, sin base de datos (regla de dinero, §4).
- **Qué se publica:** el commit del sitio escrito en `deploy/sitio/VERSION` + el parche de `deploy/sitio/parche/`. Nada más.

Archivos: `deploy/sitio/` (ver `deploy/sitio/LEEME.md`) y `.github/workflows/sitio-deploy.yml`.

---

## PARTE A0 · ENSAYO en staging (primero aquí, luego producción)
Mismo procedimiento de la Parte A pero contra el proyecto de staging, SIN tocar el dominio `golden-eventos.com` ni `goldenlogisticas.com`:
1. Paso 1 con `goldenweb-staging` en vez de `goldenweb-prod` (crea `golden-sitio-<número de staging>`).
2. Paso 2 (ensayo sin publicar) y Paso 3 con `bash deploy/sitio/deploy_sitio.sh goldenweb-staging` (agrega solo la reescritura hacia `golden-publico-staging`). Se ve en la dirección `https://golden-sitio-….web.app`.
3. En staging pon `QUOTE_TO_EMAIL` y `QUOTE_ALLOWED_ORIGINS=https://golden-sitio-<número>.web.app` (ver Parte C) y envía una cotización de prueba: debe llegar el correo.
4. Opcional, dominio de ensayo: en Firebase → Agregar dominio personalizado `sitio-staging.golden-eventos.com` y crear en Cloudflare solo el registro que Firebase muestre (nube gris). Cada paso de DNS se da uno por uno, con su orden escrito, y los ejecuta Juan David.
5. Comprobar: se ve igual que el prototipo, la fuente (Poppins) se ve bien en celular y computador, `/robots.txt` pide no indexar (en staging NO se compila con `PUBLIC_INDEXAR=1`), la cotización llega.

## PARTE A · Montaje la primera vez (Juan David)

Cada bloque es UN comando para pegar en **Cloud Shell** (console.cloud.google.com → icono `>_` arriba a la derecha), salvo donde dice «en el navegador». Orden recomendado: 1 → 2 → 3 (mirar el sitio en la dirección de Firebase) → 4 (dominio) → 5 a 9.

### Paso 0 · Estar en el repositorio y en la rama correcta
```bash
cd ~/gw-hosting && git fetch origin && git checkout <rama que el coordinador indique> && git pull && git log --oneline -1
```
*Debe verse:* la rama y el commit que el coordinador le indicó (el que trae `deploy/sitio/`). *Deshacer:* nada que deshacer.

### Paso 1 · Crear el sitio de Hosting del sitio web (una sola vez)
```bash
npx -y firebase-tools@13 hosting:sites:create golden-sitio-$(gcloud projects describe goldenweb-prod --format='value(projectNumber)') --project goldenweb-prod --non-interactive
```
*Qué hace:* crea un sitio de Hosting vacío llamado `golden-sitio-<número del proyecto>` junto al de la plataforma. No publica nada ni toca dominios.
*Debe verse:* `Site golden-sitio-… has been created` y una dirección `https://golden-sitio-….web.app`. Si pide iniciar sesión: `npx -y firebase-tools@13 login --no-localhost` y repetir.
*Deshacer:* `npx -y firebase-tools@13 hosting:sites:delete golden-sitio-<número> --project goldenweb-prod` (solo si aún no tiene dominio conectado).

### Paso 2 · Ensayo: compilar y comprobar SIN publicar
```bash
SOLO_COMPILAR=1 bash deploy/sitio/deploy_sitio.sh goldenweb-prod
```
*Qué hace:* descarga el sitio en el commit de `deploy/sitio/VERSION`, aplica el parche, compila y revisa `dist/` (canónica `https://golden-eventos.com/`, sin `noindex`, `robots.txt`, `sitemap.xml`, 404, iconos, que no quede ninguna dirección de la vista previa).
*Debe verse:* una lista de `ok` y al final `== ENSAYO TERMINADO (SOLO_COMPILAR=1): no se publicó nada`.
*Si falla:* «hace falta Node 22» → `nvm install 22 && nvm use 22` y repetir. «no se pudo clonar» → el repositorio del sitio es privado: `gh auth login` y repetir. Cualquier `FALTA` o `MAL` → no siga; avise.
*Deshacer:* nada (solo crea la carpeta `build/sitio`, que git ignora).

### Paso 3 · Publicar en la dirección de Firebase (todavía sin dominio)
```bash
bash deploy/sitio/deploy_sitio.sh goldenweb-prod
```
*Debe verse:* `== LISTO (sitio, commit 6eb6b6a)` y la dirección `https://golden-sitio-<número>.web.app`. Ábrala en el navegador: debe verse el sitio completo, igual a la vista previa (sin la sección «Lo que hemos hecho», ver Parte D).
*Nota:* en este momento el sitio YA es indexable en esa dirección `.web.app`, pero su canónica apunta a `golden-eventos.com`; conviene hacer el paso 4 el mismo día.
*Deshacer:* consola de Firebase → Hosting → sitio `golden-sitio-…` → historial de versiones → «Revertir» a la anterior; o para dejarlo en blanco: `npx -y firebase-tools@13 hosting:disable --site golden-sitio-<número> --project goldenweb-prod`.

### Paso 4 · Conectar golden-eventos.com y www (en el navegador)
**Antes de tocar nada**, en Cloudflare → `golden-eventos.com` → DNS → Records: tome una captura de pantalla de TODOS los registros actuales (es su «deshacer»). **No toque** el registro `app`, ni los `MX`, ni los `TXT` de correo (`v=spf1…`, `_dmarc`, DKIM).

1. **Firebase:** console.firebase.google.com → proyecto GoldenWeb → Hosting → sitio `golden-sitio-…` → **Agregar dominio personalizado** → escriba `golden-eventos.com` → (sin marcar redirección) → Continuar. Firebase muestra los registros exactos. Normalmente son:

   | Tipo | Nombre | Valor (use SIEMPRE el que muestre Firebase) |
   |---|---|---|
   | `TXT` | `golden-eventos.com` (en Cloudflare: `@`) | `hosting-site=golden-sitio-<número>` |
   | `A` | `golden-eventos.com` (en Cloudflare: `@`) | `199.36.158.100` |

2. **Cloudflare:** cree esos registros con la **nube GRIS («DNS only»)**. Si ya existe un `A`/`AAAA`/`CNAME` en `@` que apunte a otro lado, edítelo en vez de crear otro (dos `A` distintos rompen la verificación). TTL «Auto».
3. **Firebase otra vez:** «Verificar». El estado pasa a «Pendiente» y luego a «Conectado» (minutos a unas horas: Firebase emite el certificado).
4. **Repita para `www`:** Agregar dominio personalizado → `www.golden-eventos.com` → marque **«Redirigir a un sitio web existente»** → `golden-eventos.com`. Firebase pedirá un `CNAME` (`www` → `golden-sitio-<número>.web.app`) o un `A`; créelo en Cloudflare, también en gris. Así `www.` responde 301 a la raíz sin configurar nada más.

**Por qué nube GRIS y no naranja:** (a) Firebase verifica el dominio y renueva el certificado entrando directo a su servidor; con el proxy de Cloudflare en medio, la emisión o la renovación del certificado puede fallar meses después sin aviso; (b) Firebase ya es una red de distribución: dos en fila no aceleran y complican la caché (un cambio publicado tardaría en verse); (c) es la misma regla de `app.golden-eventos.com` (`docs/19` §10). Cloudflare queda como lo que es hoy: solo DNS.

*Comprobar:*
```bash
curl -sI https://golden-eventos.com/ | head -5 && curl -sI https://www.golden-eventos.com/cotizar | grep -i -E '^(HTTP|location)'
```
*Debe verse:* `HTTP/2 200` en la primera y `HTTP/2 301` + `location: https://golden-eventos.com/cotizar` en la segunda.
*Deshacer:* en Cloudflare, borrar los registros creados (o devolver `@` a lo que decía la captura); en Firebase, Hosting → dominio → «Quitar». La plataforma no se entera en ningún caso.

### Paso 5 · Redirección 301 desde goldenlogisticas.com (el dominio viejo)
Dos caminos. **Recomendado: A** (no mueve el DNS ni toca el correo).

**Opción A · `.htaccess` en Colombia Hosting** (cPanel → Administrador de archivos → `public_html`; active «Mostrar archivos ocultos»).
1. Descargue una copia del `.htaccess` actual (es su «deshacer»).
2. Pegue este bloque **al principio** del archivo, antes de `# BEGIN WordPress`:

```apache
# --- Redirección permanente al sitio nuevo (22-nov-2026). No afecta el correo: el correo usa los registros MX, no este archivo. ---
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{HTTP_HOST} ^(www\.)?goldenlogisticas\.com$ [NC]
# El proveedor renueva el certificado por esta carpeta: se deja pasar
RewriteCond %{REQUEST_URI} !^/\.well-known/ [NC]
RewriteRule ^(contacto|contactenos|contactanos|cotizar|cotizacion)/?$ https://golden-eventos.com/cotizar [R=301,L,NC]
RewriteCond %{HTTP_HOST} ^(www\.)?goldenlogisticas\.com$ [NC]
RewriteCond %{REQUEST_URI} !^/\.well-known/ [NC]
RewriteRule ^(terminos|terminos-y-condiciones)/?$ https://golden-eventos.com/terminos [R=301,L,NC]
RewriteCond %{HTTP_HOST} ^(www\.)?goldenlogisticas\.com$ [NC]
RewriteCond %{REQUEST_URI} !^/\.well-known/ [NC]
RewriteRule ^ https://golden-eventos.com/ [R=301,L]
</IfModule>
# --- fin de la redirección ---
```
   Todo lo demás del sitio viejo cae en la portada nueva (el sitio nuevo todavía no tiene una página por servicio; cuando existan, se agregan aquí líneas como la de `contacto`). Las direcciones viejas exactas con visitas se sacan de Search Console del dominio viejo (paso 7).
3. *Comprobar:*
```bash
curl -sI https://goldenlogisticas.com/ | grep -i -E '^(HTTP|location)' && curl -sI https://www.goldenlogisticas.com/contacto | grep -i -E '^(HTTP|location)'
```
   *Debe verse:* `301` y `location: https://golden-eventos.com/` y `…/cotizar`. Envíese un correo de prueba a `info@goldenlogisticas.com`: debe llegar igual que siempre.
*Deshacer:* volver a subir la copia del `.htaccess`. *Ojo:* el navegador recuerda los 301; pruebe en ventana de incógnito.
*Mantener:* al menos 12 meses, y el hosting de Colombia Hosting debe seguir pagado (si se cancela, se cae la redirección **y el correo**).

**Opción B · Regla en Cloudflare** (solo si algún día el DNS de `goldenlogisticas.com` se pasa a Cloudflare). No se recomienda ahora: mover los servidores de nombres obliga a copiar a mano todos los registros de correo (`MX`, SPF, DKIM, `autodiscover`) y un error deja a la empresa sin correo. Si se hace: (1) agregar el dominio en Cloudflare y revisar que importó TODOS los registros; (2) registros `A` de `@` y `www` → `192.0.2.1` con nube **naranja** (solo para que la regla tenga dónde actuar); (3) Rules → Redirect Rules → Crear: «Si el nombre de host es `goldenlogisticas.com` o `www.goldenlogisticas.com`» → Redirección dinámica, expresión `concat("https://golden-eventos.com", "/")`, código 301; (4) cambiar los servidores de nombres en el registrador. *Deshacer:* devolver los servidores de nombres a los de Colombia Hosting.

### Paso 6 · Search Console de golden-eventos.com (en el navegador)
1. search.google.com/search-console → Agregar propiedad → **Dominio** → `golden-eventos.com`. Google muestra un texto `google-site-verification=…`.
2. Cloudflare → DNS → Agregar registro: tipo `TXT`, nombre `@`, contenido ese texto. (Puede convivir con los otros `TXT`.) → en Search Console, «Verificar».
3. Sitemaps → escribir `https://golden-eventos.com/sitemap.xml` → Enviar.
4. Inspección de URL → `https://golden-eventos.com/` → «Solicitar indexación».
La propiedad de dominio cubre también `app.` y `www.`. *Deshacer:* borrar el `TXT` (pierde la verificación; no afecta al sitio).

### Paso 7 · Search Console de goldenlogisticas.com y «Cambio de dirección»
1. Agregar propiedad → Dominio → `goldenlogisticas.com` → el `TXT` se crea en Colombia Hosting (cPanel → Zone Editor → Administrar → Agregar registro `TXT` en `goldenlogisticas.com.`). Verificar.
2. Anote de «Rendimiento → Páginas» las 10 direcciones viejas con más clics (sirven para afinar el `.htaccess`).
3. Con el paso 5 ya funcionando: en la propiedad vieja → Configuración → **Cambio de dirección** → elegir `golden-eventos.com` → Validar y actualizar.
*Debe verse:* «Este sitio se está trasladando». Dura 180 días; no quitar la redirección. *Deshacer:* en la misma pantalla, «Cancelar el cambio».

### Paso 8 · Google Business Profile
business.google.com → buscar «Golden Eventos y Logística» → reclamar o crear. Categoría principal «Organizador de eventos»; dirección, teléfono y horario **idénticos** a los del pie del sitio (`src/data/sitio.json`); sitio web `https://golden-eventos.com`; fotos reales. Google verifica por video, llamada o postal. Es lo que más pesa para aparecer en el mapa con «golden eventos bogotá». *Antes:* decidir el teléfono único (hoy el sitio dice 317 427 6073 y la plataforma 318 098 1752: reporte 08, S5).

### Paso 9 · Bing Webmaster Tools
bing.com/webmasters → Importar desde Google Search Console → elegir `golden-eventos.com`. Gratis; alimenta Bing, Copilot y DuckDuckGo. *Deshacer:* eliminar el sitio en esa pantalla.

### (Opcional) Publicar desde GitHub en vez de Cloud Shell
GitHub → Settings → Environments → `production` → Variables → agregar `FIREBASE_SITE_SITIO` = `golden-sitio-<número>` (no es secreto). Después: Actions → «Sitio web (golden-eventos.com)» → Run workflow → rama `main` → escribir `PUBLICAR`. Usa la misma cuenta `golden-deployer` y Workload Identity de la plataforma (ya tiene permiso de Hosting a nivel de proyecto y solo acepta `main`). Si el repositorio del sitio es privado, hace falta el secreto `SITIO_REPO_TOKEN`.

---

## PARTE B · Cómo se cambia el sitio ya montado

1. **El bot del sitio edita en `golden-sitio-web`** (su repositorio; nadie más escribe ahí) y publica la **vista previa** en Cloudflare Pages como hasta hoy. La vista previa nunca sale en Google (se compila sin `PUBLIC_INDEXAR`).
2. **Juan David revisa la vista previa y aprueba.** El bot entrega el commit completo: `git rev-parse HEAD`.
3. **En la plataforma** (una rama, un commit): se escribe ese commit en `deploy/sitio/VERSION` y se comprueba el parche:
```bash
bash deploy/sitio/rehacer_parche.sh comprobar
```
   *Debe verse:* `APLICA LIMPIO…` (o «No hay parche»). Si dice que no aplica → «Regenerar el parche», abajo.
4. **Juan David publica:**
```bash
cd ~/gw-hosting && git pull && bash deploy/sitio/deploy_sitio.sh goldenweb-prod
```
   *Debe verse:* `== LISTO (sitio, commit <7 letras del commit aprobado>)`. Ver el cambio en `https://golden-eventos.com` (recargar; el HTML no se guarda en caché).
5. **Volver atrás:** consola de Firebase → Hosting → sitio `golden-sitio-…` → historial → «Revertir». Y devolver `deploy/sitio/VERSION` al commit anterior para que el repositorio diga la verdad.

Probar un cambio sin tocar el dominio: `CANAL=prueba bash deploy/sitio/deploy_sitio.sh goldenweb-prod` publica en una dirección temporal de Firebase (7 días).

### Regenerar el parche (cuando el bot cambió `Base.astro`, `index.astro`, `cotizar.astro`, `sitio.json`…)
```bash
bash deploy/sitio/rehacer_parche.sh abrir
```
Deja en `build/sitio/parche-trabajo` el sitio nuevo con el parche aplicado «a tres bandas»; donde chocó con un cambio del bot quedan marcas `<<<<<<<`. Se resuelven a mano (casi siempre: conservar lo del bot y volver a poner la línea del parche) y:
```bash
bash deploy/sitio/rehacer_parche.sh guardar
```
Escribe el parche nuevo en `deploy/sitio/parche/`. Luego `SOLO_COMPILAR=1 bash deploy/sitio/deploy_sitio.sh goldenweb-prod` para confirmar que compila y pasa las comprobaciones.

### Mantener el parche pequeño: que desaparezca
El parche es una muleta porque hoy nadie más puede escribir en el repositorio del sitio. **Lo correcto es que el bot incorpore el parche a su rama `main`** (una sola vez) y a partir de ahí `deploy/sitio/parche/` quede vacío: el script lo detecta («sin parche: el sitio ya trae todo») y publica el commit tal cual. Para comprobar que quedó igual, `rehacer_parche.sh abrir` + `guardar` sobre el commit nuevo debe decir «Sin diferencias».

### Comprobar que un cambio técnico no alteró lo visual
```bash
python3 deploy/sitio/comparar.py --a <dist de antes> --b <dist de después> --salida build/sitio/comparacion
```
Compara capturas de `/`, `/cotizar` y `/terminos` en 9 anchos (320 a 3440 px) y el texto visible. Debe terminar en `TODO IDÉNTICO`.

### Texto listo para pegarle al bot del sitio

> El sitio ya tiene casa definitiva: **https://golden-eventos.com**, en Firebase Hosting, publicado desde el repositorio de la plataforma. Tú sigues trabajando en `golden-sitio-web` y publicando solo la vista previa de Cloudflare Pages. Reglas nuevas:
> 1. **Incorpora a tu rama `main` el parche de montaje** que te adjunto (`0001-montaje-golden-eventos.patch`, generado contra tu commit `6eb6b6a`): `git am 0001-montaje-golden-eventos.patch` (o `git apply` y un commit tuyo). No cambia nada visual de las páginas existentes; agrega: dirección definitiva en `astro.config.mjs`, canónica, Open Graph, datos estructurados (JSON-LD) e iconos en `src/layouts/Base.astro`; `robots.txt` y `sitemap.xml` generados en `src/pages/`; páginas `/privacidad` e `/inteligencia-artificial` (BORRADOR, `sitio.json → legal.borrador`), `404`; `<h2>` en «Preguntas frecuentes» y «Por qué Golden» (misma clase, se ven igual); arreglos de accesibilidad; y la bandera `inicio.json → eventos.publicar` (hoy `false`: oculta «Lo que hemos hecho» y «Eventos» del menú hasta tener casos reales). Lee el `README.md` y el `AGENTS.md` nuevos.
> 2. **No quites** de `Base.astro` la canónica, el JSON-LD, Open Graph ni la regla `PUBLIC_INDEXAR`. No crees `public/robots.txt` ni `public/sitemap.xml` (se generan). `site` se queda en `https://golden-eventos.com`.
> 3. **Cada página nueva:** `<Base titulo="…" descripcion="…">` con título único (≤ 60 caracteres, con la palabra que la gente busca y la ciudad si aplica) y descripción única (120-160), un solo `<h1>`, secciones con `<h2>`. Entra sola al sitemap.
> 4. **Nada inventado:** ni cifras, ni clientes, ni NIT, ni teléfonos. Lo que falte se deja vacío en `src/data/sitio.json` con su `_nota`.
> 5. **Para publicar en producción:** cuando Juan David apruebe la vista previa, entrégale el commit completo (`git rev-parse HEAD`). Él (o la sesión de la plataforma) lo escribe en `deploy/sitio/VERSION` y corre el despliegue. Tú no publicas en producción.
> 6. **Siguiente trabajo de contenido, en este orden** (plan del reporte 08 §5): `/contacto`, `/servicios/registro-y-acreditacion`, `/servicios/control-de-acceso`, `/servicios/organizacion-de-eventos`, `/servicios/escarapelas-y-manillas`, `/goldenweb`. Una página = una intención de búsqueda, 400-800 palabras propias, enlace a `/cotizar`.
> 7. **No actives** las páginas legales como definitivas (`legal.borrador: false`) hasta que la asesora jurídica apruebe los textos.

---

## PARTE C · Formulario de cotización (HECHO el 22-nov-2026; sin probar con base)

`/cotizar` envía de verdad: el navegador hace `POST /api/public/quote-request` en el MISMO dominio del sitio; `deploy_sitio.sh` agrega a Firebase Hosting la reescritura `/api/public/**` → servicio Cloud Run `golden-publico` (en staging, `golden-publico-staging`; variable `SERVICIO_PUBLICO` para cambiarlo). La plataforma (`app/routers/quote_request.py`) valida, aplica un límite por IP (5 intentos cada 10 minutos), descarta lo que traiga el campo trampa y **encola un correo** a quien responde las cotizaciones. No guarda la solicitud en la base: el correo es el registro.
**Lo que pone Juan David (una sola vez por entorno; ver `deploy/gcp/README.md` §7):**
- `QUOTE_TO_EMAIL`: el correo de la persona que responde (hoy: la comercial). Es un dato de una persona: va en Secret Manager, nunca en el repositorio, y debe estar en **`golden-publico` y en `golden-web`** (el primero valida, el segundo envía).
- `QUOTE_ALLOWED_ORIGINS`: `https://golden-eventos.com,https://www.golden-eventos.com` (en staging, el dominio donde se vea el ensayo). Con la reescritura de Hosting el origen es el del sitio.
- Si `QUOTE_TO_EMAIL` falta, el formulario responde «No se pudo enviar ahora, escríbanos por WhatsApp» y no pasa nada más.
**Falta:** el aviso de privacidad (texto A del reporte 08) encima del botón y su casilla; está en borrador a la espera de la auditora. **No anunciar el sitio hasta probarlo en staging con un envío real.**

## PARTE D · Qué cambia el parche (y qué no)

| Se ve distinto | Por qué |
|---|---|
| La portada ya no muestra «Lo que hemos hecho» ni «Eventos» en el menú | Eran tres marcos vacíos («Evento real por confirmar»). Vuelven con `src/data/inicio.json → eventos.publicar: true` cuando haya casos reales. |
| Icono de la pestaña en algunos navegadores y en Google | `favicon.ico` y `favicon.svg` eran el cohete de la plantilla de Astro; ahora es el emblema de Golden. |
| Páginas nuevas: `/privacidad`, `/inteligencia-artificial`, 404 | Borradores marcados, sin indexar. |

Todo lo demás es invisible: cabeceras para Google y redes, `<h2>` con la misma clase, atributos de accesibilidad. Detalle S por S: `docs/revision_2026-11-22/09_integracion_sitio_web.md`.

## PARTE E · Deshacer todo (orden inverso)

| Qué | Cómo |
|---|---|
| Cambio de dirección | Search Console (propiedad vieja) → Configuración → Cambio de dirección → Cancelar |
| Redirección del dominio viejo | Volver a subir la copia del `.htaccess` |
| Dominio en el sitio nuevo | Cloudflare: borrar/restaurar los registros `@` y `www` según la captura · Firebase: Hosting → dominio → Quitar |
| Una publicación | Firebase → Hosting → sitio `golden-sitio-…` → historial → Revertir |
| El sitio de Hosting | `npx -y firebase-tools@13 hosting:disable --site golden-sitio-<número> --project goldenweb-prod` (lo deja en blanco) |

Nada de esto toca `app.golden-eventos.com`, Cloud Run, Neon ni el correo.

> **23-nov-2026:** `deploy/sitio/VERSION` apunta ahora a `39e4c6f` (rama `fix/pasos-tablet` del repo del sitio = `6eb6b6a` + un arreglo de 4 líneas: en tableta, 600-860 px, los tres pasos de «Cómo trabajamos» caben en la fila). El parche de montaje aplica igual encima (probado con `git am --3way`). Pendiente: que el bot del sitio incorpore esa rama a su `main`.
