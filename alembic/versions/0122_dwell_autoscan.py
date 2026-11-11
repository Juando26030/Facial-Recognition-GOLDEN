"""Permanencia en zonas, premio por porcentaje de estadía y autoescaneo (Fase 10, bloque A): columnas de events.

Revision ID: 0122_dwell_autoscan
Revises: 0121_infra_costs
"""
from alembic import op
import sqlalchemy as sa

revision = "0122_dwell_autoscan"
down_revision = "0121_infra_costs"
branch_labels = None
depends_on = None

_BOOLS = ("areas_dwell_enabled", "dwell_prize_enabled", "areas_autoscan", "inventory_autoscan")


def upgrade():
    for name in _BOOLS:
        op.add_column("events", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("events", sa.Column("dwell_reference_minutes", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("dwell_threshold_pct", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("events", "dwell_threshold_pct")
    op.drop_column("events", "dwell_reference_minutes")
    for name in reversed(_BOOLS):
        op.drop_column("events", name)
