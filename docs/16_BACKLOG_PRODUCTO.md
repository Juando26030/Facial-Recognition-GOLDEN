# Backlog de producto (acordado con Juan David, 2026-10-05)

Qué falta construir además de la migración a la nube, con las decisiones ya tomadas y el criterio de «listo» de cada pieza. **«Bloquea evento»** = sin esto un evento real no
se puede atender como la empresa lo hace; **«No bloquea»** = mejora el trabajo pero hay otra salida. Estado: ☐ pendiente · ◐ en curso · ☑ hecho.

## Decisiones transversales
- La nube va primero para lo que ya está listo; esto se construye ENCIMA, con el flujo normal (staging → despliegue automático). Los eventos sin internet siguen como antes (imagen actual en una laptop
  con router) hasta que exista el servidor local nuevo (docs/17).
- Cero hardware nuevo: celulares/tabletas Android con Chrome para registrar e imprimir; laptops Windows de la empresa como servidor local (5-6 equipos por router; más carga = más routers o 2 laptops servidoras).
- Datos personales (digitadores, clientes): solo el mínimo del formulario; la base de digitadores y de clientes solo la descarga un administrador; aviso de tratamiento de datos ya aprobado por auditoría
  (el texto lo entrega Juan David, no se redacta aquí).

## Bloquean evento
| # | Pieza | Decisiones | Listo cuando | Estado |
|---|---|---|---|---|
| B1 | **Impresión directa de escarapelas en la QL-800 desde el celular** (USB, sin computador ni app de Brother) | Chrome de Android + WebUSB; la app nativa de Brother queda descartada (no lee los PDF del sistema). Prueba con la QL-800 y un celular de Juan David | Desde el celular, un clic imprime la escarapela de un asistente y la etiqueta sale legible y cortada; el permiso USB se pide una sola vez | ◐ prototipo en `/impresion-usb` (`static/js/ql-usb.js`); falta la primera prueba con la impresora real, después integrarlo al directorio/registro |
| B1b | **Impresión desde iPad/iPhone** | Apple no permite USB ni Bluetooth de impresoras desde el navegador: un iPad imprime a través de un celular Android que tenga la impresora conectada (**cola de impresión + «estación de impresión»**, sin computador). Rollo de 62 mm continuo confirmado; el prototipo funciona en Android | Desde un iPad, un clic manda la escarapela y sale impresa en la QL-800 conectada al Android del mismo evento, sin tocar el Android | ☐ |
| B2 | **Lectura de cédula nueva y vieja al crear digitadores/clientes temporales** | La cédula nueva (MRZ) ya lee con foto; reutilizar la lectura (nueva y vieja) en el alta de usuarios temporales para llenar nombre y cédula; campos extra los define Juan David | Crear un digitador temporal escaneando su cédula llena nombre y cédula sin escribirlos | ☐ |
| B3 | **Autorregistro de digitadores y clientes por enlace** | Enlace por evento y rol (con vigencia y de un solo uso); en la pantalla final de éxito se muestra un enlace directo para iniciar sesión | Un enlace permite que la persona se registre sola y entre, con solo lo necesario | ☐ |
| B3a | — cliente | Pide: nombre y apellidos, celular y correo; empresa y nombre del evento salen solos del evento. Usuario y contraseña = teléfono o correo (a elección, **mostrado muy visible**); acceso temporal solo a ese evento | Registro completo; pantalla final con el enlace de inicio de sesión | ☐ |
| B3b | — digitador | Pide: cédula, celular, nombre, ciudad, barrio/zona y contacto de emergencia (nombre y número); coordinador, lugar y contacto de Golden se heredan del evento | Registro completo con el compromiso (B4) | ☐ |
| B4 | **Compromiso de digitadores digital, con firma, renovable** | El Word «Formato de Compromiso Digitadores» se presenta como el formulario (secciones de presentación personal mujeres/hombres, puntualidad, comportamiento, puesto de trabajo, digitación e impacto), se acepta por secciones y se firma dibujando; queda guardado (PDF) asociado al digitador. Vence a los **30 días de la firma** y el sistema **bloquea la participación en eventos** si está vencido; se puede llenar por el enlace (B3) o por el coordinador desde los parámetros del usuario | Un digitador con compromiso vencido no puede entrar a un evento hasta renovarlo; el PDF firmado se descarga | ☐ |
| B5 | **Base de datos de digitadores y clientes** | Se construye con B3/B4; solo un administrador la descarga (CSV) | Un administrador descarga la lista con contacto y vigencia del compromiso; nadie más | ☐ |
| B6 | **Servidor local (sin internet) con sincronización a la nube** | Laptop Windows como servidor, 5-6 equipos por router; sincroniza apenas haya internet y hace la copia al vuelo si solo el servidor tiene conexión. Diseño: docs/17 | Un evento completo se atiende sin internet y, al conectarse, queda igual en la nube | ☐ diseño en docs/17 |
| B7 | **Copias diarias de la base a las 3 am** | YA existe: `golden-ops-hourly` hace un respaldo por hora y uno diario a las 3 (hora de Bogotá, `OPS_DAILY_HOUR`), 30 días, con alerta si falta | Activo en producción tras el cambio (paso 6 del runbook D2.4) y verificado con `check-backups` | ☑ código · ☐ activarlo en producción |

