"""Cierre de sesión por inactividad, tiempo propio por evento. Solo ADITIVA.

  events.idle_minutes   minutos de inactividad (5 a 60) tras los que se cierra la sesión del personal que trabaja en ese evento, SOLO mientras está «en proceso». Vacía = rige el general (SESSION_IDLE_MINUTES, 10).

Columna nullable y sin DEFAULT: en Postgres no reescribe la tabla (instantáneo) y los eventos existentes quedan con el tiempo general. El código anterior la ignora; bajar la migración la quita.
Permisos: ninguno nuevo (la cubren los permisos de TABLA de `golden_app` sobre `events`).

Revision ID: 0081_event_idle_minutes
Revises: 0080_form_client_users
Create Date: 2026-11-03
"""
from alembic import op

revision = "0081_event_idle_minutes"
down_revision = "0080_form_client_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS idle_minutes INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS idle_minutes")
