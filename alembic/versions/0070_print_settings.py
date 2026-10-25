"""Valores de impresión de escarapelas POR EVENTO (orden B del 23-oct-2026): cinta, giro, recorte, corte y margen. Solo ADITIVA: una columna de texto que admite NULL
(NULL = valores de fábrica); no toca ni reescribe datos existentes y se puede deshacer quitando la columna.

Revision ID: 0070_print_settings
Revises: 0069_shared_print
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0070_print_settings"
down_revision = "0069_shared_print"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("print_settings_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "print_settings_json")
