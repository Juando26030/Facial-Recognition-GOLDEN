"""CRM → inventario por CATEGORÍAS de Almacén (19-nov-2026): un producto del CRM implica categorías (filas del checklist: Portátiles, Lectores…) y no elementos sueltos.

Reemplaza `crm_product_inventory` (0153, sin datos de producción) por `crm_product_categories`. Las demás tablas de 0153 siguen igual.

Revision ID: 0154_crm_implica_categorias
Revises: 0153_crm_implica_inventario
"""
import sqlalchemy as sa
from alembic import op

revision = "0154_crm_implica_categorias"
down_revision = "0153_crm_implica_inventario"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("crm_product_inventory")
    op.create_table(
        "crm_product_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("crm_product_id", sa.Integer(), sa.ForeignKey("crm_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checklist_key", sa.String(40), nullable=False),
        sa.Column("qty_per_unit", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("crm_product_id", "checklist_key", name="uq_crm_product_category"),
    )


def downgrade():
    op.drop_table("crm_product_categories")
    op.create_table(
        "crm_product_inventory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("crm_product_id", sa.Integer(), sa.ForeignKey("crm_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_product_id", sa.Integer(), sa.ForeignKey("inventory_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty_per_unit", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("crm_product_id", "inventory_product_id", name="uq_crm_product_inventory"),
    )
