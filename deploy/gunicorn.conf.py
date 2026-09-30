"""Configuración de Gunicorn (procesos) para la VM y, después, para Cloud Run. Todo por variables de entorno:

  PORT              puerto (Cloud Run lo fija; en la VM 8000)        BIND        dirección (por defecto 127.0.0.1 en la VM; 0.0.0.0 en contenedor)
  WEB_CONCURRENCY   procesos (por defecto 3)                          GUNICORN_TIMEOUT     segundos máximos por petición antes de matar el proceso (60)
  GUNICORN_GRACEFUL_TIMEOUT   segundos que se dan a las peticiones en curso tras SIGTERM (10: lo que da Cloud Run)
  GUNICORN_MAX_REQUESTS       reinicia cada proceso tras N peticiones (1500 + jitter): dlib/numpy pueden ir engordando la memoria con los días; 0 = nunca (el servicio público de Cloud Run,
                              ver deploy/gcp/deploy.sh). Con carga pareja TODOS los procesos llegan al límite casi a la vez (corrida 9): no lo uses sin desfasarlos.
  GUNICORN_KEEPALIVE          segundos que uvicorn mantiene abierta una conexión ociosa (5 por defecto). Alargarlo si Cloud Run muestra «connection to the instance had an error» dispersos.

Uso:  gunicorn -c deploy/gunicorn.conf.py app.main:app            (todo)
      gunicorn -c deploy/gunicorn.conf.py app.entrypoints.publico:app   (un servicio de la Fase 2: ver app/appmode.py)

Regla de conexiones: WEB_CONCURRENCY x (DB_POOL_SIZE + DB_MAX_OVERFLOW) debe quedar por debajo del máximo de conexiones de la base (Postgres por defecto: 100)."""
import os

bind = os.getenv("BIND", "127.0.0.1") + ":" + os.getenv("PORT", "8000")
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "10"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1500"))
max_requests_jitter = 300
accesslog = None                      # el log de peticiones lo escribe la propia app (JSON, con datos personales enmascarados: app/obs.py)
errorlog = "-"
capture_output = True
# Los logs propios de Gunicorn también salen en JSON (formato que entiende Cloud Logging).
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "app.obs.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
    "loggers": {"gunicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False}},
}
