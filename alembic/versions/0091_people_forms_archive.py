"""Fase 3, oleada de personas y formularios. Solo ADITIVA.

  event_attendees.archived_at / archived_by_id   archivar la inscripción de una persona a un evento = ocultarla del directorio (NULL = visible); se restaura. No toca users, consentimientos ni audit_consent_logs.
  web_forms.archived_at / archived_by_id          archivar un formulario = ocultarlo de las listas y cerrarlo al público; conserva inscripciones y pagos (contrato: poder entregar esa base).

Revision ID: 0091_people_forms_archive
Revises: 0090_event_archive
Create Date: 2026-11-07
"""
from alembic import op

revision = "0091_people_forms_archive"
down_revision = "0090_event_archive"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("event_attendees", "web_forms"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")


def downgrade():
    for table in ("event_attendees", "web_forms"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS archived_by_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS archived_at")
