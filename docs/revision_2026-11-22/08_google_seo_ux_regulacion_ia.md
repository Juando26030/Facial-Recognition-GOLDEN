# 08 · Google (SEO), experiencia de uso y regulación de IA / privacidad — sitio web corporativo y parte pública de la plataforma

**Fecha:** 22-nov-2026 · **Rama revisada:** `saas/revision-integral` (plataforma) y `golden-sitio-web` commit `6eb6b6a` (Astro 7, estático).
**Roles:** (1) y (2) dos ingenieros de búsqueda (estándares de Google), con crítica cruzada; (3) experto en UX de sitios corporativos; (4) experto en regulación de IA y privacidad (Colombia; UE/OCDE/UNESCO como buenas prácticas).
**Qué NO se tocó:** ningún archivo de código de ninguno de los dos repositorios (otro agente integra el sitio y aplica esta lista). `app/legal_texts_data.py` y `docs/legal/` solo se leyeron.

---

## 1. Resumen en 5 líneas

1. **El sitio nuevo está bien hecho por dentro (HTML limpio, rápido, accesible en lo básico), pero hoy le dice a Google «no me muestres»**: `<meta name="robots" content="noindex">` en `src/layouts/Base.astro` y `Disallow: /` en `public/robots.txt`. Mientras eso siga, ninguna otra mejora sirve. La plataforma (`app.golden-eventos.com`) no tiene `robots.txt` y su pantalla de ingreso sí es indexable: Google podría mostrar «Ingresar | GoldenWeb 2.0» en vez del sitio corporativo.
2. **Lo más grave para el negocio:** el formulario «Pida su cotización» (el único llamado a la acción del sitio) **no envía nada** (`src/pages/cotizar.astro`: «Vista previa: el envío se activará pronto»). Se publica un sitio cuyo botón principal no funciona.
3. **Para salir arriba sin pagar** hacen falta cosas que hoy no existen: dirección definitiva en `astro.config.mjs` (hoy apunta a `vista-previa…pages.dev`), canónico, `sitemap.xml`, datos estructurados (Organization/LocalBusiness/Service/FAQ), páginas propias por servicio («registro de eventos», «control de acceso», «escarapelas»), una página de contacto con datos iguales en todas partes (hoy el sitio dice un teléfono y la plataforma otro), redirección 301 desde `goldenlogisticas.com` (el dominio viejo con historial), Google Business Profile y Search Console.
4. **Expectativa honesta:** «golden eventos», «golden eventos y logística», «golden logísticas», «registro de eventos Bogotá», «acreditación de eventos Bogotá», «control de acceso para eventos» son alcanzables. **«golden» y «eventos» a secas no**: son palabras genéricas dominadas por otros (Golden State, Golden Retriever, Eventbrite, etc.); nadie las gana sin pagar y tampoco pagando.
5. **Regulación:** la plataforma está muy por encima del promedio (consentimiento inmutable, 7 días, menores fuera, textos de la auditora). Lo que falta es **transparencia sobre la IA** (nadie dice en ninguna parte que hay un sistema de reconocimiento facial automatizado ni que el software y los textos se construyeron en parte con IA), un **aviso de privacidad propio del sitio** (el formulario de cotización recoge datos y remite a una política que habla de la plataforma, no del sitio), y a nivel técnico un **registro de decisiones del modelo** (hoy la distancia, el nivel de confianza y la marca «DUDOSO» viven en un token y no se guardan) y **pruebas de sesgo por grupo** (la precisión se midió con 39 personas sin desglose por sexo, edad ni tono de piel). Los borradores de textos están en la sección 9.

---

## 2. Hallazgos

