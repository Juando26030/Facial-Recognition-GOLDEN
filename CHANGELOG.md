# Registro de cambios — Orum (antes GoldenWeb 2.0)

Qué cambió, cuándo y para quién, en orden del más reciente al más viejo. Formato libre inspirado en «Keep a Changelog»: una sección por
despliegue o por bloque entregado, con la migración de Alembic que trae y el documento donde está el detalle. **Este archivo se escribe al
cerrar cada pieza** (ver `CONTRIBUTING.md` § Definición de «hecho»). Lo anterior al 1-nov-2026 está en `docs/historial.md` y en los cierres
de fase (`docs/CIERRE_*.md`); este archivo arranca en noviembre de 2026 y se armó el 22-nov-2026 a partir de `docs/historial.md`,
`docs/ESTADO_2026-11-11.md`, `docs/FASE_10_AJUSTES_NOV10.md`, `docs/25_INVENTARIO_POR_BASE.md`, `docs/23_EVENTO_COMPARTIDO_NUBE.md` y el historial de git.

Estados: **Producción** = corre en `app.golden-eventos.com` · **Staging** = probado en staging, pendiente de autorización · **Rama** = construido, sin probar con base.

## 2026-11-28 (hotfix, tarde) — Escáner y entregas de inventario
- **La cámara se cierra también cuando la persona NO está en la base** (Control de Inventario y Control de Zonas): el aviso rojo «Sin coincidencias» quedaba escondido detrás de la cámara. Si el código no se reconoce (no es una cédula ni un QR válido) la cámara sigue abierta con su aviso, como antes.
- **Sin recuadro guía en el modo QR** (confundía: el QR se lee en cualquier parte del cuadro). Se conserva el zoom «Acercar» y la lectura de cédula vieja/nueva con su zoom.
- **Devolver entregas por elemento** (Historial de entregas de una persona; solo coordinador en adelante, igual que el historial): botón «Devolver» en cada línea → `DELETE /api/events/{id}/inventory/deliveries/{delivery_id}`. Borra esa línea (queda como si nunca se hubiera entregado), su cantidad vuelve al inventario, la persona puede recibirlo otra vez y queda auditado (`revert`, sin cédulas). De una entrega con varios ítems se devuelve solo uno. Con el evento en servidores locales NO se permite (no se sincroniza y podría reaparecer). Sin migración.
- **Historial de entregas en celular:** hasta 640 px la tabla pasa a una tarjeta por entrega con sus rótulos (antes: una letra por fila), en el historial y en «Últimas entregas».
- **«Texto al escribir» general del evento** (Parámetros › Formulario de persona, arriba del todo): UNA sola opción —«Como lo escriban», MAYÚSCULAS, minúsculas o Primera Mayúscula— que vale para el formulario PREDETERMINADO y para el a la medida (en este, cada campo aún puede tener la suya). Aplica a nombres, apellidos, cargo, entidad y campos de texto en «Registrar nuevo» y «Editar», mientras se escribe (`static/js/text-case-default.js` en el formulario de siempre) y otra vez al guardar en el servidor (también en lo que llega de la bandeja sin red). Cédula, correo (siempre minúsculas), teléfono, listas y fechas no cambian. Sin migración (va en el mismo JSON del diseño); sube la versión del diseño. Requiere `PERSON_FORM_ENABLED` encendido, como el diseñador.
- Pruebas: `tests/test_estadisticas_rediseno.py` (devolución y piezas), `tests/test_cedula_camara_busqueda.py`.

## 2026-11-28 — La plataforma pasa a llamarse **Orum** (by Golden Eventos y Logística)
- Nuevo nombre de producto: **Orum** (Or de Oro + um de Forum), pensado para venderse como SaaS. Reemplaza «GoldenWeb 2.0» en títulos de pantalla, correos, alertas, PDF, textos de ayuda, README y guías. Lo HISTÓRICO (este registro, `docs/historial.md`, notas de versiones pasadas, textos de la auditora) conserva el nombre de su época.
- Logo propio (aro azul marino con punto dorado + «rum», generado con Higgsfield): `static/img/orum-logo.svg`/`-oscuro.svg`/`orum-mark.svg` (+ PNG); favicon y ícono de celular nuevos. Login, cambio de contraseña e ingreso en espera muestran el logo y «by Golden Eventos y Logística» (`.gw-orum` en `design-system.css`); hay una versión para fondos oscuros (también de Higgsfield) y `static/js/gw-orum.js` la activa sola cuando detecta un fondo oscuro. El logo de Golden sigue en el encabezado de las pantallas internas, en escarapelas, certificados y documentos (es el de la empresa/evento).
- **Créditos de autoría:** pie pequeño en TODAS las páginas, en español e inglés, «Software diseñado y creado por Juan David Ramírez Juzga» (`app/credits.py`, middleware de `app/main.py`); más `NOTICE.md`, `AUTHORS.md`, `<meta name="author">` y `__author__`.
- NO cambia (a propósito): dominios, nombres de proyectos y servicios en la nube (`goldenweb-prod`, `golden-web`…), la carpeta de respaldos «Respaldos GoldenWeb» en SharePoint, el repo. Identidad completa: `docs/ux/MARCA_ORUM.md`.

## 2026-11-27 (noche, 2) — Digitadores: una cuenta por cédula, en cualquier cliente y evento
- **Regla (Juan David):** un digitador temporal puede estar en cualquier evento de cualquier cliente. Si la cédula ya tiene cuenta de digitador, se carga su información y simplemente se **asigna** al evento; nunca se duplica ni se le cambia el cliente. Vale por las cuatro vías: enlace del compromiso, «Crear y asignar» a mano (antes daba «Ya existe una cuenta»), «Asignar cuentas ya existentes» y el Excel (antes solo un admin podía asignar cuentas de otro cliente). Un digitador desactivado solo lo reactiva un admin; otro tipo de cuenta (admin, coordinador…) o archivada no se asigna.
- **Precargado del compromiso sin asteriscos:** al escribir la cédula llegan nombre, celular, familiar y teléfono del familiar COMPLETOS y editables (por si cambió el teléfono del familiar). Decisión expresa de Juan David; cualquiera que sepa una cédula puede leer esos datos (se le advirtió). Se quitó el enmascarado y la restauración en el servidor.
- Pruebas: `tests/test_pledge.py::test_public_link_prefills_complete_and_editable_by_cedula`, `::test_create_by_hand_and_excel_reuse_digitador_of_another_client`, `tests/test_pledge_prefill.py`.

