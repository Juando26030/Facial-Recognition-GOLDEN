# Estándares visuales de GoldenWeb 2.0 (la regla única)

**Cuándo manda:** toda pantalla, componente, correo o texto visible que se cree o se toque. Si algo visual no está aquí, se decide una vez, se agrega aquí y recién después se usa.
**Fuentes de verdad (no se duplican):**
- Valores y componentes: `static/css/design-system.css` (tokens `--gw-*`, clases `.gw-*`).
- Muestrario vivo (mirar antes de construir): `docs/ux/guia_visual.html`.
- Íconos: `static/img/icons.svg` (sprite propio). Comportamiento: `static/js/gw-ui.js`. Cabecera con tema: `templates/_gw_head.html`.
- Pruebas que lo hacen cumplir: `tests/test_design_system.py` (contraste WCAG AA por código). Si cambias un color, corre esa prueba.
- Razones y fuentes externas (NN/g, GOV.UK, WCAG 2.2, Apple HIG, Material): `docs/ux/PLAN_FASE1_UX.md` y `claude/26_ANALISIS_UX_Y_FLUJO_FACIAL.md` §3.

## 1. Reglas de oro (las 10 que no se negocian)
1. **Solo tokens y clases `.gw-*`.** Prohibido escribir colores, tamaños, radios o sombras sueltos (`#777`, `13px`, `border-radius:6px`). Si falta un valor, se agrega como token, no se improvisa.
2. **Páginas nuevas o rediseñadas:** `<body class="gw-page">`, incluir `_gw_head.html` y cargar el CSS con `url_for('static', ...)`.
3. **Un solo botón principal por vista** (`.gw-btn` primario), verbos claros («Guardar cambios», «Cargar lista»). Lo destructivo va en rojo (`--gw-danger`), nunca es el principal y pide confirmación; las muy graves, escribir el código del evento.
4. **Texto mínimo 14 px, cuerpo 16 px.** Objetivo táctil mínimo 44 px (`--gw-tap`); en puerta, iPad y celular, grande.
5. **Contraste:** texto ≥ 4,5:1; texto grande e íconos ≥ 3:1. El dorado **nunca** como texto sobre claro (usar `--gw-gold-text`); sobre dorado, texto azul marino (`--gw-on-gold`), jamás blanco.
6. **Tema claro por defecto; oscuro solo si la persona lo elige**, por dispositivo. Lo que se imprime (escarapelas, plantillas, vistas previas) lleva `.gw-no-theme` y nunca cambia de tema.
7. **Íconos solo del sprite SVG**, con texto al lado y `aria-hidden`. Prohibidos los emoji como íconos de interfaz.
8. **Fuente única:** Agrandir con Montserrat de respaldo, sin CDN ni fuentes externas. Peso normal = 600 (el 400 de Agrandir es «Thin», ilegible).
9. **Lenguaje:** español, frases cortas, palabras de quien usa la pantalla, sin jerga técnica (nada de «SMTP», «encoding», «.env»). Errores breves que dicen qué hacer. Un concepto = un nombre en toda la app.
10. **Avisos y confirmaciones con `showToast`/`showConfirm`/`showPrompt`** (`toast.js`); nunca `alert`/`confirm`/`prompt`. Sin `onclick` inline; delegación de eventos.

## 2. Tokens (resumen; el valor exacto vive en el CSS)
| Tema | Tokens |
|---|---|
| Marca | `--gw-navy`, `--gw-navy-deep`, `--gw-gold-1/2`, `--gw-gold-grad`, `--gw-on-gold`, `--gw-gold-text` |
| Superficies y texto | `--gw-bg`, `--gw-surface`, `--gw-surface-2`, `--gw-border`, `--gw-border-strong`, `--gw-text`, `--gw-text-muted`, `--gw-link`, `--gw-focus` |
| Estados (fondo/texto/línea) | `--gw-ok-*`, `--gw-warn-*`, `--gw-err-*`, `--gw-info-*`, `--gw-danger`, `--gw-on-danger` |
| Tipografía (6 tamaños) | `--gw-fs-sm` 14 · `md` 16 · `lg` 18 · `xl` 22 · `2xl` 28 · `3xl` 36; `--gw-lh-tight` 1,25 · `--gw-lh-body` 1,55 |
| Espaciado (base 4 px) | `--gw-sp-1` … `--gw-sp-8` |
| Forma | radios `--gw-radius-sm/md/lg/pill` (8/12/20/999), sombras `--gw-shadow-sm/md/lg`, `--gw-ring` (foco), `--gw-dur` (160 ms), `--gw-content-w` |

Uso del color: azul marino = identidad y acción; dorado = acento y fondo de énfasis; verde/ámbar/rojo/azul-info **solo** para estados, y siempre acompañados de ícono o texto (no depender solo del color).

