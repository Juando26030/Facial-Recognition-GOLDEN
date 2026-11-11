# Fase 10 — Ajustes del 10-nov-2026

Cada bloque (A a E) agrega su sección al final. No reescribas las de otros.

## Bloque D — Formularios y Acta de novedades

### 1. «Mostrar con asteriscos» por campo

**Qué hace.** En el editor de formularios, cada campo vinculado a la base y marcado «Se muestra pero no se puede editar» tiene ahora la casilla «Mostrarlo con asteriscos». Sin marcar, la persona ve el dato completo (que es lo que pidió Juan David). Marcada, ve algo como `A** M****`.

**Cómo se usa.** Editor del formulario, clic en el campo, panel derecho, debajo de «Se muestra pero no se puede editar».

**Decisiones.**
- Diseños guardados antes de este cambio no traen el parámetro: no se enmascara nada, salvo **correo y celular**, que siguen enmascarados (política X4: quien escribe una cédula ajena no debe leer el contacto de esa persona). Si el diseñador desmarca la casilla en uno de esos campos, se ve completo. La regla vive en `formlib.mask_wanted`.
- El enmascarado es solo visual. Al enviar, el servidor vuelve a tomar el valor real de la base (como antes).
- **Condiciones (variantes, «mostrar solo si», precios, descuentos, cupos llenos).** Se reemplazó la solución provisional (`condition_field_ids`, que mandaba el valor real al navegador). Ahora, para cada campo enmascarado, el servidor evalúa cada condición con el valor real y le entrega al navegador solo el resultado: la condición se reescribe como «siempre se cumple» o «nunca se cumple» (`formlib.freeze_conditions`). El navegador no recibe el dato personal y las reglas se comportan igual. Se puede hacer porque el campo es de solo lectura (su valor no cambia mientras se llena). Filtra solo un sí/no por regla. No se tocó `form-render.js` (las huellas de páginas congeladas siguen iguales).
- Los campos que no son de texto (opciones, fechas, números) no se enmascaran nunca (no hay máscara válida), como antes.

**No probado aquí:** el flujo completo en el navegador con base de datos (no hay base en este entorno). Se probó con pruebas puras la reescritura de condiciones.

### 2. Prellenado del compromiso del digitador

**Qué hace.** Cuando un digitador temporal ya firmó el compromiso antes, el formulario del compromiso le llega con nombre, celular, nombre del familiar y teléfono del familiar ya escritos (editables). Solo la cédula queda bloqueada. Las casillas (salud, contrato, asistencia, declaración, autorización) y la firma NUNCA se prellenan.

**Regla de coincidencia (decisión de Juan David, 10-nov).** Misma cédula en **todos** los clientes y eventos; se usa el compromiso **más reciente**. Solo aplica a cuentas de rol digitador identificadas con su sesión (cuando entra con su cédula y el sistema le pide firmar), nunca a quien escribe una cédula en el enlace público: eso mostraría datos de otra persona a un desconocido.

**Privacidad y retención.** No se guarda nada nuevo (sin migración, por eso la 0125 queda sin usar): se leen las respuestas que ya existen. Los datos del familiar viven cifrados y se borran por retención (`sensitive_retention_days`) o por supresión (`privacy.py`); si ya se borraron, no se prellenan. Nombre y celular siguen la vida de la inscripción. Nada de esto se escribe en logs.

**Código.** `app/pledge.py::previous_answers` y `prefill_for`; usado por `forms_public._payload_form`.

### 3. Acta de novedades

**Qué hace.** Sección nueva del evento («Acta de novedades», en «Más herramientas» del evento, ruta `/kiosk/<evento>/actas`). Se escribe lo ocurrido (párrafo o lista), y el coordinador y el cliente firman dibujando con el dedo o el mouse. Se pueden hacer varias actas por evento. Cada una se puede ver, imprimir o descargar.

**Cómo se usa (para Juan David; flujo ajustado el 10-nov tras probar staging).**
1. El coordinador entra a «Acta de novedades», escribe el título y lo ocurrido.
2. En la misma pantalla, antes de guardar: firma el coordinador, escribe su nombre quien firma por el cliente y dibuja la firma del cliente (en la tableta del coordinador).
3. Un solo botón «Guardar»: crea el acta ya firmada, genera el PDF y la bloquea (el texto ya no se cambia). «Descargar PDF» baja el PDF; «Imprimir» abre la versión imprimible.
4. Opción secundaria: «Guardar borrador (sin firmas)». El borrador se puede editar y borrar; un cliente con cuenta puede abrirlo y firmar la suya desde su sesión, y el coordinador firma la suya abriéndolo. Al quedar las dos firmas se genera el PDF.
Una sola firma no se acepta al crear: o las dos o ninguna.

**Permisos.** Escribe y firma por el coordinador: coordinador, admin y super_admin. La comercial ve las actas pero no las escribe. El cliente (rol cliente autorizado al evento, evento en proceso) ve y firma SOLO la suya; nadie puede firmar por otro. El digitador no entra. Todo pasa por `get_event_for_staff` y la base archivada la bloquea.

**Reglas.** Si ya hay una firma y se cambia el texto, el sistema avisa y, si se confirma, quita la firma (hay que firmar de nuevo). Un acta firmada no se edita ni se borra (si hace falta corregir, se crea otra). Un borrador sin firmas se puede borrar. La firma se guarda como imagen PNG por `app/storage.py` (carpeta `<cliente>/event_acts/<evento>/`); en la base queda el nombre de quien firmó, la fecha y la huella SHA-256 del texto firmado.

**Decisiones.**
- **PDF (decisión de Juan David, 10-nov).** Al quedar las dos firmas, el sistema genera y guarda un PDF con todo (título, evento, fecha, texto, firmas con nombre y fecha, huella) por `app/storage.py` (`<cliente>/event_acts/<evento>/<acta>_acta.pdf`), con reportlab (fijado en `requirements.txt`, import perezoso). Cada acta firmada tiene el botón «Descargar PDF». Si la generación falla, el acta queda guardada igual y aparece el botón «Generar PDF» para reintentar (coordinador). Si se cambia el texto de un acta con firma, las firmas y el PDF se quitan. El HTML imprimible sigue disponible.
- **Cliente sin cuenta (decisión de Juan David).** Firma en la tableta del coordinador, sin enlace público: el coordinador abre el acta, escribe el nombre de quien firma por el cliente y le pasa la tableta para que dibuje su firma. El cliente con cuenta sigue firmando la suya con su sesión.
- La firma es siempre negra sobre papel blanco, también en modo oscuro, para que se vea igual en el documento.
- Los exportes de evento entre entornos (`event_transfer`) todavía no incluyen las actas ni sus firmas.
- Migración `0126_event_acts` (tabla `event_acts`, con `pdf_key` y `pdf_at`). Al integrar, su `down_revision` debe apuntar a la última migración de los bloques A/B (hoy apunta a `0121_infra_costs`).

**Archivos.** `app/event_acts.py`, `app/routers/event_acts.py`, modelo `EventAct` en `app/models.py`, `templates/kiosk_actas.html`, `static/js/kiosk-actas.js`, `static/css/gw-actas.css`, `tests/test_event_acts.py`, `tests/test_pledge_prefill.py`.