## 2026-11-27 (noche) — Compromiso: digitadores de otro cliente ya no quedan en el limbo
- **Qué pasaba:** un digitador que ya había trabajado para OTRO cliente (cuenta de ese cliente) llenaba el enlace del compromiso de este, veía «¡Listo!» pero el envío se descartaba entero (no creaba cuenta ni compromiso y no dejaba rastro). Caso real: dos digitadores del evento 25 que venían del evento 22 (otro cliente); lo llenaron dos veces.
- **Arreglo:** `pledge.resolve_account` reutiliza y asigna al evento cualquier digitador activo, sea de este cliente o de otro (una cuenta por cédula; no se le cambia de cliente). Si es un digitador desactivado o archivado, ahora se le dice «avísale al coordinador» en vez de un «¡Listo!» falso, y queda `pledge_conflict` en la auditoría con el id de la cuenta (nunca la cédula). Las cuentas que no son de digitador siguen respondiendo igual que un éxito (no se revela qué cédulas existen).
- **Datos:** esas dos personas se asignaron a mano al evento 25 (quedan sin firmar y firman al ingresar con su cédula, o por el enlace una vez desplegado esto). No se pueden saber otros casos: el envío descartado no dejaba rastro.
- Pruebas: `tests/test_pledge.py::test_flow_a_reuses_digitador_account_of_another_client` y `::test_disabled_or_archived_digitador_is_told_instead_of_a_false_ok`.

## 2026-11-27 (tarde) — Compromiso: precargado por cédula
- Al escribir la cédula en el enlace del compromiso, si ya es de un digitador de cualquier evento o cliente, se precargan nombre, celular, familiar y su teléfono (ocultos en parte en el navegador; el servidor guarda los reales si no los toca). Solo queda responder las 5 preguntas, marcar las casillas y firmar. Sin migración. Detalle y límites: `docs/FASE_4_COMPROMISO.md`. Pruebas: `tests/test_pledge_prefill.py`, `tests/test_pledge.py::test_public_link_prefills_masked_by_cedula_and_restores_real_values`.

