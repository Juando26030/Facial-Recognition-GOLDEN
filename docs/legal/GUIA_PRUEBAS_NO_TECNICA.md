# Guía de pruebas para una persona no técnica (staging)

Cada prueba dice **dónde hacer clic** y **qué debe ver**. Si algo no coincide, anota la pantalla, la hora y la cédula de la persona de prueba y avísame. Todo se hace en **staging** (nunca en producción) con personas de prueba.

> Estado de cada pieza (para no esperar lo que aún no existe): el envío de correo de punta a punta depende de la sección 11 del runbook (secretos de correo cargados y servicios redesplegados); la **entrada con rostro «Entrar con mi rostro»**, el **envío masivo de enlaces** y la **selfie dentro del aviso de verificación** están en construcción y NO se prueban aquí.

## 0. Antes de empezar (una sola vez)
**Dónde:** el navegador, en la dirección de staging que ya usas. Entra con tu usuario (`/login`).
**Datos de prueba** (los mismos de las guías G1 a G3):
| Cédula | Nombre | Fecha de nacimiento | Correo | Para qué |
|---|---|---|---|---|
| 9991001 | Ana Prueba | 1990-04-02 | buzón A (tuyo) | Acepta |
| 9991002 | Beto Prueba | 1988-07-15 | buzón B (tuyo) | Acepta en la puerta |
| 9991003 | Cata Prueba | hace 15 años (p. ej. 2011-03-10) | buzón C (tuyo) | Menor de edad |
| 9991004 | Dani Prueba | 1992-11-20 | buzón D (tuyo) | Dice que no |
| 9991005 | Eli Prueba | 1995-01-30 | buzón E (tuyo) | Nunca acepta |

Necesitas: un celular (cámara y correo), un portátil (la «puerta»), los cinco buzones de correo que controlas (sirve una cuenta con `+`: `tunombre+ana@…`), un cartel impreso o en pantalla (para el QR) y un cronómetro.
**Un evento de pruebas:** menú lateral **«📅 Eventos»** → **«Nuevo evento»** → nombre «PRUEBA-ACEPT-02» → **«Crear evento»**. En la lista, en la fila del evento, **«✏️ Editar»** → cambia el **estado** a **«En Proceso»** → guardar. Para entrar: **«Ingresar →»**. Verás las tarjetas del evento (Registro, Adjuntar Base de Datos, Escarapelas, Formularios Web, Parámetros del Evento…).
**⚠️ Orden obligatorio: PRIMERO se activa el reconocimiento facial del evento y DESPUÉS se carga la lista.** La fecha de nacimiento solo se guarda si el evento ya tiene el rostro activo (Parámetros del Evento → paso guiado → «Guardar y revisar») en el momento de cargar; si se carga antes, la carga termina bien pero **la fecha NO se guarda** (el resumen lo avisa en rojo: «traían fecha de nacimiento y NO se guardaron…»), las personas menores parecen adultas y habrá que volver a cargar el mismo archivo. En un evento SIN biometría (punto 1) la fecha no se guarda por diseño.
**Cargar a las cinco personas** (en los eventos con rostro, solo DESPUÉS de activarlo, ver punto 2 pasos 1 a 3): tarjeta **«Adjuntar Base de Datos»** → sube un Excel con columnas `Cédula`, `Nombres`, `Apellidos`, `Correo`, `Fecha de nacimiento` → **«Cargar Base de Datos»**. *Debe ver:* «Carga completa: 5 perfiles cargados» y la caja «Columnas del archivo» con las columnas reconocidas.

---