**No probado aquí.** Que el PDF se vea bien en un lector real (sí se generó y se comprobó que empieza como PDF); los endpoints con base de datos (las pruebas están escritas en `tests/test_event_acts.py`, para correr en Cloud Shell) y la firma en pantalla táctil real; sí se vio en Chromium con respuestas simuladas, en claro/oscuro y a 1200 y 390 px.

## Bloque E · Historial de cambios por persona y descarga del instalador local (rama `feat/historial-instalador`, migración 0127)

### 1. Historial de datos modificados por persona
**Qué hace.** Además del registro inicial (quién y cuándo se escaneó), cada vez que se **cambia un dato de una persona que ya existía** (la ciudad, el correo, el cargo, un campo opcional…) queda una fila: campo, valor anterior, valor nuevo, quién lo cambió, cuándo y por dónde (edición, bandeja sin conexión, carga masiva, formulario web).

**Cómo se usa (Juan David).**
- En el Directorio, abre **Editar persona** (coordinador o superior): al final hay un grupo desplegable **«Historial de cambios de esta persona»**.
- En el **Excel del reporte del evento** aparece una segunda hoja **«Historial de cambios»** (cédula, nombre, campo, valor anterior, valor nuevo, quién, fecha y hora, origen). Si nadie modificó nada, el Excel queda igual que antes (una sola hoja).

**Dónde se alimenta.** `PATCH /users/{id}` (Directorio), edición sin conexión (`_outbox_edit_person`, que también es lo que usa el servidor local), carga masiva/recarga de base (solo personas que ya existían), inscripción por formulario público (lo que completa en una persona existente), corrección de cédula (queda como cambio del campo «Cédula» y el historial la sigue). Módulo: `app/person_history.py`; tabla `person_change_log`.

**Decisiones.**
- Una persona recién creada no genera historial (eso es el registro inicial). El **autorregistro** nunca modifica a una persona existente, así que no escribe aquí.
- **No se guarda biometría ni fecha de nacimiento** (la fecha ya tiene su historial en `person_changes`). Solo texto de la persona. Por eso la purga biométrica de 7/180 días no necesita tocarlo.
- Se borra **con la persona**: supresión (`privacy.erase_person` scope `all`), «Eliminar de este evento» (lo de ese evento; si la persona queda sin eventos, todo) y al borrar el evento. Sin llaves foráneas, como `person_changes`.
- La persona **PRUEBA** no deja historial ni sale en el Excel.
- Valores solo en la base, nunca en logs. Viaja con «Exportar/Importar evento» (`event_transfer`).
- Lectura: `GET /api/events/{evento}/users/{cédula}/change-history` (coordinador o superior).

**No cubierto / a saber.** Las ediciones hechas en el servidor local quedan en su base local: la subida a la nube hoy solo lleva personas nuevas e ingresos (ver `FASE_6_SERVIDOR_LOCAL.md`), así que ese historial local no sube. El borrado de un campo del evento (Parámetros) no se registra por persona (queda en `person_changes`, `field_deleted`).

### 2. Tarjeta «Servidor local» en Configuración
**Qué hace.** Nueva pestaña **Configuración → Servidor local** para todos los roles **menos digitador temporal y cliente** (los clientes son externos y el instalador es el programa completo; coincide con la regla de `FASE_6_SERVIDOR_LOCAL.md`). Muestra un botón de descarga y una explicación corta (qué es, requisitos, pasos, arrendamiento, qué pasa sin internet).

**Cómo funciona la descarga.** `GET /api/local-installer` (estado) y `GET /api/local-installer/download`, protegidos por rol. El archivo sale de `app/storage.py`, carpeta `system/local-installer/`, con nombre `GoldenLocal-Setup-<versión>.exe`; se ofrece el de versión más alta. Con Cloud Storage se redirige a una URL firmada de 10 minutos (el archivo pesa cientos de MB y Firebase corta a los 60 s); con disco local lo sirve la app. Cada descarga queda en `audit_actions`. Alternativa: variable `LOCAL_INSTALLER_URL` (HTTPS) si se publica en otro sitio.

**Estado hoy: «Aún no disponible».** No hay instalador empaquetado: nadie ha corrido `deploy/windows/build_installer.ps1` (requiere Windows + Inno Setup). Para activarlo: (1) construirlo en un Windows (paso a paso en `FASE_6_SERVIDOR_LOCAL.md`); (2) subir el `.exe` a `gs://<bucket>/<prefijo>/system/local-installer/` con `gsutil cp` (lo hace Juan David; no se crean recursos desde aquí); (3) la tarjeta lo muestra sola. El bucket debe permitir que la cuenta de servicio firme URLs (ya lo hace para las cargas directas).

**Cómo publicar el instalador (decisión del 10-nov):** sección desplegable en la misma pestaña, visible solo para admin y super_admin, y repetida en el documento sencillo. Dos caminos para construirlo (GitHub Actions sin Windows, o `build_installer.ps1` en un Windows), subida con `gsutil cp` o por la consola web, y comprobación (la tarjeta pasa a «Disponible»). Los clientes ya no tendrán cuentas (usan enlaces): la exclusión del rol cliente queda.

**Explicación para Juan David:** `docs/EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md`.

### 3. Excel del reporte: portada, gráficos e historial (reestructurado)
**Qué cambia (Juan David, 10-nov).** El Excel del reporte del evento ahora trae, en este orden: **«Portada»** → **«Reporte»** (igual que siempre, mismo contenido) → **«Gráficos»** → **«Historial de cambios»** (solo si hubo cambios de datos). Al abrirlo se ve la Portada.
- **Portada:** diseño con la paleta de Golden (azul noche y dorado), cuadrícula oculta, franja del logo, bloque azul con «REPORTE DEL EVENTO» y el nombre del evento, tarjetas con cliente, fechas, lugar/ciudad, tipo de evento, coordinador(a) y comercial; tarjetas con los totales (personas en la base, registradas, por registrar, % de asistencia, primer y último registro, hora con más registros, datos modificados) y un pie con la fecha y hora de generación (hora de Colombia) y una nota corta de privacidad (Ley 1581, sin biometría). Los totales **no cuentan a la persona PRUEBA**. Se imprime en una página.
- **Logo (decisión de Juan David, 10-nov):** UN solo logo, redimensionado con Pillow sin deformarlo: el del evento si tiene uno propio y se puede leer; si no, el de Golden (`static/img/logo-golden.png`). Cuando sale el del evento, el pie lleva una marca pequeña y discreta de Golden. No hay logo de cliente ni adicional (no se leen archivos de ese tipo). Un logo dañado se ignora y se usa el de Golden.
- **Gráficos:** gráficos nativos de Excel (editables), 2 por fila, con título en español, etiquetas de datos y colores de Golden. Tipo según la variable: sí/no y pocas categorías (hasta 6) → dona; muchas (ciudad, empresa, cargo…) → barras horizontales con las 10 principales y «Otros»; numéricas → histograma; registros por hora → columnas; por día → línea; y del historial: cambios por campo y por día. No se grafican cédula, nombres, correo, teléfono, firmas ni textos casi únicos. Los datos de apoyo van en las columnas AA y AB, ocultas (clic derecho → Mostrar).
- **Si algo falla** al armar portada o gráficos, el reporte sale igual (queda en el registro técnico, sin datos personales).
- Código: `app/report_cover.py`, `app/report_charts.py`, `app/report_book.py` (todo sin base de datos), y la llamada en `app/reports.py`. Se ajustaron 2 pruebas viejas que leían «la hoja activa» (ahora leen «Reporte»).
- **Verificado** con datos ficticios convertidos a PDF con LibreOffice (portada y gráficos revisados a la vista). **No verificado:** apertura en Excel de escritorio (LibreOffice pinta distinto), y la prueba con base de datos.

