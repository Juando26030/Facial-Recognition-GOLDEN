"""Sprint 2.4 Fase 3 (2026-09-16): print_logs — historial de impresiones de escarapela, para
poder avisar "esta persona ya se imprimió N veces" antes de repetir. Tabla nueva, no toca nada
existente.

Revision ID: 0016_print_logs
Revises: 0015_staff_phone
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_print_logs"
down_revision = "0015_staff_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("printed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("printed_by_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )
    op.create_foreign_key(
        "fk_print_logs_user", "print_logs", "users",
        ["user_id", "tenant_id"], ["id", "tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("print_logs")
