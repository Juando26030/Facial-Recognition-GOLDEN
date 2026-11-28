# Lecciones visuales (11-nov-2026) — cómo se hace lo visual en Orum

Complementa `ESTANDARES_VISUALES.md` (las 12 reglas de oro y los tokens, que siguen mandando). Esto es lo aprendido al arreglar «se descuadran los botones y el texto» con la ventana un poco más chica.

## 1. Qué pidió Juan y por qué importa
Los operadores trabajan con el navegador a ~80–90 % de zoom o con la ventana no maximizada (1000–1500 px). Con la barra lateral (~276 px) el contenido útil queda en 700–1200 px. Una pantalla «solo para escritorio» o «solo para celular» no sirve: debe verse bien en TODOS los anchos intermedios.

## 2. Regla nueva: la fila decide por el ancho de SU CONTENEDOR, no de la ventana
- Listas en filas/tablas (Formularios, Usuarios, Staff, Cuentas de cobro, `.gw-list__item`): en vez de `@media (min-width: …)` usar `container: nombre / inline-size` en la caja de la lista y `@container nombre (min-width: …)` para el modo «fila ancha».
- Umbrales usados: Usuarios `1160px` (y `1400px` para staff ancho); Formularios `1240px` (con una variante compacta entre 1240 y 1349 px). Se eligieron midiendo con el arnés: más bajo desbordaba 18 px a 1440 px con la columna «Inscripciones/Cupo» ensanchada.
- Por debajo del umbral la fila se apila como tarjeta (`grid-template-columns: minmax(0,1fr)`): nada de desplazamiento lateral.
- **Cuidado:** `container-type` crea contención de layout; NO ponerlo en `.gw-page` ni en ancestros de elementos `position: fixed`. Se pone en una caja envolvente específica (`.gw-rowsbox`, `#body.gw-cards`).
- `.gw-list__item > :not(:first-child) { flex: none; max-width: 100%; }` en `design-system.css`: los botones nunca se encogen ni se salen de la fila.
- Columnas de grid con `minmax(<mín>, <máx>)` y mínimos en `rem` (p. ej. acciones `minmax(20rem, 36rem)`, cupo `minmax(9.5rem, …)`); siempre `min-width: 0` en hijos con texto largo.

## 3. Otras decisiones de esta etapa
- «(opcional)» en los formularios públicos va en **negrilla** (`font-weight:700`, sin opacidad) para que no se confunda con «obligatorio» (`form-render.js`, constante `OPTIONAL`). Cambiar esa línea obliga a renovar el hash de `tests/test_publico_congelado.py` (las páginas públicas están congeladas a propósito).
- Credenciales que se muestran una sola vez (cliente temporal): panel `.gw-cred` con filas usuario/contraseña, botón «Copiar» por fila (`data-cred-copy`) y botón «Ya las copié» que cierra y borra el texto de pantalla.
- Archivos descargables dentro de formularios de edición: el campo se reemplaza por un botón `.gw-btn--ghost .gw-btn--sm` «Descargar <nombre>» y una pista `.gw-hint`; se retira el `<input>` para no guardar el texto de vuelta.
- Botones por columna en barras de herramientas: usar `.gw-btn--secondary .gw-btn--sm` dentro de `.gwe-inline-help`; el texto dice el efecto exacto («Descargar todos: PDF ARL (ZIP)»).
- Mensajes: español corto, con el número que importa («Se están cargando a la base las 12 inscripciones que ya estaban»).

## 4. El arnés para revisar pantallas sin base de datos (`scripts/visual_harness/`)
- `server.py` renderiza las plantillas Jinja con datos simulados (`mocks.py`) y sirve `static/`; `pages.py` lista las pantallas; `shoot.py` toma capturas con Playwright en varios anchos (1000, 1100, 1280, 1500, escritorio), claro/oscuro, y **detecta desbordes horizontales**, errores de consola y objetivos táctiles chicos.
- Uso típico (Playwright y Chromium ya están instalados en el entorno de Claude):
  ```
  REPO=/ruta/al/repo python3 scripts/visual_harness/server.py 8765 &
  python3 scripts/visual_harness/shoot.py            # escribe out/*.png y reporta DESBORDE / ERR
  ```
- Limitaciones conocidas: a veces `kiosk_usuarios` marca `list.filter is not a function` y `kiosk_parametros` `reading 'forEach'` por falta de datos simulados (es del arnés, no de la app); `cuentas_cobro` a 1000 px reportó 38 px de desborde en el botón de acciones (revisar con datos reales antes de darlo por bueno).
- Para ver una pantalla real de staging/producción: el navegador integrado de la app con la sesión que deja abierta Juan.

## 5. Lista de chequeo antes de entregar una pantalla
1. Anchos 1000 / 1100 / 1280 / 1500 / escritorio, sin desborde horizontal.
2. Claro y oscuro (`.gw-no-theme` en lo que se imprime).
3. Solo tokens `--gw-*` y clases `.gw-*`; ningún color/tamaño suelto; `url_for('static', …)`.
4. Textos ≥ 14 px, objetivos táctiles ≥ 44 px, un solo botón principal.
5. `showToast/showConfirm/showPrompt`, sin `onclick` inline, delegación de eventos.
6. Correr `tests/test_design_system.py` (los 2 fallos previos por «rgba(» en un comentario CSS son anteriores a esta etapa).