### Pruebas
- `tests/test_reporte_portada_graficos.py` (sin base: hojas y orden, gráficos presentes y 2 por fila, tipo por variable, logos ausentes o dañados, tabla vacía, falla de gráficos) y `tests/test_reporte_portada_graficos_db.py` (con base, Cloud Shell).
- `tests/test_historial_personas.py` (con base de datos): diff, edición, bandeja, carga masiva, cédula, PRUEBA, permisos, Excel, borrados.
- `tests/test_instalador_local_descarga.py` (con base de datos): roles, no disponible, versión más nueva, descarga y auditoría, URL externa, tarjeta por rol.
- `tests/test_historial_personas_texto.py` y `tests/test_instalador_local_texto.py`: de texto, corren sin base (`pytest --noconftest`).

### Lo que NO se pudo verificar
Ninguna prueba con base de datos (no hay Postgres aquí): correr las cuatro suites en Cloud Shell y `alembic upgrade head`. La carga masiva depende del formato exacto del Excel de prueba. Visualmente se revisó la pestaña con el arnés (claro/oscuro, escritorio y celular), no el grupo desplegable del modal de Editar persona con datos reales. La firma de URL de descarga con Cloud Storage real no se probó.

### Para el integrador
`down_revision` de 0127 apunta a `0126_event_acts` (bloque D); si el bloque A/B agregan 0122-0125 después, la cadena la ordena el integrador.

## Bloque B · Cuentas de cobro abiertas y gastos de infraestructura (10-nov-2026)

**Código:** `app/payment_accounts.py`, `app/routers/payment_accounts.py`, `static/js/cuentas-cobro-page.js`, `app/infra_costs.py`, `app/routers/gastos.py`, `static/js/gastos-infra.js`, `templates/gastos.html`. **Migración:** `0124_payment_acct_scope` (cadena global: 0123 del bloque A → 0124; mientras tanto apunta a `0121_infra_costs`, hay que repuntarla al integrar). **Pruebas:** `tests/test_cobros_gastos_f10b.py` (con base: correr en Cloud Shell) y `tests/test_cobros_gastos_f10b_texto.py` (corre sin base).

### 1. Cuentas de cobro: abiertas
- «Agregar cuenta de cobro» crea cuentas sin límite. Cada una dice **a qué pertenece**: a nada en particular (la puede usar cualquier formulario), a un **evento** (puede haber varias por evento), a un **formulario** o a un **panelista** (se escribe su nombre o correo; el evento es opcional). El botón «A qué pertenece» lo cambia después.
- Nada es automático ni obligatorio: ninguna cuenta se crea sola (hay una prueba que lo vigila) y un formulario sin cuenta sigue cobrando con la de Golden. Al elegir la cuenta de un formulario solo salen las que le corresponden; el servidor lo vuelve a validar.
- Llaves cifradas, webhook por cuenta, reembolsos y conciliación con la cuenta con que se cobró: sin cambios.
- Datos existentes: la migración solo agrega columnas. Las cuentas que hoy usan formularios de un solo evento quedan «de ese evento» (y «de ese formulario» si es uno solo); las demás, generales. No cambia ninguna asignación. Bajada: quita las 4 columnas, no toca cuentas ni llaves.
- Error real corregido: el cuadro de «Agregar cuenta» nunca se veía (faltaba `data-open`), así que el botón parecía no hacer nada. También se agregó `.gw-field[hidden]` al sistema de diseño.
- **Decisión:** el «panelista» es un texto libre (en el código no existe aún una «cuenta panelista»). Si el bloque de panelistas crea una entidad, se cambia `panelist_ref` por su id. `form_id` no lleva llave foránea para no crear un ciclo con `web_forms`.

### 2. Gastos › Infraestructura
**Diagnóstico por código** (la sección nunca se oculta por falta de variable o tabla vacía; las causas posibles son):
1. **La migración 0121 no está aplicada en staging** → `/api/gastos/infra/summary` daba error 500 y la pantalla decía solo «No se pudo completar la acción». Ahora responde 503 con un mensaje claro y la pantalla muestra un aviso rojo.
2. **Permiso:** la pantalla y el enlace «Gastos» eran solo de `admin`/`super_admin` globales (un admin de una empresa con `ENFORCE_STAFF_TENANT=1` recibe 403; contabilidad era redirigida). Ahora entra también **contabilidad** (principal o sumado) a Infraestructura; la pestaña «Eventos» sigue solo para admin.
3. **Variables que nunca llegaban:** el flujo de despliegue no pasaba `GCP_BILLING_EXPORT_TABLE` ni `ONEDRIVE_DRIVE_ID` a `deploy.sh`, y cada despliegue reemplaza todas las variables de Cloud Run (`--env-vars-file`), borrando lo puesto a mano. Además el botón «Importar Google ahora» corre en el servicio `web`, que no tenía la variable. Corregido: el flujo toma ambas de las **Variables de GitHub** y se las pasa a `web` y al Job de operaciones.

**Nuevo:** panel **Conexiones** siempre visible (Google, Neon, manual) con «Conectado / No conectado / Hay que revisarlo», qué variable falta y pasos simples; **Subir archivo (CSV)** como alternativa manual (coma o punto y coma, números a la colombiana, también acepta la exportación de Google; se puede volver a subir sin duplicar; marca «Archivo»).

**Qué falta en la nube (lo hace Juan David):**
- Variables de GitHub (Settings → Environments → staging → Variables): `GCP_BILLING_EXPORT_TABLE` (`proyecto.conjunto.tabla`), opcional `ONEDRIVE_DRIVE_ID`. Luego volver a desplegar.
- Activar en Facturación de Google la exportación estándar a BigQuery (solo trae datos desde que se activa).
- IAM: `roles/bigquery.jobUser` (proyecto de la tabla) y `roles/bigquery.dataViewer` (conjunto `billing_export`) para la cuenta de servicio del servicio web (`golden-app-staging`, o `golden-svc-web-staging` con cuentas separadas) y la del Job de operaciones (`golden-ops-staging`).
- Opcional (solo uso de Neon): `NEON_API_KEY` (secreto) y `NEON_ORG_ID` en el servicio web.
- Aplicar la migración 0121 (y 0124) en staging si no está.

**No se pudo probar:** nada con base de datos ni BigQuery real (solo `ruff`, `py_compile`, `node --check`, pruebas de texto y la lógica del CSV/conexiones con módulos simulados); pantallas revisadas en Chromium (claro/oscuro, computador y celular) con datos simulados.

## Bloque A · Inventario, control de áreas y autoescaneo

Migraciones: **0122** (`0122_dwell_autoscan`) y **0123** (`0123_item_requires_dwell`). Rama: `feat/inventario-areas`.

