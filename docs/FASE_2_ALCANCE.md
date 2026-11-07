# Fase 2 — alcance ajustado (decisiones de Juan David, 7-nov-2026)

Reemplaza el §7 del plan maestro (`29_PLAN_MAESTRO…`) para lo que falta. Decisiones registradas:

1. **Lo visual ya hecho no se toca.** Los «3 botones por rol» del inicio ya quedaron bien en la Fase 1.7. Lo nuevo se construye con lo que ya existe y con los mismos estándares (`ux/ESTANDARES_VISUALES.md`, tokens `--gw-*`, `.gw-*`).
2. **Calendario:** lo ven todos los roles del personal EXCEPTO digitador temporal y cliente. Cada tarjeta de evento muestra la información de la plantilla, organizada y bonita; puede ser larga (los días con un solo evento dejan espacio). Al dar clic en «Editar» sale todo como hoy.
3. **Configuración (solo super_admin y admin) → «Diseñar plantilla para eventos»:** dos pantallas con el estilo del editor de formularios web (arrastrar, mover, cambiar parámetros; sin tipografías):
   - **Vista de creación de evento:** qué información pide «Nuevo evento», en qué orden, cuáles campos son obligatorios.
   - **Vista de calendario:** de todos los campos posibles, cuáles salen en la tarjeta y dónde (izquierda, derecha, abajo…). Solo visual.
4. **Tipos de campo:** texto corto · texto largo · lista desplegable abierta (el admin define las opciones) · dinero · número · comercial (lista de comerciales existentes) · coordinador (lista de coordinadores) · fecha y hora con título propio (inicio, fin, montaje, hora montaje, inicio/fin de registro…) · país (todos los países, con búsqueda escribiendo) · ciudad (las del país elegido; si no está, texto libre) · dirección con mapa (escribir o marcar con clic) · contacto del evento (texto + teléfono) · colores de pañoletas (los colores guardados, igual que en el formulario) · inventario (el admin define los «tipos de inventario» —X, Y, Z— y cada uno con cantidad y un tipo/referencia en lista) · interruptores del evento (reconocimiento facial, control de inventario, control de áreas, ruleta…). `Código` y `Nombre` ya existen.
5. **Los interruptores de «Nuevo evento» y los de «Parámetros del evento» son lo mismo:** una sola fuente de datos, dos pantallas. Si no se definen al crear, se definen después en Parámetros.
6. **Crear evento desde «Eventos»** además de desde «Clientes»: el mismo formulario, pero pide elegir el cliente en una lista con buscador de texto. Desde un cliente, el cliente ya viene asignado.
7. **Apellido en «Registrar nuevo»:** se detecta solo al cargar la base. Si la base usó «nombre» con nombre y apellido juntos (sin columna de apellido o vacía), el apellido NO es obligatorio y se puede desmarcar; si usó nombres y apellidos por separado, ambos son obligatorios.
8. **Páginas públicas:** siguen congeladas.
9. **VM antigua:** se cierra lo que no se use en Google Cloud; si no hace nada, se puede borrar (con instantánea final y revisión previa).

## Relación con otras fases
Los puntos 3–6 adelantan lo que el plan tenía en la Fase 5 (ficha configurable, asistente de creación, inventario por cantidad). Al cerrar la Fase 2 se actualiza la Fase 5 para no duplicar.

## Respuestas del 7-nov-2026 (10:17)
- **Mapa:** gratis (OpenStreetMap con búsqueda de direcciones); Google Maps queda para después si hace falta.
- **Eventos existentes:** NO se migran todavía. Primero se construye la plantilla; cuando Claude ya la lea y entienda qué va en cada campo, se hace la migración de los eventos actuales.
- **Campos base:** código, nombre y cliente siempre obligatorios y no quitables; la obligatoriedad del resto la decide el admin.
- **Calendario, quién:** super_admin, admin, comercial y coordinador. Digitador (no existe digitador fijo por ahora) y cliente no lo ven.
- **Calendario, flujo:** clic en un evento abre un cuadrito superpuesto con las mismas acciones de la fila de Eventos/Clientes (Editar, Exportar, Cambiar estado, Ingresar); clic fuera lo cierra. Mismos permisos de siempre: la acción que el rol no puede (p. ej. Eliminar) no aparece.
- **Países y ciudades:** lista fija dentro de la plataforma, sin servicios externos.
- **Orden de entregas:** (1) calendario con los datos actuales y el cuadrito de acciones; (2) plantilla de creación y de calendario; (3) crear evento desde Eventos con selector de cliente; (4) mapa e inventario; después, migración de eventos existentes.

## Datos de países y ciudades

**Qué es.** Lista fija dentro de la plataforma (sin servicios externos) para los campos «País» y «Ciudad» de las plantillas de evento. Decisión de Juan David: País = lista de todos los países que se puede filtrar escribiendo; Ciudad = por defecto las ciudades del país elegido, y si no está, texto abierto.

