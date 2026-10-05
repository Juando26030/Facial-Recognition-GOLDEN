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
| B8 | **Bandeja de salida: registro y edición completos sin red** (REQUISITO del piloto) | Diseño, rebanadas y riesgos abajo («B8»); la primera rebanada (R1: «Registrar nuevo» sin red y sin foto) ya sirve en un evento | Registrar y corregir personas sin red y que todo llegue al servidor al volver la conexión, con resultado por ítem y sin pisar nada | ☐ diseño |

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

## Orden para el PRIMER EVENTO PILOTO (2026-10-05; ~200 asistentes, con internet, el software actual de la empresa corre en paralelo como respaldo)
Criterio: «necesario» = sin esto el piloto no se atiende con el sistema nuevo. Tamaños: **S** ≤ 1 día · **M** 2-4 días · **L** 1-2 semanas · **XL** 3 semanas o más (desarrollo, sin contar pruebas con aparatos o personas de terceros).

| Orden | # | ¿Necesario para el piloto? | Tamaño | Depende de | Porqué |
|---|---|---|---|---|---|
| 1 | **B7** copias a las 3 am activas y verificadas | **Sí, obligatorio** | S (activar y verificar con `check-backups`; el código existe) | El corte (docs/15 D2.5, paso 4) | Sin copias verificadas no se opera con datos reales. |
| 2 | **Pedidos del piloto 7a y 7b** (abajo) | Sí, los pidió J para este evento | 7a **M** · 7b **M** | El corte (rama `producto/piloto` se corta de `migra/fase1-2` después de él) | Acreditar con un clic desde cualquier fila y el logo de la empresa editable. |
| 3 | **B1** impresión desde el celular en la QL-800 | Solo si el piloto imprime escarapelas desde celulares; si imprime como hoy, no | prueba con la impresora real **S**; integrarla al directorio/registro **M** | El prototipo `/impresion-usb` ya funciona en Android | Es lo único que depende de un aparato físico: probarlo cuesta casi nada y decide si entra. |
| 4 | **B2** cédula en el alta de usuarios temporales | No (se teclea) | **S** | La lectura de cédula nueva existe (`app/mrz_ocr.py`) | Ahorra tecleo; reutiliza lo hecho. |
| 5 | **B3** autorregistro por enlace (B3a cliente, B3b digitador) | No (los crea el coordinador como hoy) | B3a **M**, B3b **M** (+ B4) | B3b necesita B4 | Quita trabajo al coordinador. |
| 6 | **B4** compromiso digital de digitadores | No (el formato del Word se sigue firmando como hoy; el respaldo de la empresa lo cubre) | **L** | Ninguna; B3b y B5 dependen de él | Política interna; el bloqueo por vencimiento solo se enciende cuando esté probado. |
| 7 | **B5** base de digitadores y clientes, descarga solo admin | No | **S** | B3 y B4 | |
| 8 | **B1b** impresión desde iPad (cola + estación Android) | No | **L** | B1 integrado | El iPad no imprime directo; el piloto usa Android o computador. |
| 9 | **B6** servidor local sin internet | **No: el piloto tiene internet**; sí antes del primer evento sin red (esos siguen en el software de la empresa o con la laptop de siempre) | **XL** (E0-E3, docs/17) | Preguntas abiertas de docs/17 | Lo más grande. |

**Qué falta para ESE evento** (además de lo de arriba):
1. **El corte hecho y verificado** (docs/15 D2.5), con la contingencia apagada en producción (ya fijado en `config.sh`).
2. **Producción configurada desde cero** (Neon vacío): super administrador, cliente (tenant), evento con sus categorías y campos de registro, coordinador y comercial, logo del cliente si aplica.
3. **Correo saliente probado en producción** (escarapela digital y formularios) y, si hay pagos, las llaves de Wompi de producción.
4. **Los 200 asistentes cargados** (carga masiva, con fotos si se usa reconocimiento facial) probados en producción antes del día.
5. **Ensayo general 1-2 días antes** con los equipos y la red reales del lugar: celulares/tabletas, lector de cédula, cámara, conexión de respaldo (datos móviles).
6. **Criterio escrito de cuándo se pasa al software de respaldo** (p. ej. 5 min sin poder acreditar) y quién lo decide: con la contingencia apagada, sin internet no hay copia local en el quiosco.
7. **Quién mira el sistema durante el evento** (`/sistema`, alertas) y a quién se llama.
8. **Capacidad:** 200 personas es poca carga; no hace falta precalentar instancias (D2.4 paso 4b es para formularios masivos). El reconocimiento facial se prende por evento en Parámetros.
9. Aviso de privacidad y consentimiento facial vigentes (el texto ya existe; el consentimiento es previo al guardado del rostro).

