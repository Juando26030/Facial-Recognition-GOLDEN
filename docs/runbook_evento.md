# Runbook de evento: qué revisar antes (y durante) una noche grande

Lista de chequeo para eventos con muchos escaneos o inscripciones (varios eventos a la vez, formularios que abren con miles de personas). Pensada para
quien opera, no para quien programa. Los enlaces a pantallas suponen rol administrador. Ver también `observabilidad.md` (qué significa cada color) y
`docs/14_FASE0_RESULTADOS.md` (los números y límites conocidos).

## A. Dos o tres días antes

1. **Estado del sistema en verde** (`/sistema`). Si algo está amarillo o rojo, resolverlo *ahora*, no el día del evento (cada chequeo dice «qué hacer»).
2. **Versión desplegada = la probada.** En «Versión desplegada» debe verse el commit que se probó. **Congelar los despliegues**: desde 3 horas antes del primer evento no se despliega
   (el propio despliegue lo impide con `/api/ops/deploy-allowed`; solo `force` lo salta y solo debe usarse en una emergencia real).
3. **Respaldo reciente**: «Último respaldo» en verde (< 26 h) y, una vez por evento grande, **restaurar el último volcado a una base de prueba** (`scripts/restore_db.sh <archivo> <base_nueva>`) para saber que sirve.
4. **Migraciones al día**: `alembic current` en la VM debe coincidir con la última (`0048_jobs_ops` a la fecha de este documento).
5. **Correo** (Graph/SMTP) y **pagos (Wompi)**: si hay formularios con pago, las llaves son las del ambiente correcto (`pub_prod_…` en producción), la URL de eventos está registrada en el panel de Wompi
   (`<PUBLIC_BASE_URL>/webhooks/wompi`, una por ambiente) y el cron de conciliación corre (`scripts/reconcile_payments.py`, cada 5 min).
6. **Cifrado del rostro**: si el evento usa biometría, «Parámetros → Privacidad» debe decir *cifrado activo* y la llave estar guardada fuera de la VM.

## B. El día anterior

1. **Formularios**: abrir cada uno con su enlace de pruebas (`?k=…`), enviarlo completo (con pago de prueba si lo tiene), y confirmar que la inscripción aparece en «Respuestas» marcada como prueba.
   Revisar **cupo total** y **cupos por variables**; recordar que se pueden subir en caliente sin perder inscripciones.
2. **Base de asistentes cargada** y, si hay biometría, **fotos cargadas**: en Registro debe verse el total esperado. Hacer **un escaneo facial de prueba** con alguien de la base: el primero de cada
   evento arma la matriz de rostros en memoria (~1 s con 8.000); los siguientes son inmediatos.
3. **Compartir el wifi del lugar**: si cientos de asistentes van a inscribirse **desde el mismo wifi** (una sola IP pública), el límite por IP del formulario (60 envíos cada 10 min por IP) los frenaría.
   Definir `PUBLIC_LIMIT_FACTOR=30` (o más) en el `.env` y reiniciar **antes** de que empiece el evento (nunca durante). Volver a 1 después.
4. **Kioscos**: dispositivos de repuesto cargados, con sesión iniciada y un evento de prueba abierto; conexión de respaldo (datos móviles). Impresoras probadas.
5. **Capacidad**: la VM aguanta lo medido en `14_FASE0_RESULTADOS.md`. Si el evento supera 5.000 inscripciones simultáneas o ~57 escaneos/s sostenidos, **no prometerlo todavía**: es de las Fases 1–4.

## C. Durante el evento

