# 15 · Usabilidad del digitador y del cliente: correcciones aplicadas (22-nov-2026)

Rol: desarrollador de front que aplica los hallazgos Alta/Media del reporte [`05`](05_usabilidad_digitador_cliente_publico.md), sin tocar
endpoints, `app/`, `_sidebar.html`, impresión ni textos legales. Rama `saas/revision-integral`; sin commit ni push de este agente.

## 1. Resumen en 5 líneas
1. Lo más grave del reporte 05 quedó cerrado: la ventana «Editar persona» ahora **dice** que guardar deja a la persona Registrada (y que se
   imprime la escarapela si la autoimpresión está activa), el botón se llama «Guardar y registrar» y el digitador tiene «Guardar sin registrar».
2. El digitador y el cliente ya **no ven el menú lateral de administrador** (ni la campana) en Control de inventario, Control de áreas, Turnos y
   Material de Golden: les queda «Elegir tarea» y «Salir». Las dos pantallas de TV nunca lo tuvieron.
3. «Imprimir», «Editar» y «⋯» miden **44 × 44 px** entre 901 y 1499 px (antes 40 × 40); el barrido de Registro sigue en OK (81 de 81).
4. El cliente lee quién le entrega el reporte; la pantalla de autorregistro tiene una salida para el personal; la campana en celular bajó de 76 a 44 px.
5. Lo que NO quedó resuelto del todo: la campana sigue siendo flotante para coordinador o superior en celular (moverla al encabezado toca
   `_sidebar.html`/`notifications.js`, fuera de mi área) y la regla `client_stats_download` existe pero **ningún código la hace cumplir**.

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | **Alta** | Editar + Guardar a alguien No registrado lo registraba (y autoimprimía) sin avisar. | `static/js/directory.js` (ventana «Editar persona» de `/kiosk/{id}/registro`) | Corregir una tilde acreditaba a quien no había llegado. | **Corregido.** Aviso amarillo dentro de la ventana: «Al guardar, esta persona queda Registrada en este evento [y se imprime su escarapela].»; botón «Guardar y registrar». **Digitador:** botón nuevo «Guardar sin registrar» (guarda los datos y no llama al cambio de estado ni abre impresión; no hizo falta ningún parámetro nuevo: el registro lo hacía una segunda llamada del navegador). **Coordinador o superior:** mismo aviso; al elegir «No registrado» en el selector el aviso se quita y el botón vuelve a «Guardar cambios». El valor por defecto «Registrado» (decisión del 23-sep-2026) no cambia. |
| 2 | **Alta** | El digitador veía el menú lateral completo en Inventario, Áreas, Turnos y Material de Golden. | `templates/kiosk_inventario.html`, `kiosk_areas.html`, `kiosk_turnos.html`, `kiosk_alistamiento.html` | Puertas cerradas que lo sacaban de su pantalla. | **Corregido** con el mismo patrón de `kiosk_registro.html`/`kiosk_select.html` (`staff_role not in ["digitador", "cliente"]` en la clase `has-sidebar` y en el `include`). Botón «Elegir tarea» (`/kiosk/{id}`) en el encabezado de la página para esos roles. `kiosk_tv.html` y `kiosk_turnos_tv.html` no incluyen el menú: sin cambio. |
| 3 | Media | La campana fija tapaba «Registrar» y tarjetas a 390 px. | `static/css/gw-notifications.css` | Flotaba donde va el pulgar. | **Corregido para digitador/cliente** (sin menú no hay campana). **Mitigado para coordinador+**: en ≤ 640 px es un círculo de 44 px pegado a la esquina (antes 76 px de ancho); la página ya deja aire abajo (regla F5-9). **Propuesto**: llevarla al encabezado (ver §4). |
| 4 | Media | Imprimir/Editar/⋯ de 40 × 40 px entre 901 y 1499 px. | `static/css/p-registro-puerta.css` | Bajo el mínimo táctil de 44 px. | **Corregido**: `var(--gw-tap)` en alto y ancho; la columna de acciones pasa de 18,5 a 19,25 rem (encabezado y fila). Medido a 390, 768, 1024, 1100, 1280, 1366, 1440, 1499 y 1920 px: mínimo 44 px, sin desplazamiento horizontal. La etiqueta con nombre sigue apareciendo desde 1500 px (no se cambió: a 1024 px no cabe sin cortar columnas). |
| 5 | Media | El cliente no puede descargar el reporte y nada se lo decía. | `templates/kiosk_estadisticas.html` | Tarea sin salida. | **Corregido** (texto): «Desde esta cuenta no se descarga el reporte. El reporte completo y la base final se los entrega su asesor comercial de Golden al cerrar el evento.» (visible también en la vista incrustada del cliente). El subtítulo ya no le promete «el reporte completo para descargar». Sin enlace: ver hallazgo 7. |
| 6 | Media | «Abrir autorregistro» dejaba al digitador sin forma de volver. | `templates/kiosk_autoregistro.html` | Quedaba atrapado con fila. | **Corregido**: al pie, plegado «Personal del evento» → «Volver al Registro» (dos toques, sin JavaScript). El enlace NO se ocultó al digitador: la ruta la abre cualquier cuenta del personal (`app/main.py`, `kiosk_autoregistro`) y la tableta de autoservicio suele abrirse con una cuenta de digitador. |
| 7 | Media (nuevo) | La regla de estado `client_stats_download` («El cliente puede descargar estadísticas e informe») se define en `app/event_rules.py` pero **no la consulta ninguna ruta ni plantilla**: el botón de exportar se oculta siempre al cliente y `GET /api/report` lo niega siempre. | `app/event_rules.py` 15, 27-36; `kiosk_estadisticas.html` | Un interruptor que promete algo que no ocurre; por eso la frase del cliente no enlaza ninguna opción. | **Propuesto** (backend, fuera de mi área): o se hace cumplir la regla o se retira de las reglas de estado. |
| 8 | Baja (nuevo) | El enlace «Volver al Registro» del autorregistro deja a quien lo toque en el Registro con la sesión del personal (igual que hoy la flecha Atrás del navegador). | `templates/kiosk_autoregistro.html` | En una tableta de autoservicio sin vigilancia, alguien del público podría llegar a la lista. Por eso va plegado. | **Propuesto**: pedir la contraseña del candado (`app/config_lock.py`) para salir del autorregistro. |

