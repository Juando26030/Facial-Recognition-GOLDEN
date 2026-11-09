# Fase 5 · Inventario con catálogo y roles Almacén / Contabilidad (rama `f5/d-inventario`)

Decisiones de Juan David (8-nov-2026, `FASE_5_DECISIONES.md`): el Super Admin define en Configuración las categorías y los productos del catálogo; esos productos aparecen como campos de
inventario al crear o editar un evento; el inventario es por cantidad con regla de cuadre; dos roles nuevos, Almacén y Contabilidad, por el sistema de roles múltiples.

## Qué hay
| Pieza | Dónde |
|---|---|
| Tablas `inventory_categories`, `inventory_products`, `event_inventory_items` | `app/models.py`, migración `0107_inventory_catalog` (`down_revision = 0104_pledge_health_flags`; el integrador la encadena) |
| Lógica pura + regla de cuadre (`check_balance`) | `app/inventory.py` |
| Lo que toca la base y la puerta «En proceso» | `app/inventory_svc.py` (gancho en `PATCH /api/events/{id}` de `app/routers/events.py`) |
| API (catálogo y líneas por evento) | `app/routers/inventory.py`, registrado en `app/main.py` con prefijo `/api` |
| Pantalla del Super Admin | Configuración → pestaña «Inventario» (`templates/configuracion.html`, `static/js/inventory-catalog-admin.js`) |
| Bloque de inventario del evento | `static/js/event-inventory-plan.js`; en «Nuevo evento» (último paso, antes del resumen) y en «Editar evento» (sección «Inventario») |
| Roles | `app/auth.py` (`EXTRA_ONLY_ROLES`, `EXTRA_ROLE_CHOICES`, `has_any_role`, `staff_with_role`, `require_role_or_any`), `static/js/gw-staff.js` |
| Pruebas | `tests/test_inventario_catalogo.py`, `tests/test_roles_almacen_contabilidad.py`, `tests/js/event_inventory_plan_check.js` |

## Qué es nuevo y qué ya existía
* `inventory_items` / `inventory_deliveries` (Fase 2 y antes) son el reparto de insumos a PERSONAS en el quiosco (`kiosk_inventario.html`): **no se tocaron**.
* **UNIFICADO (9-nov-2026, decisión de Juan David):** el campo «Inventario» del motor de plantilla (`app/event_inventory.py`, guardado en `events.extra_json`) ya no existe como inventario aparte: el único inventario es el catálogo.
  La migración `0109_inventory_unify` (`app/inventory_unify.py`) pasa cada tipo del campo viejo a un producto del catálogo (categoría «Inventario anterior»), suma las líneas de cada evento en `qty_assigned`
  (las referencias quedan en las notas), no pisa líneas que el catálogo ya tenga, deja el campo viejo «retirado» en la plantilla y conserva los valores viejos en `extra_json` como respaldo. Es idempotente.
  Ya no se puede crear un campo «inventario» en el diseñador de la plantilla (el servidor lo rechaza); el módulo `event_inventory.py` queda solo para leer lo viejo.
* El «Control de inventario» del quiosco (`inventory_items` / `inventory_deliveries`, reparto de insumos a PERSONAS) es otra función y **no se tocó**.
* «Los productos del catálogo se reflejan solos como campos de inventario»: en «Nuevo evento» y «Editar evento» el bloque lista **todos los productos activos** del catálogo; no hay que dar de alta nada por
  evento. Un producto archivado deja de ofrecerse, pero el evento que ya lo tiene lo conserva.

## Catálogo
* Categoría: nombre único (sin distinguir mayúsculas). Producto: nombre único, unidad de medida (por defecto «unidad»), SKU opcional, categoría (puede ser NULL = «sin categoría») y campos propios
  (hasta 6; texto o número; se escriben uno por línea, «Voltaje:número»). Esos campos se piden por evento (`attrs_json` de la línea).
* Archivar / restaurar / eliminar (solo archivados y sin uso). No se archiva una categoría con productos activos. Restaurar un producto cuya categoría está archivada lo deja «sin categoría».
* Solo el Super Admin crea, edita, archiva y elimina. Ver el catálogo: coordinador y más, Almacén y Contabilidad. Todo queda en `audit_actions`.

