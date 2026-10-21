# Generador de carga (Fase 4): Locust + el locustfile del repo. Se corre como Cloud Run Job en staging (ver deploy/loadtest/run_phase4.sh y docs/15).
# Imagen APARTE de la de la aplicación (no lleva dlib ni la app); Python 3.13 porque gevent/locust publican ruedas para él.
# scikit-image solo para la foto de dominio público (astronauta) del escenario facial: NUNCA se suben fotos reales de personas a la nube.
FROM python:3.13-slim
RUN pip install --no-cache-dir "locust>=2.32" pillow scikit-image numpy
RUN useradd --system --uid 10001 --home-dir /app loadgen
WORKDIR /app
COPY --chown=loadgen:loadgen tests/load/locustfile.py ./load/locustfile.py
COPY --chown=loadgen:loadgen scripts/load_cfg.py ./scripts/load_cfg.py
COPY --chown=loadgen:loadgen deploy/loadtest/run_task.py ./run_task.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER loadgen
CMD ["python", "run_task.py"]
