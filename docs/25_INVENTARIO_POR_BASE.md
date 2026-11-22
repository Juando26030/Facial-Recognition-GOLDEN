# Inventario «lo define la base», base de dependientes, vista previa de cargas y bloqueo del digitador (0161, 21-nov-2026)

Plan aprobado por Juan David el 21-nov-2026 (documento del proyecto `claude/62_PLAN_INVENTARIO_POR_BASE_Y_DEPENDIENTES_2026-11-21.md`).
Nació para un evento de regalos para hijos de asistentes. Ese evento NO lo usará (su base llegó desordenada), pero la función es general.
Todo viene **apagado por defecto**: con las opciones apagadas, el evento funciona igual que antes.

## 1. Qué activo según mi caso
| Situación | Qué activo |
|---|---|
| Llegan y escogen (comida, bebida) | Inventario → «La persona elige» (lo de siempre) |
| La base ya dice qué producto le toca a cada uno | Inventario → «La base lo define» |
| Además vienen con hijos o acompañantes | Lo anterior + **base de dependientes** |
| Solo quiero contar a los acompañantes | Base de dependientes, sin inventario: aparece el campo «Dependientes» |
| Una tableta entrega siempre lo mismo / escanea siempre la misma zona | «Bloquear la configuración del digitador» |

En Parámetros › Zonas e inventario, el asistente «¿Qué necesito?» hace estas tres preguntas y recomienda qué activar.

## 2. Inventario «La base lo define» (`app/inv_assign.py`, `app/inv_assign_core.py`)
- **Dónde se configura:** Parámetros › Zonas e inventario › control de inventario › «¿Quién decide qué se le entrega a cada persona?». Se guarda en `events.inventory_mode` (`assigned`) y `events.inventory_assign_json`.
- **Qué se elige:**
  - el campo del producto del **titular**: Cargo, Entidad, Tipo de asistente o un campo opcional;
  - su cantidad, si se quiere;
  - la columna del producto de los **dependientes** y su cantidad, si se quiere.

  Hace falta al menos un campo de producto.
- **Cómo se cuentan las unidades:**
  - sin campo de cantidad, una fila es 1 unidad;
  - filas repetidas de la misma persona y el mismo producto suman unidades;
  - con columna de cantidad, una celda vacía vale 1, y un valor inválido o 0 aparece en el puesto como problema (no se entrega).
- **Lo que le toca a cada persona se calcula EN VIVO desde la base** (no se copia). Si la base cambia, el puesto lo ve.
- **Productos:**
  - cada valor distinto (normalizado: sin mayúsculas, tildes ni espacios dobles) es un producto;
  - se crean solos al guardar, al cargar dependientes o con «Actualizar productos desde la base», con stock igual a lo asignado;
  - `source_value` los enlaza, así que el nombre visible se puede cambiar sin romper nada;
  - el stock NO se toca después: se edita a mano y puede quedar **por debajo** de lo asignado. Eso solo genera una alerta, nunca un bloqueo;
  - «Igualar el stock» sube el stock hasta lo asignado y nunca lo baja.
- **Entrega** (`/kiosk/<id>/inventario`):
  - se escanea o busca a la persona y se ve lo suyo y lo de sus dependientes;
  - hay un botón «Entregar» por línea y otro «Entregar todo»;
  - se puede entregar por partes, en días distintos;
  - solo a personas **registradas** (con un ingreso que no sea solo «Actualizado»);
  - nunca se entrega dos veces lo mismo: `inventory_deliveries.assignment_key` es `h` para el titular o `d<uid>` para una fila de dependiente, y se recalcula después del bloqueo `FOR UPDATE` de los productos;
  - con «escanear = entregar» activo, al escanear se entrega todo lo pendiente;
  - en este modo se bloquea la entrega por elección («Entregar» de siempre responde 400);
  - si ya hay entregas por elección, no se puede pasar a este modo (409).
- **Opciones de cada producto:** máximo por persona y estadía quedan como siempre y cuentan por la persona que recibe (el titular recibe lo de sus dependientes). «Repetir la entrega» no aplica: la asignación ya dice cuánto toca.
- **Buscar a un dependiente:** «¿No aparece? Busca al dependiente» (nombre o documento, mínimo 3 caracteres) muestra a qué titular está asociado.
- **Entregas de más:** si dos servidores sin internet entregan lo mismo antes de sincronizar, la entrega sobrante sale en Parámetros como «Entregas de más». No se borra nada.

