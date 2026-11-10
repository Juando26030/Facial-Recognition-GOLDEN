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
