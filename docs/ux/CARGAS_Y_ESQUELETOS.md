# Cargas y esqueletos (9-nov-2026)

Pedido de Juan David: *«agrega skeleton loaders a todos los lugares donde aplique y animaciones de carga funcionales para que en ningún momento, en ningún botón o acción, se pueda pensar que no funcionó el botón sino que está cargando»*. Aplica a toda la plataforma.

Todo vive en **`static/js/gw-carga.js`** (sin dependencias), en la sección «Carga visible» de **`static/css/design-system.css`** y en el macro **`templates/_gw_skeleton.html`**. Prueba de la lógica: `node tests/js/gw_carga_check.js`.

## 1. Cómo funciona (no hay que hacer nada en cada pantalla)

`gw-carga.js` se carga **de primero y sin `defer`** en `_gw_head.html`, así que está en todas las pantallas del personal y en las de contacto/expositor/turno/entrega que usan esa cabecera. Envuelve `fetch` y `XMLHttpRequest` antes de que la pantalla pida sus datos.

| Qué pasa | Qué se ve |
|---|---|
| La persona pulsa un botón (`button`, `.gw-btn`, `[role=button]`, `input[type=submit\|button]`, `a[data-gw-action]`) o envía un formulario, y en el siguiente segundo arranca una petición | Ese botón queda con `aria-busy="true"` y una rueda hasta que terminan **todas** sus peticiones (contador por botón), con un mínimo de 300 ms para que no parpadee. Un segundo clic o Enter sobre él se ignora (no hay doble envío). |
| El botón pulsado ya no está (la confirmación de `showConfirm` se cerró) | La rueda va al botón que abrió la confirmación (p. ej. «Archivar»), si sigue a la vista. |
| La petición nace de otro gesto (Enter en un buscador, cambiar un filtro o una casilla, escribir con autoguardado, abrir una pestaña) o de la carga de la pantalla | Barra dorada delgada arriba (`.gw-loadbar`, `role="progressbar"`) si tarda más de 400 ms; las rápidas no la muestran. |
| Se sigue un enlace o se envía un formulario clásico | Barra arriba (y el botón ocupado) hasta que la página cambia; se apaga sola a los 10 s (descargas) y al volver con «Atrás». Los enlaces a `/api/…` y a archivos (`.xlsx`, `.pdf`, `/export`…) no la encienden. |
| Un botón sin red (abrir una ventana, alternar algo) | Nada: nunca queda ocupado. |

**Rueda en cualquier botón.** En `.gw-btn` sale a la izquierda del texto (como siempre). En los demás botones el texto se vuelve transparente y la rueda queda centrada con el color que tenía el texto (`--gw-busy-c`), así el botón **no cambia de tamaño** y no se toca su contenido (solo atributos: se respeta la regla de no mutar el subárbol de `e.target`). Funciona en modo oscuro (tokens). Con «reducir movimiento» la rueda y la barra no se mueven: solo laten (opacidad).

**`GW.busy(boton, trabajo)`** sigue siendo la forma explícita (bloquea el doble clic aunque el trabajo no use la red y pasa a «Sigue trabajando…» a los 8 s); ahora usa la misma marca visual. Si un botón ya tiene `aria-busy` (GW.busy, `setButtonLoading`, la pantalla), la carga automática no lo toca.

### Lo que NUNCA enciende la carga (sondeos)
- Lo que corre dentro de `setInterval` (incluido `GW.poll`) y de un `setTimeout` de **2 s o más** (sondeos encadenados de Turnos, TV, turno público; reintentos).
- Los refrescos de `GW.onResume` (al volver de la inactividad).
- Peticiones con encabezado `X-Gw-Passive: 1` o `keepalive`, y `/health`, `/ready`, `/api/session/*`.
- A mano: `GW.quiet(() => fetch(...))`.

### Excepciones por botón
- `data-gw-busy-off` en el botón (o un contenedor): no se marca nunca (la campana lo usa).
- Pestañas (`role="tab"`), desplegables y menús (`aria-expanded`, `aria-haspopup`, `aria-pressed`): no se marcan, para poder volver a pulsarlos (cerrar); su carga se ve en la barra o en el esqueleto del contenido.

## 2. Esqueletos

El contenedor **nace** con la forma de lo que va a llegar, en vez de vacío o «Cargando…». Clases: `table` (filas `<tr>`), `cards` (tarjetas, para `.gw-cards`), `list` (filas con punto), `stats` (cifras), `block` (gráfica, calendario o vista previa) y `text` (líneas). Llevan un texto solo para lectores de pantalla (`role="status"`).

En la plantilla (sin esperar al JavaScript):
```jinja
{% from "_gw_skeleton.html" import skeleton %}
<tbody id="exBody">{{ skeleton('table', rows=4, cols=4, label='Cargando expositores…') }}</tbody>
<div id="body" class="gw-cards">{{ skeleton('cards', rows=3, label='Cargando formularios…') }}</div>
```
En JavaScript (al recargar, filtrar o abrir algo):
```js
GW.skeleton(tbody, { kind: 'table', rows: 6 });           // las columnas se cuentan del <thead>
el.innerHTML = GW.skeleton.html({ kind: 'cards', rows: 3, label: 'Cargando…' });
GW.skeleton.error(el, { title: 'No se pudo cargar', text: '…' });   // .gw-state--error con «Reintentar» (recarga); { retry: false } sin botón
```
La pantalla reemplaza el esqueleto al pintar sus datos (`innerHTML = …`). Si el archivo JS también se usa donde no hay `gw-carga.js`, se escribe con respaldo: `window.GW && GW.skeleton ? … : '<texto de antes>'`.