## 2026-11-27 — Usuarios del evento: dos Excel
- **«Descargar lista de usuarios en Excel»**, al lado de «Cuentas asignadas a este evento»: todas las cuentas del evento (digitadores primero; las demás con su rol al lado del nombre) con el formato del listado de Golden (línea amarilla con la fecha y el horario, recuadro azul con los datos del evento, «#, NOMBRE, CÉDULA»). `GET /api/events/{id}/staff-users/export.xlsx`, `app/staff_xlsx.py`.
- **«Respuestas del compromiso en Excel»**: todo lo que llenó cada digitador (celular, familiar y su teléfono, cada pregunta de salud con su «¿Cuál?», contrato, asistencia, autorización, fecha), en amarillo quien tiene alertas y «Sin firmar» para quien falta. Lleva datos sensibles por decisión de Juan David: solo coordinador y admin+, auditado sin datos, con aviso en el archivo (ver `docs/FASE_4_COMPROMISO.md`). `GET /api/events/{id}/pledge/export.xlsx`.
- Sin migración. Pruebas: `tests/test_staff_xlsx.py`, `tests/test_pledge.py::test_excel_exports_answers_and_staff_list`.

## 2026-11-26 (noche, 3) — Parámetros: «Configurar evento por cuestionario» · **Rama**
- **Pedido de Juan David:** una primera pestaña en Parámetros del evento (arriba de «Registro y pantalla») con preguntas de sí/no y de opción cerrada, en lenguaje natural, que dejen configurado todo el evento sin entrar sección por sección.
- **Cómo funciona** (`app/setup_quiz.py`, `static/js/event-quiz.js`): 8 bloques y ~40 preguntas (personas y registro, rostro, invitaciones al celular, escarapelas/roles/certificados, zonas, entregas, turnos, datos y código); algunas aparecen según lo respondido. Cada respuesta cambia los MISMOS interruptores y opciones de las demás pestañas (quedan «Sin guardar») y todo se guarda con el «Guardar cambios» de siempre: mismas validaciones, permisos e historial. Las preguntas sin responder muestran «Así está hoy» cuando se reconoce la configuración actual; si una respuesta guardada ya no coincide con la sección, se avisa y se ofrece «Aplicar esta respuesta».
- **«Requiere acción»** en amarillo con «!»: lo que una respuesta no deja hecho sola (cargar la lista, crear el formulario, subir el logo o el anexo, datos del organizador, diseñar la escarapela —una por rol si se pidió—, escribir las categorías, diseñar el certificado, crear zonas o productos, elegir la columna del producto, cargar dependientes, contraseña de desbloqueo, dónde imprime cada usuario, campos adicionales, formulario de persona) se marca en la pestaña («Requiere 3 acciones») y en la sección, y se lista en «Lo que falta hacer» con «Ir a la sección». Se calcula EN VIVO con el estado real del evento: al hacerlo, la marca se quita sola.
- Nuevo en otras pestañas: «Lista de personas» y «Formularios de inscripción» (Registro, con su enlace) y «Diseño de la escarapela» con «Una escarapela distinta por categoría» (Escarapelas; el mismo interruptor del diseñador). Respuestas en `app_settings` (`setup_quiz:<evento>`), sin migración. API: `GET/PUT /api/events/{id}/setup-quiz`.

## 2026-11-26 (noche, 2) — CRM: diseñador LIBRE del PDF de cotizaciones y proformas
- **Pedido de Juan David:** armar el PDF «como los certificados o las escarapelas». Antes, una plantilla nueva solo pedía encabezado, saludo y pie, y el diseñador (solo para cotizaciones) era una lista de bloques uno debajo de otro.
- **Hoja libre** (`static/js/crm_plantilla_hoja.js`, `app/crm/quote_free.py`, diseño `v: 2`): textos con datos ({{cliente}}, {{total}}, {{pagina}}…), imágenes, rectángulos y líneas que se arrastran, cambian de tamaño, van al frente o atrás y salen en la primera página, en todas o de la segunda en adelante; hoja Carta o A4; medidas en mm; capas; teclado (flechas, Suprimir).
- **Recuadro «Contenido»**: datos, tabla de productos, totales, condiciones y PDF insertado (los bloques de siempre) dentro de un recuadro que se mueve y se agranda; si no cabe, sigue en la página siguiente con sus propios márgenes.
- **Plantillas**: guardar (barra única), usar el diseño de otra, **exportar** a un archivo `.golden.json` con sus imágenes y PDF dentro e **importarlo** en otra plantilla o en otro entorno (staging → producción; cada archivo se revisa por su contenido, como al subirlo). Proformas con diseñador (sus datos: evento, ciudad, emisión, vence, estado) y su PDF con la huella del diseño (se regenera al cambiarlo). Una plantilla nueva pide solo tipo y nombre y abre el diseñador. Los diseños por bloques que ya existían se abren convertidos, sin perder nada, y siguen saliendo igual mientras no se guarden. Sin migraciones.

## 2026-11-26 (noche) — QR de 1 cm por cámara y búsqueda por código POR PANTALLA (migración 0169)
- **Cámara y QR pequeño (1 × 1 cm, el QR oficial):** la cámara se abría en su resolución por defecto (casi siempre 640×480: el QR quedaba de ~30 píxeles) y sin enfoque ni zoom. Ahora pide 1920×1080, enfoque continuo, zoom automático 2× donde la cámara lo permite (control «Acercar» para ajustarlo) y, cuadro de por medio, analiza el centro ampliado: un recuadro dorado indica dónde poner el QR (`static/js/qr.js`, `gw-captura.css`). Prueba con cámara simulada: lee con el QR ocupando ~60 px; antes no leía ni a 90 px en 640. Aplica a Registro, Inventario, Zonas, Almacén y Expositor (mismo componente).
- **Código de la persona: cómo se busca, en cada pantalla (0169).** En Parámetros › Campos › Código de la persona, al activar «Usar código» se despliegan «Obligatorio» y tres desplegables (Registro, Control de inventario, Control de zonas) con: primero la cédula y luego el código / primero el código y luego la cédula / solo por código / solo por cédula. Nuevas columnas `events.code_search_registro|inventario|zonas`; la migración copia lo que cada evento ya tenía (0166/0168) a las tres, así nada cambia al desplegar. `person_code.find_user(..., module)` y las pantallas (`window.EVENT_ID_ONLY`, `SearchCore` `idOnly`) usan el modo de su pantalla. Las claves viejas del API siguen sirviendo (aplican a las tres).

## 2026-11-26 (madrugada) — Estadísticas por recuadros, «Sin coincidencias» igual en todo, Zonas como Inventario
- **Estadísticas:** cada categoría grande del inventario (p. ej. «Alimentación») y «Otros productos» van en su propio recuadro con encabezado grande en mayúsculas, franja dorada y su porcentaje; en Zonas, cada zona con subzonas en su recuadro y las sueltas en «Otras zonas» (`static/js/stats-control.js`, `gw-estadisticas.css`).
- **«Sin coincidencias» en rojo, el MISMO en Registro, Inventario y Zonas:** un solo aviso en `SearchCore.noMatchHtml` (search-core.js). Sale al escribir, con Enter, con el lector y con la cámara, y dice qué se buscó (cédula, código o nombre). En Registro queda debajo del buscador (`#gwNoMatch` en `_gw_buscador.html`) y agrega «Si es una persona nueva, usa «Registrar nuevo»»; la ventana roja grande de la cédula por cámara sigue igual.
- **Zonas igual que Inventario:** el resultado sale justo debajo de la tarjeta de la persona; escribir quita tarjeta y aviso; «Personas en la zona» es una tabla alineada (fecha y hora, persona, cédula, movimiento); buscador del historial de UNA persona en todas las zonas, solo coordinador en adelante (`GET /api/events/{id}/areas/movements/person`, quién registró por nombre de cuenta). Sin migraciones.

## 2026-11-26 (madrugada, 2) — Inventario: historial por persona, tabla alineada y búsqueda más clara · **Rama**

- «Últimas entregas»: buscador del historial de UNA persona (cédula, nombre, código, lector o cámara), aparte del de arriba; solo coordinador en adelante
  (`GET /api/events/{id}/inventory/deliveries/person`, CONFIG_ROLE). La lista va en tabla con columnas alineadas (fecha y hora, persona, cédula, qué se entregó; en el historial, quién entregó).
- Al escribir otra búsqueda arriba se quita la tarjeta de la persona anterior (Inventario y Zonas). «Sin coincidencias» sale grande y en rojo, como el aviso de la entrega,
  y dice qué se buscó (código, cédula o nombre). En la tarjeta: «Estás entregando:».

## 2026-11-26 (madrugada) — Hotfix: «Solo buscar por código» y motivos reales al entregar · **Rama**

- Con «Solo buscar por código», entregar / acreditar a la persona ya elegida respondía «Esa persona no está en la base de este evento»: la pantalla manda su
  identificación y el servidor solo aceptaba el código. Ahora, si no hay un código igual, acepta la identificación de alguien INSCRITO en el evento (`app/person_code.py`).
- El límite por persona se valida primero y dice qué recibió: «Esta persona ya recibió «Alimentación»: Mazorcada Corferias. Solo se permite 1 por persona.» /
  «Esta persona ya recibió «Postre Muffin». …» (`app/subcat.py › limit_message`).
- El resultado de la entrega sale debajo de la persona (antes de «2. ¿Qué se le entrega?»); cada grupo y producto dice cuánto se le puede entregar por persona;
  la lista de coincidencias muestra también el código.

## 2026-11-26 — Inventario: la entrega dentro de la tarjeta de la persona · **Rama**

- Debajo de «Registrado», en la tarjeta de la persona, grande y para cualquier pantalla: con «La base lo define», una celda por cada regalo asignado (titular y
  dependientes) con su propio «Entregar» y «Entregar todo» si hay más de uno; con inventario elegido (p. ej. Lechona), lo marcado en celdas y un solo «Entregar» grande.

## 2026-11-26 — Rediseño del panel de Estadísticas (rama `hotfix/codigo-obligatorio-2026-11-25`; sin migración) · **Rama**

- Nuevo orden (vista del cliente, enlace público y vista del personal): **1)** Registro del evento: Base, Registrados y Pendientes (el personal ve además, desde el inicio,
  «Vienen del Excel», «Nuevos digitados a mano» y «Llegaron por formulario»); **2)** Control de inventario y **3)** Control de zonas, solo si el módulo está activo;
  **4)** «Información detallada del registro», plegado de inicio (primer y último registro, hora pico, ritmo y todas las gráficas); **5)** Gráficos por variable.
