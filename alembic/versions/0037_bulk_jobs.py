"""Sprint 5: `bulk_jobs` — cargas masivas de base en segundo plano, con progreso consultable.

Revision ID: 0037_bulk_jobs
Revises: 0036_security
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0037_bulk_jobs"
down_revision = "0036_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_status", sa.Integer(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_bulk_jobs_event", "bulk_jobs", ["event_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_bulk_jobs_event", table_name="bulk_jobs")
    op.drop_table("bulk_jobs")