**Dónde está.**
- `static/data/geo.json`: 202 países (los 195 reconocidos + Kosovo, Taiwán, Puerto Rico, Hong Kong, Macao, Aruba, Curazao). Cada uno con código ISO alfa-2, nombre en español, nombre en inglés (para buscar) y ciudades ordenadas por relevancia. Colombia trae más de 300 municipios (capitales departamentales y municipios de más de ~15.000 habitantes, más los de los cupos: Bogotá, Girardot, Montelíbano, Boyacá...). El resto: capital y ciudades principales.
- `static/js/gw-geo.js`: lógica pura (búsqueda sin acentos ni mayúsculas, orden: empieza igual, luego palabra, luego contiene; límite 50). `GWGeo.searchCountries(q)`, `GWGeo.citiesOf(code)`, `GWGeo.searchCities(code, q)` devuelven `[{value,label}]` (país: value = código). Se carga con `GWGeo.load("{{ url_for('static', path='data/geo.json') }}")`; si la ciudad no está (`GWGeo.isKnownCity`), el campo queda como texto abierto.
- `app/geo.py`: la misma normalización y consultas para validar en el servidor.

**Por qué JSON estático y no endpoint.** Son datos públicos sin información personal; `url_for('static')` agrega `?v=` y el navegador/CDN lo cachea (~36 KB). Un endpoint exigiría sesión, base y respuesta por país sin ganar nada.

**Fuente.** Elaborado a mano con conocimiento general, noviembre 2026; revisar. Colombia parte de GeoNames (`app/cities_by_country.json`, ya en el repo) depurado a mano (se quitan localidades como «Kennedy», se corrigen nombres).

**Cómo actualizar.**
1. Editar la fuente en `scripts/geo_fuente/`: `paises.txt` (`CÓDIGO|español|inglés`), `ciudades_*.txt` (`CÓDIGO: ciudad; ciudad; ...`, las más importantes primero) y `colombia.py` (`QUITAR` / `AGREGAR`).
2. `python scripts/build_geo_data.py` (regenera `static/data/geo.json`; no necesita red).
3. `python -m pytest -q tests/test_geo_data.py` y `node tests/js/gw_geo_check.js`.
4. Commit de la fuente y del JSON juntos.

## Contrato de la tarjeta del calendario
(Entrega 1 de la Fase 2, rama `f2/calendario`.) El calendario separa **qué se muestra** de **cómo se dibuja**, para que el diseñador de plantilla («Vista de calendario») solo tenga que producir un `layout`.

- **Función:** `renderCalendarCard(event, layout)` en `static/js/calendar-card.js` (archivo aislado, sin DOM ni red; devuelve HTML ya escapado). El contrato completo está en el comentario al inicio de la función; aquí el resumen.
- **`event`:** el mismo objeto que entrega `GET /api/events/calendar` (`_serialize` de `app/routers/events.py`).
- **`layout`:** `{ "fields": [ { "key": "...", "zone": "left|right|bottom", "label": true|false|"título propio" }, ... ] }`. El orden del arreglo es el orden dentro de cada zona. `null` o forma inválida → `DEFAULT_LAYOUT`.
- **Claves de campo hoy** (`FIELD_CATALOG`): `name, event_code, tenant_name, place, address, country, dates, setup_date, times, setup_times, status, commercial_name, coordinator_name, bandana_color_name, notes`. Una clave desconocida se ignora sin error; un campo sin valor en ese evento no se pinta (ni su título). Cuando existan campos nuevos de la plantilla (§4 de este documento) se agregan al catálogo con su `value(event)`.
- **Por defecto:** izquierda = nombre, código, cliente, lugar; derecha = fechas, horario, estado; abajo = comercial, coordinador, pañoleta.
- **Dónde se usa:** la tarjeta grande de la vista **Día** (`eventChip(e, true)` en `templates/calendario.html`, variable `CARD_LAYOUT`, hoy `null`). Mes y Semana siguen mostrando solo el nombre del evento.
- **Cómo lo conectará el diseñador:** que la página cargue el `layout` guardado y lo asigne a `CARD_LAYOUT` antes de `loadAndRender()`.
- **Pruebas:** `tests/js/calendar_card_check.js`.

### Cuadrito de acciones del evento (calendario)
Al tocar un evento se abre un cuadrito anclado (hoja inferior en celular) con las acciones de la lista de Eventos/Clientes y sus mismos permisos: Ingresar y Editar (todos), Cambiar estado (todos; «En proceso → Creado» pasa por «Devolver a Creado», solo admin/super_admin), Exportar (solo super_admin), Eliminar (admin/super_admin). Código: `static/js/event-actions.js` (`EventActions.actionsFor` es la regla de permisos, probada en `tests/js/event_actions_check.js`). Acceso a `/calendario`: coordinador, comercial, admin y super_admin (mínimo «coordinador»; digitador y cliente no).
