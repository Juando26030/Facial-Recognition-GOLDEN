# Observabilidad: salud, estado y logs

Todo lo que permite saber **si la app está bien, qué está pasando y qué hacer**, sin abrir la base a mano. Escrito para quien opera un evento
(no hace falta ser programador). Código: `app/ops.py`, `app/obs.py`, `app/routers/ops.py`, `templates/sistema.html`.

## 1. Los cuatro puntos de entrada

| Dirección | Quién | Para qué |
|---|---|---|
| `GET /healthz` | el orquestador (systemd, Cloud Run) | **¿El proceso está vivo?** No toca la base ni el disco: responde en milisegundos. Si falla, se reinicia el proceso. |
| `GET /readyz` | el orquestador y el despliegue | **¿Puede atender peticiones ahora?** Comprueba la base (con tiempo límite de 2 s), el almacenamiento y —solo donde corre la biometría— que el modelo facial esté cargado. Responde `503` diciendo **qué componente falla y por qué**. Si falla, se le deja de mandar tráfico (sin reiniciar). |
| `GET /api/ops/status` y la pantalla **`/sistema`** («Estado del sistema», menú lateral, solo administradores) | personas | El semáforo completo, en español, con motivo y qué hacer. Se refresca solo cada 15 s. |
| `GET /api/ops/deploy-allowed` | el despliegue y los administradores | **¿Se puede desplegar ahora?** `allowed: false` si hay un evento en curso o una apertura (evento o formulario) en las próximas N horas (`DEPLOY_FREEZE_HOURS`, 3 por defecto). Se puede llamar con sesión de administrador o con la cabecera `X-Ops-Token` (variable `OPS_TOKEN`). |

Ejemplos de `/readyz`:

```json
{"status": "ready", "checks": {"database": {"ok": true, "latency_ms": 3.1}, "storage": {"ok": true}, "biometrics_model": {"ok": true}}}
{"status": "unavailable", "checks": {...}, "failing": {"database": "TimeoutError: la base no respondió en 2 s"}}
```

## 2. Qué mide cada chequeo de «Estado del sistema» y qué significa cada color

Verde = todo bien. Amarillo = **atención**: nada está roto, pero conviene mirarlo (y, con un evento en marcha, no tocar nada). Rojo = **problema**: hay que actuar ya.
El color general de la pantalla es el del peor chequeo.

| Chequeo | Qué mide | Verde | Amarillo | Rojo | Qué hacer si no está en verde |
|---|---|---|---|---|---|
| **Versión desplegada** | Commit y fecha de lo que está corriendo (`.build_info` que escribe el despliegue, o `APP_COMMIT`/`APP_BUILD_DATE`). | Conocida | Desconocida | — | Revisar el paso «Registrar versión» del despliegue. |
| **Base de datos** | Milisegundos de un `SELECT 1`. | < 100 ms | 100–500 ms | > 500 ms o sin respuesta | Ver Postgres/Neon: ¿está arriba?, ¿`DATABASE_URL` correcta?, ¿el cómputo se está «despertando»? Mirar los logs de errores. |
| **Conexiones a la base** | Conexiones abiertas contra el máximo de la base, y las que usa este proceso contra su pool. | < 60 % | 60–85 % | > 85 % | Quedan pocas libres. En plena carga **no reiniciar**; después bajar `WEB_CONCURRENCY`/`DB_POOL_SIZE` o usar el pooler de Neon. |
| **Cola de trabajos** | Trabajos pendientes, en curso, fallidos y la edad del más antiguo. | Sin fallidos ni esperas | Algún fallido, o alguno espera > 1 min | ≥ 10 fallidos, o alguno espera > 10 min | Comprobar que el worker corre (`JOBS_WORKER`), mirar `last_error` del trabajo en la tabla `jobs`; se reintenta solo con espera creciente. |
| **Último respaldo** | Antigüedad del volcado más nuevo en `BACKUP_DIR`. | ≤ 26 h | 26–52 h, o no configurado | > 52 h, o ninguno | Ver el cron del respaldo (`backup.log`) y correr `scripts/backup_db.sh` a mano. |
| **Cargas masivas** | Cargas de base de asistentes en curso. | Ninguna | En curso (no reiniciar) | Una lleva > 10 min sin avanzar | Avisar a quien la lanzó; si el servidor se reinició debe volver a subirla. |
| **Eventos y formularios** | Eventos «En proceso» y formularios que abren en las próximas 24 h. | Nada en curso | Hay actividad | — | **No desplegar ni reiniciar** mientras haya actividad. Es un aviso, no una falla. |
| **Correos y cargas de inscripciones** | Trabajos `email`/`form_feed` pendientes y fallidos. | 0 fallidos | Algún fallido, o > 200 pendientes | ≥ 5 fallidos | Revisar credenciales de correo (Graph/SMTP) y reintentar. |
| **Pagos (Wompi)** | Último webhook recibido y pagos «pendientes» de hace más de 15 min. | 0 sin conciliar | 1–4 | ≥ 5 | Correr `scripts/reconcile_payments.py` (consulta a Wompi por referencia) y verificar la URL del webhook en el panel de Wompi. |
| **Errores (15 min)** | Errores 5xx del servidor en los últimos 15 minutos. | 0 | 1–9 | ≥ 10 | Buscar en los logs `severity=ERROR`; el código de cada error (`request_id`) aparece en la pantalla del usuario y en el log. |

