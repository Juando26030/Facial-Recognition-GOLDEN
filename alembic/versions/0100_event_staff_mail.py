"""Fase 4: interruptor por evento del correo a los digitadores asignados. Solo ADITIVA.

  events.staff_mail_enabled   true (por defecto) = al asignar un digitador temporal con correo se le avisa por correo; false = no se envía

Revision ID: 0100_event_staff_mail
Revises: 0099_digital_badge_fields
Create Date: 2026-11-08
"""
from alembic import op

revision = "0100_event_staff_mail"
down_revision = "0099_digital_badge_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS staff_mail_enabled BOOLEAN NOT NULL DEFAULT true")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS staff_mail_enabled")