## Pedidos de producto para el piloto: alcance y tamaño (propuesta, NO implementada)
Van en una rama `producto/piloto` cortada de `migra/fase1-2` DESPUÉS del cambio de la contingencia (commit con `CONTINGENCY_ENABLED`) y entran a `migra/fase1-2` por PR.

**7a · «✅ Acreditar» en TODAS las filas del directorio en vivo, con «Deshacer» ~8 s — tamaño M.**
- Hoy: el botón por fila se quitó el 2026-09-16 y solo aparece de forma puntual (`FOUND_PENDING`, tras buscar con el autoregistro apagado); acreditar sale del escaneo/búsqueda o de Editar (admin+).
- Alcance: botón en cada fila de `static/js/directory.js` (también en la lista local sin red); la fila ya acreditada muestra «Acreditado» deshabilitado. Reutiliza el endpoint de acreditar con su `client_id` idempotente (reintento seguro) y respeta la regla `registration`/`require_event_in_progress`. Roles: los que ya acreditan (digitador+; el cliente no ve el botón).
- «Deshacer»: toast de ~8 s con un botón (hoy `toast.js` no tiene acciones en los avisos: se agrega) que devuelve a «No registrado» usando el cambio de estado que ya existe. **Decisión de J:** el digitador hoy puede editar datos pero no cambiar el estado; el deshacer se limitaría a quien acreditó hace menos de ~15 s (verificación en el servidor, no solo en pantalla) para no abrirle ese permiso en general.
- Pruebas: API (acreditar desde fila, idempotente, deshacer solo del propio y dentro de la ventana, evento fuera de «registro») y JS (`tests/js`).

**7b · Logo por defecto cambiable desde Configuración — tamaño M.**
- Hoy: el logo por defecto es `static/img/logo-golden.png` (fijo en el repo; ya reducido a 400 px / 24 KB) en 8 plantillas y en `default_logo_url()`; el logo propio del evento ya manda sobre él (`event_logo_url`, modo `custom`).
- Alcance: una fila de configuración global (migración nueva) con la clave del objeto y su hash; en Configuración, sección «Logo por defecto» (admin+): subir, **previsualizar antes de guardar**, **restaurar** el de Golden. Acepta PNG/JPEG/WebP ≤ 2 MB (validado con Pillow, no solo por extensión), se **redimensiona a ~512 px** y se guarda en Cloud Storage con `get_storage()` (nunca en el disco local). Ruta pública `GET /branding/logo?v=<hash>` (sin sesión, `Cache-Control: public, max-age=31536000, immutable`; el hash cambia con cada logo, así que no hay caché vieja); las 8 plantillas y `default_logo_url()` pasan a usarla; sin logo guardado cae al de `static/`.
- Detalles a cerrar: la ruta `/branding/**` va al servicio `web` (reglas de Firebase Hosting y `appmode`); el service worker del quiosco hoy solo guarda `/static/*`, así que si algún día se enciende la contingencia hay que sumar esta ruta; el logo del evento sigue mandando.
- Pruebas: subida válida e inválida (tipo, tamaño, imagen corrupta), redimensionado, restaurar, ruta pública con el hash y precedencia del logo del evento.

Fuera del piloto (después): paridad de búsqueda sin red y el error de recarga sin red.

## B8 · Bandeja de salida: registro y edición completos SIN red (REQUISITO del piloto)
*Decidido por J (2026-10-05):* la conexión falla mucho en los eventos normales; el modo sin conexión pasa de opcional a requisito y irá **encendido en producción** (el valor de `CONTINGENCY_ENABLED` en producción lo cambia J después de probarlo en dispositivos reales; `CONTINGENCY_ENABLED` queda como interruptor de emergencia). Quiere registro y edición completos sin red.
**Hoy (Fase 3):** sin red solo se acredita por huella (`queue` en IndexedDB, `client_id` idempotente), se cambia el estado y «Registrar nuevo» está desactivado; la copia local lleva solo huella, nombre, categorías y estado.