- Inventario: unidades entregadas, personas atendidas y lo que queda, en grande; por cada producto «X de Y entregadas · quedan Z» con una barra cuyo porcentaje es lo
  entregado sobre lo que había de ESE producto (antes se repartía un 100 % entre producto, unidades y personas). Zonas: personas que entraron, adentro ahora, entradas
  y salidas; por zona, personas únicas sobre los registrados. Respeta «genera estadísticas»; la persona de prueba no cuenta. Lógica: `app/stats_control.py`;
  pantalla: `static/js/stats-control.js`. Las variables de inventario y zonas ya no se agregan solas en «Gráficos por variable» (siguen en la lista).

## 2026-11-25 (noche) — Hotfix código obligatorio + prioridad del código al buscar (rama `hotfix/codigo-obligatorio-2026-11-25`; migración `0166_code_search_first`)

- **Hotfix:** con «Código de la persona» obligatorio, Editar persona y Registrar nuevo decían «Faltan campos obligatorios: Código de la persona (QR)» aunque el código estuviera
  escrito (el código vive en la inscripción del evento y la validación no lo veía). Sin red, el alta se guarda y avisa que falta el código.
- **Nuevo interruptor** en Parámetros › Campos › Código de la persona: «Dar prioridad al código al buscar persona». Prendido: en el buscador del registro salen primero las
  coincidencias por código y después por cédula; al escanear, el servidor busca primero el código. Apagado: primero la cédula, pero el código también se encuentra.
- **Lector 2D en el buscador del registro:** si lo leído (o escrito) es el código exacto de una persona, Enter la acredita como con la cédula, aunque el código sea corto o tenga letras.
- **Compromiso del digitador habilitado (migración `0167_staff_auth_login_ok`):** la autorización de datos de salud quedó con el texto que aprobó la auditora (el mismo, sin «BORRADOR»;
  confirmado por Juan David), así que en producción ya se genera el enlace y su QR. Las preguntas «¿Tienes claras las condiciones del contrato…?» y «¿Confirmas tu asistencia?» van
  resaltadas. Un digitador ya conocido ve su cédula y nombre fijos y sus datos de contacto prellenados: solo responde salud, contrato y asistencia.
- **Entrega de inventario y Control de zonas (migración `0168_code_search_only`):** arriba, en grande, «Estás entregando» con una fila por cada cosa marcada y sus cifras
  (disponibles de total · entregadas) / «Estás registrando en» la zona con adentro · salieron · movimiento. La persona encontrada sale en una tarjeta con cédula, nombres, apellidos, los
  campos marcados «Mostrar en el registro» y su estado en Registro (en rojo si NO está registrada), con «Entregar» / «Acreditar» al lado. En las categorías de elegir una hay «Nada elegido»
  para quitar la opción. Lo marcado ya no se borra tras cada entrega. El resumen general («Categorías o productos con existencias / agotados») solo lo ve el administrador.
- **«Solo buscar por código»** (Parámetros › Campos, excluyente con «Dar prioridad al código»): lo buscado o escaneado en números solo se compara con el código; los nombres se siguen buscando.
- **Compromiso: «¿Cuál?» en las 3 preguntas de salud:** aparece y es obligatorio solo si respondió «Sí»; se guarda cifrado con lo demás sensible (se purga igual).
- **Ingreso del digitador: el coordinador autoriza UNA vez por evento.** Los siguientes ingresos al mismo evento entran directo; si lo asignan a otro evento en proceso, el siguiente
  ingreso espera una vez la autorización de ese evento.

## 2026-11-25 — Registro completo sin conexión (rama `feat/contingencia-completa`, sin desplegar; **Rama**: sin probar en equipo real)

- **Registro sin red igual que con red:** lista con todos los datos, el modal normal de Editar (todos los campos, vaciar un dato, cambiar cédula, fecha de nacimiento, firmas, estado,
  eliminar), alta completa, dependientes e impresión de la escarapela (ventana o USB).
- **Control de inventario y Control de áreas sin red:** entregar (elegido o «lo define la base») y registrar entradas/salidas; lo hecho se envía solo al volver la conexión.
- **Cómo:** copia completa cifrada (las mismas filas que ya se bajaban), peticiones guardadas que se repiten contra las rutas de siempre y service worker. Ruta nueva
  `GET /api/events/{id}/offline-pack` (una vez al abrir); `POST …/movement` acepta `client_time`. Sin migración.
