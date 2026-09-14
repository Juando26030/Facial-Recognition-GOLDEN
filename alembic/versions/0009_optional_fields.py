"""Campos opcionales dinámicos para la carga de base (hasta 30, "opcional_1".."opcional_30"),
en vez de los dos campos fijos opt_1/opt_2 de antes. users.extra_fields guarda los valores de
cada persona (JSON); events.optional_field_labels guarda el nombre que el cliente le dio a cada
columna "opcional_N" para ESE evento (JSON) — ver CLAUDE.md y routers/api.py: bulk_register.

Revision ID: 0009_optional_fields
Revises: 0008_event_attendees
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_optional_fields"
down_revision = "0008_event_attendees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("extra_fields", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("optional_field_labels", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "optional_field_labels")
    op.drop_column("users", "extra_fields")
