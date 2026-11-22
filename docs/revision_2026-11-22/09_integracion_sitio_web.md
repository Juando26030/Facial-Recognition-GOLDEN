# 09 · Integración del sitio web corporativo en golden-eventos.com

**Fecha:** 22-nov-2026 · **Rol:** ingeniero de plataforma (montaje del sitio) · **Rama:** `saas/revision-integral` (plataforma) · **Sitio:** `golden-sitio-web` commit `6eb6b6a` (Astro 7, estático).
**Qué NO se hizo:** ningún comando de nube, ningún cambio de DNS, ninguna publicación, ningún commit ni push en la plataforma, ninguna escritura en `/home/claude/golden-sitio-web` (se trabajó sobre una copia en `/tmp`). Guía de ejecución para Juan David: `docs/26_SITIO_WEB_MONTAJE.md`.

---

## 1. Resumen en 5 líneas

1. **Quedó listo para publicar, sin ejecutar nada:** `deploy/sitio/` (configuración de Firebase Hosting, script de despliegue con comprobaciones, parche del sitio, comparador visual), el flujo manual `.github/workflows/sitio-deploy.yml` y la guía paso a paso `docs/26_SITIO_WEB_MONTAJE.md` (dominio, DNS, redirección del dominio viejo, Search Console, cómo deshacer, y el texto para el bot del sitio).
2. **Lo más grave: no se pudo compilar el sitio aquí** (este entorno no llega al registro de npm y Astro no está instalado), así que el parche está comprobado en que **aplica limpio** sobre `6eb6b6a`, pero **no** en que compila ni en que se ve idéntico. El primer paso de Juan David es un ensayo que compila y revisa sin publicar (`SOLO_COMPILAR=1`), justamente para cerrar ese hueco.
3. **Hallazgo nuevo:** `favicon.ico` y `favicon.svg` del sitio eran el **cohete de la plantilla de Astro**, no el emblema de Golden; Google toma `/favicon.ico` para mostrar el icono en los resultados. Corregido en el parche.
4. **Lo más valioso:** el parche deja el sitio «entendible» para Google sin cambiar su aspecto (indexable solo en producción, dirección definitiva, canónica, sitemap y robots generados, datos estructurados, Open Graph, títulos con palabras de búsqueda) y el despliegue **se niega a publicar** si algo de eso falta.
5. **Sigue sin resolver y pesa:** el formulario de cotización no envía (S2, requiere servidor; diseño propuesto), el teléfono único (S5, decisión de Juan David), la licencia web de la fuente Agrandir y la revisión de la asesora jurídica de las dos páginas legales, que se publican como BORRADOR y sin indexar.

