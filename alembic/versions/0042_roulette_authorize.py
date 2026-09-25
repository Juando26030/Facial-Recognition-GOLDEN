"""Sprint 5: la Ruleta se gira desde la pantalla pública; el operador solo autoriza el giro.

Revision ID: 0042_roulette_authorize
Revises: 0041_form_refunds
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0042_roulette_authorize"
down_revision = "0041_form_refunds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roulette_configs", sa.Column("authorized_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("roulette_configs", "authorized_json")