1. Tener **Estado del sistema** abierto en una pestaña. Amarillo por «Eventos y formularios» es normal (es el aviso de «no desplegar»).
2. **No desplegar, no reiniciar, no cambiar variables de entorno.** Si hay que reiniciar por una emergencia, avisar antes a los kioscos: el reinicio tarda ~10 s y los formularios reintentan solos.
3. **Si el color se pone rojo**: leer el motivo. Guía rápida:
   * *Base de datos / Conexiones*: no reiniciar la app (empeora); revisar Postgres/Neon.
   * *Cola de trabajos*: las inscripciones ya están guardadas; lo que se atrasa es cargar a la base del evento y enviar la escarapela por correo. Se ponen al día solos al normalizarse.
   * *Pagos sin conciliar*: correr `scripts/reconcile_payments.py`; si Wompi está caído, su estado se ve en el formulario y en la pestaña Pagos.
   * *Errores*: pedirle al usuario el código que ve en pantalla y buscarlo en los logs.
4. **Reportes Excel**: durante el evento se genera de a uno por proceso; si sale «hay otro reporte generándose», esperar un minuto. Dejar los reportes grandes para *después* del evento.
5. **Cargas masivas de fotos**: no lanzarlas durante un evento (consumen CPU); si hay que hacerlo, en un evento que no esté en curso.

## D. Al terminar

1. Pasar el evento a **Finalizado** (los formularios pueden cerrarse o finalizarse aparte).
2. Bajar `PUBLIC_LIMIT_FACTOR` a 1 si se subió.
3. Verificar «Pagos sin conciliar = 0» y correr la conciliación una última vez.
4. Recordar la retención del dato biométrico (6 meses por defecto tras finalizar) y, si aplica, borrarlo antes desde Parámetros → Privacidad.


## Modo contingencia: preparar el quiosco (Fase 3; todavía sin desplegar a producción)

1. **Al llegar al evento, abrir el registro CON conexión** (antes de abrir puertas) y esperar unos segundos: así se descarga la copia de la lista y se guarda la página. Sin esa primera visita con red, sin conexión no hay nada que usar.
2. **iPad/iPhone: «Añadir a pantalla de inicio»** y abrir el quiosco desde ese icono.
3. **Safari borra los datos de los sitios sin uso en 7 días:** si el dispositivo estuvo guardado más de una semana, la lista se vuelve a descargar al abrirlo con red; los ingresos pendientes de sincronizar (si había) se envían al volver la red.
4. **No usar el modo privado/incógnito.**
5. Si aparece la franja roja «MODO CONTINGENCIA»: seguir escaneando (cédula/QR); quien no esté en la copia → «No registrado: verificar manualmente»; al volver la red la franja se quita sola y la cola se envía. Si dice «Sesión vencida», iniciar sesión de nuevo (enlace de la franja, en otra pestaña). «Revisar (N)» lista a quien también ingresó por otro quiosco durante el corte.
6. Al terminar la jornada, **cerrar sesión con red** (avisa si quedan ingresos sin enviar).
7. **Reglas del modo contingencia:** (a) **no cambiar el «Modo autoregistro» mientras haya un quiosco sin red** (la copia local guarda el valor anterior hasta refrescarse con red); (b) sin red la **lista local no muestra cédula ni entidad** (nombre, categorías y estado; buscar por nombre o por cédula exacta); (c) con el modo autoregistro **apagado**, escanear **solo busca y resalta**: se acredita con «✅ Acreditar» en la fila o «Editar → Registrado»; con el modo encendido, escanear acredita al instante.
## Piloto de ~200 asistentes: criterio de respaldo, `/sistema`, calentamiento y respaldo (2026-10-05, borrador)
Complementa `docs/observabilidad.md` (qué significa cada color de `/sistema`) y `docs/19_GUIA_PRODUCCION.md`.

