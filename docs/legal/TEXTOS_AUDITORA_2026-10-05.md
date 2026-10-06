# Textos de la auditora (fuente de verdad, SIN EDITAR)

> Los textos de los bloques de código de este archivo son los de la auditora, literales: no se editan. Cualquier cambio exige nueva constancia.
> Lo que va entre [corchetes] sale de datos del evento o de las variables `COMPANY_NAME`, `COMPANY_NIT`, `PRIVACY_EMAIL`, `DOMAIN`.
> Estado: las dos variantes de autorización están **SIN CONSTANCIA** hasta que la auditora emita la suya (fecha, versión, texto exacto).
> Los textos B (contratos) y D (retracto) no se usan en el piloto y no se guardan aquí.

---

## Texto C''' DEFINITIVO (VIGENTE: el que usa la política v1.1)

```text
8. FUNCIONAMIENTO LOCAL TEMPORAL EN MODO DE CONTINGENCIA (SIN CONEXIÓN A INTERNET):
Para garantizar la continuidad ininterrumpida de la acreditación durante eventos masivos frente a caídas imprevistas de red, la plataforma dispone de un modo de contingencia local.
En dicho escenario, los dispositivos del personal de control almacenan temporalmente en la memoria local del navegador (IndexedDB) una lista técnica de verificación compuesta por: nombre para mostrar, categoría de acreditación, estado del asistente y un resumen criptográfico con sal (hash) del documento de identidad exclusivo para el evento, el cual permite validar el acceso sin conexión activa a internet.
Bajo ninguna circunstancia se descargan ni conservan fotografías ni vectores biométricos en los navegadores o terminales locales. Los registros de acceso (ingresos marcados en puerta), así como las nuevas inscripciones o modificaciones de datos efectuadas sin red, se almacenan en una cola local en el dispositivo por un término técnico máximo y perentorio de siete (7) días calendario, dentro del cual se sincronizan automáticamente con el servidor central al restablecerse la conectividad. Vencido este plazo sin sincronización, la información residual no transmitida se suprime de manera automática de la memoria del navegador, eliminándose de forma definitiva.
```

## Texto C ORIGINAL (HISTÓRICO)

```text
8. TRATAMIENTO LOCAL TEMPORAL EN MODO DE CONTINGENCIA (SIN CONEXIÓN A INTERNET):
Para garantizar la continuidad ininterrumpida del control de acceso durante eventos masivos frente a caídas imprevistas de conectividad, Golden Biometrics implementa una arquitectura de contingencia offline local.
En virtud de este mecanismo, el navegador de los dispositivos autorizados del personal de recepción almacena de forma temporal y protegida en memoria local (IndexedDB) una lista técnica de validación consistente en: nombre para mostrar, categoría de acreditación y una huella matemática irreversible (HMAC con sal criptográfica única por evento) derivada del número de documento.
Bajo ninguna circunstancia se almacenan fotografías, imágenes ni vectores biométricos faciales en los dispositivos locales sin conexión. Los registros de acceso efectuados en modo contingencia permanecen en cola local cifrada y se sincronizan automáticamente con el servidor central al restablecerse la red. Si un dispositivo no restablece conexión, la información local no transmitida se conservará por un término técnico máximo y perentorio de siete (7) días calendario, tras el cual se purgará automáticamente, sin perjuicio de las auditorías de sincronización manual de la empresa.
```

## Texto C'' (HISTÓRICO, reemplazado por C''')

```text
8. FUNCIONAMIENTO LOCAL TEMPORAL EN MODO DE CONTINGENCIA (SIN CONEXIÓN A INTERNET):
Para garantizar la continuidad ininterrumpida de la acreditación durante eventos masivos frente a caídas imprevistas de red, la plataforma dispone de un modo de contingencia local.
En dicho escenario, los dispositivos del personal de control almacenan temporalmente en la memoria local del navegador (IndexedDB) una lista técnica de verificación compuesta por: nombre para mostrar, categoría de acreditación, estado del asistente y un resumen criptográfico con sal (hash) del documento de identidad exclusivo para el evento, el cual permite validar el acceso sin conexión activa a internet.
Bajo ninguna circunstancia se descargan ni conservan fotografías ni vectores biométricos en los navegadores o terminales locales. Los registros de acceso (ingresos marcados en puerta), así como las nuevas inscripciones o modificaciones de datos efectuadas sin red, se almacenan en una cola local en el dispositivo por un término técnico máximo y perentorio de siete (7) días calendario, dentro del cual se sincronizan automáticamente con el servidor central al restablecerse la conectividad. Vencido este plazo sin sincronización, la información residual no transmitida se elimina de manera automática y definitiva de la memoria del navegador, garantizando la confidencialidad de los datos.
```

