# Guía de prueba de aceptación en staging (para personas no técnicas)

**Para qué sirve:** comprobar, de punta a punta, que el reconocimiento facial voluntario funciona: la persona acepta, el sistema calcula su rostro aparte (sin hacer esperar la puerta), y después la reconoce. También comprueba los casos «no me encuentran» y «menor de edad», y deja todo limpio al final.

**Tiempo:** unos 45 minutos con 5 voluntarios. **Dónde:** staging (nunca producción). **Quién:** una persona con cuenta de administrador, 2 o 3 voluntarios con celular y un computador con cámara (el «quiosco»).

> Importante: usa **un cliente nuevo solo para esta prueba**. Las personas pertenecen a un cliente, así que así no se toca nada de la campaña de carga (que vive en el cliente «Carga staging (datos sintéticos)»). Tampoco uses cédulas reales: usa las de este ejemplo.

---

## 1. Qué preparar

**Cliente y evento**
- Cliente: crea uno que se llame **«Prueba de aceptación»** (menú **Clientes - Cuentas**, ver tu manual de siempre).
- Evento: dentro de esa tarjeta del cliente, botón **«+ Nuevo evento»**. Llena los campos obligatorios; en **«Código interno»** escribe `PRUEBA-ACEPT-01` (solo letras, números y guion; este código será parte del enlace) y en **«Nombre del evento»** `Prueba de aceptación facial`.
- Pasa el evento a **En Proceso**: menú **Eventos** → en la tarjeta del evento, el selector de estado → **En Proceso** → confirmar.

**Cinco personas de prueba** (las dos primeras y las tres últimas son voluntarios del equipo; cada quien usa **su propio rostro**):

| Cédula de prueba | Nombre | Para probar | Fecha de nacimiento |
|---|---|---|---|
| 9990001 | Ana Prueba | Aceptar desde el celular (antes del evento) | una de adulto, p. ej. 1990-04-02 |
| 9990002 | Beto Prueba | Aceptar en el quiosco, en la puerta | 1988-07-15 |
| 9990003 | Cata Prueba | **Menor de edad** | una de hace 15 años (p. ej. si hoy es 2026, 2011-03-10) |
| 9990004 | Dani Prueba | Decir **que no** al rostro | 1992-11-20 |
| 9990005 | Eli Prueba | **Sin coincidencia** (nunca acepta) | 1995-01-30 |

**Cargar a las cinco:** en el evento, tarjeta **«Adjuntar Base de Datos»**. Descarga la plantilla (`plantilla_carga_base_asistentes.xlsx`, el enlace está en esa pantalla), llena una fila por persona con **cédula, nombres y apellidos** y agrega una columna llamada **`fecha de nacimiento`** con el formato AAAA-MM-DD. **No subas fotos** (el rostro se capta en la prueba). Botón **«Cargar Base de Datos»**.

**Activar el rostro con el paso guiado:** en el evento, tarjeta **«Parámetros del Evento»**, bloque **«Reconocimiento facial: paso guiado»**:
1. Marca **«Paso 0. Este evento usará reconocimiento facial»**.
2. **«Paso 1. ¿Quién es el Responsable de los datos?»** → deja **«Evento propio de Golden (Golden es el Responsable)»**.
3. **«Paso 2»**: deja desmarcado «el cliente entregará fotos antes del evento».
4. **«Paso 3»**: marca **«Permitir aceptar el reconocimiento facial y dar la selfie desde el celular antes del evento (página /aceptar)»**. Deja «Una sola vez por persona y evento».
5. Botón **«Guardar y revisar»**.

**Qué debes ver abajo:** un cuadro con **«✅ Listo: así funcionará en la puerta»** y varias frases (Golden es el Responsable único, la autorización se pide una sola vez, hay aceptación previa por celular, etc.). Si dice **«⚠️ Falta algo antes del evento»**, lee la línea roja: te dice qué falta (por ejemplo un dato de la empresa) y no sigas hasta resolverlo.

Ahí mismo aparece **«Enlace (para el correo):»** con la dirección terminada en `/aceptar/PRUEBA-ACEPT-01` y un código QR. **Copia ese enlace**: es el de la prueba del celular.

---

## 2. Prueba A: Ana acepta desde su celular (antes del evento)

