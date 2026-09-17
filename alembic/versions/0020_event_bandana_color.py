"""Sprint 2.4 Fase 12 (2026-09-17): Event.bandana_color/bandana_color_name — "Color de pañoleta",
elegido al crear/editar el evento (input de color con gotero) más un nombre libre para ese color.
Identifica al evento en el Calendario en vez del color por estado.

Revision ID: 0020_event_bandana_color
Revises: 0019_calendar_notes
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0020_event_bandana_color"
down_revision = "0019_calendar_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("bandana_color", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("bandana_color_name", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("bandana_color_name")
        batch_op.drop_column("bandana_color")
