# Política de Privacidad y Tratamiento de Datos Personales — versión 1.1

**ESTADO: PENDIENTE DE RATIFICACIÓN por la auditora.** Esta versión no está publicada. Las frases marcadas «(texto de la auditora)» son literales de `TEXTOS_AUDITORA_2026-10-05.md` y no se modifican.

Conforme a la Ley 1581 de 2012, el Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015), la Resolución 52185 de 2025 de la Superintendencia de Industria y Comercio (SIC) y demás normas colombianas de protección de datos personales.

## 1. Quiénes somos y qué papel tenemos

**Golden Eventos y Logística S.A.S.**, NIT 901.542.833 («Golden»), presta la plataforma GoldenWeb 2.0 para inscribir, acreditar y controlar el acceso de personas a eventos. Canal de privacidad: **soporteit@goldenlogisticas.com** (se revisa a diario). Sitio: https://app.golden-eventos.com/privacidad.

Según quién organice el evento, Golden actúa así:

- **Eventos propios de Golden:** Golden es el **Responsable único** del tratamiento de los datos de los asistentes.
- **Eventos de un tercero (organizador):** el organizador es el **Responsable** de los datos de sus asistentes y Golden es el **Encargado** del tratamiento. En ese caso la pantalla de autorización nombra al organizador y a Golden.
- **En todos los casos** Golden es el **Responsable** de los datos de las cuentas de su personal y de sus clientes directos, y de los datos técnicos de operación de la plataforma.

## 2. Qué datos tratamos

| Tipo | Ejemplos |
|---|---|
| Identificación | Tipo y número de documento, nombres y apellidos, fecha de nacimiento (solo para saber si la persona es mayor de 18 años). |
| Contacto | Correo, teléfono, ciudad y país, cuando el formulario o el organizador los piden. |
| Del evento | Entidad, cargo, tipo de asistente, categoría, acompañantes y campos adicionales que defina el organizador; registros de ingreso (fecha, hora, tipo de ingreso y evento). |
| Firmas y adjuntos | Firmas digitales y archivos que la persona suba. |
| **Biométricos (sensibles)** | Fotografía facial y su representación numérica (vector), **solo** si la persona lo autoriza. |
| Pagos | El pago lo procesa Wompi; Golden **no ve ni guarda** el número de la tarjeta. Guarda la referencia, el monto, el método, el estado y la identificación de quien paga. |
| Técnicos | Cookies necesarias de sesión y seguridad, dirección IP para limitar abusos y registros de la plataforma. |

## 3. Para qué usamos los datos

Inscribir y acreditar personas, controlar el acceso (entrada, zonas e inventario), emitir escarapelas y certificados, procesar pagos y reembolsos, generar reportes para el organizador, cumplir obligaciones legales, atender consultas y reclamos, y mantener la seguridad de la plataforma.

## 4. Autorización

Tratamos tus datos con autorización previa, expresa e informada (Ley 1581, art. 9). Responder sobre datos sensibles es **facultativo**: nadie está obligado a autorizar su tratamiento (art. 6).

## 5. Reconocimiento facial: voluntario, con autorización de la persona

- **Voluntario y con alternativa permanente.** Puedes entrar al evento con tu cédula o código QR **sin ninguna restricción ni consecuencia**. El reconocimiento facial es solo una comodidad opcional.
- **La autorización la das tú, no el personal del evento.** Se pide en una pantalla completa antes de encender la cámara, una sola vez por persona y evento (o antes de cada uso, si el evento lo define así), con el texto exacto que ves; queda registrado con la fecha, la versión y la huella (SHA-256) del texto que viste. También puedes darla antes del evento desde tu celular, en la página de aceptación del evento; en ese caso tu aceptación queda «por verificar» hasta que el personal confirme tu identidad en la puerta con tu documento o QR.
- **Menores de edad.** Las personas menores de 18 años **no** pasan por captura biométrica: no se les muestra la pantalla, no se enciende la cámara y no se calcula ningún vector. Ingresan solo con cédula o QR.
- **Cuándo se calcula tu vector.** Solo **después** de que aceptes. Si no aceptas, no se calcula.
- **Si no te reconocemos.** Si la cámara no te encuentra en la lista, no se guarda tu foto en vivo ni el vector temporal: se te remite a la acreditación con tu cédula o QR.
- **Cuánto tiempo.** Tu fotografía y tu vector facial se eliminan definitivamente de las bases activas a los **siete (7) días siguientes a la finalización del evento**, salvo que estés inscrito con autorización biométrica en otro evento activo; en ese caso se conservan mientras ese evento siga abierto, **sin superar en ningún caso el tope máximo de 180 días** desde que se captaron. Las copias de seguridad técnicas sobreescriben la información en un ciclo máximo de hasta **30 días** adicionales.
- **Seguridad.** Los vectores se almacenan cifrados con una clave que administra Golden de forma exclusiva, y el acceso está restringido al personal autorizado.
- **Revocar.** Puedes revocar tu autorización en cualquier momento. Revocar equivale a suprimir tu fotografía y tu vector; sigues pudiendo entrar con tu cédula o QR.

## 6. Datos ordinarios, supresión y copias de seguridad

*Datos ordinarios (texto de la auditora):*

