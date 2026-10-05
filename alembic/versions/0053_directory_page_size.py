"""Filas por página de la tabla del directorio, por evento (Parámetros del evento).

`events.directory_page_size` (10, 20, 50, 100 o 200; por defecto 50: una página de 50 filas es ligera en un celular o un iPad; antes la tabla pintaba 200).

Revision ID: 0053_directory_page_size
Revises: 0051_biometric_retention
Create Date: 2026-10-05

NOTA al integrar con `producto/estados-evento` (migración `0052_event_states`, también hija de 0051): cambiar `down_revision` de esta a "0052_event_states" para dejar UNA sola cabeza.
"""
import sqlalchemy as sa
from alembic import op

revision = "0053_directory_page_size"
down_revision = "0051_biometric_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("directory_page_size", sa.Integer(), nullable=False, server_default="50"))


def downgrade() -> None:
    op.drop_column("events", "directory_page_size")
