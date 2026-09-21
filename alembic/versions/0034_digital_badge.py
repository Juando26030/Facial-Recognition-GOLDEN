"""Reunión 2026-09-21, ítem 17: escarapela digital.

- `events.digital_badge_enabled` — se activa desde Parámetros del Evento.
- `event_attendees.digital_contact` — correo o teléfono al que se envía (validado al guardar).
- `event_attendees.digital_token` — enlace secreto e inadivinable (/b/<token>) de la escarapela de esa persona.
- `event_attendees.digital_sent_at` — cuándo se envió por última vez.

Revision ID: 0034_digital_badge
Revises: 0033_areas_inventory
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0034_digital_badge"
down_revision = "0033_areas_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("digital_badge_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.add_column(sa.Column("digital_contact", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("digital_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("digital_sent_at", sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint("uq_event_attendee_digital_token", ["digital_token"])


def downgrade() -> None:
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.drop_constraint("uq_event_attendee_digital_token", type_="unique")
        batch_op.drop_column("digital_sent_at")
        batch_op.drop_column("digital_token")
        batch_op.drop_column("digital_contact")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("digital_badge_enabled")
