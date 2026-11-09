"""Compromiso: qué preguntas de salud respondió «Sí» (solo cuáles, nunca el detalle) para la alerta en «Usuarios temporales» (9-nov-2026).

Revision ID: 0104_pledge_health_flags
Revises: 0103_staff_extra_roles
"""
from alembic import op
import sqlalchemy as sa

revision = "0104_pledge_health_flags"
down_revision = "0103_staff_extra_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("event_staff_pledges", sa.Column("health_flags", sa.String(30), nullable=True))


def downgrade():
    op.drop_column("event_staff_pledges", "health_flags")
