# URL limpia de las inscripciones (D2.5k) — implementada el 9-nov-2026

**Qué es:** el enlace público de un formulario pasa de `app.golden-eventos.com/f/123/feria` a `inscripciones.golden-eventos.com/congreso-g12-2026/feria`, y `inscripciones.golden-eventos.com/congreso-g12-2026` abre el formulario principal del evento.
Decisión de Juan David (9-nov-2026 14:36): se hace ahora, con host propio. **Mientras no se configure el host (`PUBLIC_FORMS_BASE_URL`) NADA cambia**: los enlaces siguen saliendo como `/f/<id>/<slug>` y `/f/…` funciona siempre (correos y QR ya enviados).

## Qué quedó en el código (rama `f7/url-limpia`, migración `0113_public_slug`)
- **Nombre del evento en el enlace** (`events.public_slug`): único en TODO el sistema (índice único en minúsculas). Se genera de «nombre + año» (`congreso-g12-2026`, con `-2`, `-3`… si choca), también para los eventos que ya existen (la migración los rellena, idempotente). Los eventos nuevos y los importados reciben el suyo (el importado nunca hereda el del origen).
- **Reglas:** `a-z`, `0-9` y guiones; 3–60 caracteres; no solo números; lista de reservadas (`static`, `api`, `health`, `ready`, `webhooks`, `f`, `b`, `c`, `r`, `login`, `logout`, `kiosk`, `sistema`, `admin`, `privacidad`, `terminos`, `reembolsos`, `inscripciones`, `www`…: `app/public_slug.py`).
- **Quién lo cambia:** comercial, admin y super_admin, en «Editar evento → Enlace de inscripciones» (vista previa del enlace, disponibilidad mientras se escribe y «Formulario principal»). API: `GET/PUT /api/events/{id}/public-link`. Queda en `audit_actions`. No se puede con el evento en un servidor local.
- **Renombrar:** el nombre viejo queda en `slug_history`, responde **301** al nuevo y NO se reasigna a otro evento durante 12 meses.
- **Rutas públicas** (`app/routers/clean_url.py`): `GET /<evento>` (formulario principal; si ninguno está marcado y hay UN solo formulario abierto, ese; si no, 404) y `GET /<evento>/<formulario>`. Solo sirven la PÁGINA (el mismo cascarón de `/f/{id}/{slug}`, que sigue hablando con `/f/{id}/{slug}/state|submit|…`). Un formulario en pruebas, finalizado o archivado da 404 igual que hoy (con `?k=` el de pruebas). Se registran AL FINAL de la app y solo en `all` y `publico`, así que no tapan ninguna ruta existente.
- **Enlaces que salen:** con `PUBLIC_FORMS_BASE_URL` puesta y el evento con nombre, el panel y los enlaces personales por invitado salen limpios. Sin la variable, como siempre.
- **Infraestructura en el repo:** `make_config.py … --inscripciones` arma el segundo sitio de Hosting (todo → `publico`, `/static` desde la CDN); `manual_deploy.sh` (paso 4b) y el workflow `cloudrun-deploy.yml` lo publican SOLO si existe `FORMS_SITE`; el host entra al CORS del bucket (`config.sh`) y a los orígenes permitidos del CSRF.

## Decisión sobre la caché (no se cambió)
El diseño D2.5k decía «no-store» en la página y en `state`. Se **dejó como está**: la página es un cascarón igual para todos (`s-maxage=60`, ya probado bajo carga en docs/14-15) y `state` no se cachea por defecto (`FORM_STATE_CDN_SECONDS=0`). El cupo y el estado llegan siempre por `state`, no por el HTML. La resolución del nombre (`/<evento>`) usa la caché pública de 30 s y se vacía al cambiar el nombre.

## Pasos que faltan en la nube (los hace una persona; nada de esto lo hace el código)
**Quién:** los de Google Cloud/Firebase y GitHub, Juan David; los de Cloudflare, Claude en el navegador (o Juan David si prefiere).

### 1. Firebase (Juan David) — producción, proyecto `goldenweb-prod`
1. Consola de Firebase → **Hosting** → **Agregar otro sitio** → ID `golden-inscripciones` (el ID es el nombre del sitio; queda `golden-inscripciones.web.app`).
2. En ese sitio → **Agregar dominio personalizado** → `inscripciones.golden-eventos.com` → Firebase muestra los **registros DNS** que hay que crear (un TXT de verificación y los A, o un CNAME). **Copiar esos valores exactos.**
3. (Solo lo ve Firebase una vez: no cerrar la ventana hasta terminar el paso 2 de Cloudflare.)

### 2. Cloudflare (Claude en el navegador, con Juan David delante o su sesión abierta)
1. Entrar a Cloudflare → dominio `golden-eventos.com` → **DNS → Registros**.
2. Crear exactamente los registros que dio Firebase para `inscripciones` (nombre `inscripciones`). **Todos en «Solo DNS» (nube GRIS), nunca naranja**: la IP real del visitante depende de que Cloudflare no haga de proxy (docs/15), y detrás de Firebase la cookie y los límites por IP se rompen con el proxy.
3. Volver a Firebase y esperar a que el dominio pase a «Conectado» (el certificado se emite solo; puede tardar de minutos a unas horas).

### 3. GitHub y despliegue (Juan David)
1. Variables del Environment `production` (no son secretos): `FORMS_SITE` = `golden-inscripciones` y `PUBLIC_FORMS_BASE_URL` = `https://inscripciones.golden-eventos.com`.
2. Desplegar la versión que trae esta rama (junto con el resto de la etapa; migración `0113`). Con el despliegue manual: `FORMS_SITE=golden-inscripciones PUBLIC_FORMS_BASE_URL=https://inscripciones.golden-eventos.com bash deploy/gcp/manual_deploy.sh production goldenweb-prod`.
3. El CORS del bucket se actualiza con `bash deploy/gcp/cors.sh production` (ya incluye el host nuevo si `PUBLIC_FORMS_BASE_URL` está definida en ese entorno).

### 4. Verificar (Claude en el navegador, lectura)
- `https://inscripciones.golden-eventos.com/<evento>/<formulario>` abre el formulario; `…/<evento>` abre el principal; un nombre viejo redirige; `/f/<id>/<slug>` sigue; enviar una inscripción de prueba (formulario en pruebas con `?k=`) y subir un archivo (valida el CORS).
- Revisar que ningún registro quedó con la nube naranja.

### Staging (opcional)
Mismo procedimiento con un sitio `golden-inscripciones-staging` y, si no hay dominio, probar solo con `https://golden-inscripciones-staging.web.app` como `PUBLIC_FORMS_BASE_URL`.

## Lo que NO se pudo probar aquí
Las pruebas pytest (`tests/test_url_limpia.py`) están escritas pero no corren en este entorno (sin Postgres): se verifican en la corrida única de Cloud Shell. El sitio de Hosting, el certificado y los registros DNS no existen hasta que se hagan los pasos de arriba.
