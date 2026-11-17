# Almacén (bodega) — Pieza 1: controles, unidades con serial, QR y etiquetas

Rama `almacen/p1-catalogo`, nacida de `legalizaciones/sobre-crm` (`71eaa69`, cabeza de Alembic `0147`). Plan y decisiones: `claude/58_PLAN_ALMACEN_2026-11-17.md` y `claude/59_PASO0_ALMACEN_INFORME_2026-11-17.md` (proyecto de Claude).
Nada en `main`, nada en producción.

## Qué hay
| Pieza | Dónde |
|---|---|
| Lógica pura (tipos de control, las 43 filas del checklist GEYL, códigos QR, validaciones) | `app/almacen.py` |
| Columnas nuevas del catálogo (`tracking`, `checklist_row`, `is_consumable`, `qr_code`) y tabla `inventory_units` | `app/models.py`, migración `0148_almacen_unidades` (solo agrega) |
| API `/api/almacen/*` (meta, productos, unidades, archivar/restaurar, `scan`, `labels`) | `app/routers/almacen.py` |
| Pestaña «Almacén» dentro de `/inventario` | `templates/_almacen_panel.html`, `static/js/almacen-page.js`, `static/css/gw-almacen.css` |
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

## Siguiente
Pieza 2: salida/entrada por escaneo a un evento (`inventory_movements`), casilla «alistado» y «pendientes por devolver». Pieza 3: novedades y bloqueo. Pieza 4: Excel `.xlsx` igual al formato GEYL (hoja «Instrucciones Básicas» incluida).