---

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Crítica | No se pudo compilar el sitio: `npm ci` falla (sin acceso a `registry.npmjs.org`; `node_modules` del sitio está vacío; no hay Astro en el equipo). | Entorno de trabajo | El parche no está probado en compilación ni comparado visualmente contra el original. | Pendiente: lo cierra el paso 2 de `docs/26` (`SOLO_COMPILAR=1`) + `comparar.py`. Mitigado con las comprobaciones de la sección 5. |
| 2 | Alta | `favicon.ico` (32 px) y `favicon.svg` son el cohete de la plantilla de Astro. | `golden-sitio-web/public/` | Google y varios navegadores piden `/favicon.ico`: saldría el logo de Astro junto al nombre de Golden. | Corregido en el parche (ICO multitamaño con el emblema; SVG eliminado). |
| 3 | Alta | El sitio pide `noindex` y `Disallow: /`; un olvido el día del montaje lo deja invisible, y quitarlo a ciegas haría indexable la vista previa. | `Base.astro`, `public/robots.txt` | Sin esto no hay posicionamiento. | Corregido: indexable **solo** si se compila con `PUBLIC_INDEXAR=1` (lo hace el script); el script falla si la portada sale con `noindex`. |
| 4 | Alta | `site` apuntaba a la vista previa; sin canónica, `og:url`, sitemap ni datos estructurados. | `astro.config.mjs`, `Base.astro` | Google podía tomar la vista previa como original. | Corregido (S3, S4, S6, S12). |
| 5 | Alta | La sección «Lo que hemos hecho» publica tres marcos vacíos. | `index.astro`, `inicio.json` | Se indexa texto de relleno y resta confianza. | Corregido con bandera `eventos.publicar: false` (no se borró nada); también saca «Eventos» del menú. **Es el único cambio visible de la portada.** |
| 6 | Alta | El formulario de cotización no envía. | `cotizar.astro` | Es el único llamado a la acción. | Propuesto (diseño en `docs/26` Parte C). No publicar campaña hasta activarlo. |
| 7 | Media | El enlace «Política de privacidad» del pie y del formulario iba a la política de la plataforma (asistentes), que no cubre el sitio. | `sitio.json → privacidad` | Aviso de privacidad incorrecto para quien cotiza. | Corregido: `/privacidad` propia (BORRADOR); el enlace de la sección GoldenWeb sigue yendo a la de la plataforma (`privacidadPlataforma`). |
| 8 | Media | Las páginas legales nuevas son borradores sin revisar por la asesora. | `/privacidad`, `/inteligencia-artificial` | Publicar un texto legal sin revisar como definitivo es un riesgo. | Mitigado: marca visible «BORRADOR», `noindex` y fuera del sitemap mientras `sitio.json → legal.borrador` sea `true`. **Decisión para Juan David:** si prefiere no publicarlas ni como borrador, se quitan esos dos archivos del parche. |
| 9 | Media | El parche pesa 392 KB (5 imágenes nuevas) y es una muleta: cada cambio del bot en `Base.astro` puede obligar a regenerarlo. | `deploy/sitio/parche/` | Mantenimiento. | Mitigado: `rehacer_parche.sh` y regla «el bot incorpora el parche a su `main`» (texto listo en `docs/26`). |
| 10 | Media | `.gitattributes` no protege `*.patch`: en un Windows con conversión de saltos de línea el parche podría dañarse. | `.gitattributes` (fuera de mi área) | El despliegue corre en Linux (Cloud Shell/GitHub), ahí no pasa. | Propuesto: agregar `deploy/sitio/parche/*.patch -text`. |
| 11 | Media | Si el repositorio `golden-sitio-web` es privado, el flujo de GitHub necesita un secreto `SITIO_REPO_TOKEN` y Cloud Shell un `gh auth login`. | `sitio-deploy.yml`, `deploy_sitio.sh` | Sin eso no clona. | Previsto en ambos; no pude comprobar si es público. |
| 12 | Baja | El título por defecto mide 73 caracteres (Google corta cerca de 60). | `sitio.json → seo.titulo` | La marca queda cortada al final; las palabras de búsqueda van primero. | Aplicado tal como lo propuso el reporte 08; se cambia en un solo lugar. |
| 13 | Baja | Sin política de seguridad de contenido (CSP) en el sitio: usa estilos y un script en línea. | `deploy/sitio/firebase.json` | Riesgo bajo en un sitio estático sin formularios que envíen. | Se pusieron `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`. CSP: pendiente (requiere compilar para sacar los hashes). |

**Sobre el diseño encargado (segundo sitio de Firebase Hosting):** no encontré una razón fuerte en contra. Reutiliza cuenta, permisos (`golden-deployer` ya tiene Hosting a nivel de proyecto) y forma de desplegar; costo cero; independiente de la plataforma. Única salvedad: la cuota gratuita de Hosting es por proyecto y se comparte con el sitio de la app (irrelevante al tamaño actual).

---

## 3. Qué se cambió

### En la plataforma (archivos nuevos; ningún archivo existente modificado)