- **Contingencia encendida por defecto** (`CONTINGENCY_ENABLED=0` la apaga). El escáner de cédula funciona sin red si ya se usó una vez con conexión en ese equipo.
- **Arreglos tras la prueba en staging (25-nov):** guardar en Editar justo al caerse la red ya no da «Error de red» (va a la bandeja); lo pendiente se reintenta solo aunque se recargue sin red; el letrero rojo y el aviso de la bandeja ya no tapan nada en ningún tamaño de pantalla. Laboratorio en Chrome real: `tests/lab_contingencia/`.
- Detalle, límites y pendientes (prueba en tableta, texto legal de la auditora, copia propia de las librerías del escáner): `docs/28_CONTINGENCIA_COMPLETA.md`.

## 2026-11-24 (tarde) — Escáner de cédula: recorte automático (rama `feat/cedula-recorte-auto`, sin desplegar)

- La foto de la cédula ya no depende de encuadrar exacto: la cédula nueva se ubica en toda la foto (`CedulaReaders.mrzFind`), se endereza y se lee solo la zona de las 3 líneas;
  la vieja pasa la foto completa de cada cuadro al localizador del código. Segundo intento con foto fija a resolución máxima cuando la cédula se vio pero sin detalle.
- Al servidor va solo el recorte de las 3 líneas. Sin migraciones. `cedula-foto.js?v=5`, `cedula-readers.js?v=2`.
- Banco de pruebas en Chrome con cámara simulada (`tests/lab_cedula/`): 27/60 → 58/60 en fotos al azar. Detalle: `docs/PRUEBA_LECTOR_CEDULA.md` § Recorte automático.
- Noche: cédula vieja al revés (plan `photo`), cédula nueva torcida a cualquier ángulo (búsqueda girada 45°), chequeo previo de brillo / sin cédula con aviso inmediato y tope de 5,5 s por foto. `cedula-foto.js?v=6`, `cedula-readers.js?v=3`.
- Fluidez en equipos modestos: video a 1080p (de entrada o al medir pocos cuadros por segundo), guía en un lienzo del tamaño de pantalla y lectores cargados después de abrir la cámara. `cedula-foto.js?v=7`.
- Probado con cédulas reales y decodificador real: afinado de ángulo y límites del código de la cédula vieja (`_refineAngle`), foto fija solo si falta detalle, avisos rápidos (sin código, brillo, borroso, lejos), cédula nueva derecho/al revés alternados; sin cambio de resolución en caliente (el «zoom»). `cedula-foto.js?v=8`, `cedula-readers.js?v=4`.
- Tabletas económicas (Lenovo Tab M11): topes por intentos en vez de por reloj, botón habilitado con el lector cargado, búsqueda más liviana, ángulo fino del código, «<» leído como «K», 1080p con ≤ 4 GB. iPad: la foto se congela sin pausar el video (quedaba en negro tras un fallo). `cedula-foto.js?v=9`, `cedula-readers.js?v=5`.
- Arreglo de CI: el aviso de brillo en vivo (`setInterval` de `cedula-foto.js`) queda en la lista justificada de `tests/js/gw_idle_gate_check.js` (el CI de `main` e75977a7 falló solo por eso).

## 2026-11-23 (noche) — Confirmaciones con palabra y coordinador del evento nuevo (Rama; sin migración)

- **Staging (24-nov):** sitio web republicado con el arreglo de tableta (`39e4c6f`); pruebas E2E contra staging: 12 pasan, 6 se saltan por falta de datos o impresora. Informe de la segunda pasada: `docs/revision_2026-11-22b/README.md`.

- **Pruebas E2E:** `tests/e2e/conftest.py` anula los preparativos automáticos del `conftest.py` general (Postgres local, migraciones, dobles). Las E2E ya corren en cualquier máquina (p. ej. Cloud Shell) con solo `playwright` + `pytest`, sin base de datos local.
- **Pruebas E2E:** el evento sintético completa solo lo que exija la plantilla de staging (país, ciudad, horas, coordinador, comercial, categoría, campos personalizados…), leyendo `/api/event-template`; antes el servidor lo rechazaba (400) y 8 pruebas se saltaban.
- **Arreglo (pedido de Juan David):** en TODAS las pantallas que piden escribir una palabra para borrar o confirmar (REABRIR, ELIMINAR, SUPRIMIR, REVOCAR, REEMBOLSAR, DESHABILITAR, BORRAR, CARGAR, nombre del evento, nombre del campo), si la palabra está mal o vacía el cuadro ya NO se cierra en silencio (parecía que se había borrado y no): muestra ahí mismo el aviso rojo «No se hizo nada…» y deja corregir o cancelar. Se hizo en `showPrompt` (opción `validate`) y lo usan todos los llamadores.
- **Arreglo:** el desplegable «Coordinador» del evento nuevo ya no ofrece coordinadores temporales (ni archivados): usa la misma lista que valida el servidor. Antes el servidor respondía «El coordinador asignado no es válido». Archivos: `static/js/toast.js`, `static/js/gw-confirm-typed.js`, `app/event_template_svc.py`.
- **Cambio (decisión de Juan David):** el digitador ya no ve «Material de Golden» (los equipos y computadores que Golden alista para el evento): se quitó la tarjeta, se bloquea la página `/kiosk/{id}/alistamiento` y el API `inventory-checklist` pide coordinador o superior. «Control de inventario» (entregas a las personas) sigue igual para él.
- **Cambio (decisión de Juan David):** se quitó el botón «Guardar sin registrar» para TODOS (también el digitador). Corregir un dato sin registrar lo hace solo coordinador o superior, cambiando «Estado de registro» a «No registrado» y guardando. El digitador solo tiene «Guardar y registrar». Además, quien queda «No registrado» tras editarse ya no muestra «Recién registrado»: dice «Recién editado» (`static/js/directory.js`).

