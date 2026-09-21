"""Reunión 2026-09-21, ítems 3a y 4: etiqueta propia por evento y orden de los campos.

`event_field_configs.label` — texto a mostrar en vez del nombre por defecto del campo, SOLO en
ese evento (NULL = usar el nombre por defecto). `event_field_configs.sort_order` — posición del
campo en "Registrar nuevo"/"Editar persona" (NULL = orden por defecto). Ambas nullable: los
eventos existentes siguen viéndose exactamente igual hasta que alguien personalice algo.

Revision ID: 0025_field_config_label_order
Revises: 0024_company_to_entity
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_field_config_label_order"
down_revision = "0024_company_to_entity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("event_field_configs") as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("sort_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("event_field_configs") as batch_op:
        batch_op.drop_column("sort_order")
        batch_op.drop_column("label")
