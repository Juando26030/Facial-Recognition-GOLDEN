"""Sprint 5: Ruleta (sorteos por evento) — configuración y registro de sorteos.

Revision ID: 0038_roulette
Revises: 0037_bulk_jobs
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0038_roulette"
down_revision = "0037_bulk_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roulette_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("behavior_json", sa.Text(), nullable=True),
        sa.Column("style_json", sa.Text(), nullable=True),
        sa.Column("display_token", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_roulette_config_event"),
        sa.UniqueConstraint("display_token", name="uq_roulette_display_token"),
    )
    op.create_table(
        "roulette_draws",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("is_random", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("candidates_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filter_json", sa.Text(), nullable=True),
        sa.Column("winners_json", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_roulette_draws_event", "roulette_draws", ["event_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_roulette_draws_event", table_name="roulette_draws")
    op.drop_table("roulette_draws")
    op.drop_table("roulette_configs")
