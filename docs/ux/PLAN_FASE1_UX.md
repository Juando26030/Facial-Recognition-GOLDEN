# Plan de UX: Fase 1 (noviembre, después del piloto) y Fase 2 (con usuarios) — solo documento, sin código

Sigue la estructura de la revisión del 16 de octubre (`docs/ux/26_REVISION_VISUAL_2026-10-16.md`) y las cifras medidas en `docs/ux/ANALISIS_FLUJO_Y_UX.md`. La Fase 0 ya está hecha en la rama `producto/fase0-ux`.

## Fase 1 — sistema visual (noviembre)

### 1. Tokens de diseño (un solo archivo de variables), con /aceptar como base
| Token | Valor | Por qué (medido) | Fuente |
|---|---|---|---|
| Fuente | **una sola** para panel y páginas públicas (hoy panel = Agrandir, /aceptar = Montserrat) | coherencia | NN/g #4 |
| Escala | 5 tamaños: display 32 · título 24 · subtítulo 20 · **cuerpo 16 / interlineado 24** · etiqueta 14 px | hoy 320 de 441 tamaños < 14 px | Material 3 type scale |
| Ayuda | 14 px mínimo, gris `#5c5f6b` (≈ 6:1) | `#777`, `#888`, `#999`, `#aaa`, `#bbb` no llegan a 4,5:1 | WCAG 1.4.3 |
| Avisos | rojo `#a12631` (7,4:1), ámbar `#8a5a00` (5,9:1), verde `#1e7a3a` | `#b26a00` da 4,24:1 | WCAG 1.4.3 |
| Marca | azul `#0a0e2e`; dorado `#D4AF37` **solo como fondo** con texto oscuro | dorado como texto: 2,1:1 | WCAG 1.4.3 |
| Espaciado y radios | 4 · 8 · 12 · 16 · 24 · 32 px; radios 8 / 12 / 20 | consistencia | — |
| Objetivos táctiles | ≥ 24 × 24 px en el panel; **44–48 px** en la puerta, /aceptar, iPad y celular | 16 casillas de 18 px en Parámetros | WCAG 2.5.8; Apple HIG; Android core quality |
| Íconos | set **SVG** propio, con texto al lado y `aria-hidden` | los emoji cambian por equipo y los lee el lector de pantalla | revisión §2 |

### 2. Contraste, tamaños y lector de pantalla en todo el panel
- Reemplazar los colores que no llegan (tabla del análisis) y subir los textos de ayuda a 14 px.
- Nombre accesible para los 33 controles detectados sin etiqueta (Parámetros 18, Registro 13, carga 2).
- Prueba con lector de pantalla (NVDA en Windows y VoiceOver en iPad) de: carga, Parámetros, Registro, /aceptar.
- Revisión automática en el CI: ningún texto < 14 px ni color < 4,5:1 en las plantillas.

### 3. Parámetros en pestañas, un Guardar por pestaña
**General** · **Reconocimiento facial** · **Invitaciones** · **Escarapelas y certificados** · **Campos del formulario** · **Privacidad**.
- Un botón **Guardar** por pestaña, fijo abajo, con aviso **«Cambios sin guardar»** al salir (WCAG 3.3.7).
- No mezclar interruptores de efecto inmediato con casillas que se aplican al guardar en la misma sección (NN/g, *toggle switches*).
- **Reconocimiento facial** sigue el modelo del paso guiado (resumen «✅ Listo: así funcionará en la puerta»), con revelación progresiva: si «No usa rostro», nada más aparece. Reúne también el autoregistro del escáner, la entrada con rostro y la foto en la escarapela (super administrador).
- **Invitaciones** junta el envío masivo y «enviar el enlace al inscribirse por formulario», explicando la diferencia.
- **Privacidad**: borrar fotos del evento, revocar y suprimir, en rojo, **nunca** como botón principal, con confirmación escribiendo el código del evento (hoy el borrado del evento ya pide escribir el nombre; revocar y suprimir piden confirmar) (Apple HIG Buttons).

### 4. Menú del evento por el ciclo, con «Primeros pasos»
1 **Configurar** (Parámetros) → 2 **Cargar personas** → 3 **Invitar y aceptación** → 4 **Puerta** (Registro, entrada con rostro, áreas, inventario, ruleta) → 5 **Después** (estadísticas, certificados, documentos, legalizaciones).
Arriba, una lista **«Primeros pasos»** con ✓ (rostro elegido, lista cargada, invitaciones enviadas, puerta probada). Cada tarjeta dice para qué sirve en una frase.

### 5. Otros de la revisión
- **Nombre público del evento**: un campo aparte para /aceptar, la puerta y los correos (o validar que el nombre no sea un número o un nombre de persona).
- **Registro**: título por la tarea, «Registro y acceso».
- **Escritura** (GOV.UK): sin rutas, archivos ni proveedores en pantalla; botones con verbo («Cargar lista», «Guardar invitaciones»); errores cortos que digan qué hacer.
- Retirar `PUT /facial-enabled` (segunda vía de encender el rostro) o hacerla pasar por la validación del paso guiado.
- Diseñador de escarapelas: avisar que la foto sale en blanco mientras su interruptor esté apagado.

### Criterios de aceptación de la Fase 1
- 0 textos < 14 px y 0 colores de texto < 4,5:1 en el panel (revisión automática).
- 0 controles sin nombre accesible.
- Objetivos ≥ 24 px en el panel y ≥ 44 px en la puerta y /aceptar.
- Cada ajuste se decide en un solo lugar (lista de incongruencias del análisis cerrada).

## Fase 2 — con usuarios reales
Prueba de usabilidad con **5 coordinadores** (NN/g: con 5 personas aparecen la mayoría de los problemas). Tarea completa: crear un evento con rostro por selfie → cargar la lista → enviar invitaciones → abrir la puerta. Medir **tiempo**, **errores** y **dónde dudan**; ajustar y repetir con otras 5 personas.

## Referencias
Las de la revisión del 16 de octubre (NN/g: heurísticas, consistencia, revelación progresiva, interruptores, carga cognitiva en formularios; GOV.UK: *Question pages*, *Structuring forms*, *Writing for user interfaces*; W3C WCAG 2.2: 1.4.3, 2.5.8, 3.3.7; Apple HIG *Buttons*; Android *Core app quality*; Material *Typography*).
