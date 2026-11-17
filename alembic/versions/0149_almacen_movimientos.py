"""Almacén, Pieza 2 (17-nov-2026): movimientos de salida/entrada por QR, alistado por fila del checklist y el evento donde está cada equipo y la foto de cada elemento.

Solo AGREGA (columnas nulas y dos tablas nuevas): el código anterior las ignora, así que volver atrás de código no exige tocar la base.

Revision ID: 0149_almacen_movimientos
Revises: 0148_almacen_unidades
"""
import sqlalchemy as sa
from alembic import op

revision = "0149_almacen_movimientos"
down_revision = "0148_almacen_unidades"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory_products", sa.Column("photo_key", sa.String(200), nullable=True))
    op.add_column("inventory_units", sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True))
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("inventory_products.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("inventory_units.id"), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("extra", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("is_plan_b", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )
    op.create_index("ix_inventory_movements_event", "inventory_movements", ["event_id", "product_id"])
    op.create_index("ix_inventory_movements_unit", "inventory_movements", ["unit_id"])
    op.create_table(
        "event_checklist_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("row_key", sa.String(40), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", "row_key", name="uq_event_checklist_row"),
    )


def downgrade():
    op.drop_table("event_checklist_rows")
    op.drop_index("ix_inventory_movements_unit", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_event", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_column("inventory_units", "event_id")
    op.drop_column("inventory_products", "photo_key")