## VARIANTE 1 — evento con organizador tercero (organizador = Responsable, Golden = Encargado) — SIN CONSTANCIA

```text
AUTORIZACIÓN VOLUNTARIA DE TRATAMIENTO DE DATOS BIOMÉTRICOS SENSIBLES

En cumplimiento de la Ley 1581 de 2012 y la Resolución 52185 de 2025 de la SIC, te informamos que el suministro de tu imagen y rasgos faciales es TOTALMENTE FACULTATIVO. Si prefieres no utilizar reconocimiento facial, puedes ingresar sin restricción alguna seleccionando la opción de acreditación con documento de identidad o código QR.

Al seleccionar «Acepto y deseo usar reconocimiento facial»:
1. Declaras bajo la gravedad de juramento que eres mayor de 18 años.
2. Autorizas de manera previa, expresa e informada a [Razón Social del Organizador / NIT], en calidad de Responsable del Tratamiento, y a [Razón Social de Golden / NIT], como Encargado del Tratamiento, para tratar tu imagen facial obtenida a partir de la fotografía previamente suministrada o capturada en vivo por la cámara, así como el vector biométrico derivado de ella, con la única y exclusiva finalidad de validar tu identidad y agilizar tu acreditación de acceso al evento [Nombre del Evento].

Seguridad y Conservación: Los vectores biométricos se almacenan cifrados con clave independiente. Tu fotografía y vector facial se eliminarán definitivamente de las bases de datos activas a los siete (7) días siguientes a la finalización del evento (salvo que te encuentres inscrito con autorización biométrica en otro evento activo, caso en el cual se conservará mientras dicho evento permanezca abierto, sin superar en ningún caso el tope máximo de 180 días). Las copias de seguridad técnicas sobreescribirán la información en un ciclo máximo de hasta 30 días.

Puedes revocar esta autorización y ejercer tus derechos de consulta, actualización o supresión ante el Responsable a través de [correo del organizador] o ante el Encargado en [correo de privacidad de Golden]. Conoce la Política de Privacidad en [URL de la política].

[ BOTÓN 1: ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL ]
[ BOTÓN 2: PREFIERO INGRESAR CON DOCUMENTO / QR ]
```

## VARIANTE 2 — evento propio (Golden = Responsable único) — SIN CONSTANCIA

```text
AUTORIZACIÓN VOLUNTARIA DE TRATAMIENTO DE DATOS BIOMÉTRICOS SENSIBLES — EVENTO PROPIO

En cumplimiento de la Ley 1581 de 2012 y la Resolución 52185 de 2025 de la SIC, te informamos que el suministro de tu imagen y rasgos faciales es TOTALMENTE FACULTATIVO. Si prefieres no utilizar reconocimiento facial, puedes ingresar sin restricción alguna seleccionando la opción de acreditación con documento de identidad o código QR.

Al seleccionar «Acepto y deseo usar reconocimiento facial»:
1. Declaras bajo la gravedad de juramento que eres mayor de 18 años.
2. Autorizas de manera previa, expresa e informada a [Razón Social de Golden / NIT], en calidad de Responsable del Tratamiento, para tratar tu imagen facial obtenida a partir de la fotografía previamente suministrada o capturada en vivo por la cámara, así como el vector biométrico derivado de ella, con la única y exclusiva finalidad de validar tu identidad y agilizar tu acreditación de acceso al evento [Nombre del Evento].

Seguridad y Conservación: Los vectores biométricos se almacenan cifrados con clave que Golden administra de manera exclusiva. Tu fotografía y vector facial se eliminarán definitivamente de las bases de datos activas a los siete (7) días siguientes a la finalización del evento (salvo que te encuentres inscrito con autorización biométrica en otro evento activo, caso en el cual se conservará mientras dicho evento permanezca abierto, sin superar en ningún caso el tope máximo de 180 días). Las copias de seguridad técnicas sobreescribirán la información en un ciclo máximo de hasta 30 días. Los registros contables y fiscales de pago se conservarán por mandato legal independiente.

Puedes revocar esta autorización y ejercer tus derechos de consulta, actualización o supresión escribiendo a [correo de privacidad de Golden]. Conoce nuestra Política de Tratamiento de Información en [URL de la política].

[ BOTÓN 1: ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL ]
[ BOTÓN 2: PREFIERO INGRESAR CON DOCUMENTO / QR ]
```