## 2026-11-23 — Registro y escáner facial: pruebas en staging de `saas/revision-integral` (Rama; sin migración)
- **Arreglo:** la cámara del escáner no encendía (`setOff` se usaba antes de definirse y detenía `app.js` al cargar). El mismo error está en `main` y en producción; hoy esa pantalla no se usa allí. Pendiente de subir con el paquete de producción.
- «Editar persona»: botón «Captar rostro» (mismo camino con aceptación de la persona); si ya hay foto de registro, se muestra y el botón pasa a «Retomar la foto» (`GET /api/events/{id}/users/{uid}/registration-photo`, digitador o más, `no-store`).
- Un solo botón por persona: una persona ya acreditada solo se avisa (recuadro verde), sin segundo botón ni pregunta (en línea; sin conexión sigue preguntando). Resultado del escáner en recuadro: verde = ya consta/acreditada, amarillo = no se logró detectar el rostro (repetir), rojo = no está en la base (`reason: no_face | no_match`).
- Panel de comparación del escáner (foto de registro y captura lado a lado): botón «Acreditar a esta persona» (acreditación con método biométrico), sin pasar por «Editar».
- Foto pendiente: al verificar a la persona NO se reemplaza la foto de registro; la selfie se conserva como segunda foto (`enroll.selfie_photo_key`, cubierta por toda purga/supresión) y «Editar» muestra las dos como historial. El reconocimiento sigue usando la foto de registro. Al aceptar desde el celular, si la selfie queda pendiente, el mensaje lo dice con claridad.
- Escáner sin escribir la cédula y anexo (cambio del 23-nov-2026): con modo facial y fotos del cliente, el modo «acepto» de un clic se enciende solo. En Parámetros › Reconocimiento facial aparece «Anexo firmado del cliente» (PDF, Word, Excel o imagen, 10 MB): sin el archivo la cámara queda bloqueada, con el motivo, en el servidor (`/recognize`, `/consent-click`) y en el registro. Sustituye al formulario de referencia/fecha/casilla del súper administrador (la API `precalculo-autorizado` sigue).
- Tercer origen de la foto «Cada quien acepta» (migración 0165, `events.each_accepts`): formulario, QR o enlace. En la puerta el escáner no pide cédula: sale «Acepto», se abre la cámara y solo se reconoce a quienes ya aceptaron (no se compara con quien no aceptó). No exige anexo. Los otros dos: «Golden se hace cargo» (cédula primero) y «el cliente entrega las fotos» (anexo obligatorio).
- Parámetros › Reconocimiento facial: un solo selector de tres modos (Golden se hace cargo / la empresa se hace cargo de las fotos / cada quien acepta) en vez de «responsable» + «origen de las fotos». Empresa y «cada quien» son evento de un tercero (piden los datos del organizador). El campo del anexo está siempre en la página y se muestra con el modo «empresa». La opción «Permitir imprimir la foto del rostro en la escarapela» pasa de súper administrador a cualquier coordinador.
- Escáner con «Acepto»: si el escaneo falla (no se detectó el rostro o no está en la lista) la cámara sigue abierta y se puede reintentar hasta 3 veces en 100 s sin volver a pulsar «Acepto». El «no está en la lista» dice con cuántos rostros listos se comparó (solo un número). Botón «Copiar enlace» en el cartel con QR de Invitaciones.
- Modo «Acepto» sin cédula: el escáner ya no abre la pantalla de autorización al entrar; muestra «Continuar: llegó una persona» y, al pulsarlo, la persona acepta y se abre la cámara (al terminar vuelve a «Continuar»). En «cada quien acepta» la comparación también incluye a quien aceptó desde el celular y aún no verificó su documento (antes quedaba fuera: «se comparó con 1 rostro»); su resultado es siempre «pendiente» y «Acreditar» exige confirmar el documento (verifica la aceptación) antes de acreditar.
- «Por verificar» eliminado (decisión de Juan David, 23-nov-2026; misma lógica de un formulario abierto): quien acepta (puerta, formulario, QR o enlace) queda aceptado y se reconoce de inmediato; la selfie reemplaza la foto de registro directamente; ya no hay foto «pendiente» ni el interruptor «Verificar antes de reemplazar la foto» en Parámetros (la columna `accept_verify_photo` queda sin efecto). Las aceptaciones de `web_acceptances` se registran como verificadas («link» o «auto»). Esto deshace el hallazgo 5 de la revisión de seguridad por decisión expresa del dueño: cualquiera que conozca la cédula (y la fecha de nacimiento, si la base la trae) puede dejar su selfie bajo esa persona.
- Revisión de la Fase 5 (`docs/revision_2026-11-22b/03` a `05`): foto nueva borra la pendiente, catálogo CRM y revocar servidor cerrados a cuentas de otra empresa, `autodestruir.ps1` con candado, 204 de cotización sin cuerpo.

## 2026-11-23 — Hotfix: estadísticas por estado de registro (rama `hotfix/estadisticas-registro-2026-11-23` sobre `main`; también en `saas/revision-integral`) — sin migración
- Parámetros › Campos: al activar «Estadística» se elige sobre quién se cuenta (toda la base / solo registrados / solo no registrados); viaja en `default_chart_type` como `<gráfico>@<alcance>`.
- Estadísticas: selector por gráfica para cambiarlo solo por el momento (al recargar manda lo de Campos); también en el enlace de solo lectura. Zonas, inventario y dependientes no lo llevan.
- Barras de categorías de un color por categoría (panel y Excel). Excel: hojas «Gráficos registrados» y «Gráficos no registrados».

