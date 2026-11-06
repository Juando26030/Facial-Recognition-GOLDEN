# Estándares visuales de GoldenWeb 2.0 (la regla única)

**Cuándo manda:** toda pantalla, componente, correo o texto visible que se cree o se toque. Si algo visual no está aquí, se decide una vez, se agrega aquí y recién después se usa.
**Fuentes de verdad (no se duplican):**
- Valores y componentes: `static/css/design-system.css` (tokens `--gw-*`, clases `.gw-*`).
- Muestrario vivo (mirar antes de construir): `docs/ux/guia_visual.html`.
- Íconos: `static/img/icons.svg` (sprite propio). Comportamiento: `static/js/gw-ui.js`. Cabecera con tema: `templates/_gw_head.html`.
- Pruebas que lo hacen cumplir: `tests/test_design_system.py` (contraste WCAG AA por código). Si cambias un color, corre esa prueba.
- Razones y fuentes externas (NN/g, GOV.UK, WCAG 2.2, Apple HIG, Material): `docs/ux/PLAN_FASE1_UX.md` y `claude/26_ANALISIS_UX_Y_FLUJO_FACIAL.md` §3.

## 1. Reglas de oro (las 12 que no se negocian)
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
11. **Regla de frecuencia:** lo que se hace con cada persona o ítem va visible, a un clic y en una línea compacta (en Registro: Acreditar, Imprimir, Editar); lo que se hace una vez por evento o es destructivo se esconde (menú «Más», con confirmación). Nunca esconder en un menú la acción más usada.
12. **Guía y animación:** toda pantalla principal trae su guía de 3 pasos con «?» y recorrido de primera vez (`.gw-tour`, una vez por dispositivo); las animaciones solo con propósito (confirmar, mostrar el motivo, abrir un panel), de 250 ms como máximo y con alternativa de movimiento reducido (`prefers-reduced-motion`).

## 2. Tokens (resumen; el valor exacto vive en el CSS)
| Tema | Tokens |
|---|---|
| Marca | `--gw-navy`, `--gw-navy-deep`, `--gw-gold-1/2`, `--gw-gold-grad`, `--gw-on-gold`, `--gw-gold-text` |
| Superficies y texto | `--gw-bg`, `--gw-surface`, `--gw-surface-2`, `--gw-border`, `--gw-border-strong`, `--gw-text`, `--gw-text-muted`, `--gw-link`, `--gw-focus` |
| Estados (fondo/texto/línea) | `--gw-ok-*`, `--gw-warn-*`, `--gw-err-*`, `--gw-info-*`, `--gw-danger`, `--gw-on-danger` |
| Tipografía (6 tamaños) | `--gw-fs-sm` 14 · `md` 16 · `lg` 18 · `xl` 22 · `2xl` 28 · `3xl` 36; `--gw-lh-tight` 1,25 · `--gw-lh-body` 1,55 |
| Espaciado (base 4 px) | `--gw-sp-1` … `--gw-sp-8` |
| Puerta (Fase 1.7) | `--gw-tap-lg` 64 px (objetivo táctil de puerta), `--gw-fs-door` 24 px (veredicto, cifras, vacío grande) |
| Forma | radios `--gw-radius-sm/md/lg/pill` (8/12/20/999), sombras `--gw-shadow-sm/md/lg`, `--gw-ring` (foco), `--gw-dur` (160 ms), `--gw-content-w` |

Uso del color: azul marino = identidad y acción; dorado = acento y fondo de énfasis; verde/ámbar/rojo/azul-info **solo** para estados, y siempre acompañados de ícono o texto (no depender solo del color).

