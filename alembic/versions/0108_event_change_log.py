"""Fase 5: historial de cambios del evento por campo (`event_change_log`). Solo ADITIVA: tabla nueva, el código anterior la ignora; bajar la migración la quita.

Sin datos personales de asistentes (solo campos del evento). `golden_app` recibe SELECT/INSERT/UPDATE/DELETE y USAGE/SELECT/UPDATE de la secuencia si el rol existe (idempotente,
mismo patrón que 0077).

Revision ID: 0108_event_change_log
Revises: 0104_pledge_health_flags
"""
import sqlalchemy as sa
from alembic import op

revision = "0108_event_change_log"
down_revision = "0104_pledge_health_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_change_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("field_label", sa.String(120), nullable=False),
        sa.Column("old_value", sa.String(500), nullable=True),
        sa.Column("new_value", sa.String(500), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="edit"),
    )
    op.create_index("ix_event_change_log_event_id", "event_change_log", ["event_id"])
    op.create_index("ix_event_change_log_event_at", "event_change_log", ["event_id", "changed_at"])
    op.execute(sa.text("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON event_change_log TO golden_app;
            GRANT USAGE, SELECT, UPDATE ON SEQUENCE event_change_log_id_seq TO golden_app;
          END IF;
        END $$;
    """))


def downgrade() -> None:
    op.drop_index("ix_event_change_log_event_at", table_name="event_change_log")
    op.drop_index("ix_event_change_log_event_id", table_name="event_change_log")
    op.drop_table("event_change_log")