## Sin publicar (rama `saas/revision-integral`, 22-nov-2026)
- Revisión integral del repositorio por roles (`docs/revision_2026-11-22/`); documento consolidado de reglas inamovibles (`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`).
- `CHANGELOG.md`, `CONTRIBUTING.md`, plantilla de PR y README raíz al día (esta revisión).
- 22-nov (segunda tanda, decisiones de Juan David): `/instalar` retirado; plazo de gracia del servidor local conectado (`LOCAL_GRACE_DAYS`); al deshabilitar una llave el servidor se da de baja solo (`deploy/windows/autodestruir.ps1`, apagable con `LOCAL_WIPE_ON_DISABLE=0`; deshabilitar pide escribir la palabra); `deploy/windows/proteger-disco.ps1` (BitLocker gratuito, solo si Windows lo trae); sitio: fuente libre Poppins, contacto de la plataforma y cotización con envío real (`POST /api/public/quote-request`, variables `QUOTE_TO_EMAIL` y `QUOTE_ALLOWED_ORIGINS`); `docs/PROPUESTA_FINANCIERA_SAAS_2026-11-22.md`.
- 22-nov: `main` puesto al día con la línea de producción (fusión de `prod/llaves-escaner-2026-11-20`, `hotfix/subida-formulario-2026-11-21` y `feat/evento-compartido-nube`; sin conflictos; árbol idéntico a `feat/evento-compartido-nube`).

## 2026-11-22 — Registro: lo elegido se ve completo en cualquier ancho (Staging, rama `feat/inventario-base`)
- Cédula, nombres y apellidos siempre visibles; «Mostrar en el registro» elige los demás campos, cada uno como columna con su nombre;
  nada termina en «…» (la fila crece); con poco ancho la persona pasa a dos renglones. Barrido de 320 a 3440 px en 25 pantallas sin desplazamiento horizontal.
- Dependientes: una fila es «la misma» por titular + dependiente + producto/cantidad; corregir otros datos o reordenar el archivo no duplica lo entregado.
- Detalle: `docs/25_INVENTARIO_POR_BASE.md` §11-12.

## 2026-11-21 — Inventario «lo define la base», dependientes y candados (Staging) — migración `0161_inventario_por_base`
- Lo que le toca a cada persona se calcula en vivo desde la base cargada (`app/inv_assign.py`); entregas solo a registrados, nunca dos veces; por línea o todo.
- Base de dependientes (virtual, solo en Parámetros / Editar persona / Estadísticas); vista previa obligatoria antes de cualquier carga (`app/roster_preview.py`).
- Bloqueo por evento con contraseña del digitador (registro, zonas, inventario; 5 intentos → 5 min) en `app/config_lock.py`.
- Tipo de campo «Número», «Mostrar en el registro» por campo, «Aplicar a todos los campos de texto» en el diseñador del formulario de persona.
- Detalle: `docs/25_INVENTARIO_POR_BASE.md`.

## 2026-11-21 — Hotfix: subida de archivos del formulario público en celulares (Producción, `hotfix/subida-formulario-2026-11-21`)
- «Error de red al subir el archivo»: `direct-upload.js` copia el archivo a memoria al elegirlo y reintenta con una URL nueva si la conexión se corta. Huella de `tests/test_publico_congelado.py` renovada por orden expresa.

## 2026-11-21 — Evento compartido entre servidores locales con la nube como puente (Producción, commit `4615fb4`) — migración `0160_shared_local_events`
- Varios servidores locales atienden el mismo evento; antes de entregar o dejar entrar consultan a la nube; sin internet la acción sigue con aviso.
- Copia completa del evento en la nube (`app/local_backup.py`) como seguro contra la pérdida del servidor. Paquete de actualización de servidores locales `2026.11.21.222212`.
- Detalle: `docs/23_EVENTO_COMPARTIDO_NUBE.md`.

## 2026-11-20 — Llaves de producto del servidor local y cierre por inactividad (Producción, `prod/llaves-escaner-2026-11-20`) — migraciones `0158_local_server_keys`, `0159_node_disabled_at`
- Llaves de producto: crear, ver, deshabilitar; instalador liviano; el servidor local se bloquea al deshabilitar la llave (`app/server_keys.py`, `app/server_lock.py`).
- Cierre de sesión por inactividad ajustado a pedido de Juan David (`docs/22_SESION_INACTIVIDAD.md`).
- Detalle: `docs/17_SERVIDOR_LOCAL.md` § Llaves de producto.

## 2026-11-19 — Lector de cédula por cámara y prueba de carga «rush» (Producción, `prod/lector-2026-11-19`)
- Página de prueba `/pruebas/lector-cedula` (PDF417 con `zxing-wasm`), pestaña «Cédula nueva» y Registro → «Escanear» con tres modos (cédula vieja · cédula nueva · QR), recordando el último.
- Prueba de carga «rush» autorizada en producción sobre un evento sintético, con candados en `deploy/loadtest/run_phase4.sh` (`docs/PRUEBA_CARGA_PRODUCCION.md`).
- Escarapela digital con la misma plantilla que la física y el código de la persona (`docs/ESCARAPELA_DIGITAL_DATOS.md`).

## 2026-11-18 — Almacén piezas 3 y 4, preimpresión por categoría, diseñador emergente y guardado unificado (Producción, `prod/integrado-2026-11-18`) — migraciones `0150`–`0157`
- Almacén: novedades y bloqueo (`0152_almacen_novedades`), Excel del checklist, serial y archivos por unidad (`0155_almacen_serial_y_archivos`).
- Preimpresión con estado por categoría (`0150_print_logs_kind`, `0151_merge_preimpresion`); solo se imprime a quien ya está registrado, salvo preimpresión y certificados; sin hojas en blanco.
- Diseñador de escarapelas emergente y compacto en celular; guardado unificado y estilo común en las pantallas (`docs/ux/GUARDADO_UNIFICADO.md`); menú ocultable.
- CRM implica inventario y categorías (`0153`, `0154`); orden de legalizaciones (`0156_legalizacion_orden`); sincronización de impresiones (`0157_sync_prints_changes`).
- Correo de contacto legal pasa a `soporteit@goldenlogisticas.com` en pie legal, términos y reembolsos.
- Detalle: `docs/ALMACEN.md`.