## 1. Sin biometría (G3)
1. Tarjeta **«Parámetros del Evento»** → bloque **«Reconocimiento facial: paso guiado»**: deja **apagado** «Paso 0. Este evento usará reconocimiento facial» y marca **«🚫 Este evento NO usa biometría (bloquear)»** → **«Guardar y revisar»**. *Debe ver:* el cuadro de abajo dice **«✅ Listo: este evento no usa biometría»**, sin avisos en rojo.
2. Vuelve al evento → tarjeta **«Registro»**. *No debe aparecer:* pestaña del escáner de rostro, cámara de rostro, «Escanear Rostro», pantalla de autorización, casilla de consentimiento ni el campo «Fecha de nacimiento». (La única cámara permitida es la que lee el **documento**: «Escanear QR con cámara» o «Cédula nueva (cámara)».)
3. En **«Parámetros del Evento»**, lista de campos: no debe existir «Fecha de nacimiento».
4. Tarjeta **«Adjuntar Base de Datos»**: sube el Excel de arriba **más un zip con una foto** (`9991001.jpg`) → *Debe ver:* la carga termina, con el aviso **«Este evento no usa biometría (bloqueado): el zip de fotos se ignoró»**, y «fecha de nacimiento» en la lista **«Columnas no usadas»** («no se usa en este evento»).
5. Intenta encender el rostro (Paso 0): **debe rechazarse** con un mensaje de bloqueo.
6. **Registro:** acredita a Ana por cédula escrita y a Beto con un QR; crea a alguien nuevo con **«➕ Registrar nuevo»**. *Debe ver:* cada ingreso en 1 o 2 toques.

## 2. Interruptor del enlace personal y aceptación desde el celular
Evento nuevo «PRUEBA-ACEPT-03» (como en el punto 0, pero **todavía SIN cargar la lista**: primero los pasos 1 a 3 —activar el rostro y guardar— y SOLO DESPUÉS el paso 3b).
1. **«Parámetros del Evento»** → paso guiado: marca **Paso 0** «Este evento usará reconocimiento facial»; **Paso 1** déjalo en **«Evento propio de Golden»**; **Paso 2**, elige **B** («Cada persona se toma una selfie…»).
2. **Paso 3:** marca **«Permitir aceptar el reconocimiento facial y dar la selfie desde el celular antes del evento (página /aceptar)»**. Se despliega un recuadro con el enlace, un QR y «Imprimir póster con el QR».
3. Dentro de ese recuadro, **deja SIN marcar** «Enviar por correo, al inscribirse por formulario, el enlace personal…» (por ahora está apagado a propósito hasta la revisión de la auditora). → pulsa **«Guardar y revisar»**. *Debe ver:* «✅ Listo: así funcionará en la puerta» y la línea «Antes del evento, las personas ya inscritas pueden aceptar desde su celular…».
3b. **Ahora sí, carga las cinco personas** (punto 0, «Cargar a las cinco personas»). *Debe ver:* «Carga completa: 5 perfiles cargados», en la pantalla de carga el recuadro verde «Este evento usa reconocimiento facial… La fecha de nacimiento del archivo se guarda» y **ningún** aviso rojo de «fecha de nacimiento NO se guardó». Si lo ves, el evento no tenía el rostro activo: actívalo, guarda y vuelve a cargar el mismo archivo.
4. **En el celular de Ana:** abre el enlace que muestra el recuadro (o escanea el QR). *Debe ver:* el nombre del evento, la explicación «totalmente voluntario» y los campos **«Número de documento»** y **«Fecha de nacimiento»**. Escribe `9991001` y `1990-04-02` → **«Continuar»**.
5. *Debe ver:* el texto de autorización completo y los botones **«ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL»** y **«PREFIERO INGRESAR CON DOCUMENTO / QR»**. **Todavía no hay cámara.** Pulsa **ACEPTO…**
6. *Debe ver:* ahora sí el campo **«Tu selfie (de frente, con buena luz)»**. Toma la selfie → **«Enviar mi selfie»**. *Debe ver:* «¡Gracias! Cuando llegues, muestra tu cédula o QR en la acreditación: el personal confirmará tu identidad…».
7. *Debe ver (correo):* en el buzón A llega **«Tu autorización para entrar con reconocimiento facial — PRUEBA-ACEPT-03»** (si el correo de staging está configurado), con la constancia y, al final, el texto que aceptó. Canal: **«Portal web del evento»**. *No lleva foto.*
8. **En el portátil (puerta):** **«Registro»** → pestaña del escáner → escribe `9991001` en **«Cédula o lector de QR»** → **«Continuar»**. *Debe ver:* un aviso para **confirmar la identidad con el documento físico** («¿coincide con quien está en la puerta?»); acepta («Sí»). Ana queda verificada. Si su rostro aún se está calculando, verás «Tu reconocimiento facial se está preparando: hoy ingresa por cédula o QR»: espera unos segundos y repite; cuando esté listo se enciende la cámara → **«📸 Escanear Rostro»** → reconoce a Ana.