### 1. Pantalla de Inventario (`/inventario`)
**Qué hace.** Ya no lista todos los eventos. Tiene dos secciones:

- **Catálogo.** Las categorías, los productos y las existencias que el Super Admin crea en Configuración › Inventario. Cada producto muestra sus existencias, lo que está *en uso hoy* (asignado a eventos que ocupan el día de hoy) y lo *disponible hoy*. Hay búsqueda por nombre o código y filtro por categoría.
- **Dónde está cada equipo.** Un calendario con vista **Día, Semana y Mes**. No pinta el evento en sí sino **qué material tiene asignado cada evento** (equipos, cuántos, fechas) y cuánto queda **disponible** cada día. Se puede elegir «Ver un solo equipo» para ver, día por día, cuánto hay disponible de ese equipo. Al tocar un día se ve el detalle: por evento, lo asignado, lo que salió, lo que volvió y lo que falta por volver (si el evento ya terminó), y la tabla de disponibilidad por equipo. Desde ahí el botón «Abrir inventario del evento» abre el bloque de siempre para editar las cantidades de ese evento (así Almacén sigue registrando salidas y devoluciones).

**Quién la usa.** Coordinador en adelante, Almacén y Contabilidad (lectura). **Admin y Almacén** (y Super Admin) cambian la categoría y las existencias de un producto (botón «Cambiar») y, desde la pestaña **«Administrar catálogo»** de esta misma pantalla, **crean, renombran, archivan, restauran y eliminan** categorías y productos. Admin también lo ve en Configuración › Inventario.

**Cambio de permisos del catálogo (decisión de Juan David, 10-nov).** En la Fase 5 el catálogo lo editaba solo el Super Admin. Se abrió a Admin y Almacén porque son quienes realmente conocen y mueven la bodega. Código: las rutas de `/api/inventory/categories|products` usan ahora `MANAGER` (admin, almacén, super_admin) en vez de `require_super_admin`; coordinador, comercial y contabilidad siguen en solo lectura. Se movió el bloque de administración a `templates/_inventory_catalog_admin.html` (lo incluyen Configuración e `/inventario`). Se actualizaron las pruebas de la Fase 5 que fijaban «solo Super Admin» (`tests/test_inventario_catalogo.py`).

**Cómo se calcula.** Un evento ocupa su material desde el montaje (si lo hay y es anterior) hasta su último día; si solo tiene una fecha, ese día. Un evento sin fecha de inicio no aparece en el calendario. Cuenta lo **asignado**. Los eventos archivados no cuentan. La disponibilidad cuenta los eventos de **todos** los clientes (el material es de Golden); los nombres de eventos solo se muestran a quien tiene permiso sobre ellos.

**Técnico.** `app/inventory_calendar.py` (lógica pura), `GET /api/inventory/overview`, `GET /api/inventory/calendar?start=&end=` (máx. 100 días), `PATCH /api/inventory/products/{id}/manage`; `static/js/inventario-page.js`, `static/css/gw-inventory-calendar.css`. `inventory_svc.py` no cambió: se reutilizan `event_lines`/`to_rows` en el bloque por evento.

### 2. Control de áreas: tiempo de permanencia y premio por estadía
**Dónde se activa.** Parámetros del evento › **Zonas e inventario** › bloque «Permanencia, premio por estadía y escaneo automático» (tiene su propio botón Guardar).

**Qué hace.**
1. **Contar el tiempo de permanencia en las zonas.** Cada entrada y su salida se emparejan y los tiempos se **suman** (10 min + 5 min = 15 min). Si una persona tiene tiempos que se cruzan entre zonas (olvidó escanear una salida), el tiempo común se cuenta una sola vez.
2. **Habilitar premio por porcentaje de estadía.** El coordinador define el **tiempo de referencia** (el 100 %, p. ej. 24 h) y el **porcentaje mínimo** (p. ej. 80 %). Si deja la referencia vacía se usa la duración del evento (según sus fechas y horas).
3. **Estadística y lista** (en Parámetros y TAMBIÉN en la pantalla de Control de áreas, panel «Permanencia», con `static/js/areas-dwell.js`; solo coordinador en adelante y con el conteo activo). Botón «Calcular»: cuántas personas llegan a 50/60/70/80/90/100 % y cuántas cumplen el porcentaje elegido (se puede probar otro porcentaje y filtrar por zona). Descargas: **Excel o CSV de quienes cumplen**, o Excel de todas las personas (cédula, nombre, entidad, tiempo, porcentaje, si cumple, si quedó sin salida).
4. **Usar el resultado.**
   - **Certificados:** botón «Habilitar certificado a quienes cumplen» marca «Certificado: Sí» a esas personas (no quita a nadie; la persona de prueba no se toca). Recuerda que el certificado se descarga cuando el evento está finalizado y los certificados del evento están activos.
   - **Entregas de inventario:** en la tabla de ítems de Parámetros hay una columna «Solo a quien cumple la estadía». Un ítem así solo se entrega a quien ya llegó al porcentaje (si no, el sistema avisa con un mensaje claro y no entrega). Solo aplica con el conteo y el premio activos.

**Persona PRUEBA.** Nunca cuenta en el conteo, ni en las cifras, ni en las descargas, ni recibe el cambio de certificado. En la puerta de entregas con estadía se deja pasar (ensaya el flujo).

**Técnico.** `app/area_dwell.py` (puro), `app/area_dwell_svc.py` (base), `app/routers/areas_dwell.py`: `GET/PUT /api/events/{id}/areas-dwell/config`, `GET …/areas-dwell`, `GET …/areas-dwell/export?fmt=xlsx|csv&only=cumple|todos`, `POST …/areas-dwell/apply-certificates`. Rol: coordinador en adelante, sin comercial (igual que los reportes de áreas). Columnas nuevas en `events` (0122) e `inventory_items.requires_dwell` (0123). Cambios de configuración y descargas quedan en la auditoría.

### 3. Autoescaneo («escanear/Enter = entrega o ingreso automático»)
En los mismos Parámetros hay dos casillas:
- **Control de áreas:** escanear o dar Enter registra la entrada o salida solo, sin pulsar «Acreditar» (por servidor: es como tener el autoregistro, pero solo para zonas, sin cambiar el «Modo autoregistro» del registro).
- **Control de inventario:** el operador marca una vez qué se entrega; al escanear (o Enter, o cámara QR) a cada persona, se le entrega **lo marcado** de una vez, sin pulsar «Entregar». Lo marcado se conserva entre personas. Un segundo Enter mientras se entrega no duplica la entrega. Con «Repetir la entrega a la misma persona» apagado en un ítem, el sistema sigue bloqueando la repetición.

### 4. Ronda 3 (ajustes tras probar staging)
**Cámara QR que se cierra sola.** En entrega de inventario y en control de zonas, si la cámara lee el QR y la persona se encuentra, el panel de cámara se cierra solo (`scanner.close()` en `static/js/inventario.js` y `static/js/areas.js`). Si no la encuentra o falla, queda abierta con el aviso. Con autoescaneo la entrega/ingreso se lanza antes de cerrar.