## Regla de cuadre (`app/inventory.py`)
Por línea (producto de un evento): `asignado` (lo que pide el evento), `salió`, `volvió`, `consumido` (los tres los mueve el almacén).

| Etapa (estado base del evento) | Regla |
|---|---|
| siempre | cantidades enteras 0..1.000.000; devuelto + consumido ≤ salió; salió ≤ asignado. Si el guardado la rompe, **no se guarda nada** (400) |
| `creado` | un producto sin categoría es solo aviso |
| `en_proceso` | todo producto con línea tiene categoría; **suma exacta**: salió = asignado en cada línea |
| `cierre` (finalizado) | salió = devuelto + consumido; lo que falte es aviso, no bloquea |

* `check_balance(rows, stage)` devuelve un `BalanceReport` (`ok` = sin errores, `balanced` = sin errores ni avisos). `can_enter_in_progress(rows)` es la puerta.
* **Puerta real:** `PATCH /api/events/{id}` con `status = en_proceso` responde 400 con el motivo («faltan N por sacar del almacén…») si el inventario no cuadra. Un evento **sin** líneas de inventario pasa.
  Se apaga con `INVENTORY_BALANCE_GATE=0` (variable de entorno, sin desplegar nada). `revert-to-created` no se toca.
* Interpretación (la fuente, `docs/29` línea 247, dice solo «suma exacta; sin categorizar en creado; todo categorizado para pasar a en proceso»): se tomó «suma exacta» como asignado = salió al pasar a
  «En proceso», y el cierre (devuelto + consumido = salió) como aviso. **Por confirmar con Juan David.**

## Roles Almacén y Contabilidad
* Son **solo extra** (columna `extra_roles`, migración 0103): se suman a una cuenta coordinador o comercial desde Configuración → Staff → «Cambiar rol o añadir roles» (admin y super_admin; `admin` como
  extra sigue siendo solo del Super Admin). No son rol principal (no están en `STAFF_ROLES`, `PATCH /staff/{id}/role` y `POST /staff` los rechazan).
* Para que `max(ROLE_HIERARCHY[r] for r in effective_roles(...))` siga funcionando entran en `ROLE_HIERARCHY` con rango **-1**: nunca suben ni bajan el rango de la cuenta, la escalera
  `cliente < digitador < coordinador < comercial < admin < super_admin` no cambia, y `_rank`, `_manageable_roles`, `_assert_can_manage` y `staff_multirol` se comportan igual.
* Permisos: **Almacén** ve y edita el inventario de cualquier evento de su cliente (asignado, salió, volvió, consumido, notas, datos del producto). **Contabilidad** es solo lectura.
  Coordinador y más (sin ser almacén) editan lo que PIDE el evento (asignado, notas, datos) pero no lo que mueve el almacén (403). Almacén/contabilidad ven eventos aunque `ENFORCE_STAFF_EVENT_SCOPE=1`
  (solo en el inventario). Ninguno administra cuentas ni obtiene datos de asistentes por este camino: el extra no suma permisos fuera del inventario.
* Limitación conocida: como son extra, una persona «solo de almacén» necesita igual una cuenta principal coordinador/comercial, y esa cuenta conserva los permisos de ese rol. Si Juan David quiere una
  cuenta solo-almacén sin acceso operativo, hay que crear el rol principal (decisión de producto pendiente).
* `staff_with_role(db, role)` (en `app/auth.py`): cuentas **activas y no archivadas** con ese rol (principal o sumado). Para correos: `[s.email for s in staff_with_role(db, "almacen") if s.email]`.
  No se envía ningún correo en esta rama: queda para las demás ramas.

## No incluido / pendiente
* Exportar/importar eventos (`app/event_transfer.py`) **no** lleva todavía `event_inventory_items` (los productos del catálogo son globales y sus ids no coinciden entre entornos).
* «Lo facturado» para contabilidad depende del estado «Facturado» de otra rama; aquí Contabilidad solo ve el inventario.
* No hay informe/Excel del cuadre; la pantalla muestra el estado y los totales.
* Sin migración de datos del campo «Inventario» de plantilla al catálogo.
