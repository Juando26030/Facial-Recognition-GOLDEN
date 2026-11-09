"""Autorregistro sin base de datos en el kiosco (Fase 8): interruptor por evento, apagado por defecto.

Revision ID: 0115_kiosk_selfreg
Revises: 0113_public_slug
"""
from alembic import op
import sqlalchemy as sa

revision = "0115_kiosk_selfreg"
down_revision = "0113_public_slug"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("selfreg_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("events", "selfreg_enabled")