## 3. Qué se cambió en el código
- `static/js/directory.js`: aviso `#editModalRegNote`, botón «Guardar y registrar» / «Guardar cambios» según lo que hará el guardado, botón
  `#editModalSaveOnly` «Guardar sin registrar» (solo digitador y solo si la persona no está registrada), bandera `skipRegister`.
- `templates/kiosk_inventario.html`, `kiosk_areas.html`, `kiosk_turnos.html`, `kiosk_alistamiento.html`: menú lateral y `has-sidebar` solo para
  quien no es digitador ni cliente; botón «Elegir tarea» (`#kioskBackLink`) para ellos.
- `templates/kiosk_estadisticas.html`: nota `#clientReportNote` para el cliente y subtítulo sin la promesa de descarga.
- `templates/kiosk_autoregistro.html`: bloque plegado «Personal del evento → Volver al Registro».
- `static/css/p-registro-puerta.css`: botones de acción de 44 px entre 901 y 1499 px, columna de 19,25 rem, margen del aviso de Editar.
- `static/css/gw-notifications.css`: campana compacta en ≤ 640 px.
- `tests/test_usabilidad_digitador_2026-11-22.py` (nuevo, 6 pruebas de texto).

Comprobaciones: las 6 pruebas nuevas pasan; las 66 pruebas de texto que leen estos archivos quedan igual que antes de empezar (605-608 pasan;
los errores son `sqlalchemy` ausente en este entorno) salvo 3 fallos que aparecieron durante el trabajo y vienen de archivos de otros agentes
(`kiosk_parametros.html`, `usuarios.js`, `platform.py /instalar`); `node --check static/js/directory.js` y las 14 pruebas de `tests/js` que
cargan `directory.js` pasan; `ruff check .` limpio. Maqueta (puerto 8769, datos ficticios): las 6 pantallas cambiadas a 390, 768, 1024, 1366 y
1920 px sin desplazamiento horizontal y sin menú para el digitador; `reg_sweep.py` 81/81 OK (27 anchos × 3 variantes).

## 4. Qué queda pendiente y por qué
1. **Campana en el encabezado en celular** (1,5 h): hoy la crea `notifications.js` como botón flotante; ponerla junto a «Salir» exige tocar
   `_sidebar.html`/`notifications.js` y revisar los encabezados de todas las pantallas con menú. Solo con CSS no se puede sin tapar otra cosa.
2. **Decidir `client_stats_download`** (1 h si se retira; 3 h si se hace cumplir en `GET /api/report` y en la plantilla, con prueba).
3. **Salida del autorregistro con contraseña** (2 h, reutiliza el candado 0161).
4. **Visto bueno de Juan David al texto del cliente** (5 min): confirma que el reporte lo entrega el asesor comercial al cerrar el evento.
5. Hallazgos 9 a 19 del reporte 05 (textos y contingencia sin internet en Áreas/Inventario): sin cambios, siguen como allí se describen.

## 5. Qué NO se pudo comprobar
- Con servidor real: que «Guardar sin registrar» con datos cambiados haga solo el `PATCH /api/users/{id}` (en la maqueta se comprobó que sin
  cambios no sale ninguna petición y que el camino de registro no se ejecuta; las pruebas de `tests/js` del autoimpreso siguen pasando).
- Impresión física y cuadro de impresión de Chrome; nada de impresión se tocó (solo el tamaño del botón).
- La pestaña Estadísticas del cliente con gráficos (Chart.js viene de un CDN); la nota se verificó en el HTML servido.
- `kiosk_alistamiento.html` con datos (la maqueta no simula su API); se verificó estructura, menú y anchos.
- Staging: no se usó.

## 6. Consejo en corto y veredicto
- **Contrario:** «Guardar sin registrar» es un botón más en una ventana que debía ser simple; si en la puerta nadie lo usa, se quita y queda el aviso.
- **Primeros principios:** el botón dice lo que va a pasar; lo que el rol no puede hacer, no se muestra.
- **Expansionista:** la misma condición de rol sirve para cualquier pantalla nueva del quiosco; la prueba de texto ya lo exige en siete.
- **Forastero:** ahora entiendo qué hace «Guardar»; me sigue sobrando la campana flotante cuando soy coordinador en el celular.
- **Ejecutor:** subir a staging y probar con una tableta: Editar a un no registrado con y sin autoimpresión, e Inventario como digitador.

**Veredicto:** los dos hallazgos Altos están corregidos y fijados con pruebas; los Medios quedan corregidos o mitigados sin tocar el servidor.
**UN siguiente paso:** que Juan David pruebe en staging «Editar → Guardar sin registrar» y «Guardar y registrar» con una cuenta de digitador.
