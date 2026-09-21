"""Reunión 2026-09-21, ítems 10 y 16: `event_field_configs.help_text` — texto de política /
consentimiento que se muestra junto al checkbox de tratamiento de datos (tipo `consent`) o junto
al lienzo de firma (tipo `signature`).

Revision ID: 0026_field_config_help_text
Revises: 0025_field_config_label_order
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_field_config_help_text"
down_revision = "0025_field_config_label_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("event_field_configs") as batch_op:
        batch_op.add_column(sa.Column("help_text", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("event_field_configs") as batch_op:
        batch_op.drop_column("help_text")
