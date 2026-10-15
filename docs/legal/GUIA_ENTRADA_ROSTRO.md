# Guía no técnica: «Entrar con mi rostro» (B1, autoservicio en la puerta)

**Qué es.** Una pantalla en la puerta con un botón grande **«Entrar con mi rostro»** y, debajo, **«Ingresar con cédula o QR»**. La **persona** pulsa el botón, mira a la cámara 3 segundos y:
- si el sistema la reconoce **con claridad**, su ingreso queda registrado **solo** («¡Listo! Tu ingreso quedó registrado.»);
- si no, ve «No te encontramos en la lista con reconocimiento facial. Por favor dirígete a la acreditación con tu cédula o QR.» (texto de la auditora) y entra por cédula o QR.

**Quién se reconoce.** Solo quien **aceptó** el reconocimiento facial en ese evento (y, si aceptó desde el celular, ya quedó **verificada**). Los menores y quienes no aceptaron **nunca** se comparan.

**Qué se guarda.** Solo el registro de ingreso normal (con «Rostro (autoservicio)» como forma de registro). La foto de la cámara **no se guarda**: vive solo mientras se compara. El contador guarda **solo números** (intentos, coincidencias, sin coincidencia, distancia y margen), nunca la cédula, el nombre ni la imagen.

**«Coincidencia clara»** = distancia **≤ 0,50** al más parecido **y** al menos **0,06** de diferencia con el segundo más parecido. El 0,50 se calibra con la prueba de la sección 4.

---

## 1. Activarla en un evento
1. Evento → **Parámetros** → paso guiado de biometría: reconocimiento facial activo, sin candado.
2. Marca **«Entrada con rostro en autoservicio»** → **Guardar y revisar**. *Debes ver:* «Guardado».
3. En el equipo de la puerta (tablet o portátil con cámara), entra con una cuenta del personal (digitador o superior) y abre `/kiosk/<número del evento>/rostro` (el enlace sale junto a la casilla). *Debes ver:* el nombre del evento, el botón «Entrar con mi rostro» y, debajo, «Ingresar con cédula o QR».
4. El evento debe estar **en proceso**; si no, la pantalla responde que no se puede registrar.

## 2. Supervisión (sin hacer clic)
En la pantalla de **Registro** del evento aparece la franja **«Entradas con rostro (autoservicio)»** con las últimas 5 entradas: **foto de registro**, nombre y hora, y un contador (intentos, coincidencias, sin coincidencia, revertidas). Se actualiza sola cada 3 segundos.
- Si una entrada **no cuadra** (la foto no es la persona que entró): **Revisar** → confirmar. *Debes ver:* «Entrada revertida»; la persona queda como no registrada y debe entrar con cédula o QR. Queda en el rastro de cambios (quién y cuándo).

## 3. Reglas que el sistema cumple solo
- **Sin conexión** (o con el modo contingencia del quiosco activo) el botón «Entrar con mi rostro» **desaparece**; «Ingresar con cédula o QR» queda **siempre**.
- **Límite por persona, no por equipo:** si alguien no es reconocido **2 veces seguidas**, la pantalla muestra «No te encontramos… dirígete a la acreditación con tu cédula o QR» y **se reinicia sola** a los pocos segundos para la siguiente persona. Solo hay un tope alto por equipo contra abuso (30 intentos por minuto). No se guarda IP.
- Si alguien **ya había entrado**, no se duplica: la pantalla dice «Ya habías ingresado» (sin nombre) y en la franja del personal esa línea aparece marcada **«ya había entrado»** (con su foto de registro, sin botón de revertir).
- **Aviso en Parámetros:** mientras no exista la prueba de vida (prueba de movimiento), con la entrada con rostro encendida aparece «⚠️ Sin prueba de vida: requiere supervisión constante». Una foto o una pantalla frente a la cámara **puede pasar**: el personal debe mirar la franja todo el tiempo.
- La pantalla pública **no muestra el nombre** de nadie.
- Nada de esto funciona si el evento tiene el candado biométrico o el rostro apagado.

## 4. Prueba guiada de calibración (en STAGING, con voluntarios)
**Objetivo:** confirmar que con **0,50** entran solas las personas correctas y **nunca** una persona equivocada. **No deja fotos guardadas**: solo números.

