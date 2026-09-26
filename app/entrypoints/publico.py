"""Punto de entrada del servicio «publico» (ver app/appmode.py): `gunicorn -k uvicorn.workers.UvicornWorker app.entrypoints.publico:app`."""
import os

os.environ["APP_MODE"] = "publico"

from app.main import app  # noqa: E402,F401