## 3. Formulario público con correo real
Sirve para probar el correo con el enlace personal. **Requiere** que la auditora ya haya revisado el correo y que tú enciendas el interruptor del punto 2.3 (por ahora está apagado: haz esta prueba solo cuando lo decidas).
1. Evento «PRUEBA-ACEPT-03» → **«Formularios Web»** → **«Crear un formulario de inscripción»** → nombre «Inscripción prueba» → **«Crear y editar»**.
2. En el editor: bloque **«Estado y enlaces»** → **Estado: «Activo»** (con «Pruebas» el sistema NO envía correos ni carga a la base). Bloque **«Alimentar la base de datos del evento»** → marca **«En tiempo real»**. Guarda.
3. **«Parámetros del Evento»** → paso 3 → marca **«Enviar por correo, al inscribirse por formulario, el enlace personal…»** → **«Guardar y revisar»**.
4. Abre el enlace público del formulario en el celular y inscribe a **Beto** (cédula `9991002`, su correo, fecha de nacimiento). *Debe ver:* el mensaje de agradecimiento del formulario.
5. *Debe ver (correo, en uno o dos minutos):* en el buzón B, **«Entra más rápido a PRUEBA-ACEPT-03: autoriza el uso de tu rostro (opcional)»**, con «Es totalmente voluntario…» y un enlace personal.
6. Abre ese enlace en el celular. *Debe ver:* **sin campo de documento**, solo **«Fecha de nacimiento»** → escribe `1988-07-15` → **«Continuar»** → texto → **ACEPTO…** → selfie → **«Enviar mi selfie»**. Como el correo lo escribió la propia persona, **sigue «por verificar»**: el mensaje pide pasar por la acreditación.
7. Repite la inscripción con la **misma cédula**: *no debe* llegar un segundo correo con enlace (se envía una sola vez).

## 4. Menor de edad (Cata)
1. En el celular, abre el enlace general de `/aceptar` (punto 2.2) → documento `9991003`, fecha de nacimiento de hace 15 años → **«Continuar»**. *Debe ver:* **«No puedes usar el reconocimiento facial. Ingresa con tu cédula o QR en la acreditación.»** No aparece el texto de autorización ni la cámara.
2. En el portátil: **«Registro»** → escáner → `9991003` → **«Continuar»**. *Debe ver:* **no** aparece la pantalla de autorización ni se enciende la cámara; pasa a la búsqueda por cédula, y se puede acreditar normal.
3. *Verifica:* no llegó correo de constancia a C.

## 5. QR del cartel
1. **«Parámetros del Evento»** → recuadro de `/aceptar` → **«Imprimir póster con el QR»** (o muestra el QR en pantalla). Escanéalo con el celular de **Dani**.
2. Documento `9991004` + fecha → **«Continuar»** → pulsa **«PREFIERO INGRESAR CON DOCUMENTO / QR»**. *Debe ver:* «Listo: ingresarás con tu cédula o QR, sin restricción alguna.»
3. Con otro celular y el mismo QR, acepta con la cédula de Ana (`9991001`) y mira el correo del buzón A: la constancia debe decir **«Canal de autorización: Escaneo de código QR en la entrada»**.

