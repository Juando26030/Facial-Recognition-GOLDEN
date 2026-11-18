# Almacén (bodega) — Piezas 1 y 2: controles, unidades con serial, QR, etiquetas, salidas/entradas y alistado

Rama `almacen/p1-catalogo`, nacida de `legalizaciones/sobre-crm` (`71eaa69`, cabeza de Alembic `0147`). Plan y decisiones: `claude/58_PLAN_ALMACEN_2026-11-17.md` y `claude/59_PASO0_ALMACEN_INFORME_2026-11-17.md` (proyecto de Claude).
Nada en `main`, nada en producción.

## Qué hay
| Pieza | Dónde |
|---|---|
| Lógica pura (tipos de control, las 43 filas del checklist GEYL, códigos QR, validaciones) | `app/almacen.py` |
| Columnas nuevas del catálogo (`tracking`, `checklist_row`, `is_consumable`, `qr_code`) y tabla `inventory_units` | `app/models.py`, migración `0148_almacen_unidades` (solo agrega) |
| API `/api/almacen/*` (meta, productos, unidades, archivar/restaurar, `scan`, `labels`) | `app/routers/almacen.py` |
| Pestaña «Almacén» dentro de `/inventario` | `templates/_almacen_panel.html`, `static/js/almacen-moves.js`, `static/css/gw-almacen.css` |
| Ventana de impresión de etiquetas QR (`/inventario/etiquetas`) | `templates/almacen_etiquetas.html`, `static/js/almacen-etiquetas.js`, `static/css/gw-almacen-etiquetas.css` |
| Interruptor `ALMACEN_ENABLED` | `deploy/gcp/config.sh` (staging 1, producción 0), `deploy.sh` (solo servicio `web`), `manual_deploy.sh` (lo muestra) |
| Pruebas | `tests/test_almacen_logica.py` (sin base), `tests/test_almacen_api.py` (Postgres) |

## Decisiones
- **Un solo catálogo:** se amplía `inventory_products` (unificado el 9-nov); no hay catálogo paralelo. Los productos que ya existen quedan «por cantidad».
- **Tres controles:** *serial* (un QR por equipo; número visible consecutivo por producto que NUNCA se reutiliza), *modelo* (un QR por modelo, p. ej. impresoras) y *cantidad* (un QR por tipo).
- **Códigos:** `GW` + 6 caracteres, solo mayúsculas y números, sin 0/O/1/I/L ni símbolos: el lector USB escribe como teclado y los símbolos cambian con la distribución. El QR lleva SOLO el código.
- **Checklist:** cada producto elige una de las 38 filas de inventario del formato GEYL (las 5 filas de verificación —listado de personal, teléfonos, listado de equipos, Plan B, acarreo— no suman inventario y se llenan a mano). Necesario = lo que pide el evento; Cantidad = lo despachado; OK S/N = casilla «alistado» (Pieza 2).
- **Consumibles:** almacén los repone y los cuenta a mano.
- **Etiquetas:** página propia para el rollo de 62 mm de la Brother QL-800 (alto 29 / 40 / 62 mm, por confirmar con prueba física). NO usa ni cambia la impresión compartida de escarapelas ni sus parámetros inamovibles.
- `/api/almacen` queda cerrada para el coordinador temporal (`tests/test_coordinador_temporal.py` lo verifica) y `/inventario/etiquetas` cae bajo `/inventario`.
- Un producto con unidades no se puede eliminar del catálogo (solo archivar).

## Orden de despliegue (importante)
La rama contiene lo que hay en `legalizaciones/sobre-crm` (4 commits sin desplegar al 17-nov: `1bbccff`, `28d598a`, `8010347`, `71eaa69`) y por eso desplegarla a staging también lleva eso. La cabeza de Alembic pasa de `0147` a `0148`. Para producción el orden es CRM (doc 57) → legalizaciones → almacén.

## Pruebas (estado real al entregar)
- Ejecutadas: `tests/test_almacen_logica.py` (10), `tests/test_cadena_migraciones.py`, candados de texto (`test_visual_global`, `test_design_system`, `test_csp_trinquete`, `test_impresion_parametros_fijos`, `test_fase10_a_texto`), `ruff check .`, `node --check` de los dos JS y el análisis de las tres plantillas.
- **SIN EJECUTAR** (necesitan Postgres y las librerías de Python): `tests/test_almacen_api.py`, `tests/test_coordinador_temporal.py` con la familia nueva. La primera prueba real es staging.

## Pieza 2 — salidas, entradas, alistado y fotos (rama `almacen/p2-movimientos`, nacida de `almacen/p1-catalogo` `3b9ad70`)
Plan: `claude/60_PLAN_ALMACEN_PIEZA2_2026-11-17.md`. Migración `0149_almacen_movimientos` (solo agrega; cabeza de Alembic pasa de `0148` a `0149`).

