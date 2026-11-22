# Pendientes para la auditora (22-nov-2026)

Origen: revisión integral, reporte `docs/revision_2026-11-22/08_google_seo_ux_regulacion_ia.md` (hallazgo 26, P4 y textos E y F).
**Nada de esto está publicado.** Son BORRADORES: ningún texto legal de la plataforma (`app/legal_texts_data.py`, `templates/legal_*.html`,
`docs/legal/POLITICA_v1.1.md`, `templates/_legal_footer.html`) se cambió. Se publican solo con el visto bueno escrito de la auditora.

## 1. Cookie del traductor de Google en el formulario público

**Qué pasa hoy.** El formulario público de inscripción (`templates/form_public.html`, función `loadTranslator`) ofrece un traductor. Solo si la persona
lo activa, la página carga el traductor de Google (`translate.google.com`), que puede dejar en el navegador una cookie de preferencia de idioma
(`googtrans`). La política dice que se usan «únicamente cookies necesarias»: falta mencionar este caso.

**Frase propuesta** (para la sección de cookies de la Política de Privacidad, y si la auditora lo prefiere, también junto al botón del traductor):

> «Si usted activa el traductor del formulario, Google puede dejar en su navegador una cookie de preferencia de idioma (`googtrans`). Esa cookie solo
> se crea si usted usa el traductor; lo que usted escribe en los campos del formulario no se envía a Google.»

**Pregunta a la auditora:** ¿basta la frase en la política, o debe aparecer también en el aviso del traductor antes de activarlo?

## 2. Texto E · Frase corta sobre el reconocimiento facial (plataforma)

Propuesta para el pie legal público (`templates/_legal_footer.html`) y para la sección 5 de la política:

> «El reconocimiento facial de GoldenWeb 2.0 es un sistema automatizado de identificación biométrica, voluntario, que propone una coincidencia que
> siempre confirma un operador humano. Cómo funciona, sus límites y sus mediciones: [golden-eventos.com/inteligencia-artificial].»

Depende de que exista la página `/inteligencia-artificial` del sitio corporativo (textos C y D del reporte 08).

## 3. Texto F · Dos preguntas nuevas para «Preguntas frecuentes» del sitio corporativo

> **¿Usan inteligencia artificial?** Sí, en dos cosas: el reconocimiento facial voluntario en la puerta (un operador siempre confirma) y como
> herramienta para construir nuestro software y parte de los textos de este sitio. Lo explicamos en
> [Cómo usamos la inteligencia artificial](/inteligencia-artificial).
>
> **¿Cómo borro mis datos después de un evento?** Escriba a soporteit@goldenlogisticas.com con su nombre, documento y el evento. Su rostro, si lo
> registró, se borra solo a los 7 días; el resto lo eliminamos a su solicitud y respondemos en máximo 15 días hábiles.

**Para confirmar con la auditora:** el plazo de «15 días hábiles» y el correo de contacto deben coincidir con los de la política vigente.

## Estado

| # | Texto | Dónde iría | Estado |
|---|---|---|---|
| 1 | Cookie del traductor | Política (cookies) / aviso del traductor | Pendiente de la auditora |
| 2 | Texto E | Pie legal y política §5 | Pendiente de la auditora |
| 3 | Texto F | Preguntas frecuentes del sitio | Pendiente de la auditora |
