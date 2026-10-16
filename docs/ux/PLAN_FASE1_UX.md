# Plan de Fase 1 de UX (después del piloto) — solo documento, sin código

Punto de partida: la página pública `/aceptar` (Montserrat, fondo claro, tarjeta blanca, botones dorados), que ya es la más limpia de la app. Diagnóstico en `docs/ux/ANALISIS_FLUJO_Y_UX.md`.

## 1. Sistema visual con *tokens* (variables CSS en un solo archivo)
| Token | Valor propuesto | Por qué |
|---|---|---|
| Cuerpo | **16 px**, interlineado **24 px** | hoy 320 de 441 tamaños son < 14 px |
| Escala | 14 · 16 · 20 · 24 · 32 px (solo esas) | menos tamaños sueltos |
| Texto de ayuda | 14 px mínimo, color `#5c5f6b` (≥ 5,9:1) | reemplaza `#777`, `#888`, `#999`, `#aaa`, `#bbb` (no llegan a 4,5:1) |
| Avisos | rojo `#a12631` (7,4:1), ámbar `#8a5a00` (5,9:1), verde `#1e7a3a` | `#b26a00` no llega |
| Marca | azul `#0a0e2e`; dorado `#D4AF37` **solo como fondo** con texto oscuro | el dorado como texto da 2,1:1 |
| Espaciado | 4 · 8 · 12 · 16 · 24 · 32 px | consistencia |
| Objetivos táctiles | **≥ 24 × 24 px** (WCAG 2.5.8); en la puerta y celulares, 44–48 px (Apple HIG / Android) | casillas de 18 px hoy |
| Íconos | set **SVG** con `aria-hidden` y texto visible al lado, en vez de emoji | los emoji cambian según el equipo y los lectores de pantalla los leen en voz alta |

Se aplica por capas: primero `/aceptar` y la puerta (público), luego Parámetros, Registro y Adjuntar Base de Datos.

## 2. Parámetros en pestañas, un Guardar por pestaña
Pestañas: **General** · **Reconocimiento facial** · **Invitaciones** · **Escarapelas y certificados** · **Campos** · **Privacidad**.
- Cada pestaña tiene **un solo botón «Guardar»**, abajo y fijo; los interruptores que hoy guardan solos pasan a guardar con ese botón (o, si se quedan inmediatos, lo dicen: «se guarda al cambiar»).
- Aviso si se sale de la pestaña con cambios sin guardar (WCAG 3.3.7 *Redundant Entry*: no volver a pedir lo ya escrito).
- **Reconocimiento facial** reúne: Paso 0 (usa / no usa), Responsable, origen A/B, aceptación desde el celular, entrada con rostro, autoregistro del escáner, foto en la escarapela (super administrador). Revelación progresiva (NN/g): si «No usa rostro», el resto ni se muestra.
- **Invitaciones** reúne el envío masivo y «enviar el enlace al inscribirse por formulario», explicando la diferencia.

## 3. Acciones destructivas
En **Privacidad** (borrar rostros de una persona, del evento, supresión): confirmación con el nombre de lo que se borra y el efecto («no se puede deshacer»; «su registro de asistencia se conserva»), botón rojo con verbo concreto («Borrar el rostro»), nunca «Aceptar». Lo mismo para finalizar evento (ya hecho en Fase 0).

## 4. Menú del evento ordenado por su ciclo
1. **Preparar**: Parámetros · Adjuntar Base de Datos · Formularios · Escarapelas · Invitaciones
2. **Durante el evento**: Registro · Entrada con rostro · Áreas · Inventario · Ruleta
3. **Después**: Estadísticas · Certificados · Documentos · Legalizaciones · Usuarios
Cada tarjeta, una frase que diga **para qué sirve** (GOV.UK: una cosa por página; escribir para la tarea, no para el sistema).

## 5. Escritura de interfaces (GOV.UK, NN/g)
- Sin rutas, nombres de archivos ni de proveedores en pantalla (SMTP, Twilio, `.env`, `/kiosk/...`).
- Botones con verbos («Guardar invitaciones», «Enviar prueba»); mensajes de error que digan qué pasó y qué hacer.
- Interruptores (NN/g, *toggle switches*) solo para cambios que se aplican al instante; si hay que guardar, casillas.

## 6. Criterios de aceptación de Fase 1
- 0 textos < 14 px en el panel; 0 colores de texto < 4,5:1 (revisión automática en CI).
- 0 controles sin nombre accesible (revisión automática).
- Objetivos ≥ 24 px en el panel y ≥ 44 px en la puerta y `/aceptar`.
- Una sola fuente de verdad por ajuste (lista de la sección b del análisis cerrada).

## Referencias
NN/g: 10 heurísticas de usabilidad; *Progressive Disclosure*; *Toggle-Switch Guidelines*. GOV.UK Design System: *One thing per page*; *Writing for user interfaces*. WCAG 2.2: 1.4.3 Contraste mínimo, 2.5.8 Tamaño del objetivo (mínimo), 3.3.7 Entrada redundante. Apple Human Interface Guidelines: *Buttons*. Android: *Core app quality* (objetivos táctiles de 48 dp).