| Qué | Dónde |
|---|---|
| Reglas puras (salida, entrada, anulación, alistado, tablero, 43 filas) | `app/almacen_moves.py` |
| Fotos del elemento: validación, re-codificación a JPEG ≤ 1280 px sin metadatos | `app/almacen_photos.py` |
| Tablas `inventory_movements` (solo se agrega; anular marca `voided_*`), `event_checklist_rows`; columnas `inventory_units.event_id`, `inventory_products.photo_key` | `app/models.py`, migración 0149 |
| API: `POST /api/almacen/move`, `POST /api/almacen/movements/{id}/void`, `GET /api/almacen/events/{id}/board`, `PUT /api/almacen/events/{id}/checklist/{fila}`, `POST/GET/DELETE /api/almacen/products/{id}/photo` | `app/routers/almacen.py` |
| Pestaña «Almacén»: «Salidas y entradas por evento» (un solo buscador de evento, lector USB y cámara QR) y «Checklist del evento» | `templates/_almacen_panel.html`, `static/js/almacen-moves.js`, `static/js/qr.js` (compartido) |
| «Administrar catálogo» (único lugar para crear): control de bodega, foto, botón «Objetos y QR», QR visible, etiquetas | `templates/_inventory_catalog_admin.html`, `static/js/almacen-catalog.js` (se engancha a `inventory-catalog-admin.js` por eventos `gw:*`) |
| Pruebas | `tests/test_almacen_moves.py` (sin base, 16), `tests/test_almacen_api.py` (Postgres) |

Decisiones (Juan David, 17-nov-2026):
- **Un solo lugar para crear (cambio pedido el 17-nov, tras ver staging):** se quitó «Nuevo elemento» de la pestaña Almacén; el producto del catálogo es el TIPO («Portátil Lenovo») y se crea en «Administrar catálogo», con los campos de bodega en el mismo formulario. Cada tarjeta de tipo con serial tiene «Objetos y QR»: ahí se agregan los objetos reales y cada uno recibe su QR, mostrado en un campo (solo lectura, se selecciona al tocarlo). Los de modelo/cantidad muestran el QR del tipo en la tarjeta. La pestaña Almacén quedó solo para escanear, mover y el checklist.
- **Una lectura = un movimiento.** Salida: evento + QR (+ cantidad si es por modelo/cantidad). Entrada de un equipo con serial: el sistema deduce el evento donde estaba; por modelo/cantidad hace falta evento y cantidad.
- **Contadores:** cada movimiento actualiza `qty_out` / `qty_returned` de `event_inventory_items` en la misma transacción y pasa por `check_balance` (nada se guarda si no cuadra). NECESARIO = asignado − extras; CANTIDAD = `qty_out`.
- **Salir más de lo pedido (o algo que el evento no pidió) — cambio del 18-nov:** NO se bloquea. El movimiento se registra normal y la pantalla muestra el aviso «Falta asignar … al evento» (la API devuelve `warning`). El sobrante sube `qty_assigned` (para no romper el cuadre) pero queda como `extra` del movimiento y no cuenta como NECESARIO; `reason` y `plan_b` siguen aceptándose como datos opcionales (la pantalla ya no los pide).
- **Consumibles:** al salir cuentan como consumidos al instante; no tienen entrada.
- **Estados del evento:** salidas con «creado» o «en proceso»; entradas también con «finalizado»; archivado, nada.
- **Alistado por fila del checklist** (incluye las 5 filas de verificación manual) con observación por fila. Un elemento sin fila del checklist avisa en el tablero que no saldrá en el Excel.
- **Anular:** solo el último movimiento de ese equipo (o de ese producto en el evento); queda quién y cuándo. Un equipo devuelto con daño vuelve «disponible» hasta la Pieza 3.
- **Fotos del elemento:** opcionales al crearlo, reemplazables/quitables después; JPEG reducido y sin datos de ubicación. La foto de la novedad por daño va en la Pieza 3.

Pruebas Pieza 2: ejecutadas `tests/test_almacen_moves.py` + `tests/test_almacen_logica.py` (26), `test_design_system`, `test_visual_global`, `ruff check .`, `node --check` y análisis de las plantillas. **SIN EJECUTAR** (necesitan Postgres): `tests/test_almacen_api.py`.

Ajustes del 18-nov-2026 (pedidos por Juan David tras probar en staging):
- Se quitó «Categorías» de «Administrar catálogo» (y el selector de categoría del producto) cuando Almacén está activo; con `ALMACEN_ENABLED=1`, `inventory.check_balance` ya no pide categoría para pasar un evento a «En proceso». Con el interruptor apagado todo queda como siempre.
- Se quitó «Modo escáner» (y `almacen-page.js`); `/api/almacen/scan` sigue existiendo.
- Un solo buscador de evento (como el de Inicio: sin tildes, «N de M eventos», tarjetas con «Elegir este evento», «Cambiar evento»).
- «Escanear código» tiene el botón de cámara de siempre (`qr.js`, el mismo de Registro/Áreas/Inventario); la ventana sigue abierta y muestra el resultado y el aviso de cada lectura.

Plegar y desplegar (18-nov-2026, copiado del patrón de la plataforma: `<details class="gw-form-group">`, buscadores `type="search"` con «N de M» y la barra «Plegar todo / Desplegar todo» que pone `gw-ui.js` en cada pestaña con 2 o más bloques):
- Almacén: «1. Evento» es un bloque plegable (con buscador y lista); al elegir un evento se pliega y deja su nombre en el título, y se despliega para cambiarlo. El checklist se divide en «Filas del checklist», «Fuera de bodega» y «Últimos movimientos» (este cerrado; con contador).
- Administrar catálogo: el formulario de crear/editar es un bloque plegable (se abre solo al pulsar «Editar») y la lista de tipos tiene buscador por nombre o SKU (sin tildes).

## Siguiente
Pieza 3: novedades y bloqueo (con **foto** del daño y texto; un elemento en novedad no se asigna a un evento hasta que Almacén lo deje «disponible»; disponibilidad = existencias − novedades abiertas). Pieza 4: Excel `.xlsx` igual al formato GEYL (hoja «Instrucciones Básicas» incluida). Después: alertas de equipos sin devolver y reportes de uso.