1. Ana abre el enlace `…/aceptar/PRUEBA-ACEPT-01` en su celular.
2. **Debe ver:** el nombre del evento y el texto «Si quieres entrar al evento con reconocimiento facial, completa esto antes de llegar. Es totalmente voluntario…», con los campos **«Número de documento»** y **«Fecha de nacimiento»** y el botón **«Continuar»**.
3. Escribe `9990001` y su fecha de nacimiento → **«Continuar»**.
4. **Debe ver** la autorización completa («AUTORIZACIÓN VOLUNTARIA DE TRATAMIENTO DE DATOS BIOMÉTRICOS SENSIBLES — EVENTO PROPIO»), con la empresa «Golden Eventos y Logística S.A.S. / 901.542.833-2», el nombre del evento y el correo `soporteit@goldenlogisticas.com`; debajo, **«Tu selfie (de frente, con buena luz)»** y dos botones: **«ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL»** y **«PREFIERO INGRESAR CON DOCUMENTO / QR»**.
5. Toma la selfie y pulsa **«ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL»**.
6. **Debe ver:** «¡Gracias! Cuando llegues, muestra tu cédula o QR en la acreditación: el personal confirmará tu identidad y desde ahí podrás entrar con tu rostro.»

**Si algo sale distinto:** «No encontramos tu inscripción con ese documento y esa fecha…» significa que la cédula o la fecha no coinciden con la base cargada.

## 3. Prueba B: llegada de Ana a la puerta (el personal confirma su identidad)

1. En el computador, entra al evento → tarjeta **«Registro»** → pestaña **«1. Escáner de Acceso»**.
2. **Debe ver:** un cuadro amarillo **«🔒 Reconocimiento facial voluntario: identifica primero a la persona»** con la caja **«Cédula o lector de QR»** y el botón **«Continuar»**. La cámara **no** está encendida.
3. Escribe `9990001` → **«Continuar»**.
4. **Debe aparecer** un mensaje: «Esta persona aceptó el reconocimiento facial desde su celular. Confirma su identidad con el documento físico o el QR: ¿coincide con quien está en la puerta?» → pulsa **«Confirmar»** (haz de cuenta que miraste su documento).
5. Se enciende la cámara y aparece **«📸 Escanear Rostro»**. Ana mira la cámara → pulsa ese botón.
6. **Debe ver:** «🟡 Coincidencia encontrada — compara las fotos y confirma» (o «✅ IDENTIDAD VALIDADA Y ACCESO AUTORIZADO» si el evento acredita solo), con la foto de la selfie al lado de la captura. Confirma el ingreso con el botón que aparece.

## 4. Prueba C: Beto acepta en la puerta (sin celular)

1. Misma pantalla: escribe `9990002` → **«Continuar»**.
2. **Debe aparecer una pantalla completa** con la autorización y los botones **«ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL»** y **«PREFIERO INGRESAR CON DOCUMENTO / QR»**. La cámara sigue apagada.
3. Beto pulsa **«ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL»**.
4. **Debe ver:** se enciende la cámara y el aviso **«Capta el rostro de la persona: hoy ingresa por cédula; desde la próxima entrada, por rostro.»** → **«📸 Escanear Rostro»**.
5. **Debe ver:** «✅ Listo. Hoy ingresa por cédula o QR; tu rostro quedará listo en unos momentos.» y el sistema lo lleva a la búsqueda por cédula para acreditarlo. **La puerta no espera nada.**
6. **Espera 1 minuto** (el cálculo toma segundos). Vuelve a escribir `9990002` → **«Continuar»** → ahora **no** pide la pantalla (ya aceptó): enciende la cámara directo. **«📸 Escanear Rostro»** → debe reconocerlo.

## 5. Prueba D: Dani dice que no

1. `9990004` → **«Continuar»** → pantalla completa → **«PREFIERO INGRESAR CON DOCUMENTO / QR»**.
2. **Debe ver:** no se enciende la cámara y pasa a la búsqueda por cédula (entra sin ninguna restricción).

## 6. Prueba E: «sin coincidencia» (un rostro que no está en la lista)

