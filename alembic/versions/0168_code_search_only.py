"""«Solo buscar por código» (Parámetros › Campos › Código de la persona; 25-nov-2026). Solo ADITIVA.

  events.code_search_only   FALSE por defecto. TRUE = lo que se busque o escanee en NÚMEROS solo se compara con el CÓDIGO de la persona, nunca con la cédula
                            (Registro, Inventario, Zonas y el servidor: app/person_code.find_user). Excluyente con `code_search_first`. Solo tiene efecto con `code_enabled`.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0168_code_search_only
Revises: 0167_staff_auth_login_ok
"""
import sqlalchemy as sa
from alembic import op

revision = "0168_code_search_only"
down_revision = "0167_staff_auth_login_ok"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("code_search_only", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("events", "code_search_only")
