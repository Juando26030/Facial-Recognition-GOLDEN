"""Trazabilidad de cambios manuales sobre una persona en un evento: estado de registro (quién, cuándo, estado anterior y nuevo) y fecha de nacimiento.

Antes, pasar a «No registrado» BORRABA los accesos de la persona y no quedaba rastro de quién lo hizo. Sin llaves foráneas (una supresión de datos no se bloquea por esta tabla; ver app/privacy.py).

Revision ID: 0062_person_changes
Revises: 0061_privacy_requests
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0062_person_changes"
down_revision = "0061_privacy_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("event_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.String, nullable=True),
        sa.Column("staff_user_id", sa.Integer, nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("old_value", sa.String, nullable=True),
        sa.Column("new_value", sa.String, nullable=True),
        sa.Column("detail", sa.String, nullable=True),
    )
    op.create_index("ix_person_changes_event_user", "person_changes", ["event_id", "user_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_person_changes_event_user", table_name="person_changes")
    op.drop_table("person_changes")
