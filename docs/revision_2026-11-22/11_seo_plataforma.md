# 11 · SEO de la plataforma (app.golden-eventos.com) — 22-nov-2026

Rol: developer que aplica en la plataforma lo que pide Google para que no compita con el sitio corporativo (reporte 08, P1-P4; hallazgos 12, 25 y 26).

## 1. Resumen en 5 líneas
- La plataforma ya dice a los buscadores «solo las tres páginas legales»: nueva ruta `/robots.txt` y `noindex` en el ingreso y en las páginas públicas que faltaban.
- Lo más grave que había: `/robots.txt` daba 404 y `/login` era indexable; Google podía mostrar la pantalla de ingreso antes que el sitio.
- Lo más valioso: las páginas legales (`/privacidad`, `/terminos`, `/reembolsos`) ahora tienen descripción y dirección canónica propias.
- No se tocó ningún texto legal: la frase del traductor y los textos E y F quedaron como pendientes para la auditora.
- Las pruebas de texto pasan; las que arrancan la aplicación no se pudieron correr aquí (no hay FastAPI instalado en este entorno).

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Alta | La plataforma no servía `robots.txt` (404). | `app/routers/legal_public.py` | Los buscadores recorrían todo `app.` sin instrucciones. | Corregido: `/robots.txt` (bloquea todo, permite las 3 legales, mapa del sitio corporativo; 1 h de caché; sin base ni sesión). |
| 2 | Alta | `/robots.txt` no habría salido en el servicio `publico` de Cloud Run. | `app/appmode.py` | El servicio público solo sirve prefijos conocidos. | Corregido: agregado a `ALWAYS` (lo sirven los tres servicios, como el ícono). |
| 3 | Alta | `/login` sin `noindex`. | `templates/login.html` | Competía con el sitio por «golden eventos». | Corregido. |
| 4 | Media | Cuatro páginas sin sesión más sin `noindex`: espera de aprobación de ingreso, certificado local, estadísticas por enlace compartido (2). | `templates/ingreso_espera.html`, `certificado_local.html`, `form_stats.html`, `kiosk_estadisticas.html` | Enlaces personales o internos que no deben salir en Google. | Corregido. Las otras 14 públicas (formulario, aceptar, escarapela digital, certificado, entrega, turnos, ruleta, etc.) ya lo tenían. |
| 5 | Media | Páginas legales sin descripción ni canónico. | `templates/legal_base.html` | Son las únicas de `app.` que conviene indexar. | Corregido: descripción por página; canónico con `PUBLIC_BASE_URL` (sin parámetros; la versión histórica 1.0 apunta a `/privacidad`). |
| 6 | Baja | El reporte 08 decía que el título salía en mayúsculas por `LEGAL_NAME`. | `templates/legal_base.html` | El `<title>` usa `COMPANY_NAME` (hoy «Golden Eventos y Logística S.A.S.»), no `LEGAL_NAME`: hoy ya sale bien. | Corregido por si acaso: si `COMPANY_NAME` llega todo en mayúsculas, el título lo pasa a mayúscula inicial (queda «Sas» sin puntos ni tildes: mejor escribir bien la variable). El cuerpo legal no cambia. |
| 7 | Media | Cookie `googtrans` del traductor no mencionada en la política. | `templates/form_public.html` | Inconsistencia con «solo cookies necesarias». | Pendiente: frase redactada en `docs/legal/PENDIENTE_AUDITORA_2026-11-22.md` (con textos E y F). |
| 8 | Baja | La prueba de rutas públicas falla por `/instalar` (`platform.py`), ajeno a este encargo. | `tests/test_seguridad_2026-11-22.py` | Ya fallaba antes de mis cambios. | Pendiente (del agente dueño de `platform.py`). |
| 9 | Baja | Firebase Hosting / Nginx podrían servir su propio `robots.txt` o no reenviar la ruta. | `deploy/firebase/`, Nginx de la VM | Si la ruta no llega a la app, sigue el 404. | Propuesto: comprobar en staging tras desplegar. |

