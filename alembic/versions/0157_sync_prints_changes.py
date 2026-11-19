"""Marcas de agua de la subida del servidor local para impresiones y ediciones de personas (19-nov-2026). Solo ADITIVA.

  events.sync_print_id:  último PrintLog.id local ya CONFIRMADO por la nube.
  events.sync_change_id: último PersonChange.id local ya CONFIRMADO por la nube.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0157_sync_prints_changes
Revises: 0156_legalizacion_orden
"""
from alembic import op
import sqlalchemy as sa

revision = "0157_sync_prints_changes"
down_revision = "0156_legalizacion_orden"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("events")}
    for name in ("sync_print_id", "sync_change_id"):
        if name not in cols:
            op.add_column("events", sa.Column(name, sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("events", "sync_change_id")
    op.drop_column("events", "sync_print_id")
