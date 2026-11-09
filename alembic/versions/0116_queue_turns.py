"""Turnos y filas (Fase 8): interruptor y configuración en el evento, y las tablas de turnos y llamados.

Revision ID: 0116_queue_turns
Revises: 0113_public_slug
"""
from alembic import op
import sqlalchemy as sa

revision = "0116_queue_turns"
down_revision = "0115_kiosk_selfreg"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("queue_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("events", sa.Column("queue_config_json", sa.Text(), nullable=True))
    op.create_table(
        "queue_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("lane", sa.String(1), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="waiting"),
        sa.Column("desk", sa.String(40), nullable=True),
        sa.Column("called_seq", sa.Integer(), nullable=True),
        sa.Column("called_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("called_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="arrival"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "lane", "number", name="uq_queue_turn_number"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_queue_turn_user"),
    )
    op.create_index("ix_queue_turn_event_status", "queue_turns", ["event_id", "status"])
    op.create_table(
        "queue_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("turn_id", sa.Integer(), sa.ForeignKey("queue_turns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lane", sa.String(1), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("desk", sa.String(40), nullable=True),
        sa.Column("called_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("called_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_queue_call_event", "queue_calls", ["event_id", "id"])


def downgrade():
    op.drop_index("ix_queue_call_event", table_name="queue_calls")
    op.drop_table("queue_calls")
    op.drop_index("ix_queue_turn_event_status", table_name="queue_turns")
    op.drop_table("queue_turns")
    op.drop_column("events", "queue_config_json")
    op.drop_column("events", "queue_enabled")
