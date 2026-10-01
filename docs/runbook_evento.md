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
## E. Lo que todavía NO existe (para no prometerlo)

* **Modo contingencia del kiosco** (seguir admitiendo por cédula/QR sin conexión): construido en la rama `migra/fase1-2` (Fase 3) y todavía SIN desplegar a producción ni validado en un quiosco real; la política de privacidad de la copia local está pendiente de revisión legal. Hasta pasar el «Simulacro 3» (docs/15), no prometerlo: la VM actual no lo tiene, y sin conexión no se registra.
* **Tres servicios separados y escalado automático** (Cloud Run + Neon): Fases 1–2. Hoy todo corre en una VM con varios procesos.
* **Prueba de carga contra staging con simulacros de falla**: Fase 4. Hasta que pase, la respuesta honesta a «¿aguanta una noche de 6 eventos?» es *todavía no está demostrado*.
