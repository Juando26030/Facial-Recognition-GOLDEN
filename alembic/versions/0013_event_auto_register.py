"""Sprint 2.2, Fase B: Event.auto_register — mismo patrón que auto_print_badge (migración 0012),
pero para el registro en sí. Apagado por defecto: facial/checkin-cédula dejan de acreditar solos
con un match, quedan "pendientes" hasta que el digitador confirme, salvo que este switch esté
prendido. Ver CLAUDE.md y models.py para el detalle.

Revision ID: 0013_event_auto_register
Revises: 0012_badge_templates
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_event_auto_register"
down_revision = "0012_badge_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("auto_register", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("events", "auto_register")