### P1. Cuándo se pasa al software de respaldo (criterio concreto)
Decide **Juan David** (o, si no está, el ingeniero de TI). Se pasa al software de la empresa cuando se cumpla **cualquiera**:
1. **En la puerta no se puede acreditar ni en línea ni con la lista local** durante **2 minutos seguidos** en **2 o más dispositivos** (los dos modos fallan; con un solo dispositivo fallando se cambia de dispositivo, no de sistema).
2. Hay **más de 15 personas esperando** y la fila no baja en 3 minutos por una falla del sistema (no por falta de operadores).
3. `/sistema` está en **rojo** en *Base de datos* o *Cola de trabajos* por más de **3 minutos** y los dispositivos no están en modo «LISTA LOCAL».
4. Un dispositivo sin red **no tiene** «LISTA LOCAL: N de N» (no se calentó) y es el único en la puerta.
Al decidirlo: avisar al coordinador, **anotar la hora y el motivo**, y seguir registrando en el software de respaldo. Lo ya acreditado en el sistema nuevo queda; lo acreditado sin red se sincroniza solo al volver la conexión (no se reingresa). Volver al sistema nuevo solo con `/sistema` en verde y un escaneo de prueba bueno.
*Esto NO es un criterio de rendimiento: la contingencia sin red está para que un corte de internet no pare la puerta.*

### P2. Qué mirar en `/sistema` durante el evento (cada ~15 min y ante cualquier queja)
| Chequeo | Verde | Mirar (amarillo) | Actuar (rojo) |
|---|---|---|---|
| Base de datos | < 100 ms | 100-500 ms | > 500 ms o sin respuesta |
| Conexiones a la base | < 60 % | 60-85 % | > 85 % (**no reiniciar** en plena carga) |
| Cola de trabajos | sin fallidos ni esperas | algún fallido o espera > 1 min | ≥ 10 fallidos o espera > 10 min |
| Último respaldo | ≤ 2 h (horario) | 2-26 h | > 26 h o ninguno |
| Cargas masivas | ninguna | en curso (no reiniciar) | una > 10 min sin avanzar |
| Versión desplegada | conocida | desconocida | — |
Además: **UptimeRobot** en *Up* y ningún correo de «Golden alertas». **Durante el evento no se despliega ni se reinicia nada** (el despliegue de producción respeta el congelamiento; `FORCE` solo en emergencia y con la decisión de Juan David).

### P3. Calentamiento previo (antes de abrir) y prueba sin red
Para **cada dispositivo** de registro (celulares, tabletas, laptops):
1. **Con internet, al menos 30 minutos antes** de abrir: iniciar sesión y abrir el registro del evento (`/kiosk/<id>/registro`). **Los iPad se usan SIEMPRE como PWA instalada** (Safari → Compartir → **Añadir a pantalla de inicio**) y se abren solo desde ese ícono, nunca desde una pestaña de Safari: Safari borra los datos de un sitio tras ~7 días sin uso (la lista local y la bandeja de salida) salvo que esté instalado, y solo ahí el almacenamiento persistente es fiable. En Android/Chrome se puede usar normal o instalada.
2. Esperar a que la lista local baje y **verificar «LISTA LOCAL: N de N»**, con N = el total del evento en el servidor (hoy esa comparación no existe en pantalla: se compara a mano el contador «registrados de N» con el total de `/sistema` o del directorio; mejora propuesta en `docs/15` D2.5i).
3. **Prueba de escaneo sin red:** modo avión (o Chrome ▸ Offline), recargar el registro: debe verse la franja de **contingencia en ≤ 5 s** y la **lista local en ≤ 3 s**; escanear **una cédula de prueba** (acredita y queda en cola); quitar el modo avión: debe sincronizar y la persona aparecer registrada en el servidor.
4. Con **red muerta pero conectada** (wifi sin salida a internet; p. ej. desconectar el módem y dejar el router): repetir el paso 3.
5. Comprobar la hora del dispositivo y la batería; un cargador por equipo.
La lista local vive **24 h** desde su última actualización: en eventos de varios días, refrescarla con internet cada mañana.

### P4. Antes de abrir cada evento: respaldo y verificación (Cloud Shell)
```bash
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,backup" --wait          # respaldo ahora mismo
gcloud run jobs execute golden-ops --region us-east4 --args="-m,app.ops_runner,check-backups" --wait   # debe terminar «successfully completed»
bash deploy/gcp/scheduler.sh production check                                                          # Scheduler activo y respaldo reciente
```
Si `check-backups` falla: **no abrir** hasta entender por qué (`docs/15` D2.5f). Al terminar el evento: dejar el respaldo diario correr o ejecutar `backup-daily`.

