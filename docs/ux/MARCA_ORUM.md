# Marca Orum (28-nov-2026)

**Nombre:** Orum, «Or» de Oro + «um» de Forum. Se escribe **Orum** y, cuando hace falta la empresa, **Orum by Golden Eventos y Logística**. Ya no se usa «GoldenWeb 2.0» (solo en documentos históricos).

**Logo:** aro azul marino (#1e2a6e) con punto dorado (#d4a63f) que hace de «O», más «rum» en minúscula, trazo geométrico y plano. Archivos en `static/img/`: `orum-logo.svg` (tinta azul, fondo claro), `orum-logo-oscuro.svg` (aro y letras blancas, punto dorado; también generado con Higgsfield, para fondos oscuros), `orum-mark.svg` (solo el aro), sus PNG, `favicon-32.png` y `apple-touch-icon.png` (aro blanco y punto dorado sobre azul marino). Generados con Higgsfield (gpt_image_2_6, salida SVG) y recortados a mano; son vectoriales, sin fuentes. **Cambio automático:** `static/js/gw-orum.js` mira el color de fondo real donde está el logo (`<img data-gw-orum data-src-claro data-src-oscuro>`) y pone la versión que contrasta; también reacciona al cambiar de tema.

**Créditos de autoría (28-nov-2026):** todas las páginas HTML llevan al final un pie pequeño y responsive, en español e inglés, con el autor del diseño y el desarrollo, Juan David Ramírez Juzga (`app/credits.py`, agregado por el middleware de `app/main.py`; no se imprime; las pantallas de TV, ruleta, escarapela, certificado e impresora USB lo evitan con `data-gw-no-credit` en `<body>`). Además: `<meta name="author">` en el HTML, `__author__` en `app/__init__.py`, `NOTICE.md` y `AUTHORS.md`.

**Colores:** los de siempre de Golden, sin cambios (`--gw-navy`, `--gw-gold-*`): el azul marino lleva el peso y el dorado es el acento (un solo punto, nunca fondos grandes).

**Fuente propuesta (gratuita, OFL, ya incluida sin CDN):** Manrope (`static/fonts/manrope-latin-*.woff2`, licencia en `static/fonts/licencias/`). Hoy la app usa Agrandir con Montserrat de respaldo; pasar todo a Manrope es cambiar `--gw-font` en `design-system.css` (la marca no depende de la fuente: el logo es vectorial). Pendiente de decisión de Juan David.

**Dónde va el logo de Orum:** login, cambio de contraseña, ingreso en espera, favicon e ícono de celular. **Dónde sigue el de Golden:** encabezado de pantallas internas (es el logo de la empresa/evento y se puede cambiar por evento), escarapelas, certificados, reportes y documentos.
