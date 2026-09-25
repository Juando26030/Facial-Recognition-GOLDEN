"""Tamaño del logo propio del evento (alto y modo banner).

Revision ID: 0045_event_logo_size
Revises: 0044_digital_email_template
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0045_event_logo_size"
down_revision = "0044_digital_email_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("logo_height", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("events", sa.Column("logo_fit", sa.String(), nullable=False, server_default="logo"))


def downgrade() -> None:
    op.drop_column("events", "logo_fit")
    op.drop_column("events", "logo_height")