## 3. Componentes que ya existen (reutilizar, no reinventar)
Botón `.gw-btn` · mosaico por tarea `.gw-tile/.gw-tiles` · tarjeta `.gw-card` · campos `.gw-field/.gw-label/.gw-input/.gw-textarea/.gw-check/.gw-hint/.gw-error` · tabla `.gw-table` · insignia `.gw-badge` · aviso `.gw-alert` · estado de pantalla (vacío/cargando/error) `.gw-state/.gw-spinner` · ventana `.gw-modal` · asistente por pasos `.gw-wizard/.gw-progress` · navegación `.gw-nav` · interruptor de tema `.gw-theme-toggle` · ayuda en contexto `.gw-help/.gw-popover` · recorrido `.gw-tour` · grupo desplegable `.gw-group` (+ `__sum/__title/__hint/__body/__item`) y barra de guardado global `.gw-savebar` (+ `__status/__fail`) · grupos plegables del formulario de persona y filas en columnas `.gw-form-group/.gw-form-group__summary/.gw-form-group__body/.gw-fields-row--1..4` (heredan color y fondo de la pantalla donde se usen; distintos de `.gw-group`, que es el de Parámetros).
Carga de listas por pasos (Adjuntar Base de Datos): tarjetas numeradas `.gw-step` (`__head/__num/__title/__body`), avance `.gw-pbar` (`--ok/--err`; la usa `progress-bar.js`), `.gw-list`, `.gw-checklist`, `.gw-check--top`, `.gw-fieldset`, `.gw-container--narrow` y `.gw-shell` (cabecera y franja del evento con tokens en pantallas con menú lateral).
Botón `.gw-btn` · mosaico por tarea `.gw-tile/.gw-tiles` · tarjeta `.gw-card` · campos `.gw-field/.gw-label/.gw-input/.gw-textarea/.gw-check/.gw-hint/.gw-error` · tabla `.gw-table` · insignia `.gw-badge` · aviso `.gw-alert` · estado de pantalla (vacío/cargando/error) `.gw-state/.gw-spinner` · ventana `.gw-modal` · asistente por pasos `.gw-wizard/.gw-progress` · navegación `.gw-nav` · interruptor de tema `.gw-theme-toggle` · ayuda en contexto `.gw-help/.gw-popover` · recorrido `.gw-tour` · grupo desplegable `.gw-group` (+ `__sum/__title/__hint/__body/__item`) y barra de guardado global `.gw-savebar` (+ `__status/__fail`) · grupos plegables del formulario de persona y filas en columnas `.gw-form-group/.gw-form-group__summary/.gw-form-group__body/.gw-fields-row--1..4` (heredan color y fondo de la pantalla donde se usen; distintos de `.gw-group`, que es el de Parámetros) · zona de trabajo con lista que se desplaza por dentro `.gw-workarea` (+ `__bar/__summary/__list`) y `.gw-toolbar` (Registro, Plan 8: buscador y UNA acción principal fijos arriba; la página no crece con la lista) · etiqueta/contador pulsable `.gw-chip` (+ `--ok/--err`) · menú «Más» `.gw-menu` (+ `__panel/__item`) para las acciones secundarias de cada fila · origen de carga `.gw-origin` · fila de acciones `.gw-rowact`.
Botón `.gw-btn` · mosaico por tarea `.gw-tile/.gw-tiles` · tarjeta `.gw-card` · campos `.gw-field/.gw-label/.gw-input/.gw-textarea/.gw-check/.gw-hint/.gw-error` · tabla `.gw-table` · insignia `.gw-badge` · aviso `.gw-alert` · estado de pantalla (vacío/cargando/error) `.gw-state/.gw-spinner` · ventana `.gw-modal` · asistente por pasos `.gw-wizard/.gw-progress` · navegación `.gw-nav` · interruptor de tema `.gw-theme-toggle` · ayuda en contexto `.gw-help/.gw-popover` · recorrido `.gw-tour` · pestañas de sección `.gw-tabs/.gw-tablist/.gw-tab/.gw-tabpanel` (+ `__icon/__name/__sum/__flag/__head`), guía de pasos `.gw-steps`, piezas de ajustes `.gw-item-head/.gw-setting/.gw-choice/.gw-fieldset/.gw-actions/.gw-form-grid/.gw-msg/.gw-danger-zone/.gw-btn--danger-outline`, tarjeta de ajuste `.gw-group__item`, grupo desplegable `.gw-group` (+ `__sum/__title/__hint/__body/__item`; queda disponible, Parámetros ya usa pestañas) y barra de guardado global `.gw-savebar` (+ `__status/__fail`) · grupos plegables del formulario de persona y filas en columnas `.gw-form-group/.gw-form-group__summary/.gw-form-group__body/.gw-fields-row--1..4` (heredan color y fondo de la pantalla donde se usen; distintos de `.gw-group`, que es el de Parámetros).
Si necesitas algo que no está: primero se agrega a `design-system.css` **y** a `guia_visual.html` (con su par de contraste en `test_design_system.py`), después se usa.

