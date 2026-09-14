"""start_date/end_date/setup_date pasan de DateTime a Date — la hora ya vive por separado en
event_time_start/end y setup_time_start/end (pedirla dos veces no tenía sentido).

Revision ID: 0005_event_dates_only
Revises: 0004_event_extras
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_event_dates_only"
down_revision = "0004_event_extras"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("start_date", "end_date", "setup_date"):
        op.alter_column("events", col, type_=sa.Date(), postgresql_using=f"{col}::date")


def downgrade() -> None:
    for col in ("start_date", "end_date", "setup_date"):
        op.alter_column("events", col, type_=sa.DateTime())
