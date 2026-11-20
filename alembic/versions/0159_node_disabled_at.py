"""Servidor local deshabilitado guardado en el propio nodo (20-nov-2026). Solo ADITIVA.

  local_nodes.disabled_at: cuándo un administrador deshabilitó la llave de ese servidor. Antes solo se sabía mirando la llave; ahora las llaves
  deshabilitadas se pueden ELIMINAR de la lista y el servidor sigue recibiendo «deshabilitado» (403) en vez de un 401 genérico (y se bloquea).
  Se rellena con lo que ya estaba deshabilitado.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0159_node_disabled_at
Revises: 0158_local_server_keys
"""
from alembic import op
import sqlalchemy as sa

revision = "0159_node_disabled_at"
down_revision = "0158_local_server_keys"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("local_nodes")}
    if "disabled_at" not in cols:
        op.add_column("local_nodes", sa.Column("disabled_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE local_nodes SET disabled_at = k.disabled_at FROM local_server_keys k "
        "WHERE k.node_id = local_nodes.id AND k.disabled_at IS NOT NULL AND local_nodes.disabled_at IS NULL"
    )


def downgrade():
    op.drop_column("local_nodes", "disabled_at")