## 6. Aceptación en la puerta
1. En el portátil: **«Registro»** → pestaña del escáner → escribe `9991002` (Beto, que aún no ha aceptado) → **«Continuar»**.
2. *Debe ver:* pantalla completa con el texto de autorización y los dos botones. Que Beto pulse **ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL**.
3. *Debe ver:* se enciende la cámara con el mensaje «Capta el rostro de la persona: hoy ingresa por cédula; desde la próxima entrada, por rostro.» → **«📸 Escanear Rostro»** → «✅ Listo…». Beto entra **hoy por cédula**.
4. Pasados unos segundos, **vuelve a escanear a Beto** (cédula → «Continuar» → «📸 Escanear Rostro»): ahora **sí lo reconoce**.
5. *Debe ver (correo):* en el buzón B llega la constancia con **«Canal de autorización: En la puerta, con el personal de acreditación»**.

## 7. Escarapela real
**Virtual (por correo):** si en el evento está activa la **escarapela digital** (**«Parámetros del Evento» → «Escarapela digital» → «Activar la escarapela digital en este evento»**), la constancia trae **«🎫 Tu escarapela virtual: …»**. Ábrela en el celular: *debe ver* el nombre de la persona y un código que cambia (no sirve una captura de pantalla). Prueba el correo de la escarapela con **«Enviar prueba»** (escribe un buzón tuyo en el campo y pulsa el botón): llega un asunto que empieza por `[STAGING]`.
**Impresa:** tarjeta **«Escarapelas»** (diseño) y, en la puerta, tras reconocer o registrar a alguien, el botón **«🖨️ Imprimir Escarapela»**. *Debe ver:* la escarapela con el nombre y el QR; el QR se lee con el lector de la puerta (**«Cédula o lector de QR»**) y registra a la persona.

## 8. Fuente de la foto: A (el cliente entrega las fotos) y B (selfie)
**B** es lo que probaste en los puntos 2, 3 y 5 (la persona se toma la selfie).
**A:**
1. Evento nuevo «PRUEBA-ACEPT-04», con las personas cargadas **y un zip con la foto de Ana** (`9991001.jpg`, cara clara de frente) en **«Adjuntar Base de Datos»** (marca la casilla de autorización de las fotos).
2. **«Parámetros del Evento»** → paso guiado: Paso 0 activo; Paso 2 → elige **A** («El cliente entrega las fotos de los asistentes antes del evento…»); Paso 3 → permite aceptar desde el celular → pulsa **«Guardar y revisar»**. *Debe ver:* el resumen dice que las fotos del cliente se guardan cifradas y el rostro **no se calcula hasta que la persona acepte**.
3. En el celular, Ana abre `/aceptar`: documento + fecha → **«Continuar»** → texto → **ACEPTO…**. *Debe ver:* **no se pide selfie**; aparece el agradecimiento. (Ahora el sistema calcula su rostro con la foto que entregó el cliente.)
4. Una persona **sin foto del cliente** (Beto) que acepta igual: no se pide selfie; en la puerta se le toma el rostro en vivo (camino del punto 6).

## Si algo falla
| Qué ves | Qué probablemente pasa | Qué haces |
|---|---|---|
| «Esta página no está disponible» al abrir `/aceptar` | Falta marcar el Paso 3 «Permitir aceptar…», el rostro no está activo o el evento está bloqueado sin biometría / finalizado | Revisa el paso guiado y guarda |
| No llega ningún correo | Staging aún no tiene los secretos de correo, no se redesplegó o el formulario está en «Pruebas» | Runbook sección 11; formulario en «Activo» |
| «No encontramos tu inscripción con ese documento y esa fecha» | Cédula o fecha distinta a la de la base | Revisa el Excel cargado |
| La cámara no enciende | El navegador no tiene permiso de cámara | Permite la cámara para el sitio |