## 4. Patrones de pantalla
- **Una cosa por paso:** una decisión por pantalla en flujos largos; botón «Continuar».
- **Revelación progresiva:** lo frecuente arriba, lo avanzado aparte, máximo 2 niveles.
- **Interruptor** = efecto inmediato sin «Guardar»; **casilla/radio** = se aplica al guardar. No mezclarlos en la misma sección. (Excepción de Parámetros: ahí todo queda pendiente hasta el Guardar global.)
- **Parámetros** en pestañas de sección (`.gw-tabs`: una visible a la vez, resumen de una línea bajo cada nombre, la última vista se recuerda por dispositivo; recorrido de primera vez `.gw-tour`, guía de 3 pasos `.gw-steps`, detalle largo en «?») con **UN Guardar global** (`.gw-savebar`, decisión del dueño, Plan 6, 2026-11-04; antes «un Guardar por pestaña»): los campos, casillas e interruptores son cambios pendientes hasta guardar; la barra dice «Cambios sin guardar» / «Guardado» (con check) o qué bloque falló, y la pestaña con pendientes lo marca «Sin guardar» (lo demás sí se guarda) y la pantalla avisa al salir con cambios. **Privacidad** y toda acción destructiva (borrar campo, purgar, borrar puesto) siguen inmediatas, en rojo y con confirmación. Esto vale solo para Parámetros; el resto de pantallas conserva su botón propio.
- **Guías y animaciones:** la guía de primera vez (`.gw-tour`) sale una vez por dispositivo (localStorage en try/catch) y siempre se puede repetir; el detalle largo va en un «?» (`.gw-help`), bajo el control queda una sola línea. Una animación solo si ayuda a entender (cambio de sección, check al guardar), de 250 ms o menos y sin movimiento con `prefers-reduced-motion`.
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

### Buscador del registro y píldoras de la fila (5-nov-2026)
- Papelera del buscador: `.gw-search__row` (caja + botón) y `.gw-search__clear` (icono `#i-trash`, nombre accesible «Vaciar búsqueda»; aparece solo si hay texto).
- Píldora sólida de la fila: `.gw-recent-tag` (verde, «Recién registrado»: se acreditó a alguien de la base) y `.gw-recent-tag--new` (azul, «Recién creado»: alta manual con «Registrar nuevo»).

## 9. Fase 1.5 · piezas compartidas (docs/ux/FASE_1_5_PLAN.md)
- **Barra de guardado única** `.gw-savebar` (`templates/_gw_savebar.html`, motor `static/js/params-save.js`): botón + Ctrl o Cmd + S, «Cambios sin guardar», aviso al salir; el contenedor lleva `id="paramsRoot"`. Una por pantalla.
- **Botón que trabaja:** `GW.busy(boton, trabajo)` (`static/js/gw-busy.js`) pone la rueda (`aria-busy`), bloquea el doble clic y avisa si tarda. Todo botón que dispara una petición lo usa.
- **Encabezado de página** `.gw-page-head` (`__text`, `__title`, `__sub`, `__actions`); **vacío** `.gw-empty`; **cargando** `.gw-skeleton`.
- **Lista en tarjetas** `.gw-cards` + `.gw-card-row` (`__head`, `__title`, `__meta`, `__actions`): las acciones van SIEMPRE dentro de la tarjeta, a la vista. **Tabla que se vuelve tarjetas en celular:** `<table class="gw-table-cards">`, `td[data-label]` y `td.gw-table-cards__actions`.
- **Celular:** bajo 768 px la barra de guardado respeta el borde inferior; bajo 640 px los `.gw-modal` ocupan toda la pantalla.
- **Congelado:** lo que ven las personas no se toca (`tests/test_publico_congelado.py`).