**Planeación de inventario (Inventario › «Dónde está cada equipo»).** Panel con los artículos del catálogo por categoría y su disponible; se arrastran a un evento del calendario (día/semana/mes) o, sin arrastrar, se «arman» con un clic y se hace clic en el evento (tableta, celular, teclado). Al soltar pide la cantidad; también se edita o quita cada línea. Servidor: `POST /api/inventory/assign` (admin/almacén/super_admin; `MANAGER`). Valida evento no archivado ni finalizado y con fecha de inicio, producto activo, cantidad entera >= 0 (0 quita), saldo del evento y existencias en el tramo completo del evento **incluido el montaje y los eventos de varios días** (pico de uso de otros eventos, `peak_usage`/`max_assignable` en `app/inventory_calendar.py`); si no alcanza responde cuánto sí se puede asignar. No baja de lo que ya salió. El cliente solo hace una validación previa; manda el servidor. `GET /api/inventory/calendar` ahora devuelve `has_inventory`, tipo de evento y `can_assign`. Los eventos sin inventario se marcan «Sin inventario aún». Convive con los chips por tipo de evento (`calendar-cats.js`): filtran los eventos visibles y el panel muestra «en estos eventos N»; la disponibilidad siempre cuenta todos los eventos.

**Parámetros.** Los campos de permanencia, premio y escaneo automático ya no tienen botón propio: usan el «Guardar cambios» general y el indicador de cambios pendientes (`GWParams.register({key:'dwell'})`). «Calcular», las descargas y los certificados siguen aparte.

Pruebas nuevas: puras (`peak_usage`, `max_assignable`), texto (cierre de cámara, cableado de la planeación, Parámetros), JS (`othersPeak`, `maxAssignable`, `parseQty`, `panelGroups`) y una prueba con base (`test_assign_from_the_calendar_validates_dates_stock_and_roles`). No se pudo probar con base ni con arrastre real en navegador/táctil (solo Playwright con respuestas simuladas).

### Decisiones que tomé
- **Permisos del catálogo:** abiertos a Admin y Almacén por decisión de Juan David (ver arriba).
- **Entrada sin salida:** cuenta hasta el fin del evento (o hasta ahora si sigue en curso) y se marca «Quedó sin salida» (confirmado por Juan David).
- **Calendario sobre lo asignado:** no resta lo «salido sin devolver» de eventos terminados; eso se avisa aparte como «falta por volver».
- La persona que está en dos zonas a la vez no suma doble.
- El historial por campo de eventos (`event_history`) solo cubre campos de la plantilla; los nuevos parámetros se auditan con `audit_actions`.

### No pude probar
No hay base de datos en este entorno: las pruebas `tests/test_fase10_a_api.py` (flujo completo con base) se corren el miércoles en Cloud Shell. Sí corrieron `ruff`, `node --check`, `tests/test_fase10_a_puras.py`, `tests/test_fase10_a_texto.py` y `node tests/js/inventario_page_check.js`. La revisión visual con Playwright se hizo con respuestas simuladas.

### Preguntas para Juan David
Sin preguntas abiertas: las tres quedaron decididas el 10-nov (permisos del catálogo, entrada sin salida, estadística también en Control de áreas).

## Bloque C — QR en vCard, ruleta y calendario

Migración: solo `0128_event_types` (tipos de evento, ver 3). La ruleta y el QR no la necesitan (la configuración de la ruleta vive en `style_json`, que ya existía).

### 1. QR de la escarapela como contacto (vCard)
**Qué hace.** El QR de la escarapela impresa, de la escarapela virtual (credencial digital) y del pase de Wallet ahora es una tarjeta de contacto mínima: nombre, teléfono (solo si la persona lo comparte) y, escondido en el campo «Nota», el código de siempre (`NOTE:GW:…`). Al escanearlo con la cámara del celular, el teléfono ofrece «Guardar contacto». El código que usa Golden (la cédula del QR impreso o el código firmado `gwq1…` de la credencial digital y Wallet) no cambia.

**Cómo se usa (en simple).** Nada cambia para quien registra: Registro, Control de Áreas, Inventario, el buscador del Directorio y la cámara de expositores leen el QR nuevo y el viejo. Las escarapelas ya impresas siguen sirviendo.

**Cómo funciona por dentro.**
- `static/js/vcard.js` (construir y leer) y `app/qr_vcard.py` (mismo código en Python; una prueba compara que den el mismo resultado).
- Lectores: `qr.js` (`parse`, `classify`, `isDynamic`, `resolveDynamic` y la cámara entregan el código de adentro), `search-core.js`, y en el servidor `dynamic_qr.parse`/`looks_like` y `contacts.parse_scanned`. Una vCard ajena (otro formato) se deja igual.
- Lector de mano (el que «teclea»): la vCard llega en varias líneas, cada una con su Enter; `QrCode.collect()` las junta (Directorio, Áreas, Inventario, Registro) y descarta lo que quede a medias a los 5 s.
- Dibujo: `badge-render.js` (`drawQr`) y `digital_badge.html` usan nivel de corrección **L** (en vez de M) y UTF-8 (tildes y ñ). Wallet (`digital_public._wallet_args`) manda la vCard con el código estático firmado; `wallet.py` pasa el Apple Wallet a `utf-8`.
- El teléfono solo entra al QR si el dato ya viene en la escarapela: en la digital pública, solo si el evento lo marcó como visible (mismo criterio de `/b/{token}/data`).

**Densidad (parámetros de impresión intactos).** El tamaño del elemento QR y de la etiqueta no se tocó (`tests/test_impresion_parametros_fijos.py` pasa). Medido con la librería real (`tests/js/qr_vcard_check.js`): el QR anterior era versión 4 (33 módulos); la vCard típica queda en versión 8 (49 módulos) con nivel L, y el peor caso razonable (nombres larguísimos + teléfono con indicativo) en versión 10 (57). Con nivel M serían 1-2 versiones más. Recomendación: el elemento QR de la plantilla debe medir **25 mm o más** (0,45 mm por cuadrito en versión 8; en 20 mm baja a 0,36 mm y se vuelve exigente para la QL-800). **No pude probar la impresión física ni la lectura con celulares reales**: hay que imprimir una escarapela de prueba en la QL-800 y escanearla con un iPhone y un Android antes de usarlo en un evento.

**Archivos congelados** renovados a propósito (huellas en `tests/test_publico_congelado.py`): `badge-render.js`, `digital_badge.html`, `badge_print.html`, `certificate_public.html` (solo se agregó el `<script>` de vcard.js).

### 2. Ruleta
**Qué hace / cómo se usa** (pantalla «Apariencia» de la ruleta, que ve el coordinador):
- **Datos del ganador:** el nombre siempre sale. El coordinador marca lo demás: Empresa (marcada por defecto, como antes), Correo, Cargo, Tipo de asistente y cada campo opcional con nombre del evento (ahí vive la Ciudad u otros). Lo que la persona no tenga lleno no se muestra. Aviso en pantalla: lo marcado lo ve el público.
- **Logos o banners de arriba:** hasta 4 imágenes en una franja arriba de la pantalla del sorteo (y de la vista previa). Se suben con el mismo cargador de imágenes de la ruleta (`upload-image` → `app/storage.py`).
- **Cómo gira:** «Dura un tiempo fijo» (como antes) o «Giro libre»: un clic en «Girar» inicia, la ruleta gira sin parar y otro clic en «Detener» la frena sobre el ganador. Funciona en la ruleta circular y en el estilo casino, y también en la vista previa («Probar animación»).