> Los datos identificativos y de contacto de los asistentes se conservarán por un término de noventa (90) días calendario contados a partir del cierre del evento para fines de auditoría, control y entrega de informes al organizador, tras lo cual serán suprimidos o anonimizados.

*Supresión y copias de seguridad (texto de la auditora):*

> En caso de solicitarse la supresión de datos personales, estos serán eliminados o anonimizados de las bases de datos de producción de forma inmediata. Las copias de seguridad de recuperación técnica sobreescribirán dicha información en un ciclo de rotación máxima de hasta treinta (30) días calendario.

Al suprimir los datos de una persona, sus registros de ingreso se **anonimizan de forma irreversible**: se desvincula a la persona y se conservan solo la hora, el tipo de ingreso y el evento. Lo que no desaparece al instante es: las versiones anteriores de los archivos (se eliminan solas en 1 día), el historial de la base de datos (1 día), las copias de seguridad (hasta 30 días) y la copia local de los dispositivos sin conexión hasta su próxima sincronización.

## 7. Registro de la autorización y registros de pago

*Registro de consentimiento (texto de la auditora):*

> La revocatoria de la autorización y la supresión de los datos biométricos no conllevará la eliminación del registro pericial de auditoría que acredita que la autorización fue efectivamente otorgada en su momento, el cual se conservará debidamente bloqueado por el término de prescripción de las acciones legales (tres años), con el único fin de responder ante eventuales requerimientos de autoridades judiciales o de control.

Ese registro conserva el **identificador del titular** (su documento), la fecha, la versión y la huella del texto mostrado, y la decisión, durante tres (3) años; su lectura está restringida y no se usa para ningún otro fin.

Los **registros contables y fiscales de pago** (referencia, monto, fecha, estado e identificación de quien paga) se conservan por diez (10) años, bloqueados, solo para atender a autoridades tributarias y judiciales. Cuando se suprimen los datos de una persona, su correo de contacto de pago se elimina.

## 8. Funcionamiento local temporal en modo de contingencia (sin conexión a internet) (texto de la auditora)

8. FUNCIONAMIENTO LOCAL TEMPORAL EN MODO DE CONTINGENCIA (SIN CONEXIÓN A INTERNET):
Para garantizar la continuidad ininterrumpida de la acreditación durante eventos masivos frente a caídas imprevistas de red, la plataforma dispone de un modo de contingencia local.
En dicho escenario, los dispositivos del personal de control almacenan temporalmente en la memoria local del navegador (IndexedDB) una lista técnica de verificación compuesta por: nombre para mostrar, categoría de acreditación, estado del asistente y un resumen criptográfico con sal (hash) del documento de identidad exclusivo para el evento, el cual permite validar el acceso sin conexión activa a internet.
Bajo ninguna circunstancia se descargan ni conservan fotografías ni vectores biométricos en los navegadores o terminales locales. Los registros de acceso (ingresos marcados en puerta), así como las nuevas inscripciones o modificaciones de datos efectuadas sin red, se almacenan en una cola local en el dispositivo por un término técnico máximo y perentorio de siete (7) días calendario, dentro del cual se sincronizan automáticamente con el servidor central al restablecerse la conectividad. Vencido este plazo sin sincronización, la información residual no transmitida se suprime de manera automática de la memoria del navegador, eliminándose de forma definitiva.

## 9. Con quién compartimos datos y transmisión internacional

| Proveedor | Para qué | Ubicación |
|---|---|---|
| Google Cloud (Cloud Run, Cloud Storage, Firebase Hosting) | Alojamiento de la aplicación, de los archivos (fotos, firmas, documentos) y de las copias de seguridad | Estados Unidos (us-east4, Virginia del Norte) |
| Neon (PostgreSQL, sobre AWS) | Base de datos de la plataforma, incluidos los vectores cifrados | Estados Unidos (AWS us-east-1, Virginia) |
| Cloudflare | Seguridad y entrega de la página | Global |
| Wompi (Bancolombia) | Pagos en línea | Colombia |
| Microsoft (Microsoft 365) | Envío de correos | Según su servicio |
| El organizador del evento | Recibe los datos de sus propios asistentes | — |

El almacenamiento y el tratamiento en Estados Unidos constituyen **transmisión internacional** de datos a un país con nivel adecuado de protección según la SIC, amparada por los acuerdos de tratamiento de datos con cada proveedor.

## 10. Tus derechos y cómo ejercerlos

Puedes conocer, actualizar y rectificar tus datos; pedir prueba de la autorización; ser informado del uso que les damos; revocar la autorización y pedir la supresión (incluido tu rostro); presentar quejas ante la SIC; y acceder gratuitamente a tus datos.

Escribe a **soporteit@goldenlogisticas.com** indicando tu nombre, documento, el evento y lo que solicitas. En eventos de un tercero también puedes dirigirte al organizador, cuyo correo aparece en la pantalla de autorización. Respondemos las **consultas en máximo 10 días hábiles** y los **reclamos en máximo 15 días hábiles** (prorrogables según la ley).

## 11. Eventos fuera de Colombia, cookies y cambios

La ley aplicable es la colombiana, sin perjuicio de las normas imperativas del país donde se realice el evento o resida el titular. Usamos únicamente cookies necesarias (sesión y seguridad). Publicaremos aquí cualquier cambio y, si es sustancial para datos sensibles, volveremos a pedir tu autorización.
