"""Fase 1A, PR1: medir el tiempo por registro. Solo ADITIVA.

  access_logs.took_ms   milisegundos que tardó el digitador en registrar a la persona (desde la primera tecla en el buscador hasta que el quiosco manda el registro). Vacía en lo anterior.
  access_logs.ui_flow   pantalla con la que se registró («v0» = la de hoy; las siguientes versiones de la 1A usan otra etiqueta), para comparar antes/después. Vacía en lo anterior.

Ninguna guarda datos personales. El código anterior las ignora; bajar la migración quita las dos columnas.

Bloqueo de `access_logs` (ACCESS EXCLUSIVE, aunque muy breve): igual que 0077, el `ALTER` va con `lock_timeout` corto (4 s) dentro de un SAVEPOINT y se reintenta unas veces (5, pausa de 3 s); si no se
consigue, la migración FALLA ENTERA (nada queda a medias) y se repite en otro momento. Las dos columnas van en UN solo `ALTER` (un solo bloqueo). `ADD COLUMN` nullable y sin DEFAULT no reescribe la
tabla en Postgres (instantáneo). `SET LOCAL` vale solo dentro de la transacción de la migración, que corre por la conexión directa del dueño: la app no usa `SET`.
Variables opcionales (solo para pruebas o casos especiales): MIGRATION_LOCK_TIMEOUT_S, MIGRATION_LOCK_ATTEMPTS, MIGRATION_LOCK_PAUSE_S.

Permisos: no hacen falta nuevos. Las columnas quedan cubiertas por los permisos de TABLA que `golden_app` ya tiene sobre `access_logs` (GRANT de tabla o `ALTER DEFAULT PRIVILEGES` de `scripts/neon_app_role.py`);
no se crea ninguna tabla ni secuencia. Sin índices nuevos: el reporte filtra por `event_id` (ya indexado) y agrega en memoria los pocos miles de registros de un evento.
Esta migración debe ser la ÚLTIMA de su corrida (alembic usa una sola transacción para todas las pendientes: el bloqueo de `access_logs` dura hasta que termina la corrida; ver 0077).

Revision ID: 0079_access_log_took_ms
Revises: 0078_jobs_sin_cedulas
Create Date: 2026-11-03
"""
import os
import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "0079_access_log_took_ms"
down_revision = "0078_jobs_sin_cedulas"
branch_labels = None
depends_on = None

LOCK_NOT_AVAILABLE = "55P03"


def _alter_access_logs(statement: str, what: str) -> None:
    """`ALTER TABLE access_logs …` con `lock_timeout` corto y reintentos (mismo patrón que 0077); si no se consigue el bloqueo, falla con un mensaje claro y la migración se deshace entera."""
    timeout_s = float(os.getenv("MIGRATION_LOCK_TIMEOUT_S", "4"))
    attempts = int(os.getenv("MIGRATION_LOCK_ATTEMPTS", "5"))
    pause_s = float(os.getenv("MIGRATION_LOCK_PAUSE_S", "3"))
    bind = op.get_bind()
    for attempt in range(1, attempts + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = {int(timeout_s * 1000)}"))
                bind.execute(sa.text(statement))
            bind.execute(sa.text("SET LOCAL lock_timeout = 0"))           # el resto de la corrida, sin tope
            return
        except OperationalError as e:
            if getattr(e.orig, "pgcode", None) != LOCK_NOT_AVAILABLE:
                raise
            if attempt < attempts:
                time.sleep(pause_s)
    raise RuntimeError(f"No se pudo {what}: `access_logs` estuvo ocupada (una transacción larga la tenía abierta) en los {attempts} intentos de {timeout_s:g} s. No se cambió nada: "
                       "vuelve a correr la migración cuando no haya transacciones largas sobre esa tabla (por ejemplo, revisa `pg_stat_activity`).")


def upgrade() -> None:
    _alter_access_logs("ALTER TABLE access_logs ADD COLUMN IF NOT EXISTS took_ms INTEGER, ADD COLUMN IF NOT EXISTS ui_flow VARCHAR(12)", "agregar las columnas access_logs.took_ms y access_logs.ui_flow")


def downgrade() -> None:
    _alter_access_logs("ALTER TABLE access_logs DROP COLUMN IF EXISTS took_ms, DROP COLUMN IF EXISTS ui_flow", "quitar las columnas access_logs.took_ms y access_logs.ui_flow")