| Archivo | Qué hace |
|---|---|
| `deploy/sitio/VERSION` | Commit completo del sitio aprobado (`6eb6b6a5…`). |
| `deploy/sitio/firebase.json` | Hosting del sitio: `/_astro/**` y `/fonts/**` inmutables 1 año; HTML y lo demás `max-age=0, must-revalidate`; imágenes 1 semana; tipos de `sitemap.xml`, `robots.txt` y `site.webmanifest`; direcciones limpias sin barra final; cabeceras de seguridad. La 404 es `dist/404.html`. |
| `deploy/sitio/deploy_sitio.sh` | Clona el sitio en `VERSION` → aplica el parche → `npm ci` y `PUBLIC_INDEXAR=1 npm run build` → comprueba `dist/` → `firebase deploy --only hosting:sitio`. Sin `FORCE`, sin nada de la plataforma. Modos `SOLO_COMPILAR=1` (ensayo) y `CANAL=<nombre>` (dirección temporal). No crea el sitio de Hosting: si no existe, se detiene y da el comando. |
| `deploy/sitio/rehacer_parche.sh` | `comprobar` / `abrir` / `guardar` el parche cuando el sitio cambió. |
| `deploy/sitio/comparar.py` | Comparador visual: sirve dos `dist/`, captura 3 páginas × 9 anchos (320-3440 px) con Chromium, compara píxeles y texto, detecta desborde horizontal. |
| `deploy/sitio/parche/0001-montaje-golden-eventos.patch` | El parche del sitio (`git format-patch --binary` contra `6eb6b6a`). |
| `deploy/sitio/LEEME.md` | Índice de la carpeta. |
| `.github/workflows/sitio-deploy.yml` | Flujo manual (`confirm=PUBLICAR`, solo `main`) que corre el mismo script con Workload Identity. |
| `docs/26_SITIO_WEB_MONTAJE.md` | Guía para Juan David y para el bot. |

### En el sitio (dentro del parche; 23 archivos)

