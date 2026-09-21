"""Reunión 2026-09-21, ítem 9: Control de Áreas y Control de Inventario.

- `events.areas_enabled` / `events.inventory_enabled` — switches por evento (Parámetros del Evento).
- `event_areas` — zonas del evento, cada una con su "permitir reingresos".
- `area_movements` — cada entrada/salida (hora exacta, zona, persona, método).
- `inventory_items` — ítems a repartir con su cantidad inicial (y si se pueden entregar varias unidades).
- `inventory_deliveries` — una fila por ítem entregado; las de un mismo combo comparten `batch_id`.
  El disponible = cantidad inicial - suma de lo entregado (se descuenta solo).

Revision ID: 0033_areas_inventory
Revises: 0032_certificates
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op

revision = "0033_areas_inventory"
down_revision = "0032_certificates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("areas_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("inventory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "event_areas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("allow_reentry", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "area_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("event_areas.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("registered_by_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.ForeignKeyConstraint(["user_id", "tenant_id"], ["users.id", "users.tenant_id"]),
    )
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("initial_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allow_multiple", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "inventory_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_by_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.ForeignKeyConstraint(["user_id", "tenant_id"], ["users.id", "users.tenant_id"]),
    )


def downgrade() -> None:
    op.drop_table("inventory_deliveries")
    op.drop_table("inventory_items")
    op.drop_table("area_movements")
    op.drop_table("event_areas")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("inventory_enabled")
        batch_op.drop_column("areas_enabled")
