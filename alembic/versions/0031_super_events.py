"""Reunión 2026-09-21, ítem 19: "Superevento" — agrupa eventos independientes (ej. las sedes de un
congreso) de un mismo cliente. Cada evento hijo sigue 100% separado; lo único que cruza es el aviso
de "esta persona ya asistió a un evento hermano".

Revision ID: 0031_super_events
Revises: 0030_event_docs_expenses
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_super_events"
down_revision = "0030_event_docs_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "super_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("super_event_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_events_super_event", "super_events", ["super_event_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("fk_events_super_event", type_="foreignkey")
        batch_op.drop_column("super_event_id")
    op.drop_table("super_events")