La cámara solo se enciende para alguien que ya aceptó. Para probar a un **desconocido** frente a la cámara:
1. Escribe la cédula de **Beto** (`9990002`, que ya aceptó y ya tiene su rostro listo) → **«Continuar»** → se enciende la cámara.
2. Pide que **Eli** (que **nunca aceptó** ni tiene rostro guardado) se ponga frente a la cámara, en lugar de Beto, y pulsa **«📸 Escanear Rostro»**.
3. **Debe ver exactamente:** **«No te encontramos en la lista con reconocimiento facial. Por favor dirígete a la acreditación con tu cédula o QR.»** No se guarda nada de esa captura (ni la foto ni el rostro de Eli). Eli entra por cédula: `9990005` en la búsqueda por cédula.
4. Después de cada escaneo la cámara se apaga sola: para otra prueba hay que identificar a la persona de nuevo.

## 7. Prueba F: menor de edad (Cata)

- **En el celular:** el enlace `/aceptar/PRUEBA-ACEPT-01` → `9990003` y su fecha de nacimiento de hace 15 años → **«Continuar»**. **Debe ver:** «No puedes usar el reconocimiento facial. Ingresa con tu cédula o QR en la acreditación.» (no pide selfie ni muestra la autorización).
- **En el quiosco:** `9990003` → **«Continuar»**. **Debe ver:** no aparece ninguna pantalla de autorización ni se enciende la cámara; pasa directo a la búsqueda por cédula.

## 7b. Prueba G: la base con títulos propios y las fechas (extra)

Sirve para comprobar la carga por título de columna. Prepara una base de prueba con las columnas **`Cédula`, `Nombres`, `Apellidos`, `Fecha de nacimiento`, `Talla de camisa`** (más una columna vacía llamada `Observaciones`) y súbela en **«Adjuntar Base de Datos»**.
- **Debe ver:** que NO pregunta qué es «Talla de camisa»; al terminar, una caja **«Columnas del archivo»** con tres listas: **campos reconocidos** (cédula, nombres, apellidos, fecha de nacimiento), **campos nuevos creados** («Talla de camisa») y **columnas no usadas** («Observaciones», por estar vacía).
- **Fechas:** la columna de fecha de nacimiento acepta `2011-03-10`, `10/03/2011` y la fecha de Excel; una que no se pueda leer queda como observación de esa fila y la persona se carga igual.
- **«Parámetros del Evento»:** debe aparecer el campo **«Talla de camisa»** y también **«Fecha de nacimiento»** (solo en eventos con reconocimiento facial; se puede renombrar o mover, no apagar). **«Editar persona»** muestra la fecha de nacimiento y se puede cambiar; si se cambia a una de menor de edad, se borran su rostro y su foto.
- **Subir la misma base otra vez** (mismas cédulas): actualiza a las personas, no las duplica y no crea otro campo «Talla de camisa». (Solo se puede mientras el evento no esté «en proceso» con una base ya cargada.)

## 8. Comprobar que el cálculo pasó por la cola `golden-faces-staging`

**Lo que se ve en la aplicación:** menú lateral **🩺 Estado del sistema** (`/sistema`, solo administrador). El renglón **«Cola de trabajos»** debe quedar así después de las pruebas: «0 pendientes · 0 en curso · 0 fallidos». Mientras el cálculo corre puede decir «1 pendientes».