### Cabecera y pasos compactos en celular (Fase 1.7, M1; muestrario: `guia_visual.html#cabecera-movil`)
Retroalimentación real de Juan David (celular de ~410 px): la cabecera comía media pantalla. Todo es CSS bajo `.gw-page` y solo cambia a <= 640 px; el escritorio queda igual.
- **Franja blanca (`.golden-header`)**: UNA línea de 56 px: menú ☰, logo de 32 px, botón de tema SOLO ÍCONO (`.gw-theme-toggle` dentro del header oculta `[data-gw-theme-label]`; `aria-label` y `title` «Tema claro/oscuro» los pone `_gw_theme_toggle.html` y `gw-ui.js`), nombre recortado con «…» (el rol completo va en `title`) y «Salir». Al crear una cabecera nueva: nombre en `.gw-shell__who` / `.golden-nav-user` con `title="nombre (rol)"`.
- **Franja azul (`.golden-event-strip`)**: Cliente · Evento · Código seguidos y separados por «·»; los rótulos (`<strong>`) quedan en el DOM pero ocultos a la vista (solo lectores de pantalla).
- **`.gw-steps` = tira de 3 chips** (una sola fila, también en escritorio): cada `<li>` es una píldora con número + título corto (máx. 2 líneas); tocarla abre su «?» (`.gw-help`/`.gw-popover`, igual que antes) porque el botón `.gw-help__btn` se estira invisible sobre todo el chip. El marcado no cambia (`<ol class="gw-steps">` con `<li>` = `.gw-steps__n` + `.gw-steps__text` + `ayuda()` opcional); si un `<li>` no trae `ayuda()`, es un chip informativo. Se aplica solo a toda pantalla que ya usa `.gw-steps` (Sistema y Registro la heredan por CSS).
- **`.gw-grid-2m`**: cuadrícula para tarjetas de información o cifras que en celular reparte SIEMPRE de a 2 columnas (en escritorio: auto-fit de 14 rem).
- Encabezado de página en celular: `.gw-page-head` con menos margen y título de `--gw-fs-xl`; `.golden-section-title h2` igual.

### Piezas de puerta (Fase 1.7, Ola 0; muestrario: `guia_visual.html#puerta`)
Para el digitador en tableta, celular o quiosco. Reglas: una acción principal por vista, objetivos de `--gw-tap-lg` (64 px), texto de 18 a 24 px, estado siempre con ícono + texto, poca densidad. Solo clases nuevas: no alteran las pantallas ya migradas.
- `.gw-btn--xl`: solo las 1-2 acciones de la puerta (Escanear, Acreditar); el resto sigue en 44 px.
- `.gw-search--hero` (sobre `.gw-search`): píldora de 64 px con la lupa dentro (`.gw-search__field` + `.gw-search__icon`) y botón cuadrado de escáner `.gw-search__scan` (siempre con `aria-label`).
- `.gw-verdict` (`--ok/--warn/--err`, `--door` para pantalla grande; partes `__icon/__body/__title/__text`): veredicto de acreditar o de acceso; `role="status"`, y `role="alert"` el rojo. Reemplaza al toast para el resultado de acreditar.
- `.gw-person` (`--ok/--warn/--err/--info`, `--big`; partes `__photo/__body/__name/__meta/__status/__actions`): tarjeta de resultado en vez de fila de tabla.
- `.gw-stat` (`--ok/--warn/--err`; `__icon/__value/__label/__hint`) dentro de `.gw-stats-row` (3 por fila también en celular; `--2`).
- `.gw-tile--hero`: mosaico principal del rol, doble ancho en `.gw-tiles`.
- `.gw-segment` / `.gw-segment__opt` (`--lg`, `--fit`): elegir una opción entre pocas; seleccionado = dorado + visto (`aria-pressed`, `aria-checked` o radio dentro de `<label>`).
- `.gw-conn` (`--warn/--err/--info`, `--lg`): conexión con palabras («En línea», «Sin conexión, guardando»), ícono y color.
- `.gw-split` (`__main/__aside`, `--aside-first`, `__aside--sticky`): principal + lateral desde 960 px; en celular el lateral queda debajo.
- `.gw-state.gw-empty--hero`: estado vacío grande de puerta.
- `.gw-keypad` (`__display/__keys/__key`, `--clear` rojo, `--ok` verde): teclado numérico opcional con teclas de 72 px; no sustituye al lector.
- Íconos nuevos del sprite: `scan`, `wifi`, `backspace`, `check-lg`, `id-card`, `clock`, `arrow-in`, `arrow-out`.

