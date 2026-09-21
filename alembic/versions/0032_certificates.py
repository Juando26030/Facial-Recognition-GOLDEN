"""Reunión 2026-09-21, ítem 5: módulo de certificados.

- `events.certificates_enabled` — el coordinador lo activa desde Parámetros del Evento.
- `event_attendees.certificate` — "Certificado: Sí/No" de cada persona EN ese evento (default No).
- `badge_templates.kind` — 'badge' (escarapela, lo de siempre) o 'certificate' (plantilla del
  certificado). Reusa la misma tabla y el mismo editor: por eso la unicidad pasa de
  (event_id, category) a (event_id, category, kind).

Revision ID: 0032_certificates
Revises: 0031_super_events
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0032_certificates"
down_revision = "0031_super_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("certificates_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.add_column(sa.Column("certificate", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("badge_templates") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="badge"))
        batch_op.drop_constraint("uq_badge_template_event_category", type_="unique")
        batch_op.create_unique_constraint("uq_badge_template_event_category_kind", ["event_id", "category", "kind"])


def downgrade() -> None:
    with op.batch_alter_table("badge_templates") as batch_op:
        batch_op.drop_constraint("uq_badge_template_event_category_kind", type_="unique")
        batch_op.create_unique_constraint("uq_badge_template_event_category", ["event_id", "category"])
        batch_op.drop_column("kind")
    with op.batch_alter_table("event_attendees") as batch_op:
        batch_op.drop_column("certificate")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("certificates_enabled")