## No bloquean evento
| # | Pieza | Decisiones | Estado |
|---|---|---|---|
| N1 | **Ficha del evento configurable + estados con reglas + historial de cambios** (replica la ficha del software anterior) | Diseño en `docs/18_EVENTO_CAMPOS_ESTADOS.md`: el administrador diseña los campos en Configuración (sin la parte web), todo lo del software anterior queda cargado, cada estado prende o apaga acceso del cliente, descarga de estadísticas, digitadores temporales, ruleta, registro, inventario…, y cada campo dice si lleva historial para los correos | ☐ esperando listas (tipos, estados, jornadas…) |
| N1b | **Calendario**: más información al crear el evento, reflejada en todos los lugares | Sale de N1 (mismos campos); Juan David enviará la información faltante | ☐ esperando datos |
| N1c | **Registro touch** (sección nueva al lado de Registro y Ruleta) | Versión pensada para pantallas táctiles (también 16:9 y módulos touch), responsive, sin depender del mouse | ☐ |
| N2 | **Correo al editar un evento** | Solo por cambios en **campos clave** (lista pendiente de Juan David). Texto: «El evento [código] de nombre [nombre] del cliente [cliente] tuvo los siguientes cambios: [lo que había antes y lo que hay ahora]». Destinatarios: comercial del evento, coordinador, **almacén del evento (campo nuevo: encargado de almacén)** y **contabilidad (rol/cuenta nueva «contabilidad», un usuario asociado a cada evento; por ahora uno solo)** | ☐ esperando lista de campos |
| N3 | **Informe del cliente con encuesta** | El cliente descarga el informe solo si (1) la comercial lo habilita en el evento y (2) respondió la encuesta de satisfacción (5 preguntas Malo/Bueno/Excelente con comentario, probabilidad de recomendar 0-10 y «¿tienes próximo evento? 2 % de descuento» opcional). Si marca interés en otro evento: **alerta por correo a la comercial** | ☐ |
| N4 | **Compartir impresora entre equipos** | Un equipo manda a imprimir y otro con la impresora imprime solo (cola de impresión por evento + «estación de impresión»). Con celulares y sin computadores (B1) queda como mejora | ☐ |
| N5 | **Inventario inteligente** (los «Recursos» por día de la ficha del evento son las reservas; ver docs/18 §6) | Seguimiento **por cantidad** (serie opcional); bodega principal en Bogotá pero los equipos pueden estar en cualquier ciudad. Al crear/editar el evento se piden equipos por tipo y ciudad y se descuentan del inventario del día; si no alcanza, avisa y no deja seguir hasta conseguirlos o alquilarlos. Reserva con **1 día** de anticipación si el equipo está en la misma ciudad del evento y alerta con **1 semana** si está en otra ciudad | ☐ |

