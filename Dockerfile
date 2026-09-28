# Una sola imagen para los tres servicios de Cloud Run (publico, web, biometria) y los Cloud Run Jobs (migraciones, etc.).
# Qué sirve cada contenedor lo decide APP_MODULE (ver deploy/docker-compose.yml y docs/15_MIGRACION.md):
#   app.entrypoints.publico:app | app.entrypoints.web:app | app.entrypoints.biometria:app | app.main:app (todo junto)
# Un Job cambia el comando:  docker run <imagen> alembic upgrade head
ARG PYTHON=3.14

# ---- 1) ruedas: dlib se compila AQUÍ una sola vez (lo más lento); la imagen final solo recibe ruedas ya compiladas ----
FROM python:${PYTHON}-slim-trixie AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- 2) imagen final: sin compiladores, usuario sin privilegios ----
FROM python:${PYTHON}-slim-trixie
# tesseract-ocr: lectura de la cédula nueva por foto (app/mrz_ocr.py).
# postgresql-client-18 (repositorio oficial de PostgreSQL; Debian trae la 17): pg_dump de los respaldos del Job de operaciones.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index /wheels/*.whl
RUN useradd --system --uid 10001 --home-dir /app golden
WORKDIR /app
COPY --chown=golden:golden alembic.ini ./
COPY --chown=golden:golden alembic ./alembic
COPY --chown=golden:golden app ./app
COPY --chown=golden:golden static ./static
COPY --chown=golden:golden templates ./templates
COPY --chown=golden:golden scripts ./scripts
COPY --chown=golden:golden deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py

ARG APP_COMMIT=""
ARG APP_BUILD_DATE=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_COMMIT=${APP_COMMIT} APP_BUILD_DATE=${APP_BUILD_DATE} \
    ENVIRONMENT=production BIND=0.0.0.0 PORT=8080 \
    APP_MODULE=app.main:app WEB_CONCURRENCY=2 \
    STORAGE_LOCAL_DIR=/tmp/golden-data
USER golden
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn -c deploy/gunicorn.conf.py \"$APP_MODULE\""]
