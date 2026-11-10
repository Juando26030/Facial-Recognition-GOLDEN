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

**Cómo se usa (para Juan David).**
1. El coordinador entra a «Acta de novedades», escribe el título y lo ocurrido, y guarda.
2. Abre el acta, dibuja su firma y pulsa «Firmar».
3. El cliente entra con su cuenta de cliente, abre el acta, dibuja su firma y pulsa «Firmar».
4. Con las dos firmas el acta queda «Firmada» y el texto ya no se puede cambiar. «Imprimir» abre el documento; desde el cuadro de impresión se guarda como PDF. «Descargar» baja el archivo.

**Permisos.** Escribe y firma por el coordinador: coordinador, admin y super_admin. La comercial ve las actas pero no las escribe. El cliente (rol cliente autorizado al evento, evento en proceso) ve y firma SOLO la suya; nadie puede firmar por otro. El digitador no entra. Todo pasa por `get_event_for_staff` y la base archivada la bloquea.

**Reglas.** Si ya hay una firma y se cambia el texto, el sistema avisa y, si se confirma, quita la firma (hay que firmar de nuevo). Un acta firmada no se edita ni se borra (si hace falta corregir, se crea otra). Un borrador sin firmas se puede borrar. La firma se guarda como imagen PNG por `app/storage.py` (carpeta `<cliente>/event_acts/<evento>/`); en la base queda el nombre de quien firmó, la fecha y la huella SHA-256 del texto firmado.

**Decisiones.**
- No hay biblioteca de PDF instalada: el documento es HTML imprimible autónomo (las firmas van dentro). Si se quiere PDF directo hay que agregar una biblioteca.
- La firma del cliente se hace con su cuenta (no hay enlace público aparte): evita abrir una puerta pública nueva. Si el cliente está presente sin cuenta, hoy no puede firmar (ver preguntas).
- La firma es siempre negra sobre papel blanco, también en modo oscuro, para que se vea igual en el documento.
- Los exportes de evento entre entornos (`event_transfer`) todavía no incluyen las actas ni sus firmas.
- Migración `0126_event_acts` (tabla `event_acts`). Al integrar, su `down_revision` debe apuntar a la última migración de los bloques A/B (hoy apunta a `0121_infra_costs`).

**Archivos.** `app/event_acts.py`, `app/routers/event_acts.py`, modelo `EventAct` en `app/models.py`, `templates/kiosk_actas.html`, `static/js/kiosk-actas.js`, `static/css/gw-actas.css`, `tests/test_event_acts.py`, `tests/test_pledge_prefill.py`.

**No probado aquí.** Los endpoints con base de datos (las pruebas están escritas en `tests/test_event_acts.py`, para correr en Cloud Shell) y la firma en pantalla táctil real; sí se vio en Chromium con respuestas simuladas, en claro/oscuro y a 1200 y 390 px.

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

**Explicación para Juan David:** `docs/EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md`.

### Pruebas
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

## Bloque C — QR en vCard, ruleta y calendario

Sin migración (la configuración de la ruleta vive en `style_json`, que ya existía).

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

### 3. Calendario
**Qué hace.** Arriba del calendario hay chips clicables de «Categorías de evento» con cuántos eventos hay de cada una en el periodo. Se pueden activar varias; «Ver todas» las quita. Lo ve cualquiera que vea el calendario (mismo código para todos los roles, sin condiciones por rol) y funciona en Mes, Semana y Día.

**Decisión.** Los eventos no tienen un campo «tipo/categoría» propio; la categoría que el equipo ya maneja con color es el **estado del evento** (Configuración › Estados de evento; si el evento no tiene uno propio, Creado / En proceso / Finalizado). Los chips usan eso, con su color. Se suma al selector «Estado del evento» que ya existía (se aplican los dos). **Pregunta para Juan David:** si «categorías» se refería a otra cosa (p. ej. tipo de evento: feria, congreso…), hay que crear ese campo en la plantilla de evento y los chips lo usarían con el mismo código (`static/js/calendar-cats.js`, solo cambia `categoryOf`).

**Archivos.** `static/js/calendar-cats.js` (lógica pura, `tests/js/calendar_cats_check.js`), `templates/calendario.html`, `static/css/p-calendario.css`.

### Pruebas del bloque
`tests/test_qr_vcard.py`, `tests/js/qr_vcard_check.js`, `tests/test_ruleta_fase10.py`, `tests/js/calendar_cats_check.js`. Corren aquí las puras y las de texto/Node; las que usan base (resolver QR con vCard, ruleta con estilo y sorteo, pantalla pública) se corren en Cloud Shell.
