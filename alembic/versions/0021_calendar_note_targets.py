"""Sprint 2.4 Fase 14 (2026-09-17): CalendarNote.target_staff_ids — lista JSON de destinatarios
específicos de un recordatorio (vacío/NULL = visible para todo el equipo, comportamiento
original).

Revision ID: 0021_calendar_note_targets
Revises: 0020_event_bandana_color
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0021_calendar_note_targets"
down_revision = "0020_event_bandana_color"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_notes") as batch_op:
        batch_op.add_column(sa.Column("target_staff_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("calendar_notes") as batch_op:
        batch_op.drop_column("target_staff_ids")