**Red de seguridad:** si una petición falla (sin red o error 5xx) y, cuando ya no queda nada en curso, sigue un esqueleto **a la vista**, se cambia por el estado de error con «Reintentar». Un esqueleto dentro de una pestaña cerrada no se toca. Nunca queda un esqueleto eterno por un fallo de red; para errores 4xx cada pantalla muestra su propio mensaje (como siempre).

### Para una pantalla nueva
1. Incluir `_gw_head.html` (ya trae todo).
2. Cada contenedor que se llena desde la API nace con `skeleton(...)` de la forma correcta.
3. En el `catch`, `.gw-state--error` (o `GW.skeleton.error`) con qué hacer; nunca dejar el esqueleto.
4. Los sondeos: `GW.poll` o `setInterval` (ya quedan callados). Un sondeo con `setTimeout` corto (< 2 s) o un `fetch` en segundo plano justo después de un clic: `GW.quiet`.
5. Nada más: los botones se marcan solos.

## 3. Pantallas cubiertas

- **Esqueleto inicial y al recargar:** Inicio (mis eventos), Eventos, Calendario, Clientes (y eventos de cada cliente), Staff, Configuración (Estados, Alertas, Catálogo de inventario), Usuarios del evento, Formularios y plantillas, editor de formularios (respuestas, accesos de cliente, códigos de descuento), Estadísticas del formulario, Documentos, Legalizaciones, Áreas (presencia), Inventario del evento (ítems y entregas), Inventario global (lista y plan por evento), Servidor local, Sincronización, Gastos (infraestructura y análisis de eventos), Cuentas de cobro, Expositores, Estadísticas del evento (cifras, gráficas, gráficas por variable, informe de tiempos), Certificados, Ruleta (enlace y sorteos), Nuevo evento, Plantilla del evento, Parámetros (solicitudes de reimpresión, puestos de impresión, formulario de persona, zonas, ítems, privacidad), Registro (lista de personas), Historial del evento, Diseñador de escarapela (plantillas guardadas), Exportar/importar evento (historial), campana de notificaciones, Turnos (consola y pantalla), carga de lista (eventos anteriores), Sistema.
- **Botón ocupado y barra:** todas las pantallas que incluyen `_gw_head.html` (todas las del personal, el diseñador de escarapela, y las de contacto, expositor, turno público, entrega, autorregistro e ingreso en espera).
- **Bug corregido (revisión visual):** en Eventos, la lista y la apertura por `?editar=` arrancan en `DOMContentLoaded`; ya no dependen de que los scripts de la ventana de edición carguen antes de que responda la API.
- **Configuración:** las secciones que cargan al abrir su pestaña ahora también cargan si se abre con el teclado o al recordar la última pestaña (`params-save.js` avisa `gw:tabshow`); antes quedaban vacías.

## 4. Páginas públicas congeladas (`tests/test_publico_congelado.py`)

Orden expresa de Juan David («en ningún botón»): se revisó cada una.
- **Ya mostraban su carga, no se tocaron:** envío del formulario público («Enviando…»), certificado («Buscando…», «Generando PDF…»), ruleta del proyector («Girando…»), páginas legales (sin botones con petición).
- **No la mostraban; se agregó SOLO el estado de carga** (atributo `aria-busy` + una rueda propia en su `<style>`, sin cambiar textos, validaciones ni flujo; además evita el doble envío): `form_public.html` («Continuar» del código de acceso y de la identificación), `aceptar.html` («Continuar», aceptar / no aceptar, «Enviar mi selfie»; los textos literales de la auditora no cambian) y `digital_badge.html` (Google Wallet). Huellas renovadas con el comentario «9-nov-2026, orden expresa de Juan David: estado de carga en botones».
- Estas páginas **no** cargan `gw-carga.js` ni el sistema de diseño (siguen aisladas, como exige la prueba).

## 5. Lo que no se tocó y por qué

- **Impresión** (`badge_print.html`, `impresion_usb.html`, parámetros de `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`): ni `gw-carga.js` ni esqueletos. La prueba lo verifica.
- **TV del evento** (`kiosk_tv.html`) y **pantalla del proyector** (`roulette_display.html`): pantallas de exhibición sin `_gw_head.html`; tienen sus propios estados.
- **Puerta con rostro** (`kiosk_rostro.html`): ya tiene su estado «verificando» propio (`.gw-rostro__msg--busy`); sus peticiones las lanza la cámara, no un botón.
- **Modo touch del Registro:** su diseño no cambia. La lista muestra filas esqueleto con las columnas de la tabla; el menú de cada fila (`.gw-menu__item`) conserva su propia rueda.
- **Textos cortos en línea** (p. ej. «Cargando…» del estado del formulario en el editor): se dejaron; un esqueleto de bloque no cabe en una línea de texto.
