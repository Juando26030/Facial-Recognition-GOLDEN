"""EventAttendee: lista de personas esperadas/asociadas a un evento, separada de User (decisión
de modelado documentada en CLAUDE.md, 05_MODELO_DATOS.md §3 pregunta 1, opción (b)) — necesaria
para que "cargar la base de un evento" sea agnóstica al método de registro (cédula/facial/QR).

Revision ID: 0008_event_attendees
Revises: 0007_unique_codes
Create Date: 2026-09-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_event_attendees"
down_revision = "0007_unique_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_attendees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id", "tenant_id"], ["users.id", "users.tenant_id"]),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_attendee"),
    )


def downgrade() -> None:
    op.drop_table("event_attendees")
