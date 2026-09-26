"""Punto de entrada del servicio «biometria» (ver app/appmode.py): `gunicorn -k uvicorn.workers.UvicornWorker app.entrypoints.biometria:app`."""
import os

os.environ["APP_MODE"] = "biometria"

from app.main import app  # noqa: E402,F401