## 3. Logs estructurados

Cada línea de log es **un JSON en la salida estándar**, con los campos que Cloud Logging reconoce:

```json
{"severity": "INFO", "message": "POST /f/1/feria/submit -> 200", "time": "2026-09-26T22:23:26.517+00:00", "logger": "golden.http",
 "request_id": "87d3aa606efe48d4", "httpRequest": {"requestMethod": "POST", "requestUrl": "/f/1/feria/submit", "status": 200, "latency": "0.011s", "remoteIp": "203.0.113.*"},
 "logging.googleapis.com/trace": "projects/<proyecto>/traces/<id>"}
```

* **`X-Request-ID`**: se respeta el que llegue (si es un identificador razonable) o se genera; vuelve siempre en la respuesta y sale en cada log de esa petición.
  Es el «código» que el usuario ve si algo falla: con ese código se encuentra la traza completa.
* **`logging.googleapis.com/trace`** aparece si llega `X-Cloud-Trace-Context` y está definida `GOOGLE_CLOUD_PROJECT`.
* Una línea por petición (`golden.http`); `/healthz` no se registra. Los errores 5xx salen con `severity=ERROR`.
* Gunicorn/uvicorn escriben en el mismo formato (configurado en `deploy/gunicorn.conf.py`).

### Errores para el usuario
Un error no controlado devuelve `500` con un mensaje amable («Ocurrió un error inesperado… avisa a soporte con este código: `<id>`»), nunca la traza. La traza completa va solo al log.
Si la base no responde (reinicio, cómputo despertando, pool agotado) la respuesta es `503` con `Retry-After: 3`: los kioscos y los formularios reintentan solos.

## 4. Datos personales: PROHIBIDO en los logs

Dos capas, para que un descuido no se convierta en filtración:

1. **El código no registra cuerpos, cabeceras ni cookies.** La ruta se guarda enmascarada (`/b/[token]`, `/api/users/***/cedula`, `?t=[x]`), y la IP sin el último octeto.
2. **El formateador enmascara todo mensaje y toda traza**, venga de donde venga (librerías, excepciones): correos (`a***@***`), teléfonos y cédulas (`***34`), vectores de encodings (`[encoding]`) y tokens largos (`[token]`).

Lo que **no** se puede enmascarar automáticamente son los **nombres de personas**: por eso la regla de código es *nunca poner nombres en mensajes de log* (usar el id de la
inscripción/persona interno, no el nombre). Las pruebas (`tests/test_observability.py`) verifican el enmascarado.

## 5. Variables de entorno

`OPS_TOKEN`, `DEPLOY_FREEZE_HOURS`, `BACKUP_DIR`, `BACKUP_MAX_AGE_HOURS`, `READYZ_TIMEOUT_SECONDS`, `LOG_LEVEL`, `APP_COMMIT`, `APP_BUILD_DATE`, `GOOGLE_CLOUD_PROJECT`. Todas opcionales (ver `.env.example`).

## 6. Qué mirar en la noche de un evento

1. Abrir **Estado del sistema** (`/sistema`) en una pestaña fija: si el banner sale rojo, leer el motivo y «qué hacer».
2. Antes de abrir un formulario a mucha gente: `runbook_evento.md` (lista de chequeo).
3. Si un usuario reporta un error: pedirle el **código** que aparece en pantalla y buscarlo en los logs (`request_id`).