## 3. Base de dependientes (`app/dependents.py`, tabla `event_dependents`)
- **Dónde se carga:** Adjuntar base de datos › «Base de dependientes». Solo **después** de la base de registro, y nunca con el evento finalizado. Hay un archivo de ejemplo en `static/templates/plantilla_carga_dependientes.xlsx`.
- **Columnas:**
  - obligatoria: `cedula_titular` (también se aceptan `cc`, `cedula` o `documento`);
  - opcionales: `nombre_dependiente`, `cedula_dependiente`, `producto`, `cantidad`, y cualquier otra columna, que se guarda tal cual en `data_json`;
  - **«nombre» a secas no es el nombre del dependiente**: en las bases reales suele ser el del titular.
- **Quién es cada dependiente:** se identifica por su documento; si no tiene, por su nombre; si no tiene ninguno, cada fila es un dependiente distinto. Dos filas con el mismo nombre o documento son el mismo dependiente con dos productos.
- **Vista previa** (no escribe nada) y luego **Reemplazar** (por defecto) o **Agregar solo lo nuevo**:
  - una fila igual a una ya cargada se conserva (mismo `uid`, así la entrega sigue enlazada);
  - con «Reemplazar», lo que ya no viene se borra, **salvo lo ya entregado**.
- **Filas que no entran:** sin cédula del titular, titular que no está en el evento, o la persona de prueba. La vista previa lista cada una con su fila y el motivo.
- **Dependiente que también está en la base con su propio documento:**
  - se le entrega directamente a esa persona;
  - no se cuenta dos veces.
- **Campo «Dependientes»** (`parametros.DEPENDENTS_KEY`, virtual: solo con `include_virtual=True`):
  - en Parámetros › Campos se le cambia el nombre, la posición y «Generar estadística»; nunca es obligatorio;
  - en «Editar persona» se ve la cantidad y, al desplegarlo, quiénes son y sus datos (solo lectura: se cambia volviendo a cargar la base);
  - en el reporte sale una columna y la hoja «Dependientes».
- **Estadística:** muestra los titulares **registrados** por número de dependientes, más el total «registrados + dependientes asociados». No reemplaza las estadísticas de siempre.
- **Privacidad:** los dependientes no tienen rostro ni reconocimiento. Al sacar a una persona del evento, borrar la base cargada o suprimir sus datos, se van también sus dependientes.

## 4. Vista previa en TODAS las cargas de base (`app/roster_preview.py`, `static/js/roster-preview.js`)
Antes de cargar, en la carga normal, en «Solo agregar» y en la de dependientes, la pantalla muestra:
- el resumen;
- cómo cambia la base del evento (hoy N personas, después M; cuántas nuevas, cuántas se inscriben, cuántas se actualizan o no se tocan);
- las columnas;
- **hasta 10 personas repartidas de punta a punta del archivo**, tal como quedarían en «Editar persona», con «Antes:» en lo que cambia.

Nada se guarda hasta confirmar. `POST /api/bulk_roster/preview` acepta `mode=normal|append` (por defecto `append`, como siempre). En la vista previa de la carga normal:
- no se escribe nada: ni etiquetas, ni campos, ni la detección del apellido;
- no se pregunta el nombre de las columnas «opcional_N»: se pregunta al cargar.

## 5. Bloquear la configuración del digitador (`app/config_lock.py`, `static/js/config-lock.js`)
- **Registro:** la opción de siempre, «Mostrar la configuración del registro a los digitadores». Apagada (por defecto), el digitador **ve** el engranaje, pero al tocarlo le pide la contraseña.
- **Zonas** (`areas_config_locked`): fija la zona y el movimiento elegidos.
- **Inventario** (`inventory_config_locked`): fija lo marcado para entregar.

En los tres casos, lo elegido se recuerda en la tableta (localStorage). La contraseña es una por evento y se guarda con hash en `config_unlock_hash`. Tras 5 intentos fallidos hay que esperar 5 minutos. El desbloqueo dura hasta «Bloquear de nuevo» o hasta recargar la página. El coordinador, el administrador y el super administrador nunca quedan bloqueados. Es una ayuda contra errores: el servidor valida todo igual.

## 6. Servidores locales
- **Paquete del evento:** incluye `event_dependents` (el `uid` viaja igual), los productos con `source_value` y la configuración del evento. Carga la base de dependientes ANTES de bajar el evento.
- **Sincronización:** las entregas suben y bajan con `akey` (`node_extra.delivery_row` / `apply_deliveries`).
- **Consulta previa a la nube** (`app/node_precheck.py`, `POST /api/node/events/{id}/precheck`):
  - solo en un evento compartido y en el servidor local;
  - se hace una consulta de máximo 3 s antes de entregar (asignado, o ítems sin repetición) o de dejar entrar a una zona sin reingreso;
  - si la nube ya lo tiene, se frena;
  - sin internet, la acción sigue con aviso (decisión de Juan David);
  - no hay consultas periódicas.

