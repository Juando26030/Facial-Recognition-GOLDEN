# Guía no técnica: enviar el enlace personal de autorización por correo (entrega 1)

**Para qué sirve.** Cada persona del listado que cargó Golden recibe un correo con **su enlace personal**. Al abrirlo escribe su fecha de nacimiento, se toma una selfie y acepta (o no) el reconocimiento facial. Como el correo viene del listado de Golden, su aceptación queda **verificada** y entra directo al reconocimiento. El texto del correo es el que la auditora aprobó el 9 de octubre, sin cambios. Es **voluntario**: quien no lo hace entra con cédula o QR.

**Dónde está.** En el evento → **Parámetros** → «Permitir aceptar desde el celular» (debe estar marcado) → cuadro **«Enviar el enlace personal por correo…»**. Solo lo ven coordinadores y administradores, y solo en eventos **propios de Golden**.

## Qué ve la persona al abrir su enlace
- **Si aún no ha aceptado:** la página le pide su **cédula y su fecha de nacimiento**. Solo continúa si **las dos** coinciden con **su** registro (no se busca en todo el evento). Si no coinciden, ve el mismo mensaje de siempre, sin saber cuál falló.
- **Límite:** tras **5 intentos fallidos en 15 minutos**, ese enlace se pausa 15 minutos (aunque después escriba bien los datos). No se guarda IP ni navegador. Un acierto reinicia el conteo.
- **Si ya aceptó:** ve de inmediato «Tu autorización ya quedó registrada…», **sin** pedir cédula ni fecha y sin ningún dato personal en pantalla.

## Después de aceptar
Una vez la persona aceptó, su enlace **solo muestra el estado** de su autorización: no deja volver a tomar, cambiar ni renovar la foto. Un cambio de foto lo hace únicamente el personal de Golden en acreditación. Para revocar, la persona escribe a soporteit@goldenlogisticas.com o se lo dice al personal. (Lo mismo vale para el portal con cédula.)

## Reglas que el sistema cumple solo
- **Máximo 25 correos por minuto** (uno cada 2,4 segundos). 200 personas tardan unos 8 minutos.
- **Solo adultos con correo válido** (si la persona **no tiene fecha de nacimiento** registrada, se le invita igual: la página de aceptación la pide y bloquea a los menores; la vista previa dice cuántas son) que no se inscribieron por un formulario abierto (ese correo lo escribió quien se inscribió, no es del listado) y que no han aceptado ni rechazado ya.
- **Nunca dos veces a la misma persona.** Si algo se corta, **no se reenvía solo**: queda como «sin confirmar» en el registro y lo revisas tú.
- **Se puede detener** en cualquier momento y **reanudar** sin repetir a nadie.
- **Registro:** quién (cédula), fecha y hora (UTC) y resultado. No se guarda IP ni navegador, ni la dirección de correo. Cada fila se borra sola **60 días después de su fecha** (decisión de la auditora). La constancia de aceptación (la prueba del consentimiento) **no** se borra con esto.

## Paso a paso (antes del envío real)
1. **Actualizar vista previa.** Debes ver: «Recibirían el correo: N personas (unos X min). Se omiten M.» y debajo cuántas se omiten y **por qué** (sin correo, correo no válido, menor de edad, ya se le envió, ya respondió, se inscribió por formulario). Revisa que N sea lo que esperas.
2. **Enviar prueba.** Escribe **tu** correo y pulsa «Enviar prueba». Debes ver el aviso verde «Prueba enviada», y en tu bandeja un correo con asunto que empieza por **[PRUEBA]** y el mismo texto aprobado. El enlace de la prueba **no funciona a propósito** (no pertenece a nadie). Revisa también la carpeta de spam.
3. **Iniciar envío.** Pulsa «Iniciar envío» y confirma. Debes ver «Envío iniciado». Pulsa «Actualizar vista previa» de vez en cuando: «Enviados» sube y «Recibirían» baja.
4. **Detener envío** (si hace falta). Debes ver «Envío detenido…». Para seguir, «Iniciar envío» otra vez: solo se envía a quienes faltan.
5. Al terminar, «sin envío en curso» y «Recibirían el correo: 0».

## Si algo sale mal
- **El envío se detiene solo** tras 3 fallos seguidos: casi siempre el correo del sistema no está configurado (secretos `golden-azure-*`). No insistas; avisa al equipo técnico.
- **«Sin confirmar» mayor que 0:** el sistema se reinició justo al enviar y no se sabe si el correo salió. Esa persona **no se reenvía sola** (para no duplicar). Aparece en una lista bajo la vista previa, con un botón **Reenviar** por persona (aparece pasados 5 minutos). Reenvía solo si ella dice que no le llegó. Al reenviar, su enlace anterior deja de servir y recibe uno nuevo; un doble clic no duplica.
- **«Fallidos»:** el correo no salió; la persona queda libre y entra en el siguiente envío que inicies.

## Descargas (botones del mismo cuadro)
- **Descargar enlaces (CSV):** cédula, nombre, correo y **enlace personal confiable** de cada adulto del listado (incluidos quienes no tienen correo), para enviarlos por otro medio. ⚠️ Cada enlace es la llave de una persona: no lo compartas ni lo dejes en carpetas abiertas; bórralo al terminar. Cada descarga queda registrada (quién y cuándo, sin datos personales) en «hechos del sistema». Un enlace sirve hasta que el evento se finaliza (o se desactiva la aceptación por enlace); pasada esa fecha, o si se suprime a la persona, deja de funcionar.
- **Descargar registro (CSV):** el registro de envíos para auditoría.

## Lo que debe probar Juan en staging (después de que Claude suba la rama y se despliegue)
1. Un evento propio con 3 personas de prueba (correos tuyos) → vista previa = 3.
2. Prueba al correo propio → llega con [PRUEBA].
3. Iniciar, ver llegar 3 correos, abrir uno: debe pedir fecha de nacimiento y la aceptación debe quedar **verificada**.
4. Iniciar de nuevo → «No hay personas a quienes enviar».
5. Con otras 3 personas: iniciar, detener a la mitad, reanudar → ninguna recibe dos correos.
