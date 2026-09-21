"""Reunión 2026-09-21, ítem 1: logo por evento — `events.logo_mode` ('default' = el logo de Golden de
siempre, 'hidden' = sin logo, 'custom' = imagen propia) y `events.logo_path` (archivo de la imagen
propia, en data/<tenant>/event_logos/). Los eventos existentes quedan en 'default': nada cambia.

Revision ID: 0027_event_logo
Revises: 0026_field_config_help_text
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0027_event_logo"
down_revision = "0026_field_config_help_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("logo_mode", sa.String(), nullable=False, server_default="default"))
        batch_op.add_column(sa.Column("logo_path", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("logo_path")
        batch_op.drop_column("logo_mode")
