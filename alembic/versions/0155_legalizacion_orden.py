"""Orden manual de los gastos de una legalización (18-nov-2026). Solo ADITIVA.

  event_expenses.position: lugar del gasto dentro de su rubro (se arrastra y se suelta en la pantalla). NULL = gasto anterior al orden manual: sale primero, por fecha.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0155_legalizacion_orden
Revises: 0154_crm_implica_categorias
"""
from alembic import op
import sqlalchemy as sa

revision = "0155_legalizacion_orden"
down_revision = "0154_crm_implica_categorias"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("event_expenses", sa.Column("position", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("event_expenses", "position")