**Decisiones.**
- No hay migración: `winner_fields`, `top_images` y `spin_mode` van en `style_json` (con valores por defecto, así las ruletas ya configuradas no cambian).
- El ganador sigue decidiéndose en el servidor al pulsar «Girar»; «Detener» solo es la animación. No cambia la auditoría ni el sorteo real.
- Seguridad: la pantalla pública sigue sin recibir la cédula; si el coordinador desmarca la empresa, ni siquiera viaja. Imágenes: solo del propio cliente, extensiones de imagen, máximo 4.
- Para no dejar la pantalla colgada, el giro libre se frena solo a los 2 minutos. Si hay varios ganadores en un mismo sorteo, cada uno pide su «Detener». Un giro que se muestra en otra pantalla (no la que pulsó) usa el tiempo fijo.
- La «Ciudad» no es una columna de la persona en la base; sale de los campos opcionales con nombre del evento (p. ej. uno llamado «Ciudad»).
- `roulette_display.html` y `roulette-render.js` son archivos congelados: huellas renovadas con esta orden.

**Probado.** Con Chromium (arnés con datos ficticios): giro libre circular y casino, «Detener», tarjeta con datos, franja de logos, pantalla angosta y la pantalla de Apariencia. Pruebas pytest con base (`tests/test_ruleta_fase10.py`) escritas pero no ejecutadas aquí.

### 3. Calendario y «Categoría (tipo de evento)»
**Qué hace.** Arriba del calendario hay chips clicables de «Categorías de evento» con cuántos eventos hay de cada una en el periodo. Se pueden activar varias; «Ver todas» las quita. Lo ve cualquiera que vea el calendario (mismo código para todos los roles) y funciona en Mes, Semana y Día. Se suma al selector «Estado del evento» (se aplican los dos).

**Decisión de Juan David (10-nov).** Las categorías **no son los estados**: son el **tipo de evento**. Por eso existe el campo nuevo **«Categoría (tipo de evento)»** y los chips filtran por él. Un evento sin tipo cuenta como **«Sin categoría»** (chip al final).

**Lista de tipos.** Tabla `event_types` (migración **`0128_event_types`**, a mano, `down_revision` `0127_person_change_log`, compatible con el pooler de Neon) + `events.event_type_id` (nullable, con índice). Siembra: Feria, Congreso, Corporativo, Social, Otro (con color). La administra el **super_admin** en **Configuración › Tipos de evento** (pestaña solo para él): agregar, renombrar, color opcional (o quitarlo), archivar y restaurar. No se borra: un tipo archivado deja de ofrecerse, pero los eventos que ya lo tienen lo conservan y el calendario lo sigue mostrando. Cada cambio queda en `audit_actions`.

**API** (`app/routers/event_types.py`, prefijo `/api`): `GET /event-types` (coordinador o más; `include_archived` solo super_admin), `POST /event-types`, `PATCH /event-types/{id}`, `POST /event-types/{id}/archive` y `/restore` (super_admin). Nombres únicos sin importar mayúsculas (máx. 80); color `#RRGGBB`. Crear/editar evento valida con `check_assignable`: el tipo debe existir y no estar archivado (conservar el que ya tiene sí se permite).

**Dónde aparece el campo.** Asistente «Nuevo evento» (sección Datos del evento, justo después del nombre; las plantillas guardadas antes lo reciben solas en `merge_missing_base`) y modal de edición (`?editar=`, selector `#eeEventType`; si la lista no carga, el selector se deshabilita y no se envía, para no borrar el tipo por accidente). Historial por campo: el snapshot guarda el **nombre** del tipo. Exportar/importar evento (`event_transfer`): viaja por **nombre**; si no existe en el destino, el evento queda «Sin categoría» con una advertencia en el informe.

**Archivos.** `alembic/versions/0128_event_types.py`, `app/routers/event_types.py`, `app/models.py`, `app/routers/events.py`, `app/event_template.py`, `app/event_history.py`, `app/event_transfer.py`, `static/js/event-types-admin.js`, `static/js/event-field-render.js`, `static/js/nuevo-evento.js`, `static/js/calendar-cats.js` (solo cambió `categoryOf`), `templates/configuracion.html`, `templates/_event_edit_modal.html`, `templates/calendario.html`.

### Ajustes tras probar staging (10-nov, bloque C)
- **Categoría en «Editar evento» (bug).** El selector existía pero estaba dentro del grupo plegable «Superevento y pañoleta», por eso quien miraba «Datos del evento» (Nombre, Estado, Observaciones) no lo veía. No dependía de la plantilla guardada. Ahora está SIEMPRE en «Datos del evento», justo bajo el nombre, para todos los eventos (viejos incluidos); vacío = «Sin categoría». Prueba de texto: `test_edit_modal_shows_the_category_in_the_first_group_for_every_event`.
- **Opciones de la categoría desde el diseñador de plantilla** (`/configuracion/plantilla-evento`, panel del campo «Categoría (tipo de evento)», debajo de «Obligatorio»): lista, agregar, renombrar, color, archivar, ver archivadas y restaurar (`static/js/event-type-options.js`). Es la MISMA tabla `event_types` y la misma API/permiso que la pestaña «Tipos de evento» de Configuración (solo super_admin escribe; un admin ve la lista). Cada cambio se guarda al instante (no espera el botón Guardar de la plantilla) y se ve de inmediato en el selector de Nuevo/Editar evento y en los chips del calendario, porque todos leen la misma tabla.

### Ruleta: tamaño de logos y de los datos del ganador (ajuste tras staging)
- **Por logo/banner** (Apariencia › Imágenes): deslizador de tamaño (4 a 40 % del alto de la pantalla; por defecto 18, antes ~13) y alineación Izquierda/Centro/Derecha. Se guarda en `style_json.top_images_cfg` (una entrada por imagen, en el mismo orden; el servidor la normaliza y la recorta/rellena al número de imágenes).
- **Texto del ganador** (Apariencia › Datos del ganador): escala del nombre (`name_scale`, 50-300 %, por defecto 100) y de los demás datos (`fields_scale`, por defecto 150 %, que antes se veían pequeños en el proyector). Variables CSS `--rr-name-scale` y `--rr-fields-scale`.
- Vista previa en vivo: al mover cualquiera de los deslizadores se repinta la franja de logos y aparece un ganador de ejemplo. Sin migración. `roulette-render.js` (congelado): hash renovado con esta orden.