**Diseño (propuesta):** una **bandeja de salida** (`outbox`) en IndexedDB; el servidor sigue siendo la única autoridad.
1. **Definición de campos del evento en el dispositivo**, junto con la lista (`fields`: `field_configs_json`, rótulos, categorías, qué es obligatorio, versión del esquema y **texto y versión del consentimiento**). Con ella el formulario de alta/edición funciona igual sin red (validaciones de cédula, obligatorios, tipos).
2. **Operaciones pendientes** (`op_id` = `client_id` idempotente, `device_id`, hora, `base_version`, estado local `pendiente | enviando | ok | duplicado | revisión | error`): `accredit` (ya existe), `create_person` (campos + foto + consentimiento) y `edit_person` (solo los campos que el operador escribe; la copia local NO lleva el resto, por privacidad). Cada operación se guarda en **una transacción** de IndexedDB antes de mostrar «guardado».
3. **Sincronización** a un endpoint nuevo por lotes (`POST /api/events/{id}/outbox/sync`, hasta 500 operaciones, como `access-logs/sync`): idempotente por `op_id` (`replayed`), un **resultado por ítem** (`ok`, `duplicado`, `revisión`, `error` con motivo) que la pantalla «Bandeja» muestra con reintento y descarte (con confirmación).
4. **Conflictos:** `create_person` con una **cédula ya existente NO se pisa**: queda en `revisión` (se compara lado a lado y alguien decide fusionar o descartar). `edit_person` lleva `base_version` (marca de la persona cuando se bajó la copia, `u` en el roster): si el servidor cambió esa persona desde entonces → `revisión`, no se pisa; si no, se aplica por campo. La cédula de una persona existente no se edita sin red (igual que hoy).
5. **Foto y consentimiento sin red:** la foto (JPEG ≤ 1024 px) y el consentimiento (aceptación + hora + versión del texto + dispositivo) se guardan en la operación. **La biometría se calcula en el servidor al sincronizar** (cola de trabajos, como una carga masiva); sin consentimiento no se guarda el rostro (igual que hoy). **El reconocimiento facial sin red sigue sin existir** (eso es B6).
6. **Dos dispositivos sin red a la vez** no se ven entre sí: pueden registrar a la misma persona. Por diseño eso termina en `duplicado/revisión`, nunca en una pisada silenciosa.

**Datos personales en claro en el dispositivo — protección razonable:** (a) **cifrado en reposo con WebCrypto** (AES-GCM) de cada operación y foto, con una clave **no extraíble** guardada en IndexedDB: protege contra copiar el archivo del perfil o un respaldo del equipo, **no** contra quien controle el navegador ya abierto; (b) **PIN del operador** opcional por evento para derivar la clave (PBKDF2) y pedirlo al abrir/cada 30 min: protege un dispositivo robado, con fricción; (c) **TTL**: lo pendiente se conserva hasta sincronizar y como máximo N días (hoy 30 para los ingresos; **decisión de J si baja a 7 para datos en claro**); (d) **borrado tras sincronizar**: al pasar a `ok` se borran campos, foto y consentimiento y solo queda `op_id` + resultado unos días; (e) «Cerrar sesión» **no** borra lo pendiente (se avisa, como hoy) pero queda cifrado y expira; (f) indicador permanente «N pendientes sin enviar» y exportación de emergencia (archivo cifrado). **Límites reales en iOS:** Safari borra los datos del sitio tras ~7 días sin uso salvo que la página esté **instalada como PWA** (pantalla de inicio) y `navigator.storage.persist()` solo es fiable en PWA; no hay llavero accesible desde la web (la clave vive en el mismo origen que los datos); WebCrypto exige HTTPS. En Android/Chrome es parecido pero más permisivo. **Conclusión:** el cifrado reduce la exposición, no la elimina; lo que protege de verdad es sincronizar pronto y el TTL corto.
**Qué cambia en el apartado 5-bis de la política de privacidad** (versión 1.0 con constancia; **no se toca el diseño actual hasta que J decida**): hoy dice que no se guardan fotos, teléfonos ni correos y que el documento va como huella. Con B8 se guardarían **en claro (cifrado en reposo)** nombre, documento, contacto, foto y consentimiento de personas **nuevas** y las correcciones de campos, hasta sincronizar. Eso exige un texto nuevo (qué se guarda, cuánto, cuándo se borra, riesgo residual) **marcado pendiente de revisión legal** y subir la versión de la política (el sistema ya vuelve solo a borrador si el texto cambia: `app/legal.py`).

