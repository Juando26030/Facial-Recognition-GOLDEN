"""Cola de trabajos en segundo plano (tabla en Postgres; después Cloud Tasks / Cloud Run Jobs) y registro de eventos del sistema
(errores 5xx, último webhook de Wompi...) para la pantalla «Estado del sistema».

Revision ID: 0048_jobs_ops
Revises: 0047_fase0_carga
Create Date: 2026-09-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0048_jobs_ops"
down_revision = "0047_fase0_carga"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),   # queued | running | done | failed
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_status_run_at", "jobs", ["status", "run_at"])
    op.create_index("uq_jobs_dedupe", "jobs", ["kind", "dedupe_key"], unique=True, postgresql_where=sa.text("dedupe_key IS NOT NULL"))
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False),      # error_5xx | wompi_webhook | ...
        sa.Column("ref", sa.String(), nullable=True),        # id de petición, referencia de pago... (nunca datos personales)
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_system_events_kind_at", "system_events", ["kind", "at"])


def downgrade() -> None:
    op.drop_index("ix_system_events_kind_at", table_name="system_events")
    op.drop_table("system_events")
    op.drop_index("uq_jobs_dedupe", table_name="jobs")
    op.drop_index("ix_jobs_status_run_at", table_name="jobs")
    op.drop_table("jobs")
