# Guía no técnica: enviar el enlace personal de autorización por correo (entrega 1)

**Para qué sirve.** Cada persona del listado que cargó Golden recibe un correo con **su enlace personal**. Al abrirlo escribe su fecha de nacimiento, se toma una selfie y acepta (o no) el reconocimiento facial. Como el correo viene del listado de Golden, su aceptación queda **verificada** y entra directo al reconocimiento. El texto del correo es el que la auditora aprobó el 9 de octubre, sin cambios. Es **voluntario**: quien no lo hace entra con cédula o QR.

**Dónde está.** En el evento → **Parámetros** → «Permitir aceptar desde el celular» (debe estar marcado) → cuadro **«Enviar el enlace personal por correo…»**. Solo lo ven coordinadores y administradores, y solo en eventos **propios de Golden**.

## Reglas que el sistema cumple solo
- **Máximo 25 correos por minuto** (uno cada 2,4 segundos). 200 personas tardan unos 8 minutos.
- **Solo adultos con correo válido** que no se inscribieron por un formulario abierto (ese correo lo escribió quien se inscribió, no es del listado) y que no han aceptado ni rechazado ya.
- **Nunca dos veces a la misma persona.** Si algo se corta, **no se reenvía solo**: queda como «sin confirmar» en el registro y lo revisas tú.
- **Se puede detener** en cualquier momento y **reanudar** sin repetir a nadie.
- **Registro:** quién (cédula), fecha y hora (UTC) y resultado. No se guarda IP ni navegador, ni la dirección de correo.

## Paso a paso (antes del envío real)
1. **Actualizar vista previa.** Debes ver: «Recibirían el correo: N personas (unos X min). Se omiten M.» y debajo cuántas se omiten y **por qué** (sin correo, correo no válido, menor de edad, ya se le envió, ya respondió, se inscribió por formulario). Revisa que N sea lo que esperas.
2. **Enviar prueba.** Escribe **tu** correo y pulsa «Enviar prueba». Debes ver el aviso verde «Prueba enviada», y en tu bandeja un correo con asunto que empieza por **[PRUEBA]** y el mismo texto aprobado. El enlace de la prueba **no funciona a propósito** (no pertenece a nadie). Revisa también la carpeta de spam.
3. **Iniciar envío.** Pulsa «Iniciar envío» y confirma. Debes ver «Envío iniciado». Pulsa «Actualizar vista previa» de vez en cuando: «Enviados» sube y «Recibirían» baja.
4. **Detener envío** (si hace falta). Debes ver «Envío detenido…». Para seguir, «Iniciar envío» otra vez: solo se envía a quienes faltan.
5. Al terminar, «sin envío en curso» y «Recibirían el correo: 0».

## Si algo sale mal
- **El envío se detiene solo** tras 3 fallos seguidos: casi siempre el correo del sistema no está configurado (secretos `golden-azure-*`). No insistas; avisa al equipo técnico.
- **«Sin confirmar» mayor que 0:** el sistema se reinició justo al enviar. Esa persona **no se reenvía sola** (para no duplicar). Revisa el registro y, si hace falta, reenvíale su enlace a mano.
- **«Fallidos»:** el correo no salió; la persona queda libre y entra en el siguiente envío que inicies.

## Descargas (botones del mismo cuadro)
- **Descargar enlaces (CSV):** cédula, nombre, correo y **enlace personal confiable** de cada adulto del listado (incluidos quienes no tienen correo), para enviarlos por otro medio. ⚠️ Cada enlace es la llave de una persona: no lo compartas ni lo dejes en carpetas abiertas.
- **Descargar registro (CSV):** el registro de envíos para auditoría.

## Lo que debe probar Juan en staging (después de que Claude suba la rama y se despliegue)
1. Un evento propio con 3 personas de prueba (correos tuyos) → vista previa = 3.
2. Prueba al correo propio → llega con [PRUEBA].
3. Iniciar, ver llegar 3 correos, abrir uno: debe pedir fecha de nacimiento y la aceptación debe quedar **verificada**.
4. Iniciar de nuevo → «No hay personas a quienes enviar».
5. Con otras 3 personas: iniciar, detener a la mitad, reanudar → ninguna recibe dos correos.
