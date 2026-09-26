"""Conexión a la base de datos. Todo por variables de entorno (ver .env.example):

  DATABASE_URL        obligatoria. En Cloud Run apuntará al POOLER de Neon (PgBouncer en modo transacción): por eso nada de esta app usa
                      `SET` de sesión, tablas temporales, LISTEN/NOTIFY ni advisory locks de sesión (los `SELECT ... FOR UPDATE` sí valen: viven
                      dentro de una transacción).
  DIRECT_DATABASE_URL solo para las migraciones de Alembic (conexión directa, sin pooler); si falta se usa DATABASE_URL (ver alembic/env.py).
  DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_POOL_RECYCLE / DB_CONNECT_TIMEOUT / DB_CONNECT_RETRIES  tamaño del pool por proceso.
      Regla: PROCESOS x (DB_POOL_SIZE + DB_MAX_OVERFLOW) debe quedar por debajo del máximo de conexiones de la base."""
import logging
import os
import time

import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

load_dotenv()
log = logging.getLogger("golden.db")

# Forzamos PostgreSQL. La cadena de conexión debe venir del .env (ver .env.example).
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL no está definida. Copia .env.example a .env y configura la cadena de conexión."
    )

CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
CONNECT_RETRIES = max(1, int(os.getenv("DB_CONNECT_RETRIES", "3")))


def _dsn() -> str:
    """La URL de SQLAlchemy convertida a la que entiende libpq (sin el «+psycopg2» del esquema)."""
    return make_url(SQLALCHEMY_DATABASE_URL).set(drivername="postgresql").render_as_string(hide_password=False)


def _connect():
    """Conecta con reintentos y espera creciente: una base que se está despertando (Neon) o un reinicio de red no deben tumbar la petición."""
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            return psycopg2.connect(_dsn(), connect_timeout=CONNECT_TIMEOUT)
        except psycopg2.OperationalError as exc:
            if attempt == CONNECT_RETRIES:
                raise
            log.warning("no se pudo conectar a la base (intento %s/%s): %s", attempt, CONNECT_RETRIES, str(exc).splitlines()[0][:120])
            time.sleep(0.5 * attempt)


engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    creator=_connect,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "10")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,            # una conexión que el servidor/pooler ya cerró se reemplaza sola al sacarla del pool
    pool_use_lifo=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from app import faces_version  # noqa: E402,F401 — engancha la versión de rostros al flush de toda sesión


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
