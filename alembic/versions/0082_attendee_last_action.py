"""Cola compartida de recién registrados: hora del SERVIDOR de la última acción de cada persona. Solo ADITIVA.

  event_attendees.last_action_at   hora (UTC, del servidor) del último alta o acreditación de la persona en ese evento. NULL = sin acción registrada con esta columna (filas viejas, sin relleno).
  ix_event_attendees_event_last_action   índice (event_id, last_action_at) para ordenar la cola.

Columna nullable y sin DEFAULT: en Postgres no reescribe la tabla (instantáneo). El código anterior la ignora; bajar la migración quita índice y columna.
Permisos: ninguno nuevo (la cubren los permisos de TABLA de `golden_app` sobre `event_attendees`).

Revision ID: 0082_attendee_last_action
Revises: 0081_event_idle_minutes
Create Date: 2026-11-04
"""
from alembic import op

revision = "0082_attendee_last_action"
down_revision = "0081_event_idle_minutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE event_attendees ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMP")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_attendees_event_last_action ON event_attendees (event_id, last_action_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_event_attendees_event_last_action")
    op.execute("ALTER TABLE event_attendees DROP COLUMN IF EXISTS last_action_at")
