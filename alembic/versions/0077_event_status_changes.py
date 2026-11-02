"""Eventos en curso, pedido B: devolver un evento «en curso» a «creado». Solo ADITIVA.

  event_status_changes   bitácora de los retrocesos de estado (quién, cuándo, motivo opcional, cuántas personas e ingresos tenía). Solo INSERT, sin llaves foráneas ni datos personales.
  access_logs.doubtful_reason   «sin_hora_valida» en el ingreso que un quiosco sin red sincronizó tras el retroceso sin una hora válida (columna nueva y vacía; para revisarlos).

El código anterior las ignora; bajar la migración quita la tabla y la columna.

Bloqueo de `access_logs` (ACCESS EXCLUSIVE, aunque muy breve): mientras `ALTER TABLE` espera el bloqueo, TODA lectura y escritura nueva de esa tabla hace fila detrás de él (los ingresos de la puerta). Por eso el
`ALTER` va con `lock_timeout` corto (4 s) dentro de un SAVEPOINT y se reintenta unas veces (5, con pausa de 3 s entre una y otra, para que la fila acumulada se vacíe); si no se consigue, la migración FALLA ENTERA
(nada queda a medias) con un mensaje claro y se repite en otro momento. `SET LOCAL` vale solo dentro de la transacción de la migración, que corre por la conexión directa del dueño: la app no usa `SET`.
Variables opcionales (solo para pruebas o casos especiales): MIGRATION_LOCK_TIMEOUT_S, MIGRATION_LOCK_ATTEMPTS, MIGRATION_LOCK_PAUSE_S.

Permisos: `golden_app` recibe SELECT/INSERT/UPDATE/DELETE sobre la tabla nueva y USAGE/SELECT/UPDATE sobre su secuencia (si el rol existe). En Neon ya los daría `ALTER DEFAULT PRIVILEGES` de
`scripts/neon_app_role.py` (el patrón de 0074/0075); aquí se dan de forma explícita e idempotente para no depender de él. La columna nueva queda cubierta por los permisos de tabla que ya tiene `access_logs`.
Esta migración debe ser la ÚLTIMA de su corrida: alembic usa una sola transacción para todas las migraciones pendientes, así que el bloqueo de `access_logs` se mantiene hasta que termina la corrida.

Revision ID: 0077_event_status_changes
Revises: 0076_print_mode
Create Date: 2026-11-01
"""
import os
import time

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision = "0077_event_status_changes"
down_revision = "0076_print_mode"
branch_labels = None
depends_on = None

LOCK_NOT_AVAILABLE = "55P03"


def _alter_access_logs(statement: str, what: str) -> None:
    """`ALTER TABLE access_logs …` con `lock_timeout` corto y reintentos; si no se consigue el bloqueo, falla con un mensaje claro (y la migración se deshace entera)."""
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
    op.create_table(
        "event_status_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.Column("staff_username", sa.String(80), nullable=True),
        sa.Column("from_status", sa.String(12), nullable=False),
        sa.Column("to_status", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("attendees_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("access_logs_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_event_status_changes_event_id", "event_status_changes", ["event_id"])
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON event_status_changes TO golden_app; "
               "GRANT USAGE, SELECT, UPDATE ON SEQUENCE event_status_changes_id_seq TO golden_app; END IF; END $$")
    _alter_access_logs("ALTER TABLE access_logs ADD COLUMN IF NOT EXISTS doubtful_reason VARCHAR(24)", "agregar la columna access_logs.doubtful_reason")


def downgrade() -> None:
    _alter_access_logs("ALTER TABLE access_logs DROP COLUMN IF EXISTS doubtful_reason", "quitar la columna access_logs.doubtful_reason")
    op.drop_index("ix_event_status_changes_event_id", table_name="event_status_changes")
    op.drop_table("event_status_changes")
