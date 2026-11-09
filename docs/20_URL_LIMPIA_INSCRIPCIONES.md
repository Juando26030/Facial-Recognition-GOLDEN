# URL limpia de las inscripciones (D2.5k) — implementada el 9-nov-2026

**Qué es:** el enlace público de un formulario pasa de `app.golden-eventos.com/f/123/feria` a `app.golden-eventos.com/inscripciones/congreso-g12-2026/feria`, y `app.golden-eventos.com/inscripciones/congreso-g12-2026` abre el formulario principal del evento.
**Decisión de Juan David (9-nov-2026 14:44):** NO hay host ni sitio de Firebase aparte (se descartó `inscripciones.golden-eventos.com`): todo vive en el mismo host de la app, bajo el prefijo `/inscripciones/`. **Mientras no se defina `PUBLIC_FORMS_BASE_URL` NADA cambia**: los enlaces siguen saliendo como `/f/<id>/<slug>`, y `/f/…` funciona siempre (correos y QR ya enviados).

## Qué quedó en el código (migración `0113_public_slug`)
- **Nombre del evento en el enlace** (`events.public_slug`): único en TODO el sistema (índice único en minúsculas). Se genera de «nombre + año» (`congreso-g12-2026`, con `-2`, `-3`… si choca) y los eventos existentes lo reciben al migrar; los nuevos e importados también.
- **Reglas:** `a-z`, `0-9` y guiones; 3–60 caracteres; no solo números; lista de reservadas (`static`, `api`, `login`, …; se conserva aunque el prefijo ya evita choques).
- **Quién lo cambia:** comercial, admin y super_admin, en «Editar evento → Enlace de inscripciones» (vista previa del enlace, disponibilidad mientras se escribe y «Formulario principal»). API: `/api/events/{id}/public-link`.
- **Renombrar:** el nombre viejo queda en `slug_history`, responde **301** al nuevo (`/inscripciones/<nuevo>`) y NO se reasigna a otro evento durante 12 meses.
- **Rutas públicas** (`app/routers/clean_url.py`, prefijo `/inscripciones`): `GET /inscripciones/<evento>` (formulario principal; si ninguno está marcado y hay UN solo formulario abierto, ese; si no, 404) y `GET /inscripciones/<evento>/<formulario>`. Se registran al final y solo en `all` y `publico`. **No existen rutas en la raíz (`/<evento>`)**: no pueden tapar ninguna ruta de la app. Los formularios no publicados siguen en 404.
- **Reparto entre servicios:** `/inscripciones/` está en `appmode.PUBLIC_PREFIXES`, así que `make_config.py` genera solo la regla de Firebase Hosting `/inscripciones/** → publico` (el servicio `web` no la sirve). No hace falta tocar Firebase a mano: sale con el próximo despliegue de Hosting.
- **Enlaces que salen:** con `PUBLIC_FORMS_BASE_URL=https://app.golden-eventos.com/inscripciones` y el evento con nombre, el panel y los enlaces personales por invitado salen limpios. Sin la variable, como siempre.
- **Sin infraestructura aparte:** se eliminaron `FORMS_SITE`, `make_config.py --inscripciones`, el paso 4b de `manual_deploy.sh`, el paso del workflow, el host extra del CORS del bucket y de los orígenes permitidos (mismo host de la app).

## Caché (no se cambió)
La página es un cascarón igual para todos (`s-maxage=60`, ya probado bajo carga en docs/14-15) y `state` no se cachea por defecto; la cookie `__session` y los estáticos (`/static` desde la raíz del mismo host, CDN de Firebase) no cambian.

## Lo único que falta (despliegue, sin pasos de nube)
1. Definir `PUBLIC_FORMS_BASE_URL=https://app.golden-eventos.com/inscripciones` en el despliegue de producción (variable de entorno del Environment de GitHub, o al correr `manual_deploy.sh`: `PUBLIC_FORMS_BASE_URL=https://app.golden-eventos.com/inscripciones bash deploy/gcp/manual_deploy.sh production goldenweb-prod`).
2. Desplegar junto con el resto de la etapa (migración `0113`; el despliegue de Hosting publica la regla nueva).
3. Verificar en el navegador: `…/inscripciones/<evento>/<formulario>` abre; `…/inscripciones/<evento>` abre el principal; un nombre viejo redirige; `/f/<id>/<slug>` sigue; enviar una inscripción de prueba.

## Lo que NO se pudo probar aquí
Las pruebas pytest (`tests/test_url_limpia.py`) están escritas pero no corren en este entorno (sin Postgres): se verifican en la corrida única de Cloud Shell. Sí se comprobó a mano que `make_config.py` genera la regla `/inscripciones/**` hacia `publico` y que `appmode` la permite en `publico` y la niega en `web` y `biometria`.