**Lo que se ve en Google Cloud (Cloud Shell):**
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="golden-biometria-staging" AND httpRequest.requestUrl:"/internal/faces/run"' --limit 10 --format='value(timestamp,httpRequest.status)'
```
Debe haber líneas con estado `200`, a los pocos segundos de la aceptación de Beto (y de Ana). Eso demuestra que la tarea llegó a **golden-biometria-staging** por la cola de caras y no por la general.

```bash
gcloud tasks queues describe golden-faces-staging --location us-east4 --format="yaml(name,state,rateLimits)"
gcloud tasks list --queue golden-faces-staging --location us-east4
```
La cola debe estar `RUNNING`, y la lista, **vacía** (las tareas terminan en segundos). Si ves tareas que no se van, copia el mensaje y avísame.

---

## 9. Borrar los datos de prueba al final

Todo se borra desde el mismo evento, uno por uno. Como el cliente es «Prueba de aceptación», **no se toca nada del cliente de la campaña de carga**.

1. Eres **administrador**: evento → **«Parámetros del Evento»** → baja a **«Privacidad de datos biométricos»**.
2. En la caja de cédula escribe `9990001` y pulsa **«Suprimir TODOS los datos de esta persona»** → confirma. **Debe decir:** «Listo. No se borra al instante: …» (te lista las copias de seguridad y demás que se limpian solas en 1 a 30 días).
3. Repite con `9990002`, `9990003`, `9990004` y `9990005`.
4. **Comprobar:** en el evento, **«Registro»** → la lista ya no debe mostrar a ninguna de las cinco. Y `/sistema` sin alertas.
5. **Comprobar con el mapa de datos** (Cloud Shell; no muestra datos personales, solo qué hay):
```bash
gcloud run jobs execute golden-ops-staging --region us-east4 --args=-m,app.ops_runner,export-person-data --update-env-vars EXPORT_CEDULA=9990001 --wait
```
En el resultado (en el registro de la ejecución, campo `jsonPayload.results`) debe verse `"personas": []` y `"suprimida": true`. Repite si quieres con otras cédulas. (Quita la variable después: `gcloud run jobs update golden-ops-staging --region us-east4 --remove-env-vars EXPORT_CEDULA`.)
6. Lo único que **queda a propósito** es el registro de las aceptaciones y rechazos (prueba legal, 3 años, bloqueado). Es normal y no se borra.
7. Opcional: pasa el evento a **Finalizado** (selector de estado en **Eventos**).

**Atención:** no uses «Borrar los datos biométricos de TODO el evento» ni toques los botones de otros clientes. Para esta prueba solo se usa el botón por persona.

---

## 10. Si algo falla

| Síntoma | Qué significa | Qué hacer |
|---|---|---|
| El enlace `/aceptar/…` dice «Esta página no está disponible» | Falta marcar la opción del Paso 3, o el evento no tiene rostro activo | Revisa el paso guiado y **«Guardar y revisar»** |
| El cuadro de resumen dice «Falta …» | Falta un dato de la empresa o del organizador | Léelo y avísame |
| Después de aceptar, el rostro nunca queda listo | La tarea no corrió | Mira la sección 8; si hay tareas fallidas: `gcloud run jobs execute golden-ops-staging --region us-east4 --args=-m,app.ops_runner,retry-face-jobs --wait` |
| La cámara no enciende | El navegador no tiene permiso de cámara | Permite la cámara para el sitio |

---

# Guiones por escenario del piloto (G1, G2, G3)

> Todavía no sabemos cómo llegarán las 200 personas del piloto del 29 de octubre. Estos tres guiones dejan probados los tres casos. **G3 se puede probar ya.** G1 y G2 usan piezas que se están construyendo (enlace personal por correo, entrada con rostro, selfie en la verificación, estado por persona, exportación de enlaces); cada guion dice qué pieza necesita y se prueba cuando esté desplegada en staging.

## Datos de prueba que debes preparar (una sola vez)

| Qué | Cuántos | Para qué |
|---|---|---|
| Buzones de correo reales que controles (sirve una cuenta con `+`: `tunombre+ana@…`, `tunombre+beto@…`) | 6 | Recibir enlaces y constancias |
| Un celular iPhone, un Android y un iPad | 3 | Cámara y pantallas reales |
| Un portátil (Chrome o Edge) | 1 | Quiosco de la puerta |
| Cartel con el QR de `/aceptar` impreso | 1 | G2 |
| Dos documentos de identidad físicos (los de personas que estén presentes) | 2 | Verificación en la puerta (G2) |
| Un cronómetro | 1 | Toques y segundos por persona |
| Bases de Excel (ver abajo) | 2 | Cargas |

**Base de G1** (`base_g1.xlsx`), columnas `Cédula`, `Nombres`, `Apellidos`, `Correo`, `Fecha de nacimiento`, `Talla de camisa`:

| Cédula | Nombres | Apellidos | Correo | Fecha de nacimiento | Rol en la prueba |
|---|---|---|---|---|---|
| 9991001 | Ana | Prueba | buzón A | 1990-04-02 | Acepta por el enlace |
| 9991002 | Beto | Prueba | buzón B | 1988-07-15 | Acepta por el enlace |
| 9991003 | Cata | Prueba | buzón C | hace 15 años (p. ej. 2011-03-10) | Menor de edad |
| 9991004 | Dani | Prueba | buzón D | 1992-11-20 | Dice que no |
| 9991005 | Eli | Prueba | buzón E | 1995-01-30 | Nunca acepta |
| 9991006 | Fede | Prueba | **el mismo buzón A** | 1985-05-05 | Correo repetido (debe avisar) |
| 9991007 | Gus | Prueba | `correo-mal-escrito` | 1980-09-09 | Correo inválido (debe avisar) |

**Base de G3** (`base_g3.xlsx`): las cédulas 9993001 a 9993005, columnas `Cédula`, `Nombres`, `Apellidos`, `Correo`, `Fecha de nacimiento`, con fechas en los tres formatos (`2011-03-10`, `10/03/2011` y una celda de fecha de Excel). Más un zip `fotos_g3.zip` con una foto cualquiera nombrada `9993001.jpg` (solo para comprobar que se rechaza).
**G2** no necesita Excel: se inscriben desde el formulario público 5 personas con los datos de G1.

---

## G1. Escenario 1: la base se carga con un correo real por persona
**Piezas necesarias:** enlace personal por correo (B2a), fuente de foto (B2c), entrada con rostro (B1), estado por persona, exportación y envío de enlaces, correo de constancia (B2b), validación de la selfie en el servidor (B2d reducida).

**Preparar el evento:** evento propio de Golden. Paso guiado: Paso 0 rostro activo; Paso 1 «Evento propio de Golden»; Paso 2 «el cliente entregará fotos antes» **sin marcar**; Paso 3 aceptación desde el celular **activa**, «enviar enlace personal por correo» **activo**, fuente de foto **«la persona se toma la selfie»**, «Entrada con rostro» **activa**. **Debe ver:** el resumen «✅ Listo: así funcionará en la puerta».

1. **Cargar la base** (`base_g1.xlsx`) en «Adjuntar Base de Datos». **Debe ver:** la caja «Columnas del archivo» con «Talla de camisa» como campo nuevo; un aviso por el correo repetido (Fede) y por el inválido (Gus).
2. **Enviar los enlaces** (o **Exportar enlaces personales** si el correo aún no está configurado: sale un archivo con cédula, nombre, correo y enlace). **Debe ver:** en el directorio, para cada persona, «enlace enviado»; Gus y Fede sin envío.
3. **Ana, en el celular:** abre el enlace → ve el texto de autorización → acepta → confirma su fecha de nacimiento → se toma la selfie. **Debe ver:** mensaje de gracias; en el buzón A, el correo de constancia con la escarapela virtual y **sin foto**. En el directorio: «aceptó · verificada · vector listo» (en unos segundos).
4. **Cata (menor):** abre su enlace → al poner su fecha de nacimiento **no se abre la cámara** y dice que entra por cédula o QR. **Debe ver:** sin selfie, sin vector y sin correo de constancia de rostro.
5. **Dani** pulsa «No acepto»: queda sin rostro. **Eli** no hace nada.
6. **Selfie mala:** con Beto, subir una selfie a oscuras, otra borrosa y otra con dos personas. **Debe ver:** «intenta de nuevo» con el motivo, y nada guardado hasta que una sea buena.
7. **Puerta, Ana:** en el portátil, pantalla «Entrar con mi rostro» → Ana pulsa → mira a la cámara. **Debe ver:** coincidencia; el operador confirma con **un toque**. Cronometra toques y segundos.
8. **Puerta, Eli y Dani:** pulsan «Entrar con mi rostro». **Debe ver:** «No te encontramos… dirígete a la acreditación con tu cédula o QR», y entran por cédula. Comprueba en la base que **no se guardó imagen ni vector**.
9. **Respaldo:** acredita a Cata y a Gus por cédula y por QR.
10. **Revocar:** Ana escribe a `soporteit@goldenlogisticas.com` (o se lo dice al personal); el personal ejecuta la supresión. **Debe ver:** Ana ya no se reconoce y entra por cédula.
11. Secciones 8 (cola `golden-faces-staging`) y 9 (borrar los datos de prueba).

## G2. Escenario 2: inscripción por formulario público, sin correo verificado
**Piezas necesarias:** página de agradecimiento con el enlace (B2a), selfie en la verificación y estado por persona, validación de la selfie (B2d reducida). La aceptación queda **«por verificar»**.

**Preparar el evento:** igual que G1, pero **sin** «enviar enlace personal por correo» (o con él: el enlace sale igual, pero la aceptación sigue «por verificar» porque el correo lo escribió la propia persona).

1. **Inscribir a 5 personas** desde el formulario público, en celulares distintos (cédula, nombre, correo, fecha de nacimiento). **Debe ver:** al terminar, un enlace y un QR para autorizar el rostro.
2. **Aceptar:** 3 personas aceptan (por el enlace de agradecimiento, por el QR del cartel y por el enlace del correo), 1 dice no, 1 no hace nada. **Debe ver:** gracias; en el directorio «aceptó · **por verificar**».
3. **Puerta, una persona «por verificar»:** el operador escribe o escanea la cédula → «Continuar». **Debe ver:** el aviso de verificación **con la selfie guardada**; el operador compara con el documento físico y con la persona → «Sí, coincide». Cronometra toques y segundos (esperado: 4 a 5 toques, 18 a 28 s). Después del «Sí», la persona queda «verificada» y se reconoce con «Entrar con mi rostro».
4. **Suplantación:** con otro celular, aceptar con la cédula y la fecha de nacimiento de una persona inscrita pero con **la selfie de otra persona**. En la puerta, con el documento de la persona real. **Debe pasar:** el operador ve que la selfie guardada no es esa persona y responde «No coincide»; la aceptación sigue «por verificar» y la persona entra por cédula.
5. **Menor:** inscribir a Cata con su fecha de nacimiento: sin cámara, sin vector, entra por cédula.
6. **Correo falso:** inscribir con un correo que no existe: la inscripción se completa y la persona puede aceptar por el QR.

## G3. Escenario 3: sin biometría
**Se puede probar apenas el cierre del escenario esté en staging** (está en la rama `producto/sin-biometria`, pendiente de tu confirmación).

**Preparar el evento:** evento propio. Paso guiado: **apaga** el Paso 0 y marca **«🚫 Este evento NO usa biometría (bloquear)»** → «Guardar». **Debe ver:** el resumen «✅ Listo: este evento no usa biometría» (sin avisos rojos).

1. **La pantalla de la puerta:** abre el quiosco de registro. **No debe aparecer:** pestaña del escáner, cámara de rostro, botón «Escanear Rostro», pantalla de autorización, casilla de consentimiento ni campo «Fecha de nacimiento». La única cámara permitida es la que lee el **documento** (QR o reverso de la cédula).
2. **Parámetros y Editar persona:** no existe «Fecha de nacimiento» en la lista de campos ni en el modal de edición.
3. **Cargar `base_g3.xlsx` con el zip de fotos.** **Debe ver:** la carga termina; el aviso «Este evento no usa biometría (bloqueado): el zip de fotos se ignoró»; en «Columnas del archivo», «fecha de nacimiento» en **no usadas** con el motivo; ninguna foto guardada y el rostro sigue apagado.
4. **Acreditar** 5 personas: por cédula, por QR y creando a alguien nuevo desde «Registrar nuevo». Cronometra 10 registros por cédula (esperado: 1 a 2 toques cada uno).
5. **Intentar activar el rostro** (casilla del Paso 0 y el interruptor simple): **debe rechazarse** con el mensaje del bloqueo.
6. **Sin red** (solo en staging, hasta que se encienda en producción): modo avión en el portátil; sigue acreditando; al volver la red sincroniza sin duplicados.
7. **Escarapela virtual:** con la escarapela digital activa, el correo de cada persona llega aunque no haya rostro.
8. **Comprobar en la base** (Neon, solo lectura): `SELECT count(*) FROM users u JOIN event_attendees a ON a.user_id = u.id AND a.tenant_id = u.tenant_id WHERE a.event_id = <id del evento> AND u.face_encoding IS NOT NULL` debe dar **0**, y no debe haber fotos en el almacenamiento bajo esas cédulas.
9. Sección 9 (borrar los datos de prueba).
