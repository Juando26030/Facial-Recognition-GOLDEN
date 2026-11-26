"""Prioridad del código al buscar persona (Parámetros › Campos › Código de la persona). Solo ADITIVA.

  events.code_search_first   FALSE por defecto. TRUE = en el buscador del registro (y al escanear) primero salen las coincidencias por CÓDIGO y después las de cédula;
                             FALSE = primero la cédula, pero el código también se encuentra. Solo tiene efecto con `code_enabled`.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0166_code_search_first
Revises: 0165_each_accepts
"""
import sqlalchemy as sa
from alembic import op

revision = "0166_code_search_first"
down_revision = "0165_each_accepts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("code_search_first", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("events", "code_search_first")
