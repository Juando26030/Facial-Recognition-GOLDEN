"""Tokens de servidores locales y estado de subida de sus eventos (Fase 6).

Revision ID: 0112_local_nodes
Revises: 0111_event_lease
"""
from alembic import op
import sqlalchemy as sa

revision = "0112_local_nodes"
down_revision = "0111_event_lease"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "local_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_version", sa.String(80), nullable=True),
        sa.UniqueConstraint("name", name="uq_local_nodes_name"),
        sa.UniqueConstraint("token_hash", name="uq_local_nodes_token_hash"),
    )
    op.add_column("events", sa.Column("cloud_event_id", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("sync_log_id", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("sync_persons_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("sync_package_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("sync_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("sync_error", sa.String(300), nullable=True))


def downgrade():
    for col in ("sync_error", "sync_attempt_at", "sync_package_at", "sync_persons_at", "sync_log_id", "cloud_event_id"):
        op.drop_column("events", col)
    op.drop_table("local_nodes")
