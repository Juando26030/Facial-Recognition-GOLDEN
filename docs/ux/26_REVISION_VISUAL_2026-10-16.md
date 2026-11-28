# 26 · Análisis de flujo y UX — Orum (16 oct 2026)

> Revisión visual entregada por Juan David el 17 de octubre de 2026 (copia literal). El contraste con el código y lo que se hizo están en `docs/ux/ANALISIS_FLUJO_Y_UX.md`; el plan, en `docs/ux/PLAN_FASE1_UX.md`.

Revisión visual hecha en staging (navegador, sesión de Juan, sin guardar cambios) sobre el evento PRUEBA-ACEPT-03 (/kiosk/5): lista de eventos, menú del evento, Adjuntar Base de Datos, Parámetros del Evento, Registro y página pública /aceptar (vista celular). Contrastado con guías oficiales (NN/g, GOV.UK, W3C/WCAG 2.2, Apple HIG, Android/Material). Calendario que manda: corte 20-oct, congelamiento 26-oct, piloto 29-oct.

## 1. Hallazgo principal: el reconocimiento facial se decide en TRES lugares

| Lugar | Control | Qué hace hoy |
|---|---|---|
| Parámetros → Paso 0 | Casilla «Este evento usará reconocimiento facial» | Configura el evento |
| Parámetros → Paso 0 | Otra casilla «🚫 Este evento NO usa biometría (bloquear)» | Bloqueo en servidor. Son dos casillas que pueden contradecirse |
| Adjuntar Base de Datos | Casilla «¿Desea activar el reconocimiento facial?» | Al marcarla pide el **zip de fotos** y la declaración del cliente (flujo A), aunque el evento esté en Paso 2 = B (selfie). Si no se marca, la carga **ignora la fecha de nacimiento** |

Consecuencias observadas:
- Caso del 16-oct: Paso 0 marcado y Paso 2 = B, pero la carga dijo «fecha de nacimiento: no se usa en este evento (no tiene reconocimiento facial)». El usuario no marcó la casilla de la carga porque le pedía un zip que no aplica. Resultado: la fecha se perdió y el enlace personal la volvió a pedir.
- La pantalla de carga no lee la configuración del evento: arranca desmarcada aunque el evento ya use rostro.
- La tarjeta del menú del evento refuerza el error: «marca la casilla de reconocimiento facial si quieres activar la cámara».

Norma que se incumple: NN/g heurística #4 Consistencia y estándares («los usuarios no deberían preguntarse si palabras, situaciones o acciones distintas significan lo mismo»); WCAG 2.2 criterio 3.3.7 Redundant Entry (no pedir otra vez lo que ya se dio en el mismo proceso); GOV.UK «pedir cada dato una sola vez».

**Regla propuesta (una sola fuente de verdad):**
1. El evento tiene UN estado de biometría, elegido en un solo lugar (Parámetros): «No usa rostro (bloqueado)» / «Usa rostro». Control de opción única (dos radios o un interruptor), nunca dos casillas.
2. Si usa rostro, el origen de la foto es UNO: B (selfie) o A (fotos del cliente en zip). Se elige en Parámetros.
3. La pantalla de carga NO decide nada: muestra el estado en un aviso de solo lectura («Este evento usa reconocimiento facial · fotos por selfie · cambiar en Parámetros») y:
   - con rostro activo, guarda siempre la fecha de nacimiento;
   - solo pide el zip y la declaración del cliente si el origen es A;
   - sin rostro, avisa ARRIBA que la columna de fecha no se usará (minimización) con enlace a Parámetros.
4. La tarjeta del menú se reescribe: «Carga masiva desde Excel/CSV».

## 2. Otros hallazgos (por pantalla)