## 10. Fase 1.7 · M6 · introducción mínima en celular (<= 640 px)
- Lo que no sirve para actuar (etiqueta superior, título, subtítulo, pasos 1·2·3 y «Guía») va en un bloque compacto pegado a la cabecera: etiqueta superior solo para lectores de pantalla, título `--gw-fs-lg` en una línea con «…», subtítulo de una línea con «…» (el texto completo queda en `title`, lo pone `gw-ui.js`), márgenes de 4-8 px. Nada se quita del DOM.
- «Ver la guía» (`data-gw-tour-restart`) pasa a ser el 4.º chip «Guía» de `.gw-steps` (`gw-ui.js` lo reubica en un `li.gw-steps__guide`; al ensanchar la ventana vuelve a su sitio; ids y `data-gw-tour*` intactos). Pasos + guía = una fila.
- Un nivel menos de espaciado en `.gw-container`, `.gw-stack(-lg)`, `.gw-card`, `.gw-card-row`, `.gw-cards`; franja azul del evento en una línea con «…»; botón ☰ de 40 px alineado con la cabecera de 56 px; el separador `.golden-content-spacer` no ocupa espacio.
- El ícono del interruptor de tema (`.gw-theme-toggle .gw-icon`) tiene tamaño y trazo propios y no se encoge en cabeceras apretadas (Registro).
- Escritorio sin cambios (todo va dentro de `@media (max-width: 640px)`).

## 11. Fase 1.7 · M8 · chips, «Vaciar búsqueda» y Registro en celular
- **Chips de pasos y «Guía» (<= 640 px, todas las pantallas):** los pasos 1·2·3 y el 4.º chip «Guía» son píldoras iguales (borde `--gw-border-strong`, fondo `--gw-surface`, radio `--gw-radius-pill`, 40 px de alto) en UNA fila. Insignia numérica de 1,25 rem, texto `--gw-fs-sm`; los títulos cortos caben en una línea y los largos pasan a dos SIN partir palabras (`overflow-wrap: normal`; nunca «Acredi/ta»). «Guía» = ícono de ayuda + la palabra en una línea; el `li.gw-steps__guide` lleva el borde y el botón de dentro va transparente.
- **Vaciar búsqueda (`.gw-search__clear--in`):** TODO campo de búsqueda (input `type=search`, inputs dentro de `.gw-search` o con placeholder «Buscar…», «Filtrar…», «Escribe o escanea…», también los que genera el JS) lleva a la derecha una papelera (`#i-trash`, `aria-label` «Vaciar búsqueda») visible solo con texto. La instala `gw-ui.js` (delegada + `MutationObserver`, sin `onclick` en línea): vacía el campo, devuelve el foco y dispara `input` (y `search`) para que el filtro se refresque. El campo gana `.gw-input--clearable`; si no está en un `.gw-search__field`, se envuelve en `.gw-clearable`. Para excluir uno: `data-gw-no-clear`. El Registro conserva su papelera propia junto a la caja (`#searchClearBtn`, la maneja `directory.js`, mismo nombre accesible). No toca al lector de cédula: el lector escribe y envía Enter, el botón no está en ese camino.
- **Registro en celular (410 px):** cabecera de una fila (título pequeño; «En línea» y engranaje como botones pequeños a la derecha; sin la etiqueta de la empresa), chips bajo la franja del evento, caja de 44 px, «Escanear» y «Registrar nuevo» como dos botones de 48 px mitad y mitad, contadores en UNA fila (origen y «Limpiar filtros» detrás del chip «Filtros», `#gwSummaryMore`), tarjeta de persona con las tres acciones en una fila. El cálculo de alturas está en el comentario de `static/css/p-registro-puerta.css`. El modo touch (`shared-print.js`) fuerza `font-size`/`padding` con `!important` en todo botón: por eso las reglas del Registro en celular también llevan `!important` donde hace falta.