### Calendario sin eventos ni chips (bug de staging) y grupo «Tipo de evento»
- **Causa.** El 9-nov (Fase 5 A) se agregó `GET /api/events/{event_id}` en `events.py`, que se incluye ANTES que el router del calendario. La ruta tragaba `GET /api/events/calendar` (tomaba «calendar» como id y respondía 422). La página ignoraba el error de eventos (solo fallaba si fallaban eventos Y recordatorios), pintaba «No hay eventos ni recordatorios en este mes» y, como no había eventos, ocultaba los chips. El Inventario no se afectó porque usa `/api/inventory/calendar`. Arreglo: la ruta ahora es `/events/{event_id:int}` (ya no recibe «calendar») y la página muestra «No se pudo cargar el calendario» si la API falla, en vez de un calendario vacío. No hay una regla que oculte eventos a propósito: el calendario muestra todos los no archivados del periodo que la cuenta puede ver (por cliente y pertenencia).
- **Chips siempre visibles.** El grupo sale aunque el mes esté vacío: «Todos» + todos los tipos vigentes del catálogo (`/api/event-types`) con su conteo (0 incluido) + «Sin categoría».
- **Grupo con título «Tipo de evento»**, componente compartido por Calendario e Inventario › Dónde está cada equipo (`static/js/calendar-cats-ui.js`, `static/css/gw-calendar-cats.css`), con el chip «Todos» (activo cuando no hay ninguno elegido). Verificado con Chromium en claro, oscuro y ancho de celular (calendario).
- **«Formulario Web» en Inventario.** El código no inventa tipos: los chips salen de `events.event_type_id` → tabla `event_types`. Si aparece «Formulario Web», es una fila de esa tabla creada en staging (Configuración › Tipos de evento o desde el diseñador) y algún evento la tiene asignada; el origen del evento (base/manual/autoregistro) no se mezcla. Si no debe ser un tipo, se archiva o renombra desde Configuración (los eventos que la tengan pasan a verse con su nombre hasta reasignarlos).

### Pruebas del bloque
`tests/test_qr_vcard.py`, `tests/js/qr_vcard_check.js`, `tests/test_ruleta_fase10.py`, `tests/js/calendar_cats_check.js`, `tests/test_tipos_evento.py`. Corren aquí las puras y las de texto/Node; las que usan base (resolver QR con vCard, ruleta con estilo y sorteo, pantalla pública) se corren en Cloud Shell.

---

## Costos (Neon/Cloud Run): el Job horario ahora es económico

**El problema, en simple.** Neon cobra por las horas que su motor está encendido y se apaga solo después de 5 minutos sin que nadie le pregunte nada. El Job `golden-ops-hourly` le preguntaba algo **cada hora** (respaldo, cola, precalentamiento…), así que Neon casi nunca llegaba a dormirse, aunque no hubiera ningún evento.

**Qué cambió.** El Job sigue avisando igual, pero ahora **piensa antes de despertar la base**:
1. Si el aviso llega muy pronto después del anterior (menos de `OPS_MIN_INTERVAL_MINUTES`, por defecto 50), sale al instante sin hacer nada.
2. Cada tarea (respaldo por hora, respaldo diario, purga de biometría, archivado semanal, importación mensual de costos, copia a OneDrive, revisión de respaldos, limpieza de reportes) **recuerda cuándo salió bien por última vez** (archivo `ops/steps.json` en el almacenamiento, no en la base) y solo corre si ya le toca. Así da igual si el Scheduler avisa cada hora o cada 2 horas: nada se pierde. Si una tarea falla no se anota y se reintenta en el siguiente aviso.
3. Lo primero que toca la base es **una sola consulta** (tres conteos): ¿hay eventos «en proceso»?, ¿alguno empieza en las próximas 6 horas?, ¿hay trabajos pendientes en la cola? Solo se hace si hubo actividad en las últimas 3 horas o si toca el «turno de reposo» (cada 4 h).
4. **Sin eventos en proceso ni cercanos:** no hay precalentamiento (solo se bajan a cero las instancias mínimas si estaban arriba, sin tocar la base), no se barre la cola si no hay trabajos vencidos y el respaldo por hora pasa a cada 8 h.
5. **Con eventos (o actividad):** todo como antes: respaldo cada ~hora, precalentamiento y cola.

**Lo que NO cambia (las reglas):** respaldo diario y purga biométrica **una vez al día** (a partir de las 3 y las 4 a. m.; si el Job no cae justo a esa hora, corre en el primer aviso posterior ese día); archivado de eventos a los 90 días semanal; los rostros se borran a los 7 días de finalizado el evento igual que antes; alertas por correo igual (máximo cada 6 h por problema).

**Qué puede hacer Juan David (opcional, desde Cloud Shell):**
- Sin tocar nada ya se ahorra: el Job sigue cada hora pero casi siempre sale sin despertar la base.
- Para ahorrar un poco más, pasar el Scheduler a cada 2 horas: `OPS_SCHEDULE="5 */2 * * *" bash deploy/gcp/scheduler.sh <entorno> ensure` y ponerle al Job `OPS_MIN_INTERVAL_MINUTES=110`. En ese caso conviene `OPS_SCHEDULE_MAX_AGE_H=2.5` al correr `scheduler.sh check`. Los respaldos con actividad quedan entonces cada 2 h (no cada hora); si se quiere conservar «máximo 1 h de pérdida» durante eventos, **no** cambiar el Scheduler.
- `BACKUP_HOURLY_MAX_AGE_H` debe seguir en 9 (ya está así en `common.yaml`): sin actividad el respaldo por hora llega cada 8 h.

**Variables nuevas (todas opcionales):** `OPS_MIN_INTERVAL_MINUTES` (50), `OPS_IDLE_EVERY_H` (4), `OPS_IDLE_BACKUP_H` (8), `OPS_EVENT_LOOKAHEAD_H` (6), `OPS_REPORTS_EVERY_H` (6); `OPS_SCHEDULE` y `OPS_SCHEDULE_MAX_AGE_H` solo para `scheduler.sh`. Sin migración. `hourly-full` corre a mano la versión anterior (todo según la hora).

**Otras rutas revisadas.** `/health` no toca la base (hay prueba), en Cloud Run el nodo de la cola usa Cloud Tasks (sin hilo que consulte), los sondeos del navegador del personal ya se pausan solos tras 60 s sin uso (`GW.poll`). Corregido: la **pantalla de TV de turnos** consultaba cada 3 s sin parar aunque quedara olvidada toda la noche; ahora pasa a cada 10 s si nada cambia en 5 min y a cada 30 s a los 30 min, y vuelve a 3 s en cuanto cambia algo o se vuelve a mirar la pestaña. No se tocaron páginas públicas congeladas ni impresión.

**Cuánto se espera ahorrar (estimado, no medido).** Neon a 0,25 CU encendido todo el mes cuesta ~US$19. Antes, cada despertar horario dejaba el motor prendido ~8 a 12 minutos (el respaldo más los 5 min de gracia) → ~4 h/día ≈ 120 h/mes. Ahora, un día sin eventos despierta la base ~6 a 8 veces (consulta cada 4 h, respaldo cada 8 h, diario y purga) ≈ 1 h/día ≈ 30 a 40 h/mes: **alrededor de un 70 % menos de horas de cómputo** en los días sin eventos. Los días con eventos cuestan lo mismo que antes (la base está en uso de todos modos). Valor real: compararlo en la consola de Neon (Billing → Compute hours) una semana después de desplegar.

**Sin probar aquí.** Las pruebas de `tests/test_ops_economico.py` corren sin base (`pytest --noconftest`); la consulta SQL de la sonda (`PROBE_SQL`) y el flujo con almacenamiento real y Neon quedan para verificar en Cloud Shell/staging (mirar el JSON que imprime el Job: `probe`, `skipped`). En staging, revisar que tras un evento las instancias mínimas bajen a 0 (paso `warmup-down`).

