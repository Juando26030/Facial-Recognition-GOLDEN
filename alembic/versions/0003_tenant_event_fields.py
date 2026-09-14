"""Campos operativos de Tenant (cliente) y Event: contacto del cliente, código de evento,
fechas/horarios de montaje, ubicación detallada y observaciones.

Revision ID: 0003_tenant_event_fields
Revises: 0002_auth_roles_events
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_tenant_event_fields"
down_revision = "0002_auth_roles_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("contact_name", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("contact_phone", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("contact_email", sa.String(), nullable=True))

    op.add_column("events", sa.Column("event_code", sa.String(), nullable=True))
    op.add_column("events", sa.Column("setup_date", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("event_schedule", sa.String(), nullable=True))
    op.add_column("events", sa.Column("setup_schedule", sa.String(), nullable=True))
    op.add_column("events", sa.Column("country", sa.String(), nullable=True))
    op.add_column("events", sa.Column("city", sa.String(), nullable=True))
    op.add_column("events", sa.Column("address", sa.String(), nullable=True))
    op.add_column("events", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("notes", "address", "city", "country", "setup_schedule", "event_schedule", "setup_date", "event_code"):
        op.drop_column("events", col)
    for col in ("contact_email", "contact_phone", "contact_name"):
        op.drop_column("tenants", col)
