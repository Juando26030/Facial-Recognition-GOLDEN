"""Event.roster_uploaded: marca si ya se cargó al menos una base para este evento (bulk_register).
Se usa para bloquear un re-upload accidental mientras el evento ya está en_proceso — ver
routers/api.py: bulk_register y CLAUDE.md.

Revision ID: 0011_roster_uploaded_flag
Revises: 0010_event_facial_enabled
Create Date: 2026-09-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_roster_uploaded_flag"
down_revision = "0010_event_facial_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("roster_uploaded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("events", "roster_uploaded")