### P5. Contactos y registro
Anotar al inicio: quién vigila `/sistema`, quién decide el cambio al software de respaldo, teléfonos de los dos ingenieros y del coordinador. Durante el evento anotar toda incidencia con hora (qué se vio, qué se hizo): alimenta el postmortem y la lista de mejoras.

## Reconocimiento facial voluntario: operación del piloto (L6, 2026-10-06; decisiones de la auditora)

**Antes del evento (coordinador):** en Parámetros del evento, sección «Autorización del reconocimiento facial»: confirmar «Evento propio de Golden», dejar «Una sola vez por persona y evento» y, si se quiere que la gente acepte desde el celular, activar la página de aceptación; imprimir el póster con el QR. Cargar el listado (la columna «fecha de nacimiento» es opcional: sin ella la foto del zip no se conserva). Nadie del equipo marca «autoriza» por la persona: **la aceptación la da la persona en la pantalla**.

**En la puerta, dos filas con letrero visible:**
- **Fila A, reconocimiento facial** (solo personas que ya aceptaron): el digitador escribe o escanea la cédula/QR, el sistema consulta; si ya aceptó, enciende la cámara. Si es la primera vez, la persona ve la pantalla completa y pulsa «ACEPTO…»; se capta su rostro y **hoy entra por cédula**: desde la próxima entrada, por rostro (el vector se calcula aparte, nunca se hace esperar a nadie).
- **Fila B, cédula o QR:** para quien no quiere rostro, es menor de 18 años, no aparece en la lista facial o no quiere esperar. **Nunca se bloquea la puerta** ni se presiona a nadie.
- Si la cámara dice «No te encontramos en la lista con reconocimiento facial», se acredita por cédula o QR. No se guarda nada de esa captura.
- Quien aceptó desde el celular: el digitador pide el documento o el QR y, al ver el cuadro «Confirma su identidad», lo confirma; antes de eso su rostro no se usa.

**Bloqueo de pantalla de los dispositivos (obligatorio):** código alfanumérico o biométrico del operador y bloqueo automático a los **2 minutos**. Sin PIN dentro de la aplicación en el piloto.

**Sin conexión:** hay cédula/QR con la copia local; el rostro necesita servidor. Las decisiones tomadas (aceptar o rechazar) se guardan en el dispositivo y se envían solas; lo no enviado en 7 días se avisa desde el día 3 y se elimina.

**Quien quiera revocar o que se borren sus datos:** admin o super_admin, Parámetros → Privacidad: «Revocar autorización» (borra rostro y deja constancia) o «Suprimir TODOS los datos». Atender la consulta en máximo 10 días hábiles y el reclamo en 15. Correo de privacidad: soporteit@goldenlogisticas.com (se revisa a diario).

**Al terminar:** marcar el evento «finalizado» **el mismo día**: desde ahí corren los 7 días de borrado de rostros. Si queda sin finalizar, el sistema avisa en `/sistema` pasados 3 días del fin.

## E. Lo que todavía NO existe (para no prometerlo)

* **Modo contingencia del kiosco** (seguir admitiendo por cédula/QR sin conexión): construido en la rama `migra/fase1-2` (Fase 3) y todavía SIN desplegar a producción ni validado en un quiosco real; la política de privacidad de la copia local está pendiente de revisión legal. Hasta pasar el «Simulacro 3» (docs/15), no prometerlo: la VM actual no lo tiene, y sin conexión no se registra.
* **Tres servicios separados y escalado automático** (Cloud Run + Neon): Fases 1–2. Hoy todo corre en una VM con varios procesos.
* **Prueba de carga contra staging con simulacros de falla**: Fase 4. Hasta que pase, la respuesta honesta a «¿aguanta una noche de 6 eventos?» es *todavía no está demostrado*.
