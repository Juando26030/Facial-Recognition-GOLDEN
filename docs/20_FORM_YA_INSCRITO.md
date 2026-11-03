# Formularios: «Ya estás inscrito» y «Registrado en formulario» (3-nov-2026)

Sin migración: el ajuste vive en `settings_json` del formulario y la marca de la carga usa la tabla `form_submissions` con un estado propio.

## 1. Ajuste «Bloquear inscripciones repetidas» (editor del formulario > Configuración)
- `settings.block_repeats = {"enabled": bool, "field": "<id de campo>"}`. `field` vacío = el campo vinculado a «Cédula» (clave `id`). Otros campos válidos: texto corto, correo, teléfono, número.
- Guardar con el ajuste activo y sin nada con qué comparar (sin cédula y sin campo elegido) devuelve 400 con un mensaje claro.
- Mensaje único: «Ya estás inscrito. No necesitas volver a inscribirte.» (`formsvc.ALREADY_MSG`); la respuesta es `409 {"detail", "duplicate": true, "already": true}` y no trae nada de la persona.
- Qué cuenta como inscrita: solo inscripciones **confirmadas, reales (no de prueba) de ESE formulario**, más las marcadas desde la carga de la base (§2). Las de prueba nunca bloquean ni cuentan.
- Por cédula: `lookup` (paso «Identifícate») responde 409 en cuanto se escribe una cédula ya inscrita; además `POST /f/{evento}/{slug}/check` avisa al salir del campo si el formulario no tiene paso de identificación. El envío sigue usando `precheck` y `form_reserve_slot` (la duplicidad por cédula se rechaza SIEMPRE, con o sin ajuste, como antes; el ajuste agrega el aviso temprano).
- Por otro campo (correo, teléfono, documento u otro): comparación normalizada y exacta (`formlib.normalize_identifier`): correo/documento/otro en minúsculas y sin espacios, puntos ni guiones; teléfono = solo dígitos (no se quita el 57). Se hace en SQL sobre `data_json` (no se traen datos de nadie). Atomicidad: se repite DENTRO del bloqueo del formulario (justo después de `form_reserve_slot`, antes del INSERT), así que doble clic o envíos simultáneos con el mismo correo dejan una sola inscripción. Costo: una consulta extra solo en formularios con el ajuste activo por un campo que no es la cédula.
- Límites de tasa: `lookup` y `check` comparten el límite `form_lookup` (60/min por IP); el envío conserva `form_submit`.

## 2. Columna «Registrado en formulario» en la carga de la base
- Títulos reconocidos (sin importar mayúsculas ni tildes): «Registrado en formulario», «Registrado en el formulario», «Ya inscrito», «Inscrito en formulario»… Valores «sí»: `sí/si/1/x/true/yes` (los de la columna «Certificado»). Vacío o «no» = no hace nada. Vale en la carga normal y en «solo agregar».
- Interpretación: «si está en sí, que se tenga presente como ya registrado» = la persona queda **ya inscrita** en los formularios del evento: bloqueada en `lookup` y en el envío, **sin ocupar cupo**, y se ve aparte en la lista de formularios («+N ya registradas desde la base»). Si la regla fuera que SÍ ocupe cupo, basta cambiar `formsvc.held_count`/`form_reserve_slot` (hoy solo cuentan `confirmed`).
- Implementación: se crea una fila `FormSubmission` con `status='preregistered'`, `data_json='{}'`, `source='carga_base'`, `fed=true` por cada formulario del evento (`formsvc.mark_preregistered`, idempotente). Como todos los conteos, listas, reportes, analítica y la carga a la base filtran `status='confirmed'`, esa fila es invisible para ellos; `precheck` y `lookup` sí la ven. Bloquea solo con el interruptor «Bloquear inscripciones repetidas» encendido (ver §2b). Con un formulario sin cédula, el correo o teléfono elegido también se compara con la ficha de la persona marcada.
- Limitación: aplica a los formularios que ya existan al cargar la base. Para un formulario nuevo, volver a cargar el mismo archivo (es idempotente).
- Plantilla Excel: no se tocó (las pruebas fijan sus columnas); la columna es opcional y la pantalla de carga la explica.

## 2b. Lista «Personas ya registradas» POR FORMULARIO (editor > Configuración)
- Botón «Cargar / recargar lista»: archivo Excel/CSV con la cédula (o el campo identificador elegido; para correo/teléfono basta una columna «Correo»/«Teléfono» o con el nombre del campo) y, opcional, «Registrado en formulario» (si existe, solo cuentan las filas con «sí»). Vale SOLO para ese formulario y sirve también para formularios creados después de la carga del evento. Se puede recargar en pleno evento.
- Modo: **Agregar** (no quita nada, no duplica; si una persona ya estaba como «solo bloquear» y ahora se pide «ocupar cupo», pasa a ocupar cupo) o **Reemplazar** (quita todas las marcas previas del formulario, también las de la carga del evento, y deja solo las del archivo).
- Efecto: **Solo bloquear** (por defecto; estado `preregistered`, no ocupa cupo) u **Ocupar cupo y bloquear** (fila `confirmed` con `source='lista_cupo'`: `form_reserve_slot` y `held_count` ya cuentan `confirmed`, así que NO hizo falta migración y no hay sobreventa; cuenta como inscripción en `submissions`, con respuestas vacías salvo la cédula/identificador). La carga corre con la fila del formulario bloqueada (`FOR UPDATE`), así que ningún envío simultáneo la ve a medias. Si la lista supera el cupo, el mensaje lo avisa.
- Interruptor: las marcas «solo bloquear» (de la lista o de la carga del evento) solo bloquean con «Bloquear inscripciones repetidas» encendido. La casilla de la carga («Encender … si está apagado», por defecto sí) es el modo explícito: lo enciende al cargar. Las que ocupan cupo bloquean siempre por cédula (son inscripciones confirmadas).
- «Quitar todas las marcas» (`DELETE .../registered`, con confirmación): borra las marcas de ese formulario (liberan el cupo las que lo ocupaban); nunca toca inscripciones reales. La pantalla muestra «+N ya registradas (M ocupan cupo)». Fuentes de marca: `carga_base`, `lista`, `lista_cupo`.

## 3. Probar en staging (sin saber de código)
1. Formulario con campo Cédula > Configuración > marcar «Bloquear inscripciones repetidas» > Guardar > ponerlo Activo.
2. Abrir el enlace público, inscribirse con una cédula; volver a abrirlo y escribir la misma cédula: debe decir «Ya estás inscrito».
3. Configuración > «Personas ya registradas»: subir un CSV con una columna Cédula, elegir «Agregar» + «Solo bloquear», cargar; esa cédula dice «Ya estás inscrito». Probar «Ocupar cupo y bloquear» con un cupo pequeño y «Quitar todas las marcas».
4. Cargar una base con la columna «Registrado en formulario» (sí en una fila) y comprobar que esa cédula dice «Ya estás inscrito» y que el cupo del formulario no baja.
Pruebas: `tests/test_form_ya_inscrito.py`.