## 7. Rutas nuevas (`app/routers/inv_base.py`)
`GET|PUT /api/events/{id}/inventory-assign` · `POST …/inventory-assign/sync` · `POST …/inventory-assign/match-stock` · `GET …/inventory/assigned?cedula=` · `POST …/inventory/deliver-assigned` ·
`GET …/dependents?holder=` · `GET …/dependents/search?q=` · `GET …/dependents/summary` · `POST …/dependents/preview` · `POST …/dependents/load` · `DELETE …/dependents` (escribir BORRAR) ·
`GET|PUT …/config-lock` · `POST …/config-lock/unlock`.

## 8. Pruebas
`tests/test_inventario_por_base_puro.py` (reglas puras) y `tests/test_inventario_por_base.py`. Este último cubre:
- vista previa y carga de dependientes, con reemplazar y agregar;
- creación de productos y stock, y la alerta;
- entrega por partes y todo, sin repetir, solo a registrados;
- campo y estadística «Dependientes»;
- vista previa de la carga normal y de «Solo agregar»;
- candados y contraseña;
- consulta previa.

## 9. Pendiente (no construido todavía)
- Imprimir escarapela a los dependientes. La columna `events.dependents_badge` quedó reservada; se arma cuando un evento lo pida, para no ofrecer una casilla que no haga nada.
- Columna «Dependientes» en la tabla del directorio en vivo. Hoy se ve en «Editar persona» y en el reporte.
- Modos «un servidor se conecta a otro» y «servidor intermedio» (docs/23). La consulta previa ya está lista para ellos.

## 10. Agregado el 21-nov-2026 (mismo paquete, antes de staging)
- **Tipo de campo «Número»** (Parámetros › Campos): solo acepta números (signo y decimales con punto o coma). Mientras se escribe, lo que no es número se quita (`data-gw-number` en `static/js/field-render.js`) y el servidor lo vuelve a comprobar («Número no válido — …», `api._invalid_email_fields`/`_bad_value_prefix`). También en el autorregistro.
- **«Mostrar en el registro»** (`event_field_configs.show_in_card`, columna nueva en Parámetros › Campos): define qué datos se ven en la tarjeta de cada persona en la pantalla de Registro sin abrir «Editar». De fábrica salen la cédula, los nombres y los apellidos; la entidad ya no. Los campos marcados van debajo, cada uno con su nombre, y la tarjeta crece hacia abajo sin cortar nada (`static/js/directory.js`, `p-registro-puerta.css`). Se puede marcar también «Dependientes»: `/api/users` trae `dependents` cuando el evento tiene esa base.
- **«Aplicar a todos los campos de texto»** en el diseñador del formulario de persona: copia el «Texto al escribir» (MAYÚSCULAS / minúsculas / como lo escriban) del campo elegido a todos los campos de texto. Cédula, correo, teléfono, listas y fechas no cambian.

## 11. Corregido tras probar en staging (21-nov-2026, noche)
- **Directorio:** la huella (ETag) de `/api/users` ahora incluye la base de dependientes; antes, cargarla no cambiaba la huella y el navegador seguía mostrando «Dependientes» viejo (304).
- **Recargar dependientes (Reemplazar o Agregar):** una fila es «la misma» por **titular + dependiente + columnas de producto y cantidad** (las configuradas, o `producto`/`cantidad` si existen; si no hay, todas). Antes se comparaban TODAS las columnas y el número de fila:
  - corregir la edad o una nota de una fila ya entregada la duplicaba y volvía a quedar pendiente;
  - subir el archivo con menos columnas duplicaba la fila;
  - el dependiente sin nombre ni documento cambiaba de identidad al reordenar el archivo.
  Ahora la fila se conserva (mismo `uid`, la entrega sigue enlazada) y, en «Reemplazar», sus demás columnas se actualizan en el lugar («con datos corregidos» en la vista previa). «Agregar» nunca cambia lo que ya estaba. Dos filas iguales siguen siendo dos unidades. Cambiar el producto de una fila entregada sí crea una fila nueva (es otra asignación). Prueba: `test_reload_never_duplicates_a_delivered_row_…`.