`astro.config.mjs`, `src/layouts/Base.astro`, `src/layouts/Legal.astro` (nuevo), `src/components/Header.astro`, `src/pages/index.astro`, `cotizar.astro`, `privacidad.astro` (nuevo), `inteligencia-artificial.astro` (nuevo), `404.astro` (nuevo), `robots.txt.ts` (nuevo), `sitemap.xml.ts` (nuevo), `src/data/sitio.json`, `src/data/inicio.json`, `public/` (`favicon.ico` reemplazado; `favicon.svg` y `robots.txt` eliminados; `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `img/og.jpg`, `site.webmanifest` nuevos), `README.md`, `AGENTS.md`.

### Reporte 08, S por S

| Ítem | Estado | Detalle |
|---|---|---|
| S1 indexación | **Aplicado** | `noindex` solo si NO se compila con `PUBLIC_INDEXAR=1`; `robots.txt` generado con la misma regla (`Allow: /` + `Sitemap:` en producción). La vista previa sigue oculta. |
| S2 formulario | **No aplicado** (encargo) | Diseño en `docs/26` Parte C. |
| S3 dirección y canónica | **Aplicado** | `site: https://golden-eventos.com`; canónica y `og:url` sin barra final. |
| S4 sitemap | **Aplicado, sin paquete** | `@astrojs/sitemap` no está instalado ni en el `package-lock`: se genera `/sitemap.xml` al compilar desde las páginas que existan (una página nueva entra sola). Ojo: la dirección es `/sitemap.xml`, no `/sitemap-index.xml`. |
| S5 contacto único | **No aplicado** | Decisión de Juan David (teléfono). No se tocó ningún dato de contacto. |
| S6 datos estructurados | **Aplicado** | `Organization`+`LocalBusiness` y `WebSite` en todas las páginas, `FAQPage` en la portada; solo con datos de `sitio.json`/`inicio.json`. Código postal y año de fundación quedan vacíos con nota «PENDIENTE Juan David» y **no se publican**. No se incluyó `Service` con direcciones: las páginas por servicio aún no existen. |
| S7 título y descripción | **Aplicado en parte** | Título y descripción por defecto (los del reporte 08) y de `/cotizar`. El H1 creativo se conserva. **No** se cambió el `kicker` de la portada (es texto visible/comercial). |
| S8 marcos vacíos | **Aplicado** | Bandera `inicio.json → eventos.publicar` (`false`). No se tocó el marco «Video de la plataforma en uso» de la sección GoldenWeb (sigue visible: pendiente de un video o captura real). |
| S9 scroll con inercia | **No aplicado** (encargo) | |
| S10 dominio viejo | **Preparado** | `.htaccess` exacto y pasos en `docs/26` paso 5 y 7. Lo ejecuta Juan David. |
| S11 términos (PayU) | **No aplicado** | Es texto legal/comercial; `/terminos` sigue mencionando PayU. Pendiente con la asesora. |
| S12 Open Graph | **Aplicado** | `og:type`, `og:site_name`, `og:image` (1200×630: emblema sobre crema, provisional), medidas, `twitter:card`. |
| S13 fuentes WOFF2 | **No aplicado** (encargo) | Licencia Agrandir sigue pendiente. |
| S14 encabezados | **Aplicado en parte** | «Preguntas frecuentes» y «Por qué Golden» pasan de `<p>` a `<h2>` con la misma clase `.kicker` (verificado: mismas medidas y captura idéntica en 4 anchos). **No** se renombraron los `id` `servicios`/`lineas`: cambia a dónde llevan el menú y «Ver qué hacemos»; lo decide el bot del sitio. |
| S15 accesibilidad | **Aplicado a, b, c, e** | (a) sin `tabindex` en `<li>` decorativos; (b) `role="img"` solo en la tarjeta, el botón «Ver el reverso» queda accesible; (c) `aria-invalid` + `aria-describedby` con mensajes solo para lector de pantalla (lo visible no cambia); (e) «Correo o celular» sin `autocomplete="email"`. (d) botón de pausa de la cinta: no (cambia lo visual). |
| S16 páginas legales | **Aplicado como BORRADOR** | `/privacidad` (texto B) e `/inteligencia-artificial` (textos C y D, porque C enlaza la ficha). Sin enlace nuevo en el pie para no cambiar lo visual: se llega desde el enlace «Política de privacidad» que ya existía y desde la propia política. |
| S17 README | **Aplicado** | README en español con lista de revisión; nota de publicación en `AGENTS.md`. |
| S18 iconos | **Aplicado, con corrección** | `apple-touch-icon`, `site.webmanifest`, iconos 192/512. **No** se declaró `favicon.svg` (era el de Astro): se eliminó y se rehízo `favicon.ico`. |
| P1-P4, D1-D8 | No son de este encargo | Plataforma. |
| Plan de contenido (§5) | No aplicado | Lo redacta Juan David con el bot; va en el texto para el bot. Se agregó la 404. |

---

## 4. Qué queda pendiente y por qué

| Orden | Qué | Horas | Quién |
|---|---|---|---|
| 1 | Ensayo de compilación (`SOLO_COMPILAR=1`) y comparación visual original vs. parchado con `comparar.py` (con `eventos.publicar: true` para probar «idéntico», y con `false` para ver la diferencia esperada) | 0,5 | Juan David en Cloud Shell, o cualquier sesión con acceso a npm |
| 2 | Decidir: ¿se publican `/privacidad` e `/inteligencia-artificial` como borrador, o se esperan a la asesora? | — | Juan David |
| 3 | Pasos 1-4 de `docs/26` (crear sitio, publicar, dominio) | 1 + espera del certificado | Juan David |
| 4 | Formulario de cotización (S2) con aviso de privacidad | 4-6 | Agente de plataforma + asesora (texto A) |
| 5 | Teléfono y correo únicos (S5) | 0,5 | Juan David |
| 6 | Redirección del dominio viejo, Search Console ×2, Cambio de dirección, Business Profile, Bing (pasos 5-9) | 3 | Juan David |
| 7 | Que el bot incorpore el parche a su `main` (parche vacío) | 0,5 | Bot del sitio |
| 8 | Páginas por servicio y `/contacto` (reporte 08 §5) | 2-3 por página | Juan David + bot |
| 9 | Términos sin PayU (S11), textos legales definitivos | 1 + asesora | Bot + asesora |
| 10 | S9, S13, S15d, CSP, `-text` para `*.patch` en `.gitattributes` | 3 | Bot / plataforma |
| 11 | Licencia web Agrandir; código postal y año de fundación | — | Juan David |

---

## 5. Qué NO se pudo comprobar (y qué sí)

**No se pudo:**
- **Compilar el sitio** (original ni parchado): `npm ci --offline` → `ENOTCACHED`; `npm ci` → sin resolución de `registry.npmjs.org`. Por tanto no sé con certeza que el parche compile en Astro 7. Riesgos concretos que solo la compilación despeja: que `import.meta.env.PUBLIC_INDEXAR` llegue desde la variable del comando, la forma exacta de `Astro.url.pathname` (el código la normaliza en ambos casos), `import.meta.glob` en `sitemap.xml.ts` y el uso de `set:html` en `Legal.astro`.
- **Comparar visualmente** `dist/` original contra `dist/` parchado. `comparar.py` solo se probó con dos carpetas de prueba hechas a mano (detecta bien «idéntico» y «distinto»).
- **Leer el documento 66** del proyecto (de donde debía salir `comparar.py`): no está en disco y no tengo herramienta para leer el proyecto. `comparar.py` es una versión propia con el mismo propósito.
- **Confirmar la sintaxis fina de Firebase Hosting** (no pude abrir su documentación desde aquí): el orden de precedencia cuando dos reglas de cabeceras coinciden (asumí «gana la última», por eso van de general a específica) y que `/cotizar` se sirva desde `cotizar/index.html` con `trailingSlash: false`. Se confirma en el paso 3 mirando `https://golden-sitio-….web.app/cotizar` y con `curl -sI …/_astro/<archivo>`.
- Los registros DNS exactos que pedirá Firebase (los muestra su consola; la guía dice usar esos), si el repositorio del sitio es público, qué hay hoy en el registro raíz de `golden-eventos.com`, y qué direcciones del sitio viejo tienen visitas.
- El flujo de GitHub y `deploy_sitio.sh` no se ejecutaron (solo `bash -n` y validación del YAML).

**Sí se comprobó:**
- El parche **aplica limpio** (`git apply --check`) sobre `6eb6b6a` y el resultado es byte a byte igual a la copia de trabajo; `rehacer_parche.sh comprobar` lo confirma.
- `<p class="kicker">` → `<h2 class="kicker">` con el CSS real del sitio: mismas propiedades calculadas, misma caja y **captura idéntica** a 320, 860, 1440 y 3440 px (también con `.metodo__sub`).
- Los JSON (`sitio.json`, `inicio.json`, `firebase.json`, `site.webmanifest`) son válidos; `ruff check deploy/sitio/comparar.py` pasa.
- Las imágenes nuevas se generaron del emblema que ya está en el sitio (`public/img/emblema-1120.webp`), sin texto ni elementos nuevos.

---

## 6. Consejo en corto y veredicto

- **Contrario:** «Un parche de 392 KB sin compilar no es una entrega, es una promesa.» — Cierto: por eso el primer comando es un ensayo que no publica y el script se niega a publicar si algo no cuadra.
- **Primeros principios:** un sitio estático solo necesita tres cosas para montarse bien: una dirección única, que Google pueda entrar, y poder volver atrás en un clic. Las tres quedan resueltas; el resto es contenido.
- **Expansionista:** con el sitio en el mismo proyecto y un endpoint en `publico`, cada cotización puede caer directo en el CRM; y `/inteligencia-artificial` es material de venta para el SaaS, no solo cumplimiento.
- **Forastero:** lo que un visitante notará no es el JSON-LD: es que ya no hay marcos vacíos, que el icono es el de Golden, y que el botón de cotizar todavía no envía. Eso último es lo que hay que arreglar antes de anunciar nada.
- **Ejecutor:** ensayo hoy (10 minutos), publicar en `.web.app`, mirar, conectar el dominio; el dominio viejo y Search Console al día siguiente; el parche al bot esta misma semana.

**Veredicto:** el montaje está listo para ejecutarse y es reversible en cada paso, pero no debe darse por bueno hasta ver compilar el parche. **UN siguiente paso:** que Juan David corra en Cloud Shell `SOLO_COMPILAR=1 bash deploy/sitio/deploy_sitio.sh goldenweb-prod` (no publica nada) y pegue el resultado.
