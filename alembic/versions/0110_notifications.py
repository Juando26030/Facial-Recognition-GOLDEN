"""Notificaciones dentro de la aplicación (campana + correo) y existencias del catálogo de inventario (Fase 5).

Revision ID: 0110_notifications
Revises: 0109_inventory_unify
"""
from alembic import op
import sqlalchemy as sa

revision = "0110_notifications"
down_revision = "0109_inventory_unify"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("staff_user_id", "dedupe_key", name="uq_notification_dedupe"),
    )
    op.create_index("ix_notifications_user_unread", "notifications", ["staff_user_id", "read_at"])
    op.add_column("inventory_products", sa.Column("qty_total", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("inventory_products", "qty_total")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