**Preparar (30 min).**
- Un evento de prueba propio de Golden, en proceso, con rostro activo y «Entrada con rostro» marcada.
- **12 voluntarios inscritos** que **aceptan** con selfie desde su enlace (idealmente: 2 con gafas, 2 parecidos entre sí o familiares, distintas edades y tonos de piel).
- **5 voluntarios NO inscritos** (o inscritos que **no** aceptan): son los «impostores».
- La tablet o el portátil **en el sitio y con la luz reales** de la puerta (o lo más parecido).

**Correr (45 min).**
1. Cada uno de los 12 inscritos hace **5 intentos** (de frente; uno con gafas o gorra si las usa; uno algo de lado; uno a contraluz si la puerta lo tiene). Entre intentos de la misma persona, el personal pulsa **Revisar** en la franja para dejarla otra vez como no registrada.
2. Cada uno de los 5 impostores hace **3 intentos**.
3. Pareja de parecidos: cada uno intenta 3 veces y se anota si alguna vez entró **el otro**.

**Anotar (planilla en papel, sin fotos):** por intento → persona (código V01…V17, no el nombre), si quedó **dentro** o **no encontrado**, y si la franja mostró **a la persona correcta**.

**Leer el resultado.** Al final, `GET /api/events/<número>/door-face/stats` (o el contador de la franja) da intentos, coincidencias y las **distancias** de cada intento (solo números). Envíame la planilla y esos números.
- **Debe ser cero:** impostores que entraron y entradas de la persona equivocada. Si hay **uno solo**, bajamos el umbral (p. ej. 0,45) y repetimos.
- **Deseable:** que al menos 4 de cada 5 intentos de inscritos entren solos. Si muchos quedan «no encontrado» con distancias entre 0,50 y 0,55, se puede subir un poco el umbral, pero **solo** si los impostores siguen en cero.
- El umbral se cambia sin programar, con la variable `DOOR_AUTO_MAX_DIST` (la ajusto yo en la configuración y se despliega con tu orden).

**Al terminar:** borra el evento de prueba y las personas (sección 9 de la guía de staging) y pide a los voluntarios que, si quieren, revoquen su autorización.

## 5. Prueba de movimiento (prueba de vida) — requisito para el piloto
**Qué hace.** Tras la cuenta 3-2-1, la pantalla toma una foto **de frente** y enseguida pide **«Ahora gira un poco la cabeza hacia tu IZQUIERDA»** (o DERECHA: lo elige el servidor al azar en cada intento), con una flecha. Toma una segunda foto 1,5 s después. Solo entra quien **giró hacia el lado pedido**, con **una sola cara** y siendo **la misma persona** en las dos fotos. Una foto impresa o una pantalla frente a la cámara **no produce ese giro** y no pasa («No pudimos comprobar el movimiento. Intenta de nuevo siguiendo la indicación.»). Ninguna de las dos fotos se guarda.

**Dónde se enciende.** Parámetros → paso guiado → debajo de «Entrada con rostro»: **«Prueba de movimiento (prueba de vida)»**, encendida por defecto. Si la apagas, vuelve el aviso «⚠️ Sin prueba de vida: requiere supervisión constante».

**Qué probar (en staging, en la tablet/portátil de la puerta):**
1. Tú, inscrito y con aceptación: pulsa, mira de frente, y gira **hacia el lado que diga la pantalla**. *Debes ver:* «¡Listo! Tu ingreso quedó registrado.» Repite 5 veces (usa «Revisar» en la franja entre intento e intento).
2. Gira al lado **contrario** al pedido. *Debes ver:* «No pudimos comprobar el movimiento…».
3. **Tu foto en el celular** (o impresa) frente a la cámara, inclinándola cuando pida el giro. *Debes ver:* «No pudimos comprobar el movimiento…» **siempre**. Repite 5 veces.
4. Anota cuántas veces falló el paso 1 (personas válidas rechazadas).

**Si el paso 1 falla SIEMPRE** (incluso girando bien), es la dirección de la cámara de ese equipo: dímelo y cambio la variable `LIVENESS_SIGN` (sin programar). **Si falla a veces**, se puede bajar el giro mínimo (`LIVENESS_MIN_TURN`, hoy 0,18). Si no queda confiable para el 26, apaga la casilla y el piloto sale con supervisión humana (C + D), como decidiste.

**Lo que NO cubre:** un **video** de la persona girando justo hacia el lado pedido podría pasar. Por eso la franja de supervisión sigue siendo obligatoria.
