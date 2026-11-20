"""Llaves de producto del servidor local (20-nov-2026). Tabla nueva, solo ADITIVA.

  local_server_keys: código único `GLD-XXXX-XXXX-XXXX`, vigencia, reclamo del instalador, activación (nodo) y deshabilitación.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0158_local_server_keys
Revises: 0157_sync_prints_changes
"""
from alembic import op
import sqlalchemy as sa

revision = "0158_local_server_keys"
down_revision = "0157_sync_prints_changes"
branch_labels = None
depends_on = None


def upgrade():
    if "local_server_keys" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "local_server_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("label", sa.String(60), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("installation_id", sa.String(64), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("local_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("code", name="uq_local_server_keys_code"),
    )


def downgrade():
    op.drop_table("local_server_keys")