### 4. Barra de formato de los textos enriquecidos en tema oscuro (ajuste 7)

La barra (negrita, cursiva, subrayado, color, tamaño, letra, alineación, listas) y el cuadro de escritura de `static/js/rich-text.js` traían colores fijos claros, por eso en oscuro se veían blancos y rotos. `rich-text.js` es un archivo congelado (huella), así que no se tocó: `static/css/gw-editor-form.css` la reestiliza con tokens `--gw-*` (fondo, bordes, botones, selectores, estados hover/activo/foco, cuadro de texto). El único otro texto con formato editable de la app (el cuerpo del correo en Parámetros, `.gw-pm-editor`) ahora también toma fondo y color del tema. El único lugar que monta la barra es el editor de formularios. Revisado en Chromium en claro y oscuro. El cuadro de color del navegador conserva su negro por defecto (lo fija el JS congelado).

## Ajustes del 11-nov-2026 (revisión de staging)
- **Inventario › Dónde está cada equipo:** tablero del día (eventos con material, unidades, equipos distintos y faltantes, con una tarjeta por evento y sus equipos principales); en el mes, cada evento es una cinta con color de su tipo y su cantidad, y cada día muestra su total («N uds»). En pantallas angostas el mes pasa a ser una agenda de los días con material (antes eran puntos).
- **Inventario › Catálogo:** selector de día (anterior, siguiente, Hoy y calendario). `GET /api/inventory/overview?day=AAAA-MM-DD` devuelve usos y disponibles de ese día (sin `day`, hoy).
- **Ruleta:** el tamaño de «más datos» no se veía en la proyección porque una regla repetida de `gw-ruleta-display.css` lo anulaba (corregido). Nueva pestaña **Sorteos en fila**: se guarda una copia del sorteo configurado en «Cómo se elige», cada paso con su forma de girar (tiempo fijo o libre) y arranque (clic o solo tras una pausa); `PUT /roulette/queue`, `POST /roulette/authorize {queue:true}` y el giro avanza de paso sin pedir otra autorización. Sin migración (la fila vive en `behavior_json`). Editar la fila cancela una autorización de fila vigente. Huella de `roulette_display.html` renovada a propósito.
- **Volver al kiosco:** `static/js/kiosk-back.js` (cargado desde el menú lateral) pone el botón junto al título en toda pantalla `/kiosk/<id>/<sección>`.
- **Editar persona:** se quitó «¿Es cédula nueva?» (solo aplica al registro nuevo).
- **Parámetros › Permanencia:** «Paso 1 · Medir (solo informativo)» y «Paso 2 · Exigir el porcentaje», con un resumen que dice qué efecto tiene hoy.
- **No probado aquí (sin base de datos):** los endpoints de la fila de sorteos y el filtro por día (corren en Cloud Shell con pytest); la parte visual sí se revisó con el arnés (computador, celular, claro y oscuro).
- **Segunda ronda (11-nov, tarde):** la fila de sorteos ya no tiene su propio «Guardar»: se registra en el guardado general (`GWParams`, clave `queue`) y se guarda con la barra «Guardar cambios». «Volver al kiosco» pasó a una píldora dorada con borde claro en la franja azul «Cliente · Evento · Código» (si la pantalla no tiene franja, queda en una fila propia sobre el contenido), así no mueve el título. En el Kiosco, «Más herramientas» abre desplegado por defecto (se puede plegar).

## Ajustes del 12-nov-2026

Pedidos de Juan David tras ver producción (commit 25cccaa) en una ventana de navegador algo más pequeña de lo normal.

### 1. Filas que se descuadraban (botones y textos)
- **Causa:** la fila de cada formulario (`kiosk_formularios`, `p-formularios.css`) se ponía en UNA línea cuando la ventana medía ≥ 901 px, pero la barra lateral le quita ~276 px: con ventanas de 1100-1450 px los botones («Archivar», «⋯») se salían por la derecha y aparecía scroll horizontal. Medir la ventana era la pregunta equivocada.
- **Arreglo:** la fila delgada ahora depende del ANCHO DE LA LISTA (`container: forms / inline-size`, `@container forms (min-width: 1240px)`). Más angosta, conserva la tarjeta (las acciones saltan de línea). También se ensanchó la columna «Inscripciones / Cupo» para que «Cupo» no se corte. Probado de 1000 a 1800 px y en celular con la herramienta de capturas: sin desborde.
- **Regla para pantallas nuevas:** una lista de una sola línea con botones se decide por el ancho del contenedor, no por el de la ventana.

### 2. «(opcional)» en negrilla
`static/js/form-render.js`: el «(opcional)» de los campos no obligatorios de los formularios públicos pasa de letra fina y apagada a `font-weight:700` (sin opacidad). Hash de `tests/test_publico_congelado.py` renovado A PROPÓSITO, con orden expresa.

### 3. Cliente temporal del evento
- **Qué es:** en «Usuarios del evento › Nueva cuenta», el rol «Cliente (temporal, con usuario y contraseña propios)». Tiene los MISMOS permisos que el digitador temporal (su rol sigue siendo `digitador`; columna nueva `staff_users.client_temp`, migración `0129_staff_client_temp`), pero entra con un usuario `cli-xxxxxx` y una contraseña aleatoria de 14 caracteres generados por el servidor (`app/temp_client.py`), SIN la solicitud de ingreso que autoriza el coordinador (`login_control.applies` lo excluye).
- **Entrega:** el usuario y la contraseña se muestran UNA sola vez a quien crea la cuenta (panel verde con «Copiar»); no se guardan en claro, no van por correo ni a los registros. Si se pierden: «Restablecer contraseña» genera una nueva (`PUT /api/staff/{id}/password` con `{"generate": true}`).
- **Qué se mantiene:** el bloqueo por intentos fallidos de `security` (por usuario+IP) sigue valiendo; el compromiso digital, la eliminación con «Eliminar los usuarios temporales», el alcance por evento y las puertas `get_event_for_staff` / `require_event_in_progress` son las del digitador.
- **Decisiones (documentadas porque eran ambiguas):** no lleva correo (el correo nunca lleva contraseñas y su texto habla de la cédula); la contraseña no vence ni obliga a cambiarla (cuenta del evento); sin «Permitir / No permitir / Desbloquear» en su fila.
- **Pruebas:** `tests/test_ajustes_nov12.py` (de texto, sin base de datos). Pendiente: prueba con base de datos (crear, ingresar sin autorización, restablecer) en la sesión de pruebas completas.

### Archivos de formularios (11-nov-2026)
- **Respuestas:** un botón «Descargar todos: <columna> (ZIP)» por cada columna de archivo (`GET /events/{e}/forms/{f}/files-zip?field=…`; nombres `cedula_Columna.ext`; sin pruebas salvo que la casilla esté marcada; tope 1.000 archivos / 300 MB; queda en auditoría).
- **Editar persona:** los campos de archivo vinculados al registro (`opcional_N`) se muestran como enlace «Descargar <archivo>» (`GET /api/events/{e}/users/{id}/form-files`, coordinador+). Al cargar a la base ya no se guarda el diccionario como texto, solo el nombre (`formfiles.stored_text`). Lógica pura en `app/formfiles.py`.
