"""Llamado de asistencia del personal temporal del evento (28-nov-2026, Juan David). Solo ADITIVA: tabla nueva `event_staff_attendance`.

Una fila por (evento, cuenta) con `status` = on_time | late | absent; sin fila = sin marcar. Se borra en cascada con la cuenta o el evento. Escrita a mano; sin SET de sesión (pooler de Neon).
Id <= 32 caracteres.

Revision ID: 0170_staff_attendance
Revises: 0169_code_search_by_module
"""
import sqlalchemy as sa
from alembic import op

revision = "0170_staff_attendance"
down_revision = "0169_code_search_by_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_staff_attendance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("marked_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "staff_user_id", name="uq_event_staff_attendance"),
    )


def downgrade() -> None:
    op.drop_table("event_staff_attendance")
