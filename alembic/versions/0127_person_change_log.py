"""Historial de datos modificados por persona (Fase 10, bloque E): tabla person_change_log.

Sin llaves foráneas (como person_changes): se borra con la persona y con el evento desde el código.

Revision ID: 0127_person_change_log
Revises: 0121_infra_costs  (al integrar: apuntar a la última migración del bloque D, 0126)
"""
from alembic import op
import sqlalchemy as sa

revision = "0127_person_change_log"
down_revision = "0121_infra_costs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "person_change_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("old_value", sa.String(500), nullable=True),
        sa.Column("new_value", sa.String(500), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="edit"),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_person_change_log_person", "person_change_log", ["tenant_id", "user_id"])
    op.create_index("ix_person_change_log_event", "person_change_log", ["event_id"])


def downgrade():
    op.drop_index("ix_person_change_log_event", table_name="person_change_log")
    op.drop_index("ix_person_change_log_person", table_name="person_change_log")
    op.drop_table("person_change_log")
