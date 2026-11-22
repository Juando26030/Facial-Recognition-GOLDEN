"""Servidor local con alcance por cliente (revisión de seguridad 22-nov-2026, 03 #3 y 04 #3). Solo ADITIVA.

  local_nodes.tenant_id        «solo eventos de este cliente». NULL = sin restricción: todo servidor ya instalado sigue igual.
  local_server_keys.tenant_id  el cliente elegido al crear la llave (opcional); el servidor lo hereda al vincularse.

Sin llave foránea a propósito: archivar o borrar un cliente no debe tumbar ni «abrir» un servidor (con un cliente que ya no existe, el servidor
simplemente no ve ningún evento). Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

OJO (coordinador): 0162 lo escribe otro agente. Si 0162 ya existe al juntar las ramas, cambiar `down_revision` de esta migración a ese id
(una sola cabeza); hoy apunta a 0161 porque 0162 todavía no está en el árbol.

Revision ID: 0163_local_nodes_tenant
Revises: 0161_inventario_por_base
"""
from alembic import op
import sqlalchemy as sa

revision = "0163_local_nodes_tenant"
down_revision = "0161_inventario_por_base"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    for table in ("local_nodes", "local_server_keys"):
        if "tenant_id" not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))


def downgrade():
    op.drop_column("local_server_keys", "tenant_id")
    op.drop_column("local_nodes", "tenant_id")
