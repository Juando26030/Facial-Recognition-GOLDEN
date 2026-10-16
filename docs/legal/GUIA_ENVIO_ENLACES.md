# Guía no técnica: enviar el enlace personal de autorización por correo (entrega 1)

**Para qué sirve.** Cada persona del listado que cargó Golden recibe un correo con **su enlace personal**. Al abrirlo escribe su fecha de nacimiento, se toma una selfie y acepta (o no) el reconocimiento facial. Como el correo viene del listado de Golden, su aceptación queda **verificada** y entra directo al reconocimiento. El texto del correo es el que la auditora aprobó el 9 de octubre, sin cambios. Es **voluntario**: quien no lo hace entra con cédula o QR.

**Dónde está.** En el evento → **Parámetros** → «Permitir aceptar desde el celular» (debe estar marcado) → cuadro **«Enviar el enlace personal por correo…»**. Solo lo ven coordinadores y administradores, y solo en eventos **propios de Golden**.

## Qué ve la persona al abrir su enlace
- **Si aún no ha aceptado:** la página le pide **solo su cédula** (como al pedir un certificado). Continúa si coincide con **su** registro (no se busca en todo el evento); si no, ve un mensaje genérico. La mayoría de edad sale de la **fecha de nacimiento ya cargada en la base**; si la base **no** la tiene, entonces (y solo entonces) la página pide la fecha y bloquea a los menores. La página general del QR del cartel sigue pidiendo cédula + fecha.
- **Límite:** tras **5 cédulas equivocadas en 15 minutos**, ese enlace se pausa 15 minutos (aunque después escriba bien los datos). No se guarda IP ni navegador. Un acierto reinicia el conteo.
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

## Cámara y aspecto de la página (A1) — qué probar en staging
La página de aceptación ahora tiene el **mismo estilo** de los formularios públicos y muestra el **logo del evento** (si tiene uno cargado) o el de Golden. Textos fijos de la auditora: encima del botón de aceptar «Este proceso es 100% voluntario…», debajo «Tecnología biométrica y tratamiento de datos operados por Golden Eventos y Logística S.A.S.» y, bajo la cámara, «Solo guardamos la foto final que decidas enviar…». El texto legal y su huella **no** cambian.

Pruébalo en **Android (Chrome)**, **iPhone (Safari)** y **computador**:
1. Abre un enlace personal, escribe cédula y fecha, acepta. *Debes ver:* «Abrir la cámara» y, debajo, «O sube una foto desde tu dispositivo».
2. «Abrir la cámara» → permite el permiso. *Debes ver:* la cámara frontal en vivo con un **óvalo** guía. «Tomar foto» → vista previa con **Repetir** y **Usar esta foto**.
3. Tápate la cámara con la mano y toma la foto. *Debes ver:* «La foto está muy oscura… Intenta de nuevo» y **sin** botón «Usar esta foto». Repite una segunda vez mal: ahora sí aparece «Usar esta foto» («Si no logras una mejor, puedes usar esta»).
4. Con una buena foto: «Usar esta foto» → «Enviar mi selfie». *Debes ver:* el mensaje de gracias.
5. Niega el permiso de cámara en otro dispositivo. *Debes ver:* el aviso y la opción de subir un archivo, que funciona igual.
6. Anota cualquier equipo donde la cámara no abra o la revisión rechace siempre fotos buenas (marca y modelo): los umbrales se pueden ajustar.

## Foto biométrica en la escarapela (A1)
En Parámetros, solo un **super administrador** ve «Permitir imprimir la foto biométrica en la escarapela». Viene **apagado**: el elemento «foto» de la escarapela (impresa y digital) sale como un recuadro vacío. Para el piloto del 29 déjalo apagado (y además quita el elemento de foto de la plantilla, como decidiste).

## Revisión de la selfie en el servidor (B2d)
Además de la revisión simple del celular, el servidor revisa la selfie **antes** de registrar la aceptación: **una sola cara**, de **tamaño suficiente**, **nítida** y con **luz razonable**. Si no, la persona ve el motivo («En la foto aparece más de una persona…», «Tu cara se ve muy pequeña…», etc.), la repite y **nada queda registrado** (ni la aceptación ni la foto). Para probarlo: envía una foto con dos personas, otra muy lejana y otra a oscuras; las tres deben pedir repetir.

## Mensaje para menores (texto de la auditora)
Cuando la persona resulta menor de 18 años (en el enlace personal o en la página del QR), ve en bloques: «Acceso facial restringido por edad» / «Según tu fecha de nacimiento registrada, eres menor de 18 años.» / el recuadro destacado «🎫 Tu entrada está garantizada: …» / y al final «¿Hay un error en tu fecha de nacimiento? …». Si la fecha la **escribió la propia persona** (no venía en la base), la segunda frase dice «Según tu fecha de nacimiento, eres menor de 18 años.» (sin «registrada»).

**Casilla de mayoría de edad:** solo aparece en eventos de **terceros** (es la declaración «Declaro bajo la gravedad de juramento que tengo 18 años o más», que acompaña al texto de la auditora para ese tipo de evento). En eventos propios no debe verse; un error de estilo la mostraba vacía y ya quedó corregido.

## Menores de edad en el envío
Si en la base la persona aparece como **menor de 18 años** (por su fecha de nacimiento), **no se le envía el enlace ni el correo** y ni siquiera se emite su enlace. Al pulsar «Iniciar envío» queda en el registro de envíos como **«omitido: menor de edad»**, sin más datos (no se guarda su correo ni nada del envío), y el resumen muestra la línea **«Omitidos por menor de edad: N»**. La vista previa ya los cuenta como omitidos («es menor de edad (sin biometría)»). El botón «Reenviar» tampoco funciona con un menor. Si la persona **no tiene fecha de nacimiento**, el flujo sigue como siempre: se le invita y la página de aceptación pide la fecha y bloquea si resulta menor.
