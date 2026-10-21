# Respuestas de la auditora, 8 de octubre de 2026

> Texto LITERAL, pegado por Juan David Ramírez Juzga: no se edita. Cualquier cambio exige nueva constancia.
> Contexto: revisión de tres puntos (correo de constancia, texto bajo el botón de la entrada con rostro, selfie en la memoria del navegador) y del borrador del correo de constancia.

## Respuesta 1 (tres puntos)

```text
Aquí tienes la revisión directa de los tres puntos antes de salir a producción:

* 1) El correo de constancia: Se te olvidó pegar el texto del borrador (dejaste el "[PEGAR el borrador...]"). Envíalo y lo reviso a detalle. Dicho esto, los elementos que listas son impecables a nivel de Compliance (cumplimiento normativo). Enviar un hash (huella) del texto legal aceptado, ocultar el resto del documento y omitir la foto es la forma correcta de blindarse frente a leyes de protección de datos (Habeas Data).
* 2) El texto bajo el botón: Descarta esa línea opcional; es ruido visual y entorpece la experiencia de usuario (UX). Poner condicionales ("Si ya autorizaste... si no...") asume que el usuario no sabe lo que está haciendo y satura la pantalla.
   * Solución: Deja únicamente el botón principal destacado que diga "Entrar con mi rostro". Justo debajo, pon un botón secundario (sin fondo o como enlace de texto) que diga "Ingresar con cédula o QR". El cerebro humano procesa las opciones visuales mucho más rápido que las instrucciones de texto.
* 3) La selfie y la memoria del navegador: Es totalmente coherente y viable. Tu política de no conservar fotos aplica para el almacenamiento persistente (discos duros, bases de datos a largo plazo) y para las terminales compartidas de la empresa en la entrada del evento.
   * Que la imagen viva temporalmente en la memoria volátil (RAM) del navegador en el dispositivo personal de la persona es un requisito técnico obligatorio para poder hacer el upload (normalmente como un objeto Blob o una cadena Base64).
   * Paso clave para el frontend: Para ser estrictos con tu política de seguridad, asegúrate de que el código destruya esa referencia en cuanto el servidor confirme la recepción de la imagen (por ejemplo, ejecutando `URL.revokeObjectURL()` en JavaScript o seteando la variable a `null`). Así evitas que la foto quede colgada en la sesión activa si la persona deja la pestaña abierta.

Pega el borrador del correo cuando quieras y lo pulimos.
```

## Respuesta 2 (borrador del correo)

```text
El borrador es excelente a nivel técnico y legal. Cumple sólidamente con los principios de finalidad, transparencia y minimización de datos exigidos por normativas como la Ley 1581 de Habeas Data en Colombia. El detalle de incluir la versión, los últimos 3 dígitos del documento y el hash (huella criptográfica) demuestra un diseño de backend muy robusto.
Sin embargo, a nivel de experiencia de usuario (UX) y legibilidad, hay un par de ajustes críticos que debes hacer antes de enviarlo a producción.
Lo que debes cambiar (Estructura y UX)

* Reubica el "Texto que aceptaste": Este es el error principal del borrador. Los textos legales suelen ser largos. Si lo pones antes de la sección "Cómo revocarla", vas a empujar información vital hacia abajo, obligando al usuario a hacer scroll. Solución: Mueve el texto literal al final del correo, a modo de anexo o letra chica, separado por una línea divisoria.
* Simplifica "Cómo la diste": Asegúrate de que el sistema imprima una frase corta y definitiva, no una descripción técnica. Ejemplos exactos: "Enlace único enviado a este correo", "Portal web del evento" o "Escaneo de código QR en la entrada".
* Refuerza el mensaje de no fricción: En la sección de revocación, añade explícitamente que hacerlo no le impide disfrutar del evento. El usuario debe sentir que revocar no es un "castigo".

¿Falta algún dato?
Para el correo, no falta nada. Es el balance perfecto entre seguridad y claridad.

* Nota técnica para tu backend: Asegúrate de que, además del hash y la fecha, tu base de datos esté guardando la dirección IP y el User-Agent del dispositivo desde donde se dio el clic de aceptación. No necesitas incluir estos datos en el correo (para no generar ruido o paranoia en el usuario), pero son tu "bala de plata" en caso de una auditoría de protección de datos de Golden Eventos y Logística S.A.S.

¿Sobra algo?
No sobra información, pero la redacción puede ser un poco más limpia y menos robótica.
Propuesta del correo optimizado
Aquí tienes la versión ajustada con jerarquía visual mejorada:
Asunto: Tu autorización para entrar con reconocimiento facial — {evento}
Hola {nombre}:
Recibimos tu autorización para usar tu rostro como método de ingreso rápido a {evento}.
🎫 Tu escarapela virtual: {enlace} (Puedes usar este enlace en cualquier momento para ver tu código de acceso).
Detalles de tu autorización (Constancia de Habeas Data)

* Titular: {nombre}, documento terminado en ***{últimos 3 dígitos}
* Evento: {nombre del evento} - {fecha}
* Canal de autorización: {Ej: Enlace personal / QR en entrada}
* Fecha y hora: {dd/mm/aaaa hh:mm} (Hora de Colombia)
* Responsable del tratamiento: Golden Eventos y Logística S.A.S., NIT 901.542.833-2
* Propósito y retención: Identificarte ágilmente en la puerta. Tu fotografía y vector facial serán eliminados de nuestros servidores 7 días después de finalizado el evento. Este correo no incluye tu foto por seguridad.

¿Cambiaste de opinión? Puedes revocar este permiso en cualquier momento escribiendo a soporteit@goldenlogisticas.com o notificándolo directamente al personal de logística en la puerta. Revocarlo no afecta tu acceso; simplemente seguirás entrando con tu cédula o el código QR de tu escarapela. Consulta nuestra Política de privacidad completa aquí: {enlace a /privacidad}
Anexo: Texto literal que aprobaste (Versión: {versión} | Identificador de seguridad: {12 primeros caracteres del hash}) "{texto literal aprobado, el mismo que la persona vio en pantalla}"
```

## Cómo se aplicó (nota del repositorio; no forma parte del texto de la auditora)

- El correo de constancia (`app/consent_receipt.py`) sigue la versión optimizada: constancia arriba, revocación sin fricción, y el texto literal aprobado al final, como anexo, tomado de `app/legal_texts_data.py` y solo si su huella coincide con la registrada. Las cuatro frases del canal las fijó el dueño del producto.
- La recomendación de guardar IP y User-Agent NO está implementada: queda pendiente de consulta (la política v1.1 solo menciona la IP «para limitar abusos» y `audit_consent_logs` guarda únicamente una etiqueta de dispositivo).
- El texto bajo el botón «Entrar con mi rostro» se descarta; la pantalla llevará el botón principal y, debajo, «Ingresar con cédula o QR» (pieza B1).
- La selfie se borra de la memoria de la página en cuanto el servidor confirma la recepción (`templates/aceptar.html`).