## 2026-11-17 — Almacén piezas 1 y 2, gráfico de gastos y UX por pantalla (Staging) — migraciones `0148_almacen_unidades`, `0149_almacen_movimientos`
- Catálogo con controles, unidades con serial, QR y etiquetas; salidas y entradas por QR, alistado por fila, tablero del evento y foto del elemento.
- Panel de gastos: gráfico de barras; Neon pide el rango que cubre el mes completo.
- Ronda visual por pantalla (ramas `ux/base`, `ux/kiosk`, `ux/evento`, `ux/admin`, `ux/crm`, `ux/inventario`, `ux/almacen`).

## 2026-11-16 — CRM, coordinador temporal y contactos del cliente (Producción, commit `1d5ed06`) — migraciones `0130`–`0146`
- CRM completo (cuentas, contactos, oportunidades, cotizaciones con diseñador de PDF, plantillas, productos, importación de SuiteCRM). Apagado en producción (`CRM_ENABLED=0`).
- Coordinador temporal (`staff_users.event_only`): solo sus eventos; lista de rutas permitidas en `app/event_only.py` (`0146_event_only_staff`, `docs/COORDINADOR_TEMPORAL.md`).
- Eventos: duplicar, borrar la base cargada, código sugerido, contactos del cliente por evento (`0145_event_contacts`); informe final y encuesta automática al contacto principal al pasar a «Facturado».
- Código de la persona y subcategorías (`0140_codigo_subcategorias`, 12-nov; campo desde el 17-nov): serial aparte de la cédula, solo con el interruptor del evento.
- Legalizaciones: modelo de datos (14-nov) y formato Excel (`0147_legalizaciones_formato`, 17-nov).
- Detalle: `docs/PASO_A_PRODUCCION_2026-11-16.md`, `docs/crm/README.md`.

## 2026-11-11 — Fases 5 a 9 + ajustes (Producción, commit `0899e02`) — migraciones hasta `0129_staff_client_temp`
- Cliente temporal (`cli-xxxxxx`, contraseña mostrada una vez), listas por ancho de contenedor, «(opcional)» en negrilla en formularios públicos,
  descarga ZIP de archivos de formularios, paso a «tiempo real» que encola inscripciones existentes.
- Fase 10 (10-nov): «Mostrar con asteriscos» por campo, prellenado del compromiso, Acta de novedades, historial de cambios por persona,
  descarga del instalador local, cuentas de cobro abiertas y gastos de infraestructura, inventario/control de áreas/autoescaneo, QR en vCard, ruleta y calendario;
  Job horario económico (Neon puede dormir).
- Fases 5-9 (9-nov, `f5/integracion`): eventos configurables (facturado, encuesta, jornada, historial, inventario), servidor local Windows con instalador, URL limpia de inscripciones,
  QR dinámico/Wallet, contactos de expositores, cobros Wompi multicuenta, alertas de borrado masivo y copia semanal cifrada a OneDrive.
- Detalle: `docs/ESTADO_2026-11-11.md`, `docs/FASE_10_AJUSTES_NOV10.md`, `docs/REVISION_F5-9_PLAN_VS_CODIGO.md`, `docs/FASE_9_PLATAFORMA.md`.

## 2026-11-09 — Fase 4: Equipo del evento (Producción, commit `2c8c4d7`) — migraciones hasta `0104`
- Compromiso digital del digitador con firma, credenciales por correo, autorizar a todos, clave de primera vez, descargas de bases solo para administradores.
- Detalle: `docs/CIERRE_FASE_4.md` y `docs/FASE_4_*.md`.

## 2026-11-07 — Fase 2 (diseño y calendario) y Fase 3 (CRUD, archivado, seguridad) (Staging, `f2/integracion`) — migraciones `0087`–`0094`
- Plantillas de evento, calendario, archivado y auditoría de personas/staff/eventos/catálogos; matriz CRUD y ronda de seguridad.
- Detalle: `docs/CIERRE_FASE_2.md`, `docs/FASE_3_AUDITORIA.md`, `docs/FASE_3_SEGURIDAD.md`.

## 2026-11-05 — Cierre de las Fases 0 y 1 (Producción, despliegue del 5-nov 9 pm)
- Fase 1A: buscador único (cédula, nombre, empresa, lector), cola compartida de impresión, carga flexible, autoimpresión, formulario de persona, parámetros agrupados, permisos del coordinador.
- Fase 1B: reimpresión con permisos de un solo uso aprobados por el coordinador del evento (pantalla o correo). Persona de prueba `PRUEBA` en cada evento.
- Fase 0B/0C: limpieza del repositorio (72 ramas borradas, `docs/0B_ramas_borradas.md`), `ruff` en todo el repo, escáneres de seguridad, hallazgos corregidos.
- Detalle: `docs/CIERRE_FASES_0_1.md`, `docs/1B_reimpresion_permisos.md`, `docs/historial.md` (entradas del 1 al 5 de noviembre).

## 2026-11-01 a 04 — Formularios web y eventos en curso (Producción con el cierre del 5-nov)
- Formularios: valores de la base como opciones (P7), texto con formato (P3), ancho configurable (P4), paso de identificación editable (P5), nombre de presentación (P8),
  condiciones en árbol y variantes (P9), editor plegable (P10), tabla de variantes (P11/P11b), hojas (P12). Mensaje editable de cupo lleno; cupo en 0 = cerrado temporalmente.
- Eventos en curso: «Solo agregar personas nuevas» (`app/roster_append.py`) y devolver un evento «en curso» a «creado».
- Contraseñas con motivo claro y «ojito» en el inicio de sesión.
- Detalle: `docs/historial.md` (secciones del 1 al 4 de noviembre).