**Cómo se prueba:** (1) unitarias en Node con IndexedDB y red falsos: encolado atómico, idempotencia, validación local desde la definición de campos; (2) **caída de red a media operación**: cortar entre el envío y la respuesta (reenvío ⇒ `replayed`, nunca duplicado), cortar durante la foto, cerrar la pestaña con operaciones `enviando` (se reanudan); (3) **dos dispositivos registrando a la misma persona** y editando el mismo campo (resultado `duplicado/revisión`, ninguno pisa); (4) API: idempotencia, permisos por rol, evento finalizado, límites, esquema cambiado durante la desconexión (campo nuevo obligatorio ⇒ `error` editable); (5) carga del sync (500 ops con foto); (6) **dispositivos reales**: Chrome Offline, modo avión, iPad Safari como PWA, red lenta/muerta (guion en `docs/runbook_evento.md` (sección «Piloto», P3)).

**Diferencias con B6 (servidor local):** B8 acumula operaciones en **cada navegador** y las sube cuando hay internet; no hay servidor en el sitio, no comparte estado entre dispositivos sin red, no hace facial sin red. B6 es una laptop servidora local (un solo escritor por evento, comparte la lista y los registros entre los equipos del sitio, puede hacer facial local y sincroniza después). **B8 cubre cortes de internet; B6 cubre eventos sin internet o con facial sin red.** Pueden convivir (B8 es la red de seguridad del dispositivo incluso con B6).

**Tamaño y rebanadas entregables** (total **L-XL, ~3-4 semanas** con pruebas en dispositivos):
- **R1 (S-M, 3-4 días) — ya sirve en un evento:** «Registrar nuevo» sin red **sin foto**: definición de campos local + bandeja cifrada (clave no extraíble) + `outbox/sync` para `create_person` + resultado por ítem + cédula existente ⇒ revisión. Permite registrar en la puerta a quien no estaba en la lista.
- **R2 (M):** foto + consentimiento sin red; biometría calculada al sincronizar.
- **R3 (M):** edición de campos del operador sin red + `base_version` + conflictos + pantalla Bandeja completa.
- **R4 (S-M):** protección: PIN opcional, TTL, borrado tras sincronizar, aviso permanente, exportación de emergencia, pruebas iOS PWA y texto 5-bis (pendiente legal).
- **R5 (S):** dos dispositivos: revisión lado a lado, métricas y runbook.
**Dependencias:** la recarga local-first (`fix/offline-recarga`, D2.5h); un endpoint que sirva la definición de campos versionada; el texto versionado del consentimiento; la decisión de J sobre datos en claro y TTL. **Riesgos:** expulsión de datos en iOS, duplicados entre dispositivos, reloj del dispositivo desfasado (la hora la fija el servidor al sincronizar y se guarda la local como dato), esquema que cambia durante la desconexión, tamaño de las fotos, complejidad de la pantalla de revisión y el riesgo legal de guardar datos en claro.

## N6 · URL limpia para las inscripciones públicas
Diseño y tamaño en `docs/15` **D2.5k**: host propio `inscripciones.golden-eventos.com/<evento>`, `public_slug` único global con reservadas, redirección 301 al renombrar, `/f/{id}/{slug}` se conserva, segundo sitio de Firebase y sin proxy de Cloudflare. **M (4-5 días)** + pasos de nube de J. Va después del piloto.

## Aprobados por J (2026-10-05), AL FINAL de la cola
**7a** «✅ Acreditar» en todas las filas con «Deshacer»: la regla propuesta (solo quien acreditó, hace menos de ~15 s verificado en el servidor; interfaz ~8 s) queda **aprobada**. **7b** logo por defecto editable desde Configuración: **aprobado**. Orden de trabajo: A y B (nube) → 1 (recarga) → 2 a 5 → 7a y 7b al final.