## 3. Componentes que ya existen (reutilizar, no reinventar)
Botón `.gw-btn` · mosaico por tarea `.gw-tile/.gw-tiles` · tarjeta `.gw-card` · campos `.gw-field/.gw-label/.gw-input/.gw-textarea/.gw-check/.gw-hint/.gw-error` · tabla `.gw-table` · insignia `.gw-badge` · aviso `.gw-alert` · estado de pantalla (vacío/cargando/error) `.gw-state/.gw-spinner` · ventana `.gw-modal` · asistente por pasos `.gw-wizard/.gw-progress` · navegación `.gw-nav` · interruptor de tema `.gw-theme-toggle` · ayuda en contexto `.gw-help/.gw-popover` · recorrido `.gw-tour` · grupo desplegable `.gw-group` (+ `__sum/__title/__hint/__body/__item`) y barra de guardado global `.gw-savebar` (+ `__status/__fail`) · grupos plegables del formulario de persona y filas en columnas `.gw-form-group/.gw-form-group__summary/.gw-form-group__body/.gw-fields-row--1..4` (heredan color y fondo de la pantalla donde se usen; distintos de `.gw-group`, que es el de Parámetros) · zona de trabajo con lista que se desplaza por dentro `.gw-workarea` (+ `__bar/__summary/__list`) y `.gw-toolbar` (Registro, Plan 8: buscador y UNA acción principal fijos arriba; la página no crece con la lista) · etiqueta/contador pulsable `.gw-chip` (+ `--ok/--err`) · menú «Más» `.gw-menu` (+ `__panel/__item`) para las acciones secundarias de cada fila · origen de carga `.gw-origin` · fila de acciones `.gw-rowact`.
Si necesitas algo que no está: primero se agrega a `design-system.css` **y** a `guia_visual.html` (con su par de contraste en `test_design_system.py`), después se usa.

## 4. Patrones de pantalla
- **Una cosa por paso:** una decisión por pantalla en flujos largos; botón «Continuar».
- **Revelación progresiva:** lo frecuente arriba, lo avanzado aparte, máximo 2 niveles.
- **Interruptor** = efecto inmediato sin «Guardar»; **casilla/radio** = se aplica al guardar. No mezclarlos en la misma sección. (Excepción de Parámetros: ahí todo queda pendiente hasta el Guardar global.)
- **Parámetros** en grupos desplegables (`.gw-group`, solo el primero abierto, lo abierto se recuerda por usuario) con **UN Guardar global** (`.gw-savebar`, decisión del dueño, Plan 6, 2026-11-04; antes «un Guardar por pestaña»): los campos, casillas e interruptores son cambios pendientes hasta guardar; la barra dice «Cambios sin guardar» / «Guardado ✓» o qué bloque falló (lo demás sí se guarda) y la pantalla avisa al salir con cambios. **Privacidad** y toda acción destructiva (borrar campo, purgar, borrar puesto) siguen inmediatas, en rojo y con confirmación. Esto vale solo para Parámetros; el resto de pantallas conserva su botón propio.
- **No pedir dos veces** un dato ya dado (autocompletar). Decir antes qué se va a pedir.
- **Los 3 estados siempre:** cada lista o carga tiene vacío, cargando y error diseñados, con qué hacer.
- **Inicio por rol:** mosaicos grandes por tarea, ordena sin esconder; los principios aplican también al super_admin.
- **Formularios de datos no se cierran al hacer clic afuera.**

## 5. Accesibilidad mínima obligatoria
Todo control con nombre accesible (`<label for>` o `aria-label`); foco visible (`--gw-ring`); navegable con teclado; respeta movimiento reducido (`prefers-reduced-motion`); no se comunica solo por color; la ayuda «?» funciona con teclado. Antes de cerrar una fase visual: prueba con lector de pantalla (NVDA / VoiceOver) en las pantallas tocadas.

## 6. Lo que NO se toca sin orden expresa
Impresión de escarapelas (`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`: 62 × 99,8 mm, Brother QL-800, Chrome normal, nunca `--kiosk-printing`), y los textos legales de la auditora (literales, `app/legal_texts_data.py`).

## 7. Cómo se trabaja una pieza visual (siempre igual)
1. Abrir `guia_visual.html` y elegir los componentes existentes.
2. Construir solo con tokens y clases `.gw-*` (reglas de oro).
3. Probar en claro y oscuro, en ancho de celular (360 px) y de iPad, y con teclado.
4. Correr `python -m pytest -q tests/test_design_system.py` y `ruff check .`.
5. Capturas antes/después en la descripción del PR y en la conversación; Juan David aprueba el aspecto antes de fusionar.
6. Si se creó un valor o componente nuevo: queda en el CSS, en la guía y en este archivo.

## 8. Dónde se aplica en el plan
Base ya construida (Fase 1A pieza 0, 3-nov). El rediseño de pantallas existentes es la **Fase 2** del plan maestro (`docs/29`); mientras tanto, toda pantalla que se toque en otras fases (1A, 1B, 3…) **ya sale con estos estándares** y no se reabre después.
