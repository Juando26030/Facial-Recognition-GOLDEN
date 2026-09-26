"""Punto de entrada del servicio «web» (ver app/appmode.py): `gunicorn -k uvicorn.workers.UvicornWorker app.entrypoints.web:app`."""
import os

os.environ["APP_MODE"] = "web"

from app.main import app  # noqa: E402,F401
