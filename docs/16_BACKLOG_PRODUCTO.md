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
| N1 | **Calendario**: más información al crear el evento, reflejada en todos los lugares | Juan David enviará la información faltante | ☐ esperando datos |
| N2 | **Correo al editar un evento** | Solo por cambios en **campos clave** (lista pendiente de Juan David). Texto: «El evento [código] de nombre [nombre] del cliente [cliente] tuvo los siguientes cambios: [lo que había antes y lo que hay ahora]». Destinatarios: comercial del evento, coordinador, **almacén del evento (campo nuevo: encargado de almacén)** y **contabilidad (rol/cuenta nueva «contabilidad», un usuario asociado a cada evento; por ahora uno solo)** | ☐ esperando lista de campos |
| N3 | **Informe del cliente con encuesta** | El cliente descarga el informe solo si (1) la comercial lo habilita en el evento y (2) respondió la encuesta de satisfacción (5 preguntas Malo/Bueno/Excelente con comentario, probabilidad de recomendar 0-10 y «¿tienes próximo evento? 2 % de descuento» opcional). Si marca interés en otro evento: **alerta por correo a la comercial** | ☐ |
| N4 | **Compartir impresora entre equipos** | Un equipo manda a imprimir y otro con la impresora imprime solo (cola de impresión por evento + «estación de impresión»). Con celulares y sin computadores (B1) queda como mejora | ☐ |
| N5 | **Inventario inteligente** | Seguimiento **por cantidad** (serie opcional); bodega principal en Bogotá pero los equipos pueden estar en cualquier ciudad. Al crear/editar el evento se piden equipos por tipo y ciudad y se descuentan del inventario del día; si no alcanza, avisa y no deja seguir hasta conseguirlos o alquilarlos. Reserva con **1 día** de anticipación si el equipo está en la misma ciudad del evento y alerta con **1 semana** si está en otra ciudad | ☐ |

## Orden propuesto
1. B1 prueba real con la QL-800 (lo único que depende de un aparato físico) y B7 verificado.
2. B2 + B3 + B4 + B5 (un solo bloque: cualquier persona nueva entra por el enlace, con su compromiso y su cédula).
3. B6 por fases (docs/17), en paralelo cuando B1 esté probado.
4. N2 y N3 cuando lleguen la lista de campos clave y los datos del calendario (N1); luego N4 y N5.
