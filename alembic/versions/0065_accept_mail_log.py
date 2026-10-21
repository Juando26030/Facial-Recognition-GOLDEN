"""Envío masivo de enlaces personales de autorización: registro de cada envío y la tanda en curso del evento.

`accept_mail_log` no lleva IP ni User-Agent ni llaves foráneas (una supresión de datos no se bloquea por esta tabla; ver app/privacy.py).

Revision ID: 0065_accept_mail_log
Revises: 0064_accept_link
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0065_accept_mail_log"
down_revision = "0064_accept_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accept_mail_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("event_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.String, nullable=True),
        sa.Column("staff_user_id", sa.Integer, nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("run_id", sa.String, nullable=True),
        sa.Column("detail", sa.String, nullable=True),
    )
    op.create_index("ix_accept_mail_log_event_at", "accept_mail_log", ["event_id", "at"])
    op.create_index("ix_accept_mail_log_user", "accept_mail_log", ["tenant_id", "user_id"])
    op.add_column("events", sa.Column("accept_mail_run", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "accept_mail_run")
    op.drop_index("ix_accept_mail_log_user", table_name="accept_mail_log")
    op.drop_index("ix_accept_mail_log_event_at", table_name="accept_mail_log")
    op.drop_table("accept_mail_log")
