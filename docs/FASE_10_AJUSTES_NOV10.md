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
