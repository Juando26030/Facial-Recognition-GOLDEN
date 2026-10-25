"""Impresión compartida: el trabajo guarda los parámetros de impresión del equipo que lo pidió (24-oct-2026). Solo ADITIVA: una columna de texto que admite NULL (NULL = los
del evento, como hasta ahora); no toca ni reescribe datos existentes y se puede deshacer quitando la columna.

Revision ID: 0071_print_job_prefs
Revises: 0070_print_settings
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0071_print_job_prefs"
down_revision = "0070_print_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("print_jobs", sa.Column("prefs_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("print_jobs", "prefs_json")