Severidad: **Crítica** = sin esto no hay resultado o hay riesgo legal/reputacional directo; **Alta** = pesa mucho en posicionamiento o confianza; **Media** = mejora clara; **Baja** = detalle.

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Crítica | El sitio pide no ser indexado: `<meta name="robots" content="noindex">` y `robots.txt` con `Disallow: /`. | `golden-sitio-web/src/layouts/Base.astro` (línea 21), `public/robots.txt` | Google obedece: el sitio no aparece en ningún resultado. `docs/05` lo menciona como paso manual: fácil de olvidar el día del montaje. | Propuesto (sección 4, ítem S1) |
| 2 | Crítica | El formulario de cotización no envía nada; solo valida y dice «el envío se activará pronto». | `src/pages/cotizar.astro` (script al final) | Es el único objetivo del sitio. Cada visita que llega por Google se pierde. | Propuesto (S2) |
| 3 | Crítica | `site` apunta a la vista previa (`https://vista-previa.golden-sitio-web.pages.dev`); no hay `<link rel="canonical">` ni `og:url`. | `astro.config.mjs`, `Base.astro` | Sin dirección definitiva Google puede indexar la vista previa en Cloudflare Pages como «la original» y tratar `golden-eventos.com` como copia. | Propuesto (S3) |
| 4 | Crítica | No hay `sitemap.xml` ni integración que lo genere. | `golden-sitio-web/public/`, `astro.config.mjs` | Con 3 páginas no es grave hoy, pero Search Console lo pide y las páginas nuevas (sección 5) lo necesitan. | Propuesto (S4) |
| 5 | Crítica | Datos de contacto distintos entre el sitio y la plataforma: sitio = `+57 317 427 6073` e `info@goldenlogisticas.com`; plataforma (pie legal) = `+57 318 098 1752` y `soporteit@goldenlogisticas.com`; la dirección se escribe de 3 formas («Carrera 14a # 71a-59, Bogotá» / «Carrera 14a # 71a - 59, Bogotá, Colombia»); razón social en mayúsculas sin tildes en la plataforma («GOLDEN EVENTOS Y LOGISTICA SAS») y con tildes en el sitio. | `src/data/sitio.json`; `deploy/gcp/env/common.yaml` (`LEGAL_PHONE`, `LEGAL_EMAIL`, `LEGAL_NAME`, `LEGAL_ADDRESS`); `templates/_legal_footer.html` | Google cruza nombre-dirección-teléfono (NAP) entre el sitio, Business Profile, redes y directorios. Si no coinciden, baja la confianza en la ficha local. `sitio.json` ya tiene una nota «PENDIENTE: Juan confirma el número oficial de WhatsApp». | Propuesto (S5; es configuración, no código) |
| 6 | Alta | No hay datos estructurados (JSON-LD) de ningún tipo. | `Base.astro`, `index.astro` | Sin `Organization`/`LocalBusiness` Google no arma el panel de marca ni asocia redes, logo y NIT; sin `Service` no entiende qué vende; sin `FAQPage` las preguntas no se marcan. | Propuesto con el código exacto (S6) |
| 7 | Alta | Es un sitio de una sola página: solo existen `/`, `/cotizar` y `/terminos`. Todo («Registro y acreditación», «Control de acceso y zonas», «Escarapelas») vive en anclas `#` de la portada. | `src/pages/` | Google posiciona **páginas**, no anclas. Para «registro de eventos Bogotá» o «control de acceso eventos» hace falta UNA página por servicio con título, descripción, H1 y 400-800 palabras propias. Hoy la única candidata para todas esas búsquedas es la portada, cuyo H1 es «Su evento, de la puerta al aplauso.» (sin ninguna palabra que la gente busque). | Propuesto (plan de contenido, sección 5) |
| 8 | Alta | Título y H1 sin las palabras de búsqueda. `<title>` = «Golden Eventos y Logística · Eventos corporativos en Colombia»; H1 = «Su evento, de la puerta al aplauso.»; `kicker` = «Bogotá · 25 años…». | `Base.astro` (valor por defecto), `src/data/inicio.json` → `hero` | El título es lo que más pesa. Falta «registro», «acreditación», «Bogotá». El H1 creativo se puede conservar si el título y el primer párrafo llevan las palabras. | Propuesto (S7) |
| 9 | Alta | La sección «Lo que hemos hecho» publica tres marcos vacíos con «Evento real por confirmar · Nombre · ciudad · año» y «Aquí va una foto real». | `index.astro` sección 10, `inicio.json` → `eventos` | Google indexa ese texto y los visitantes lo leen: parece inacabado y resta confianza (E-E-A-T: experiencia demostrable). Mejor no publicar la sección hasta tener 2-3 casos reales con permiso. | Propuesto (S8) |
| 10 | Alta | El sitio toma el control de la rueda del ratón (`wheel` con `preventDefault`, scroll «con inercia») y usa cursor propio. | `src/scripts/fluidez.ts` (bloque «Scroll con inercia») | Lighthouse lo marca («no usa listeners pasivos»); afecta INP (Core Web Vitals) en equipos modestos; a muchos usuarios el scroll «flotante» les marea y a lectores de pantalla no les ayuda. Solo pasa con mouse/trackpad, no en celular. | Propuesto: apagarlo o dejarlo solo como opción (S9) |
| 11 | Alta | No hay redirección desde el dominio viejo `goldenlogisticas.com` (WordPress, con años de historial y enlaces) hacia `golden-eventos.com`. | Decisión 22-nov (`docs/REGLAS_INAMOVIBLES…` §9); `docs/05_como_montar…` | Si el viejo sigue vivo compite consigo mismo; si se apaga sin 301, se pierde el historial. Hace falta 301 por URL (al menos raíz, `/servicios`, `/contacto` del viejo) y «Cambio de dirección» en Search Console. | Propuesto (S10; lo ejecuta Juan David en DNS/Colombia Hosting) |
| 12 | Alta | La plataforma no sirve `robots.txt` (404) y `/login` es indexable (sin `noindex`, sin descripción). `/` redirige a `/login`. | `app/main.py`, `templates/login.html`; `app/public_slug.py` reserva «robots-txt» y «sitemap-xml» pero no existe ruta | Google puede mostrar la pantalla de ingreso de la plataforma para «golden eventos» por encima del sitio. Las únicas páginas que sí deben indexarse en `app.` son `/privacidad`, `/terminos`, `/reembolsos`. | Propuesto (P1, P2) |
| 13 | Alta | No hay aviso de uso de inteligencia artificial en el sitio ni en la plataforma: ni que el reconocimiento facial es un sistema automatizado de identificación biométrica asistido por un operador humano, ni que el software, los textos y las animaciones se construyeron en parte con IA. | Sitio: ninguna página. Plataforma: `templates/legal_privacidad*.html`, `docs/legal/POLITICA_v1.1.md` (no mencionan «inteligencia artificial», «automatizado» ni «sesgo») | Transparencia exigida como buena práctica (OCDE 2019/2024 principio 1.3; UNESCO 2021 §«Transparencia y explicabilidad»; Ley de IA de la UE art. 13 y 50 para sistemas de alto riesgo e interacción con personas) y esperada por la SIC bajo el principio de **responsabilidad demostrada** (Decreto 1377/2013 arts. 26-27). También protege la marca: un cliente que descubre después que «lo hizo una IA» se siente engañado. | Borrador listo (sección 9, textos C y D) |
| 14 | Alta | El formulario de cotización recoge nombre, empresa, correo/celular y remite a la política de la plataforma (`https://app.golden-eventos.com/privacidad`), que describe el tratamiento **de los asistentes a eventos**, no el de **quien pide una cotización en el sitio**. No hay aviso de privacidad en el punto de recolección (Decreto 1377/2013 art. 15). | `src/pages/cotizar.astro` (`form__legal`), `src/data/sitio.json` → `privacidad` | La autorización debe ser previa e informada **para esa finalidad** (comercial/cotización). Hoy el texto dice «Usaremos estos datos solo para responder su solicitud» sin responsable, derechos ni canal. | Borrador listo (sección 9, textos A y B) |
| 15 | Alta | Los Términos del sitio (`/terminos`, «julio de 2025») hablan de **PayU**; la plataforma cobra con **Wompi** y tiene Términos y Reembolsos aprobados por la auditora (6-oct-2026). | `src/pages/terminos.astro`; `app/routers/legal_public.py` | Dos versiones contradictorias de los Términos bajo la misma marca. | Propuesto (S11) |
| 16 | Alta | A nivel de desarrollo no se guarda la **decisión del modelo**: la distancia (0-1), el nivel («Muy parecido / Parecido / Revisar con cuidado»), si fue DUDOSO y qué hizo el operador viajan en un token firmado de corta vida y se pierden; `access_logs` solo guarda `registration_method='biometrico'`. | `app/faces.py` (`make_match_token`, `confidence`, `is_doubtful`), `app/routers/api.py` líneas ~700-800, `app/models.py` `AccessLog` | Sin registro de decisiones no se puede auditar un reclamo («me dejaron entrar como otra persona» / «no me reconoció»), ni medir falsos positivos en producción, ni demostrar la supervisión humana. Es el «registro de eventos» (logging) que piden la Ley de IA de la UE (art. 12) y las guías OCDE/UNESCO para sistemas biométricos. **No requiere guardar imágenes**: solo números y la acción del operador. | Propuesto (D1) |
| 17 | Alta | No hay pruebas de sesgo por grupo. La precisión se midió con 39 personas (docs/14 §6.2: 100 % aciertos, 0 falsos positivos) sin desglose por sexo, edad, tono de piel, gafas o tapabocas. El modelo (dlib/`face_recognition`) tiene sesgos documentados en la literatura. | `docs/14_FASE0_RESULTADOS.md`, `scripts/bench_jitters.py` | Un umbral único (0,55) puede rendir distinto por grupo: más «no te reconozco» para unos (y por tanto más fila) y más confusiones para otros. Buenas prácticas (UE art. 10, OCDE, UNESCO, NIST FRVT) piden medirlo y repetirlo cuando cambie el modelo. | Propuesto (D2) |
| 18 | Alta | No existe una **evaluación de impacto** (PIA) documentada del tratamiento biométrico ni una **ficha del sistema** (model card) pública. Hay mucho material disperso (`docs/14`, `docs/legal/*`, `TABLA_RETENCION_REGISTROS.md`) pero no un documento que lo junte con riesgos, medidas y responsables. | `docs/legal/` | La SIC puede pedir prueba del principio de responsabilidad demostrada; la Resolución 52185 de 2025 (citada por la auditora) y las guías de la SIC sobre datos sensibles lo esperan para biometría. | Borrador de ficha pública en sección 9 (texto D); plantilla de PIA en D3 |
| 19 | Media | Sin `og:image`, `og:url`, `og:type`, `twitter:card`. | `Base.astro` | Al compartir en WhatsApp/LinkedIn sale sin imagen. Indirectamente afecta clics y enlaces. | Propuesto (S12) |
| 20 | Media | Fuentes en WOFF (6 archivos, 160 KB), no WOFF2; solo se precargan 2. La licencia web de Agrandir está **pendiente** (`docs/legal/LICENCIA_AGRANDIR.md`; `docs/03` del sitio dice que no se publicaría hasta tenerla) y los archivos están en `public/fonts/` del repositorio. | `public/fonts/`, `src/styles/global.css` | WOFF2 ahorra ~30 %. Lo legal: publicar una fuente sin licencia web es infracción de derechos; Juan David la gestiona. | Propuesto (S13); licencia: Pendiente de Juan David |
| 21 | Media | Encabezados: la sección «Preguntas frecuentes» no tiene `<h2>` (solo un `<p class="kicker">`); «Por qué Golden» es un `<p>` con `<h3>` debajo; la sección con `id="servicios"` es la de tecnología y los servicios reales están en `#lineas`. | `index.astro` secciones 8 y 11, `sitio.json` → `nav` | Google y los lectores de pantalla usan los H2 como índice. | Propuesto (S14) |
| 22 | Media | Accesibilidad (WCAG 2.2 AA): (a) `tabindex="0"` en `<li>` no interactivos (pasos, razones, fichas) → reciben foco sin hacer nada (4.1.2); (b) el contenedor de la escarapela 3D tiene `role="img"` y adentro un `<button>` «Ver el reverso» → el botón queda oculto para lectores de pantalla (hijos de `role=img` son presentacionales); (c) errores del formulario sin `aria-invalid`/`aria-describedby` (3.3.1); (d) la cinta de tipos de evento se mueve sola sin botón de pausa (2.2.2; se pausa solo al pasar el mouse; con «reducir movimiento» sí se detiene); (e) «Correo o celular» con `autocomplete="email"` (1.3.5). Contrastes verificados: todos ≥ 5,3:1 (bien). | `index.astro`, `cotizar.astro`, `src/styles/global.css` | Son fallos que un validador (axe, Lighthouse Accessibility) marca y que un cliente institucional puede exigir. | Propuesto (S15) |
| 23 | Media | No hay página `404` propia ni página de contacto (`/contacto`) con mapa, horario y NAP; los datos están solo en el pie. | `src/pages/` | Google espera «páginas de confianza»: contacto, quiénes somos, privacidad, términos, en el mismo dominio. | Propuesto (sección 5) |
| 24 | Media | La política de privacidad y los términos enlazados desde el sitio viven en otro dominio (`app.golden-eventos.com`). | `sitio.json` → `privacidad` | Funciona, pero Google valora que el dominio principal tenga su propia política; además la de la plataforma no cubre el sitio (hallazgo 14). | Propuesto (S16) |
| 25 | Media | Páginas legales de la plataforma sin `meta description`, sin canónico y con título en mayúsculas («Política de Privacidad \| GOLDEN EVENTOS Y LOGISTICA SAS» por `LEGAL_NAME`). | `templates/legal_base.html`, `common.yaml` → `LEGAL_NAME` | Son las únicas páginas de `app.` que conviene indexar (confianza). | Propuesto (P3) |
| 26 | Media | El formulario público de inscripción carga el widget de **Google Translate** desde `translate.google.com` (a petición del usuario) y la política dice «usamos únicamente cookies necesarias». El widget puede dejar una cookie `googtrans`. | `templates/form_public.html` (`loadTranslator`) | Pequeña inconsistencia con la política; basta una frase en la política o en el aviso del traductor (ya avisa en inglés que lo escrito no se envía). | Propuesto (P4; texto para la auditora) |
| 27 | Media | Cifra «25 años» (kicker y `alt` del emblema) y membresías: `docs/01` del sitio pide confirmarla con fuente. | `inicio.json` → `hero.kicker`, `index.astro` `alt` del emblema | Google no lo penaliza, pero una afirmación sin respaldo en un sitio que presume rigor legal es incoherente. | Pendiente de Juan David |
| 28 | Baja | `README.md` del sitio es la plantilla de Astro («Seasoned astronaut? Delete this file»). | `golden-sitio-web/README.md` | No afecta a Google; afecta a quien retome el repositorio. | Propuesto (S17) |
| 29 | Baja | `favicon.svg` existe pero no se declara; falta `apple-touch-icon` y `manifest` mínimo. | `Base.astro`, `public/` | Detalle de pulido en resultados móviles y al guardar en pantalla de inicio. | Propuesto (S18) |
| 30 | Baja | El HUD de la escena muestra «Ingresos 1.284» (etiquetado «animación ilustrativa», `aria-hidden`). | `index.astro` sección 2 | Correcto como está; solo cuidar que nunca se lea como cifra real (no quitar la etiqueta). | Nada |

---

## 3. Qué se cambió en el código

**Nada.** El encargo lo prohíbe (otro agente integra el sitio y aplicará esta lista). Todo lo de abajo es lista de trabajo con archivo, etiqueta y texto exactos.

---

## 4. Lista priorizada y concreta por página / archivo

### 4.1 Sitio web (`/home/claude/golden-sitio-web`)

**S1 · Dejar de pedir «no indexar» (Crítico, 0,5 h).**
- `src/layouts/Base.astro`: quitar `<meta name="robots" content="noindex" />` **o, mejor**, hacerlo condicional para que la vista previa siga oculta y producción no: `{import.meta.env.PUBLIC_INDEXAR !== '1' && <meta name="robots" content="noindex" />}` y en el build de producción `PUBLIC_INDEXAR=1`.
- `public/robots.txt` de producción:
  ```
  User-agent: *
  Allow: /
  Sitemap: https://golden-eventos.com/sitemap-index.xml
  ```
  Y en la vista previa de Cloudflare Pages mantener `Disallow: /` (o un `robots.txt` distinto por entorno).

**S2 · Hacer que el formulario envíe (Crítico, 4-6 h).** Opciones, de más simple a más integrada: (a) función de Cloudflare Pages / Firebase con Turnstile y correo a `info@`; (b) un endpoint `POST /api/cotizaciones-web` en el servicio `publico` de la plataforma (crea un lead en el CRM interno: ya existe `crm_leads`), con Origin permitido para `golden-eventos.com`, límite de peticiones y honeypot. La opción (b) deja el lead donde Golden ya trabaja. En ambos casos: mensaje de éxito claro, correo de confirmación opcional y **aviso de privacidad** (sección 9, texto A) justo encima del botón.

**S3 · Dirección definitiva y canónico (Crítico, 0,5 h).**
- `astro.config.mjs`: `site: 'https://golden-eventos.com'` (decidir **sin** `www`; redirigir `www.` → raíz con 301 en Firebase Hosting/Cloudflare).
- `src/layouts/Base.astro`, dentro de `<head>`: `<link rel="canonical" href={new URL(Astro.url.pathname, Astro.site).href} />` y `<meta property="og:url" content={new URL(Astro.url.pathname, Astro.site).href} />`.

**S4 · Sitemap (Crítico, 0,5 h).** `npx astro add sitemap` (`@astrojs/sitemap`) y en `astro.config.mjs` `integrations: [sitemap()]` → genera `/sitemap-index.xml`. Si no se pueden instalar paquetes, un `public/sitemap.xml` escrito a mano con las URL finales (`/`, `/cotizar`, `/contacto`, `/servicios/...`, `/privacidad`, `/terminos`, `/inteligencia-artificial`). Enviarlo en Search Console.

**S5 · Un solo juego de datos de contacto (Crítico, configuración, 0,5 h).** Decidir con Juan David UN teléfono público (hoy `317 427 6073` en el sitio y `318 098 1752` en la plataforma), UN correo general (`info@`) y el correo de privacidad (`soporteit@`, puede ser distinto pero debe aparecer también en el sitio). Escribir la dirección igual en todas partes: `Carrera 14A # 71A-59, Bogotá D.C., Colombia`. Dónde: `src/data/sitio.json` (`empresa`, `whatsapp`), `deploy/gcp/env/common.yaml` (`LEGAL_PHONE`, `LEGAL_EMAIL`, `LEGAL_ADDRESS`, `LEGAL_NAME="Golden Eventos y Logística S.A.S."`), Google Business Profile, Instagram/LinkedIn/Facebook/YouTube.

**S6 · Datos estructurados JSON-LD (Alta, 2 h).** En `Base.astro` (sitio entero) un bloque `<script type="application/ld+json" set:html={JSON.stringify(ld)} />` armado desde `sitio.json`:
```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": ["Organization", "LocalBusiness"],
      "@id": "https://golden-eventos.com/#org",
      "name": "Golden Eventos y Logística S.A.S.",
      "alternateName": ["Golden Eventos", "Golden Logísticas"],
      "legalName": "Golden Eventos y Logística S.A.S.",
      "taxID": "901.542.833-2",
      "url": "https://golden-eventos.com/",
      "logo": "https://golden-eventos.com/img/emblema-560.webp",
      "image": "https://golden-eventos.com/img/og.jpg",
      "telephone": "+57-317-427-6073",
      "email": "info@goldenlogisticas.com",
      "address": { "@type": "PostalAddress", "streetAddress": "Carrera 14A # 71A-59", "addressLocality": "Bogotá", "addressRegion": "Bogotá D.C.", "postalCode": "110231", "addressCountry": "CO" },
      "openingHoursSpecification": [{ "@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"], "opens": "08:00", "closes": "18:00" }],
      "areaServed": { "@type": "Country", "name": "Colombia" },
      "sameAs": ["https://www.instagram.com/golden_eventosylog/", "https://www.linkedin.com/company/golden-logisticas", "https://www.facebook.com/goldeneventosylogistica25/", "https://www.youtube.com/@goldenlogisticas"],
      "foundingDate": "[AAAA: confirmar]",
      "makesOffer": [
        { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "Registro y acreditación de asistentes", "serviceType": "Registro de eventos", "areaServed": "Colombia", "provider": { "@id": "https://golden-eventos.com/#org" }, "url": "https://golden-eventos.com/servicios/registro-y-acreditacion" } },
        { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "Control de acceso y zonas con GoldenWeb 2.0", "serviceType": "Control de acceso para eventos", "url": "https://golden-eventos.com/servicios/control-de-acceso" } },
        { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "Organización integral de congresos, convenciones y asambleas", "serviceType": "Organización de eventos corporativos", "url": "https://golden-eventos.com/servicios/organizacion-de-eventos" } }
      ]
    },
    { "@type": "WebSite", "@id": "https://golden-eventos.com/#web", "url": "https://golden-eventos.com/", "name": "Golden Eventos y Logística", "inLanguage": "es-CO", "publisher": { "@id": "https://golden-eventos.com/#org" } }
  ]
}
```
Y **solo en la portada** (o en la futura `/preguntas`) un `FAQPage` generado desde `inicio.json → preguntas.items` (`mainEntity: [{ "@type": "Question", "name": q.p, "acceptedAnswer": { "@type": "Answer", "text": q.r } }]`). *Ojo (crítica cruzada, ingeniero 2):* desde 2023 Google solo muestra el «resultado enriquecido» de FAQ a sitios gubernamentales o de salud; para Golden el FAQPage **no** dará cajas desplegables en Google, pero sí ayuda a entender la página. No prometerle eso a Juan David. Para `GoldenWeb 2.0` se puede añadir `SoftwareApplication` (`applicationCategory: BusinessApplication`, `operatingSystem: Web`) en la página de tecnología. Validar todo en https://validator.schema.org y en la prueba de resultados enriquecidos de Google.

**S7 · Título, descripción y H1 con las palabras que la gente busca (Alta, 1 h).**
- `Base.astro` valor por defecto de `titulo`: **«Registro y acreditación de eventos en Bogotá | Golden Eventos y Logística»** (≤ 60 caracteres visibles: Google corta a ~600 px). Alternativa si prefieren marca primero: «Golden Eventos y Logística · Registro, acreditación y control de acceso para eventos».
- `descripcion`: «Registro de asistentes, acreditación con QR, cédula o rostro (voluntario), escarapelas en el sitio y organización de congresos, convenciones y asambleas en Bogotá y Colombia. 25 años. Pida su cotización.» (≈ 155 caracteres).
- H1: puede seguir «Su evento, de la puerta al aplauso.» si el `kicker` cambia a **«Registro, acreditación y logística de eventos · Bogotá, Colombia»** y el `lead` conserva «Registro, acreditación y logística para congresos, ferias y asambleas». El H1 que ve Google es el texto, no el `aria-label`: ambos ya coinciden, bien.
- Cada página nueva: título único (≤ 60), descripción única (120-160), un solo H1, H2 por bloque.

**S8 · No publicar marcos vacíos (Alta, 0,5 h).** En `index.astro` envolver la sección 10 en `{d.eventos.items.some((e) => e.src) && (...)}` para que solo aparezca cuando exista al menos un medio real; o quitar `eventos` del menú hasta entonces. Lo mismo para el «Video de la plataforma en uso» de la sección GoldenWeb (reemplazar por una captura real de la pantalla de la plataforma sin datos personales, que sí existe: p. ej. `docs/ux/guia_visual.html` muestra componentes).

**S9 · Scroll con inercia (Alta, 0,5 h).** En `src/scripts/fluidez.ts` desactivar el bloque «Scroll con inercia» (dejar el scroll nativo) o condicionarlo a `data-suave` que por defecto esté apagado. El resto de animaciones (IntersectionObserver, `requestAnimationFrame` con pausa cuando no está a la vista, `prefers-reduced-motion`) está bien hecho.

**S10 · Dominio viejo (Alta, lo hace Juan David, 1-2 h).** En Colombia Hosting (`goldenlogisticas.com`): `.htaccess` con `Redirect 301 / https://golden-eventos.com/` y mapas puntuales (`/servicios` → `/servicios/`, `/contacto` → `/contacto`, `/politica-de-privacidad.pdf` → `/privacidad`). Los MX (correo) no se tocan. En Search Console: verificar ambos dominios y usar «Cambio de dirección». Mantener la redirección al menos 12 meses.

**S11 · Términos (Alta, 1 h).** `src/pages/terminos.astro`: dejar solo los términos **del sitio web** (uso del sitio, propiedad intelectual, jurisdicción) y para cupos, pagos y reembolsos enlazar a `https://app.golden-eventos.com/terminos` y `/reembolsos` (aprobados por la auditora). Quitar «PayU». Fecha de actualización real.

**S12 · Open Graph completo (Media, 1 h).** Crear `public/img/og.jpg` (1200×630, emblema sobre crema con «Registro y acreditación de eventos · Bogotá») y en `Base.astro`: `og:type=website`, `og:image`, `og:image:width/height`, `og:site_name`, `twitter:card=summary_large_image`.

**S13 · Fuentes (Media, 1 h + licencia).** Convertir las 6 fuentes a WOFF2 (`woff2_compress`), declarar `format("woff2")` primero; precargar también `agrandir-grandheavy` (se usa en el H1) y mantener `font-display: swap`. **Antes de publicar: licencia web de Agrandir** (`docs/legal/LICENCIA_AGRANDIR.md`, pendiente de Juan David); si no llega, publicar con Montserrat/Inter (ya definidas como respaldo).

**S14 · Encabezados (Media, 0,5 h).** `index.astro`: sección «Preguntas» → `<h2 class="titulo">Preguntas frecuentes</h2>`; «Por qué Golden» → `<h2>`; renombrar `id="servicios"` de la vitrina a `id="tecnologia"` y `id="lineas"` a `id="servicios"` (y actualizar `sitio.json → nav`).

**S15 · Accesibilidad (Media, 2 h).** Quitar `tabindex="0"` de `<li class="paso">`, `<li class="razon">` y `<li data-juego>` de `.fichas` (o convertirlos en `<button>` si de verdad hacen algo); en `.crea__escena` cambiar `role="img"` por un `<div>` normal con `aria-label` en el `<figure>` interno y dejar el botón fuera del `role=img`; en `cotizar.astro` poner `aria-invalid="true"` y `aria-describedby="error-<campo>"` con un `<small id="error-<campo>">` visible; a la cinta agregar un botón «Pausar» o dejarla estática en `<` 861 px; `contacto` sin `autocomplete="email"` (o dos campos: correo y celular, ambos opcionales con uno obligatorio).

**S16 · Páginas legales propias (Media, 1-2 h + revisión de la auditora).** `src/pages/privacidad.astro` (texto B de la sección 9) y `src/pages/inteligencia-artificial.astro` (texto C). `sitio.json → privacidad` pasa a `/privacidad`; en esa página, un enlace claro «Política de la plataforma GoldenWeb 2.0 (asistentes a eventos)» a `https://app.golden-eventos.com/privacidad`.

**S17 · README (Baja, 0,5 h).** Reemplazar la plantilla de Astro por `docs/05_como_montar_en_mi_dominio.md` resumido + la lista de revisión de salida a producción (S1-S5).

**S18 · Iconos (Baja, 0,5 h).** `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`, `<link rel="apple-touch-icon" href="/apple-touch-icon.png">` (180×180) y `site.webmanifest` mínimo.

### 4.2 Plataforma (`/home/claude/facial-recognition-golden`, solo parte pública)

**P1 · `robots.txt` en `app.golden-eventos.com` (Alta, 1 h).** Firebase Hosting sirve los archivos estáticos antes de las reescrituras: `deploy/firebase/make_config.py` puede copiar un `deploy/firebase/robots.txt` a la raíz de `build/firebase/public/`. Contenido:
```
User-agent: *
Disallow: /
Allow: /privacidad
Allow: /terminos
Allow: /reembolsos
Allow: /static/
```
(En la VM actual, el mismo archivo en Nginx.) Así se indexan solo las páginas legales y se evita que `/login`, `/f/<formulario>`, `/aceptar/...` compitan con el sitio.

**P2 · `noindex` en `/login` y cabecera global (Alta, 0,5 h).** `templates/login.html`: `<meta name="robots" content="noindex, nofollow">`. Mejor aún, en el middleware de `app/main.py` que ya pone `no-store` en HTML: añadir `X-Robots-Tag: noindex` a toda respuesta HTML **salvo** `/privacidad`, `/terminos`, `/reembolsos`. (Cambio pequeño; lo decide el agente de plataforma.)

**P3 · Páginas legales como páginas de confianza (Media, 1 h).** `templates/legal_base.html`: `<meta name="description" content="{{ page_description }}">`, `<link rel="canonical" href="https://app.golden-eventos.com{{ request.url.path }}">`, `lang="es-CO"`; `LEGAL_NAME` en `common.yaml` con mayúsculas y tildes normales. En cada página legal, un enlace «Sitio corporativo: golden-eventos.com» (y desde el sitio a ellas) para que Google una los dos dominios.

**P4 · Google Translate (Media, texto para la auditora, 0,5 h).** Una frase en la política §11 (cookies): «Si usted activa el traductor del formulario, Google puede dejar una cookie de preferencia de idioma (`googtrans`); lo que escribe en los campos no se envía a Google.» No se edita el texto sin la auditora.

### 4.3 Fuera del código (lo hace Juan David)

- **Google Business Profile**: crear/reclamar la ficha de «Golden Eventos y Logística S.A.S.» con la dirección de la Carrera 14A, categoría principal «Organizador de eventos» (secundarias: «Servicio de logística», «Empresa de software»), horario, teléfono único, sitio `https://golden-eventos.com`, fotos reales de la oficina y de eventos (con permiso), y responder reseñas. Es lo que más pesa para «golden eventos bogotá» en el mapa.
- **Search Console**: verificar `golden-eventos.com` (propiedad de dominio por DNS), `app.golden-eventos.com` y `goldenlogisticas.com`; enviar el sitemap; «Cambio de dirección» desde el viejo; revisar «Páginas» cada semana el primer mes.
- **Bing Webmaster Tools** (gratis, importa desde Search Console): Bing alimenta a Copilot y DuckDuckGo.
- **Redes**: mismo nombre, misma dirección, mismo teléfono, enlace a `golden-eventos.com` en los 4 perfiles.
- **Enlaces naturales**: ficha en el directorio de la Cámara de Comercio de Bogotá, MPI Colombia (si la membresía está vigente, hallazgo 27), proveedores y clientes que acepten enlazar un caso.

---

## 5. Plan de contenido: páginas que faltan (en orden)

| Orden | URL | Título (≤ 60) | Qué lleva (400-800 palabras, sin inventar) | Para qué búsqueda |
|---|---|---|---|---|
| 1 | `/contacto` | Contacto · Golden Eventos y Logística, Bogotá | Dirección, mapa (incrustar Google Maps con `loading="lazy"`), teléfono, WhatsApp, correo general y de privacidad, horario, NIT, razón social, formulario corto (mismo backend que S2). | «golden eventos bogotá», «golden logísticas contacto» |
| 2 | `/servicios/registro-y-acreditacion` | Registro y acreditación de asistentes para eventos en Bogotá | Qué es, métodos (QR, cédula, autorregistro, rostro voluntario), escarapelas impresas en el sitio, aforo en vivo, inscripción en línea con pagos (Wompi), cómo se cotiza, 3-4 preguntas. Captura real de la pantalla de registro (sin datos). | «registro de eventos», «registro eventos Bogotá», «acreditación de eventos», «inscripción de asistentes» |
| 3 | `/servicios/control-de-acceso` | Control de acceso y zonas para eventos · GoldenWeb 2.0 | Zonas por escarapela, aforo, inventario, turnos, modo sin internet, reconocimiento facial voluntario con enlace a `/inteligencia-artificial` y a la política. | «control de acceso eventos», «control de acceso para eventos Bogotá» |
| 4 | `/servicios/organizacion-de-eventos` | Organización de congresos, convenciones y asambleas en Colombia | Las 4 líneas de `inicio.json → lineas` desarrolladas (organización, contact center, mercadeo, audiovisuales), proceso antes/durante/después. | «organización de eventos corporativos Bogotá», «logística de eventos» |
| 5 | `/servicios/escarapelas-y-manillas` | Escarapelas para eventos impresas en el sitio | El «Cree su escarapela» (sección 5 de la portada) vive mejor aquí: diseño, impresión Brother en segundos, QR, manillas. | «escarapelas para eventos», «escarapelas Bogotá» |
| 6 | `/goldenweb` | GoldenWeb 2.0: plataforma de registro y control de acceso para eventos | Qué hace la plataforma, para quién (organizadores que quieren contratarla como servicio: decisión SaaS 22-nov), privacidad en 3 líneas, `SoftwareApplication` en JSON-LD. | «plataforma de registro de eventos», «software de acreditación» |
| 7 | `/casos` (cuando haya 2-3 reales con permiso) | Eventos realizados · casos reales | Por caso: cliente (con permiso), ciudad, año, asistentes, qué hizo Golden, 1 foto real, 1 frase del cliente. | Confianza (E-E-A-T), «golden eventos» |
| 8 | `/nosotros` | Quiénes somos · 25 años organizando eventos en Colombia | Historia con fechas confirmadas, equipo (nombres y cargos reales con permiso), NIT, membresías vigentes, políticas. | Confianza, panel de marca |
| 9 | `/preguntas` | Preguntas frecuentes sobre registro y logística de eventos | Las 5 actuales + 10 más (precio orientativo por rango de asistentes, tiempos, qué pasa sin internet, qué datos piden, cómo borrar mis datos, menores). FAQPage JSON-LD. | Búsquedas largas («¿cómo funciona el registro con QR en un evento?») |
| 10 | `/privacidad`, `/inteligencia-artificial`, `/terminos` | (textos B, C y S11) | Legal propio del sitio. | Confianza |

Reglas: una página = una intención de búsqueda; el nombre de la ciudad aparece en título, H1 o primer párrafo (no repetido artificialmente); cada página enlaza a `/cotizar` y a 2-3 páginas hermanas; nada de texto generado en masa, nada de clientes o cifras sin permiso (`docs/01` del sitio ya lo exige). Los textos los redacta Juan David con el bot del sitio; esta lista solo fija estructura y palabras.

**Qué sí y qué no esperar (ingenieros 1 y 2 de acuerdo):** con S1-S7, Business Profile y las páginas 1-4, en 2-3 meses el sitio debería ser el primer resultado para su marca («golden eventos», «golden eventos y logística», «golden logísticas») y aparecer en la primera o segunda página para «registro de eventos Bogotá» y «acreditación de eventos Bogotá» (poca competencia local). «control de acceso eventos» es más disputado (empresas de seguridad y torniquetes): primera página es posible con la página 3 y casos reales. «golden» y «eventos» solos: no.

---

## 6. Crítica cruzada entre los dos ingenieros de búsqueda

- **Ing. 1:** «Sitio de una página con anclas basta si el contenido es bueno». **Ing. 2:** No para este caso: la portada no puede ser al mismo tiempo «registro de eventos», «control de acceso» y «organización de congresos»; Google elige una intención por URL. Se mantiene el plan de páginas (sección 5). *Acuerdo.*
- **Ing. 2:** «Agregar FAQPage, HowTo, Product, Review». **Ing. 1:** No inventar valoraciones (`AggregateRating` sin reseñas reales es manipulación y se penaliza); HowTo ya no da resultados enriquecidos; FAQPage tampoco para empresas. Solo Organization/LocalBusiness/Service/WebSite (+ SoftwareApplication y FAQPage por claridad). *Acuerdo.*
- **Ing. 1:** «Hay que medir con Lighthouse antes de opinar sobre velocidad». **Ing. 2:** No se pudo compilar (sección 8). Con el código a la vista: HTML comprimido, CSS en línea cuando es pequeño, 3 imágenes WebP (172 KB entre las tres, con `srcset` y `fetchpriority="high"` en la del hero), 6 fuentes WOFF (160 KB), JS ~66 KB de fuente (~30-35 KB minificado, ~12 KB comprimido), sin librerías externas, sin analítica, sin fuentes de Google. **Estimación** de la portada: ~450-500 KB y ~15 peticiones en la primera carga; LCP razonable (la imagen del hero está precargada por prioridad). Lo único que preocupa para Core Web Vitals es el `wheel` no pasivo (hallazgo 10) y las 4 escenas en `<canvas>` en celulares de gama baja (están pausadas cuando no se ven: bien). Esto son estimaciones, no puntajes. *Acuerdo.*
- **Ing. 2:** «Poner Google Analytics». **Ing. 1:** Solo si hace falta: implicaría banner de cookies y una frase en la política; Search Console ya dice qué búsquedas traen visitas. Si Juan David quiere medir conversiones, usar la analítica de Cloudflare (sin cookies) o Plausible. *Acuerdo: sin GA por ahora.*

---

## 7. Qué queda pendiente y por qué (horas y orden)

| Orden | Qué | Horas | Quién |
|---|---|---|---|
| 1 | S1 + S3 + S4 + S5 (indexar, dominio, sitemap, NAP) | 2 | Agente integrador + Juan David (teléfono oficial) |
| 2 | S2 formulario funcionando con aviso de privacidad (texto A) | 4-6 | Agente integrador |
| 3 | S7 + S14 (títulos, descripción, encabezados) y S8 (ocultar marcos vacíos) | 2 | Agente integrador |
| 4 | S6 JSON-LD + S12 Open Graph + S18 iconos | 3 | Agente integrador |
| 5 | P1 + P2 (robots y noindex en la plataforma) + P3 | 2,5 | Agente de plataforma |
| 6 | S16 páginas `/privacidad` e `/inteligencia-artificial` con textos B y C, S11 términos | 3 + revisión de la auditora | Integrador + auditora |
| 7 | Business Profile, Search Console, Bing, redirección 301 del dominio viejo (S10) | 3 | Juan David (con comando/guía paso a paso) |
| 8 | S9 scroll, S15 accesibilidad, S13 fuentes WOFF2 | 3,5 | Agente integrador |
| 9 | Páginas de contenido 1-6 (sección 5) | 2-3 h por página (textos de Juan David + bot del sitio) | Juan David + bot del sitio |
| 10 | D1 registro de decisiones del modelo (ver abajo) | 6-8 | Agente de plataforma (migración nueva, pruebas) |
| 11 | D2 pruebas de sesgo por grupo | 8-12 + reclutamiento de voluntarios con consentimiento | Golden + agente de plataforma |
| 12 | D3 evaluación de impacto (PIA) y ficha del sistema (texto D) | 6 + revisión de la auditora | Claude redacta, auditora revisa |
| 13 | Licencia Agrandir (hallazgo 20), cifra «25 años» y membresías (27) | — | Juan David |

### Nivel de desarrollo (rol 4): qué debe tener la plataforma

- **D1 · Registro de decisiones del modelo facial** (sin imágenes): tabla nueva `recognition_decisions` (o columnas en `access_logs`): evento, fecha/hora UTC, versión del modelo y del umbral (`FACE_TOLERANCE`, `MATCH_MARGIN`, `RECOGNITION_JITTERS`, versión de la matriz), resultado (`NO_FACE` / `NO_MATCH` / `MATCH` / `DUDOSO`), distancia del mejor candidato y del segundo (redondeadas a 2 decimales), nivel (`high/medium/low`), **acción del operador** (confirmó el principal / eligió otro candidato / rechazó / pasó a cédula) y operador. Con eso se responde cualquier reclamo y se mide el falso positivo real. Retención: la misma que `access_logs` (anonimizar al suprimir a la persona). Hoy todo esto ya se calcula (`app/faces.py` `confidence`, `is_doubtful`, `make_match_token`): solo falta persistirlo en `app/routers/api.py` cuando se consume el token.
- **D2 · Pruebas de sesgo**: extender `scripts/bench_jitters.py` para aceptar una etiqueta de grupo por carpeta (sexo, rango de edad, tono de piel según escala Monk o Fitzpatrick, gafas, tapabocas) y reportar por grupo: tasa de no-reconocimiento (FNMR), falsos positivos (FMR) y distancia media, al umbral 0,55 y al 0,50. Mínimo 20 personas por grupo, voluntarias, con consentimiento específico para la prueba y borrado al terminar. Repetir cada vez que cambie el modelo, el umbral o los jitters. Publicar solo agregados (en la ficha del sistema).
- **D3 · Evaluación de impacto en la protección de datos (PIA)**: documento en `docs/legal/EVALUACION_IMPACTO_BIOMETRIA.md` con: descripción del tratamiento, necesidad y proporcionalidad (alternativa siempre disponible), riesgos (falso positivo → entra otra persona; falso negativo → fila y molestia; fuga de vectores; uso fuera de finalidad; menores; discriminación por grupo), medidas (cifrado, 7 días, consentimiento inmutable, operador humano, candidatos, DUDOSO, pruebas de sesgo, registro de decisiones), responsables, fecha de revisión. Base legal: principio de responsabilidad demostrada (Decreto 1377/2013 arts. 26-27, hoy en el Decreto 1074/2015) y Circular Externa 002 de 2015 de la SIC; referencia: art. 27 de la Ley de IA de la UE (evaluación de impacto sobre derechos fundamentales) y marco de gestión de riesgos de IA del NIST.
- **D4 · Ficha del sistema (model card) interna y pública**: la pública es el texto D (sección 9); la interna añade: modelo exacto (`dlib` ResNet de 128 dimensiones vía `face_recognition`, versión instalada), umbrales, resultados de D2, limitaciones conocidas, fecha.
- **D5 · Supervisión humana escrita**: ya existe de hecho (el operador ve foto de registro y candidatos y confirma; `docs/14 §6.3`). Falta ponerlo por escrito como regla: «ningún ingreso por rostro se marca sin confirmación de un operador» y «ante DUDOSO siempre cédula o QR». Añadirlo a la ficha y a la capacitación del personal (`docs/legal/GUIA_ENTRADA_ROSTRO.md`).
- **D6 · Registro de incidentes y de cambios del modelo**: una sección en `docs/legal/` o en `/sistema` donde quede cada cambio de umbral/modelo con fecha y quién lo autorizó, y cada incidente (acceso con identidad equivocada, reclamo) con su respuesta.
- **D7 · Verificar con la auditora si aplica el Registro Nacional de Bases de Datos (RNBD)** de la SIC (Decreto 886/2014 y Decreto 090/2018: obligatorio para sociedades con activos totales superiores a 100.000 UVT). Si aplica, la base «Asistentes a eventos (con datos biométricos)» se inscribe.
- **D8 · Ya está bien y hay que conservarlo** (para que nadie lo «optimice»): vector después de aceptar, menores fuera, cifrado con clave propia, supresión y revocación, registro de consentimiento 3 años, nada personal en logs, Google Translate solo a petición.

---

## 8. Qué NO se pudo comprobar (sin inventar)

- **No compilé el sitio.** `npm ci` falló por falta de red hacia el registro de npm («Exit handler never called»; no hay caché local de npm ni Astro instalado globalmente). Por tanto **no medí** tamaño del HTML final, tiempo de carga, número de peticiones ni Core Web Vitals, y **no corrí Lighthouse** (tampoco está instalado). Las cifras de la sección 6 son estimaciones a partir del código fuente y están marcadas así.
- No visité la vista previa en Cloudflare Pages ni `goldenlogisticas.com` (sin navegador autorizado para eso en este encargo), así que no sé qué URL del sitio viejo tienen enlaces entrantes; la lista de redirecciones de S10 debe armarse con Search Console del dominio viejo.
- No comprobé Google Business Profile ni Search Console (no hay acceso).
- No comprobé en producción la ausencia de `robots.txt` en `app.golden-eventos.com`: lo deduzco del código (no hay ruta ni archivo) y del `make_config.py` de Firebase.
- No ejecuté `scripts/bench_jitters.py` ni vi fotos: lo de sesgo sale de `docs/14` (39 personas, sin desglose).
- La licencia de Agrandir: solo consta como pendiente en `docs/legal/LICENCIA_AGRANDIR.md`; no sé si ya se compró.
- Playwright y Chromium están disponibles pero sin `dist/` no había qué medir.

---

## 9. BORRADORES de textos informativos (español, para revisión de Juan David y de la auditora)

> **Todos son BORRADOR.** No sustituyen ni modifican los textos literales de la auditora (`app/legal_texts_data.py`, `docs/legal/TEXTOS_AUDITORA_2026-10-05.md`, `POLITICA_v1.1.md`). Los corchetes `[ ]` son datos por confirmar. Donde digo «7 días», «180 días», «30 días», «3 años», «90 días», «10/15 días hábiles» copio la política 1.1; si la auditora cambia algo, cambia aquí.

### Texto A · Aviso de privacidad del formulario de cotización (sitio, justo encima del botón «Enviar solicitud»)

**BORRADOR**

> **Aviso de privacidad.** Golden Eventos y Logística S.A.S. (NIT 901.542.833-2, Carrera 14A # 71A-59, Bogotá) es responsable de los datos que usted escribe aquí. Los usamos **solo para responder su solicitud de cotización y hacerle seguimiento comercial** sobre ese evento. Los conservamos [12] meses desde el último contacto y luego los eliminamos. Puede conocer, actualizar, corregir o pedir la eliminación de sus datos, y revocar esta autorización, escribiendo a **soporteit@goldenlogisticas.com**. Al enviar, acepta este aviso y nuestra [Política de privacidad](/privacidad).
> ☐ He leído el aviso y autorizo el tratamiento de mis datos para recibir la cotización. *(casilla obligatoria, sin marcar por defecto)*

### Texto B · Política de privacidad del sitio web golden-eventos.com (página `/privacidad`)

**BORRADOR**

> # Política de privacidad del sitio web
> *Versión [1.0] · [fecha]. Aplica al sitio **golden-eventos.com**. El tratamiento de los datos de las personas que asisten a los eventos que operamos con la plataforma GoldenWeb 2.0 se rige por la [Política de Privacidad y Tratamiento de Datos Personales de la plataforma](https://app.golden-eventos.com/privacidad).*
>
> **1. Responsable.** Golden Eventos y Logística S.A.S., NIT 901.542.833-2, Carrera 14A # 71A-59, Bogotá D.C., Colombia. Correo para asuntos de datos personales: soporteit@goldenlogisticas.com (se revisa a diario). Teléfono: [+57 …].
>
> **2. Qué datos recogemos en este sitio.** (a) Los que usted escribe en el formulario de cotización o de contacto: nombre, empresa, tipo de evento, fecha, ciudad, número de asistentes, correo o celular. (b) Si nos escribe por WhatsApp, su número y lo que nos cuente (WhatsApp es un servicio de Meta con sus propias condiciones). (c) Datos técnicos mínimos que registran nuestros proveedores de alojamiento (dirección IP, navegador, página visitada) para seguridad y para que el sitio funcione.
>
> **3. Para qué.** Responder su solicitud, preparar y enviar la cotización, hacerle seguimiento comercial sobre ese evento, y mantener la seguridad del sitio. No vendemos ni cedemos sus datos a terceros para publicidad.
>
> **4. Cookies y seguimiento.** Este sitio **no usa cookies de publicidad ni de analítica de terceros**. [Si en el futuro se agrega una herramienta de medición, la indicaremos aquí y pediremos su consentimiento si usa cookies.]
>
> **5. Cuánto tiempo.** Las solicitudes de cotización se conservan [12] meses desde el último contacto; si se firma un contrato, pasan a la carpeta del cliente y se conservan mientras dure la relación y los plazos legales (contables: 10 años). Los registros técnicos se conservan hasta [90] días.
>
> **6. Con quién compartimos.** Proveedores que nos prestan el alojamiento del sitio y el correo: Google (Firebase Hosting / Google Cloud, Estados Unidos), Cloudflare (seguridad y entrega, global), Microsoft 365 (correo). Son transmisiones internacionales a proveedores con acuerdos de tratamiento de datos. [Confirmar la lista final con la infraestructura elegida.]
>
> **7. Sus derechos.** Conocer, actualizar y rectificar sus datos; pedir prueba de la autorización; saber cómo los usamos; revocar la autorización; pedir la supresión; y presentar quejas ante la Superintendencia de Industria y Comercio. Escriba a soporteit@goldenlogisticas.com con su nombre, documento y lo que solicita. Respondemos consultas en máximo 10 días hábiles y reclamos en máximo 15 días hábiles, prorrogables según la ley.
>
> **8. Inteligencia artificial.** Este sitio no toma decisiones automatizadas sobre usted. Parte de los textos, ilustraciones animadas y el código del sitio se elaboraron con ayuda de herramientas de inteligencia artificial, siempre revisados por personas de Golden. Nuestra plataforma de eventos ofrece reconocimiento facial **voluntario**; cómo funciona y qué garantías tiene está en [Transparencia sobre el uso de inteligencia artificial](/inteligencia-artificial).
>
> **9. Menores.** Este sitio está dirigido a empresas y organizadores. No pedimos datos de menores de edad; si un menor nos escribe, eliminamos sus datos al identificarlo.
>
> **10. Marco legal y cambios.** Ley 1581 de 2012, Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015) y demás normas colombianas. Publicaremos aquí cualquier cambio con su fecha.

### Texto C · Transparencia sobre el uso de inteligencia artificial (página `/inteligencia-artificial` del sitio; enlazada desde la portada «GoldenWeb 2.0», desde el pie y desde la política)

**BORRADOR**

> # Cómo usamos la inteligencia artificial
> *Última actualización: [fecha]. Esta página existe para que usted sepa, antes de contratarnos o de asistir a un evento nuestro, dónde interviene la inteligencia artificial (IA) y dónde no.*
>
> **1. En la puerta del evento: reconocimiento facial voluntario.**
> Nuestra plataforma GoldenWeb 2.0 puede identificar a un asistente por su rostro para agilizar la entrada. Es un sistema automatizado de **identificación biométrica**: compara una imagen tomada en el quiosco con los rostros de las personas inscritas en **ese evento** que **aceptaron** usarlo. Lo que debe saber:
> - **Es voluntario.** Siempre puede entrar con su cédula o su código QR, sin filas adicionales ni consecuencias. Nadie le pedirá el rostro sin que usted lo haya aceptado en una pantalla con el texto completo.
> - **Una persona decide, no la máquina.** El sistema propone una coincidencia y un nivel de confianza; un operador de Golden la compara con la foto de registro y confirma. Si hay duda (dos personas muy parecidas o baja confianza), el sistema lo marca y se le pide la cédula o el QR.
> - **Qué no hace.** No detecta emociones, no clasifica por raza, sexo ni edad, no vigila el recinto, no busca a nadie en bases de datos externas ni en redes sociales, y no se usa con menores de 18 años.
> - **Sus datos.** La foto y el patrón numérico del rostro se guardan cifrados y se eliminan a los 7 días de terminado el evento (máximo 180 días en todo caso). Puede revocar y pedir la eliminación en cualquier momento escribiendo a soporteit@goldenlogisticas.com. Detalle en la [Política de privacidad de la plataforma](https://app.golden-eventos.com/privacidad).
> - **Precisión y límites.** Lo medimos antes de usarlo y lo seguimos midiendo. Ningún sistema de este tipo es perfecto: puede no reconocerlo (mala luz, gafas, tapabocas) y entonces entra con cédula o QR; y puede confundir a personas muy parecidas, por eso siempre confirma un operador. Publicamos un resumen de las mediciones en la [ficha del sistema](#ficha).
> - **Normas que seguimos.** Ley 1581 de 2012 y Decreto 1377 de 2013 (datos biométricos como datos sensibles, tratamiento facultativo y con autorización previa, expresa e informada), lineamientos de la Superintendencia de Industria y Comercio, y como buenas prácticas los principios de IA de la OCDE, la Recomendación de la UNESCO sobre la ética de la IA y el Reglamento de IA de la Unión Europea (transparencia, supervisión humana, registro de funcionamiento y gestión de riesgos).
>
> **2. En este sitio web y en nuestra plataforma: herramientas de IA para construir y redactar.**
> Parte del código de la plataforma GoldenWeb 2.0 y de este sitio, de los textos informativos y de las ilustraciones animadas se elaboró con ayuda de herramientas de inteligencia artificial, bajo la dirección y revisión de personas de Golden. No usamos imágenes de personas generadas con IA presentadas como reales, ni publicamos cifras, clientes o testimonios que no podamos demostrar. Los textos legales fueron redactados y aprobados por nuestra asesora jurídica.
>
> **3. Lo que no hacemos con IA.** No tomamos decisiones automatizadas con efectos legales sobre usted (precios, admisión, sanciones) sin intervención humana. No usamos sus datos para entrenar modelos de IA.
>
> **4. Preguntas o reclamos.** soporteit@goldenlogisticas.com · [teléfono]. Puede presentar quejas ante la Superintendencia de Industria y Comercio (www.sic.gov.co).

### Texto D · Ficha pública del sistema de reconocimiento facial (ancla `#ficha` de la página anterior, o página aparte)

**BORRADOR** — las cifras en corchetes salen de `docs/14` y deben actualizarse con cada medición.

> ## Ficha del sistema de reconocimiento facial de GoldenWeb 2.0
> | | |
> |---|---|
> | **Para qué sirve** | Confirmar la identidad de un asistente ya inscrito para agilizar su acreditación en la puerta del evento. |
> | **Para qué NO sirve** | Vigilancia, búsqueda de personas, análisis de emociones o de características físicas, decisiones sobre menores, uso fuera del evento. |
> | **Cómo funciona** | Se calcula un patrón numérico (vector de 128 números) del rostro de cada persona que aceptó, a partir de su foto de registro. En la puerta se calcula el mismo patrón de la imagen del quiosco y se compara con los de ese evento. Si la distancia es menor que **0,55** se considera coincidencia y se muestra al operador con un nivel: «Muy parecido» (< 0,40), «Parecido» (0,40-0,50) o «Revisar con cuidado» (0,50-0,55). Si el mejor y el segundo candidato están a menos de **0,06** de distancia, el resultado es «dudoso» y se pide cédula o QR. |
> | **Quién decide** | Siempre un operador humano, viendo la foto de registro y los candidatos. |
> | **Modelo** | Red neuronal de código abierto `dlib` (ResNet de 128 dimensiones) a través de la biblioteca `face_recognition`. No se entrena con datos de asistentes. |
> | **Precisión medida** | [Sept. 2026, 39 personas voluntarias, 5 fotos de puerta por persona: 100 % de aciertos y 0 falsos positivos al umbral 0,55 (docs/14 §6.2).] Pendiente: medición por grupos (sexo, edad, tono de piel, gafas, tapabocas) con al menos 20 personas por grupo. |
> | **Limitaciones conocidas** | Poca luz, contraluz, gafas oscuras, tapabocas, fotos de registro de mala calidad; personas con gran parecido físico (gemelos). En todos esos casos se entra con cédula o QR. |
> | **Datos y plazos** | Foto y vector cifrados; eliminación a los 7 días de finalizado el evento (tope 180 días); registro de la autorización 3 años (solo para responder a autoridades). Menores de 18 años: excluidos. |
> | **Registro de funcionamiento** | [Pendiente D1] Cada reconocimiento deja registro de fecha, resultado, nivel de confianza y decisión del operador, sin guardar la imagen. |
> | **Revisión** | Se repiten las mediciones cuando cambia el modelo, el umbral o la forma de capturar. Última revisión: [fecha]. Responsable: [cargo]. |
> | **Contacto** | soporteit@goldenlogisticas.com |

### Texto E · Frase corta para la plataforma (propuesta a la auditora; NO se edita nada sin su visto bueno)

**BORRADOR** para el pie legal público (`templates/_legal_footer.html`) y para la sección 5 de la política:

> «El reconocimiento facial de GoldenWeb 2.0 es un sistema automatizado de identificación biométrica, voluntario, que propone una coincidencia que siempre confirma un operador humano. Cómo funciona, sus límites y sus mediciones: [golden-eventos.com/inteligencia-artificial].»

### Texto F · Dos preguntas nuevas para «Preguntas frecuentes» del sitio

**BORRADOR**

> **¿Usan inteligencia artificial?** Sí, en dos cosas: el reconocimiento facial voluntario en la puerta (un operador siempre confirma) y como herramienta para construir nuestro software y parte de los textos de este sitio. Lo explicamos en [Cómo usamos la inteligencia artificial](/inteligencia-artificial).
>
> **¿Cómo borro mis datos después de un evento?** Escriba a soporteit@goldenlogisticas.com con su nombre, documento y el evento. Su rostro, si lo registró, se borra solo a los 7 días; el resto lo eliminamos a su solicitud y respondemos en máximo 15 días hábiles.

---

## 10. Consejo en corto y veredicto

- **Contrario:** «¿Para qué tanto SEO si el 90 % de los clientes de Golden llegan por referidos y licitaciones?» — Cierto; por eso el orden es: primero que el botón de cotización funcione y que los datos coincidan, después Google.
- **Primeros principios:** Google solo necesita tres cosas: poder entrar (quitar el `noindex`), entender qué vende cada URL (una página por servicio con título claro) y creer que la empresa existe (NAP igual en todas partes, Business Profile, casos reales). Todo lo demás es decoración.
- **Expansionista:** Si la plataforma va a venderse como servicio (decisión SaaS 22-nov), la página `/goldenweb` y la de transparencia de IA son material de ventas, no solo cumplimiento: pocos competidores en Colombia pueden mostrar consentimiento inmutable, 7 días, menores fuera y una ficha pública del modelo.
- **Forastero:** Un visitante que no conoce Golden ve hoy: botón que no envía, tres recuadros «Evento real por confirmar», un teléfono en el sitio y otro en la política. Eso se arregla en un día y pesa más que cualquier palabra clave.
- **Ejecutor:** Un solo commit del integrador con S1-S8 + P1-P2, un correo a la auditora con los textos A-E, y Juan David abre Business Profile y Search Console. Tres frentes, una semana.

**Veredicto:** el sitio es publicable en una semana si se hacen S1-S8 (indexar, dominio, sitemap, contacto único, JSON-LD, títulos, ocultar marcos vacíos, formulario que envía) y P1-P2 en la plataforma; el posicionamiento real llega con las páginas por servicio y Business Profile en 2-3 meses; la parte de IA y privacidad requiere la revisión de la auditora de los textos A-E y, en código, el registro de decisiones del modelo (D1) y las pruebas por grupo (D2). **UN siguiente paso:** que el agente integrador aplique S1-S5 (2 horas) y active el envío del formulario (S2) con el texto A encima del botón; sin eso, no publicar.
