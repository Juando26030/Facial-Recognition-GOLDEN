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
- **«Parámetros del Evento»:** debe aparecer el campo **«Talla de camisa»** y también **«Fecha de nacimiento»** (se puede renombrar o mover, no apagar). **«Editar persona»** muestra la fecha de nacimiento y se puede cambiar; si se cambia a una de menor de edad, se borran su rostro y su foto.
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