**Lista de eventos**
- El estado del evento (Creado / En proceso / Finalizado) se cambia con un desplegable en la misma tarjeta, sin confirmación. Cambiar a Finalizado debería pedir confirmación (Apple HIG: acciones con consecuencias se confirman; NN/g #5 prevención de errores).
- Nombres internos visibles («8», «Juan David»): el nombre del evento sale tal cual en la página pública /aceptar. Separar «nombre público del evento» del código interno, o validar que no quede vacío/ambiguo.

**Menú del evento («¿Qué vas a hacer hoy?»)**
- 10 tarjetas con el mismo peso; «Parámetros del Evento», que es el primer paso, está de último. Ordenar por el ciclo del evento: 1 Configurar → 2 Cargar personas → 3 Invitar/aceptación → 4 Puerta → 5 Después (estadísticas, legalizaciones). Opción: lista «Primeros pasos» con ✓ (NN/g: estructura y transparencia en formularios).
- Íconos emoji: se ven distintos en Windows, iPad y Android. Usar un set de íconos propio (SVG) consistente.

**Parámetros del Evento**
- Una sola página muy larga con ~12 secciones sin relación (filas por página, biometría, envío de enlaces, privacidad, certificados, escarapela digital, áreas, inventario, logo, categorías, campos). Al menos 5 botones de guardar distintos («Guardar y revisar», «Guardar pre-cálculo», «Guardar categorías», «Guardar cambios», «Radicar»): el usuario no sabe qué guardó. NN/g: revelación progresiva (máx. 2 niveles) y no mezclar controles inmediatos con formularios de envío.
  Propuesta: pestañas o subpáginas — General · Reconocimiento facial · Invitaciones · Escarapelas y certificados · Campos del formulario · Privacidad. Un botón Guardar por pestaña, fijo abajo, con aviso «Cambios sin guardar».
- Acciones destructivas mezcladas con ajustes normales: «Borrar los datos biométricos de TODO el evento», «Suprimir TODOS los datos de esta persona». Moverlas a Privacidad, estilo rojo de «acción destructiva», confirmación escribiendo el código del evento (Apple HIG: el rol destructivo nunca es el botón principal).
- Lenguaje técnico visible para coordinadores: «.env.example», «data/outbox/», «SMTP», «Twilio», «encoding», «/kiosk/5/rostro», «Paso 0». GOV.UK: usar las palabras del usuario, sin jerga. Reemplazar por frases operativas y botones «Abrir pantalla de la puerta».
- El paso guiado de biometría está bien encaminado (resumen en palabras simples «✅ Listo: así funcionará en la puerta»): es el modelo a seguir para el resto.

**Adjuntar Base de Datos**
- La casilla «Reemplazar las fechas…» no tiene etiqueta accesible (el lector de pantalla la lee como «true»). Asociar `<label for>`.
- Ver §1 para la casilla de rostro.

**Registro**
- Título «Control de Acceso FACIAL INTELIGENTE» en una pantalla que también registra por cédula: el título debería ser la tarea («Registro y acceso»).
- La franja de supervisión funciona y se entiende; mantener.

**Página pública /aceptar (celular)**
- Es la mejor pantalla de la app: tipografía legible (~16-18 px), etiquetas claras, un botón principal, un mensaje. Debe ser la referencia visual del panel interno.

**Panel interno en general**
- Texto de ayuda pequeño y gris claro sobre blanco/gris: probable incumplimiento de contraste 4.5:1 (WCAG 1.4.3; Android core quality «Visual_Contrast»). Medirlo.
- Fuente del panel distinta a la de la página pública. Unificar.

## 3. Estándares a aplicar (con fuente)

| Tema | Regla | Fuente |
|---|---|---|
| Consistencia | Un mismo concepto, un solo nombre y un solo lugar | NN/g heurística #4 |
| No pedir dos veces | Datos ya dados se autocompletan | WCAG 2.2 · 3.3.7; GOV.UK |
| Una cosa por paso | Una decisión por pantalla/paso; botón «Continuar» | GOV.UK Question pages |
| Revelación progresiva | Lo frecuente arriba, lo avanzado aparte, máx. 2 niveles | NN/g Progressive disclosure |
| Interruptor vs casilla | Interruptor = efecto inmediato sin «Guardar»; casilla/radio = se aplica al guardar. No mezclar en la misma sección | NN/g Toggle-switch guidelines |
| Tamaño táctil | Mínimo 24×24 px (WCAG AA); objetivo 44×44 pt (Apple) / 48 dp (Android) para iPad y celular | W3C WCAG 2.2 · 2.5.8; Apple HIG Buttons; Android Core app quality |
| Contraste | 4.5:1 texto normal; 3:1 texto grande y gráficos | WCAG 1.4.3; Android Core app quality |
| Tipografía | Cuerpo 16 px (1rem) con interlineado 24 px; ayuda mínimo 14 px; escala fija de 5 tamaños (display, título, subtítulo, cuerpo, etiqueta) | Material 3 type scale (body-medium 1rem/1.5rem) |
| Botones | Un botón principal por vista; verbos claros («Cargar lista», «Guardar cambios»); destructivo en rojo y nunca principal | Apple HIG Buttons |
| Lenguaje | Frases cortas, palabras del usuario, sin jerga técnica; errores breves y directos | GOV.UK Writing for user interfaces |
| Formularios | Estructura, transparencia (decir antes qué se va a pedir), claridad, ayuda en el momento | NN/g 4 principios de carga cognitiva |

## 4. Plan por fases (respetando el calendario)

**Fase 0 — antes del congelamiento (hasta dom 25-oct; idealmente antes del corte del 20):** solo lo que afecta el piloto.
- §1 completo: una sola fuente de verdad de biometría; la carga lee el estado del evento; zip solo con origen A; aviso arriba de fechas ignoradas.
- Paso 0 como opción única (no dos casillas).
- Etiqueta accesible de «Reemplazar fechas».
- Confirmación al cambiar el estado del evento a Finalizado.
- Quitar jerga técnica visible en Parámetros (textos, sin cambiar lógica).
- Texto de la tarjeta «Adjuntar Base de Datos».

**Fase 1 — después del piloto (noviembre):** sistema visual.
- Tokens de diseño (colores, escala tipográfica, espaciado, radios) tomando la página /aceptar como base; un solo set de íconos SVG.
- Contraste y tamaños táctiles en todo el panel; prueba con lector de pantalla.
- Parámetros en pestañas con un Guardar por pestaña; Privacidad aparte con acciones destructivas confirmadas.
- Menú del evento ordenado por ciclo del evento + «Primeros pasos».

**Fase 2 — con usuarios reales:** prueba de usabilidad con 5 coordinadores (tarea: crear evento con rostro por selfie, cargar lista, invitar, abrir la puerta), medir tiempo y errores, ajustar.

## 5. Fuentes
- NN/g — 10 Usability Heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/
- NN/g — Consistency and Standards: https://www.nngroup.com/articles/consistency-and-standards/
- NN/g — Progressive Disclosure: https://www.nngroup.com/articles/progressive-disclosure/
- NN/g — Toggle-Switch Guidelines: https://www.nngroup.com/articles/toggle-switch-guidelines/
- NN/g — 4 Principles to Reduce Cognitive Load in Forms: https://www.nngroup.com/articles/4-principles-reduce-cognitive-load/
- NN/g (video) — Consistency and Standards: https://www.youtube.com/watch?v=owal0_UmRZ8
- GOV.UK Design System — Question pages: https://design-system.service.gov.uk/patterns/question-pages/
- GOV.UK Service Manual — Structuring forms: https://www.gov.uk/service-manual/design/form-structure
- GOV.UK Service Manual — Writing for user interfaces: https://www.gov.uk/service-manual/design/writing-for-user-interfaces
- W3C — What's New in WCAG 2.2: https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22
- Apple HIG — Buttons: https://developer.apple.com/design/human-interface-guidelines/buttons
- Android — Core app quality guidelines: https://developer.android.com/docs/quality-guidelines/core-app-quality
- Material Web — Typography: https://material-web.dev/theming/typography
