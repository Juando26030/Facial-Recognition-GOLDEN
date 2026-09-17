"""Sprint 2.4 Fase 5 (2026-09-16): Event.commercial_staff_id — la comercial "dueña" del evento,
igual que coordinator_staff_id pero para el rol comercial. Nullable a nivel de columna (eventos
viejos no tienen uno) — para eventos NUEVOS se exige a nivel de API (ver routers/events.py:
create_event), mismo criterio ya usado para coordinator_staff_id. Sin backfill: no hay forma de
adivinar quién era la comercial de un evento ya creado antes de que este campo existiera.

Revision ID: 0018_event_commercial
Revises: 0017_staff_phone_unique
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_event_commercial"
down_revision = "0017_staff_phone_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("commercial_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("commercial_staff_id")
