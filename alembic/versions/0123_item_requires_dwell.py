"""Ítems de inventario del quiosco que solo se entregan a quien llegó al porcentaje de estadía (Fase 10, bloque A).

Revision ID: 0123_item_requires_dwell
Revises: 0122_dwell_autoscan
"""
from alembic import op
import sqlalchemy as sa

revision = "0123_item_requires_dwell"
down_revision = "0122_dwell_autoscan"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory_items", sa.Column("requires_dwell", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("inventory_items", "requires_dwell")