## Orden propuesto
1. B1 prueba real con la QL-800 (lo único que depende de un aparato físico) y B7 verificado.
2. B2 + B3 + B4 + B5 (un solo bloque: cualquier persona nueva entra por el enlace, con su compromiso y su cédula).
3. B6 por fases (docs/17), en paralelo cuando B1 esté probado.
4. N2 y N3 cuando lleguen la lista de campos clave y los datos del calendario (N1); luego N4 y N5.

## Orden para un PRIMER EVENTO PILOTO (2026-10-05; la empresa mantiene su software actual como respaldo)
Criterio: «estrictamente necesario» = sin esto el piloto no se puede atender con el sistema nuevo. Como el respaldo es el software de siempre, los eventos sin internet y todo lo que ya tiene alternativa quedan fuera. Tamaños: **S** ≤ 1 día · **M** 2-4 días · **L** 1-2 semanas · **XL** 3 semanas o más (de trabajo de desarrollo, sin contar pruebas con aparatos o personas de terceros).

| Orden | # | ¿Necesario para el piloto? | Tamaño | Depende de | Porqué |
|---|---|---|---|---|---|
| 1 | **B7** copias a las 3 am activas y verificadas | **Sí (obligatorio)** | S (activar y verificar; el código existe) | El corte (docs/15 D2.5, paso 5) | Sin copias verificadas no se opera con datos reales. |
| 2 | **B1** impresión desde el celular en la QL-800 | Solo si el piloto imprime escarapelas desde celulares; si imprime como hoy (PDF/impresora del equipo) no | prueba con la impresora real **S**; integrarla al directorio/registro **M** | B7 no; el prototipo `/impresion-usb` ya existe y funcionó en Android | Es lo único que depende de un aparato físico: probarlo ya cuesta casi nada y decide si entra al piloto. |
| 3 | **B4** compromiso digital de digitadores | No (el formato del Word se sigue firmando como hoy) | **L** (formulario por secciones, firma dibujada, PDF, vencimiento a 30 días y bloqueo) | Ninguna; B3b y B5 dependen de él | Es política interna, no de operación del evento; el bloqueo por vencimiento sí podría estorbar si se enciende antes de tiempo. |
| 4 | **B2** cédula en el alta de usuarios temporales | No (se teclea) | **S** | La lectura de cédula nueva ya existe (`app/mrz_ocr.py`) | Ahorra tecleo; reutiliza lo hecho. |
| 5 | **B3** autorregistro por enlace (B3a cliente, B3b digitador) | No (los crea el coordinador como hoy) | B3a **M**, B3b **M** (+ B4) | B3b necesita B4; B3a ninguna | Quita trabajo al coordinador, no bloquea. |
| 6 | **B5** base de digitadores y clientes, descarga solo admin | No | **S** | B3 y B4 (de ahí salen los datos) | |
| 7 | **B1b** impresión desde iPad (cola + estación Android) | No | **L** | B1 integrado | Un iPad no puede imprimir directo; el piloto usa Android o computador. |
| 8 | **B6** servidor local sin internet | **No para un piloto con internet**; sí antes del primer evento sin red (hasta entonces esos eventos siguen en el software de la empresa o con la laptop de siempre) | **XL** (E0-E3 de docs/17) | Preguntas abiertas de docs/17 (equipos, facial offline, quién lo instala) | Lo más grande; es lo único que reemplaza la operación sin internet. |

Lo que SÍ necesita el piloto y no es del backlog B: el **corte** (docs/15 D2.5), el modo contingencia apagado o decidido (D2.5d), y la configuración del evento con lo que ya existe hoy. Las piezas de N (estados, ficha, correos, inventario, registro touch) tampoco bloquean el piloto.