## Frases para la política v1.1 (literales)

### 8.1 Datos ordinarios (90 días)

```text
Los datos identificativos y de contacto de los asistentes se conservarán por un término de noventa (90) días calendario contados a partir del cierre del evento para fines de auditoría, control y entrega de informes al organizador, tras lo cual serán suprimidos o anonimizados.
```

### 8.2 Supresión y copias de seguridad

```text
En caso de solicitarse la supresión de datos personales, estos serán eliminados o anonimizados de las bases de datos de producción de forma inmediata. Las copias de seguridad de recuperación técnica sobreescribirán dicha información en un ciclo de rotación máxima de hasta treinta (30) días calendario.
```

### 8.3 Registro de consentimiento (3 años)

```text
La revocatoria de la autorización y la supresión de los datos biométricos no conllevará la eliminación del registro pericial de auditoría que acredita que la autorización fue efectivamente otorgada en su momento, el cual se conservará debidamente bloqueado por el término de prescripción de las acciones legales (tres años), con el único fin de responder ante eventuales requerimientos de autoridades judiciales o de control.
```

## Textos anteriores de autorización (HISTÓRICOS, reemplazados por las variantes 1 y 2)

### Texto A (evento de un tercero)

```text
AUTORIZACIÓN VOLUNTARIA PARA EL TRATAMIENTO DE DATOS BIOMÉTRICOS SENSIBLES

En cumplimiento de la Ley 1581 de 2012 y el Decreto 1074 de 2015, te informamos que el suministro de tu imagen facial es de carácter TOTALMENTE FACULTATIVO. Si decides no suministrarlo, podrás ingresar al evento identificándote con tu documento de identidad o código QR sin restricción alguna.

Al presionar "Acepto y deseo usar reconocimiento facial", autorizas de manera previa, expresa, informada y cualificada a [Nombre del Organizador] (como Responsable) y a Golden Biometrics S.A.S. (como Encargado del Tratamiento) para capturar tu imagen facial en vivo a través de webcam, generar un vector matemático biométrico cifrado y utilizarlo única y exclusivamente con la finalidad de validar tu identidad y agilizar tu acreditación de acceso al evento [Nombre del Evento].

Tus datos biométricos serán almacenados de forma cifrada en servidores seguros y serán eliminados definitivamente a los siete (7) días siguientes a la finalización del evento (y en respaldos técnicos rotativos hasta por 30 días adicionales). Puedes consultar nuestra Política de Privacidad y ejercer tus derechos de consulta, actualización y supresión mediante comunicación a: privacidad@goldenbiometrics.com.

[ BOTÓN 1: ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL ]
[ BOTÓN 2: NO DESEO USAR RECONOCIMIENTO FACIAL (INGRESAR CON DOCUMENTO) ]
```

### 8.4 Variante evento propio (anterior)

```text
AUTORIZACIÓN VOLUNTARIA DE DATOS BIOMÉTRICOS — EVENTO PROPIO
(Art. 6, Ley 1581 de 2012 y Res. 52185 de 2025 de la SIC)

En cumplimiento de la normativa colombiana de protección de datos personales, te informamos que el suministro de tu imagen y rasgos faciales es de carácter TOTALMENTE FACULTATIVO Y VOLUNTARIO. Si prefieres no usar reconocimiento facial, puedes ingresar sin restricción alguna seleccionando la opción de acreditación por cédula o código QR.

Al presionar «Acepto y deseo usar reconocimiento facial», declaras bajo juramento ser mayor de 18 años y autorizas de manera previa, expresa e informada a [Razón Social de Golden / NIT], en calidad de Responsable del Tratamiento, para capturar tu imagen facial mediante cámara, calcular un vector biométrico cifrado y tratarlo con la única finalidad de verificar tu identidad y agilizar tu acreditación de ingreso al evento [Nombre del Evento].

Seguridad y Plazos de Borrado: Tu vector facial se almacena cifrado con una clave que solo Golden controla. La foto y el vector se eliminarán definitivamente de nuestras bases activas siete (7) días después de finalizado el evento (con una permanencia máxima en copias de seguridad de recuperación técnica de hasta 30 días adicionales).

Puedes revocar esta autorización o ejercer tus derechos de consulta, actualización y supresión escribiendo a [correo de privacidad]. Conoce nuestra Política de Tratamiento en [URL de la política].

[ BOTÓN 1: ACEPTO Y DESEO USAR RECONOCIMIENTO FACIAL ]
[ BOTÓN 2: PREFIERO INGRESAR CON DOCUMENTO / QR ]
```