## 3. Qué se cambió en el código
- `app/routers/legal_public.py`: ruta `GET /robots.txt` (`ROBOTS_TXT`, `INDEXABLE_PATHS`, `CORPORATE_SITEMAP`), descripciones por página (`DESCRIPTIONS`) y `canonical_path` para la versión histórica. Las reglas usan `Allow: /privacidad$` (con `$`: solo la dirección exacta, sin `/privacidad/v1.0` ni parámetros).
- `app/appmode.py`: `/robots.txt` en `ALWAYS`.
- `templates/legal_base.html`: `<meta name="description">`, `<link rel="canonical">`, título normalizado. Solo el `<head>`.
- `templates/login.html`, `ingreso_espera.html`, `certificado_local.html`, `form_stats.html`, `kiosk_estadisticas.html`: `<meta name="robots" content="noindex,nofollow">`.
- `tests/test_seo_plataforma.py` (nuevo, 7 pruebas de texto).
- Fuera del área, por necesidad: `tests/test_seguridad_2026-11-22.py` (se agregó `/robots.txt` a la lista cerrada, pedido del coordinador) y `tests/test_publico_congelado.py` (hash renovado de `legal_base.html`, con nota).
- `docs/legal/PENDIENTE_AUDITORA_2026-11-22.md` (nuevo).
- No se tocó `app/main.py`, `app/legal_texts_data.py` ni ningún texto legal.

## 4. Qué queda pendiente y por qué
1. **Comprobar en staging** que `https://staging.golden-eventos.com/robots.txt` responde 200 y que las legales muestran el canónico correcto (0,5 h; necesita despliegue, que autoriza Juan David).
2. **Auditora**: frase del traductor y textos E y F (0,5 h de correo; la respuesta no depende de nosotros).
3. **Cabecera `X-Robots-Tag: noindex`** global en el middleware de `app/main.py`, salvo las legales (0,5 h): cubre también JSON y páginas armadas a mano. No se hizo porque otro agente está tocando `main.py`.
4. **Enlace «Sitio corporativo: golden-eventos.com»** en las páginas legales (0,5 h): es texto visible en páginas legales; mejor con el visto bueno de la auditora.
5. **Search Console** para `app.golden-eventos.com` y pedir retirar `/login` si ya está indexado (0,5 h, Juan David).

## 5. Qué NO se pudo comprobar
- Las pruebas que arrancan la aplicación (`client`): aquí no está instalado FastAPI. No se pidió `/robots.txt` ni una página legal a un servidor real; el `<head>` legal sí se renderizó con Jinja2 suelto y salió correcto.
- Si Firebase Hosting o Nginx dejan pasar `/robots.txt` hasta la aplicación.
- Si Google ya tiene indexado `/login`.
- `LEGAL_NAME`/`COMPANY_NAME` reales de producción (viven en el despliegue).

## 6. Consejo en corto y veredicto
- **Contrario:** `robots.txt` no retira lo ya indexado y además impide que Google lea el `noindex` de `/login`; si ya aparece, hay que pedir el retiro en Search Console.
- **Primeros principios:** una plataforma privada solo necesita mostrar al mundo sus tres páginas de confianza; todo lo demás cerrado por defecto.
- **Expansionista:** la cabecera global `X-Robots-Tag` cerraría de una vez todo lo que se agregue en el futuro.
- **Forastero:** que al buscar «Golden Eventos» salga la empresa y no una pantalla de contraseña es lo que cualquier cliente espera.
- **Ejecutor:** desplegar a staging, abrir `/robots.txt` y ver el código fuente de `/privacidad`: cinco minutos.

**Veredicto:** P1-P3 quedaron aplicados y probados en texto; P4 espera a la auditora. **UN siguiente paso:** desplegar a staging y abrir `/robots.txt`.
