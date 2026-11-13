"""Código opcional por evento y subcategorías (zonas e inventario).

- `events.code_enabled` / `events.code_required`: el evento usa un «código» (serial del QR, distinto de la cédula) y si es obligatorio al registrar.
- `event_attendees.code`: el código de la persona EN ese evento; único dentro del evento sin distinguir mayúsculas (índice parcial).
- `event_areas` / `inventory_items`: `parent_id` (subcategoría de otra fila del mismo evento), `stats_enabled` (genera estadísticas) y `max_per_person`
  (límite por persona: entradas a la zona o unidades del grupo de inventario; NULL = sin límite). Las filas existentes quedan iguales (sin padre, con estadísticas, sin límite).

Escrita a mano; sin SET de sesión (pooler de Neon).

Revision ID: 0140_codigo_subcategorias
Revises: 0129_staff_client_temp
"""
from alembic import op
import sqlalchemy as sa

revision = "0140_codigo_subcategorias"
down_revision = "0129_staff_client_temp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("code_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("events", sa.Column("code_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("event_attendees", sa.Column("code", sa.String(64), nullable=True))
    op.create_index(
        "uq_event_attendee_code", "event_attendees", ["event_id", sa.text("lower(code)")],
        unique=True, postgresql_where=sa.text("code IS NOT NULL"),
    )
    for table in ("event_areas", "inventory_items"):
        op.add_column(table, sa.Column("parent_id", sa.Integer(), sa.ForeignKey(f"{table}.id"), nullable=True))
        op.add_column(table, sa.Column("stats_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.add_column(table, sa.Column("max_per_person", sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_parent", table, ["parent_id"])


def downgrade():
    for table in ("inventory_items", "event_areas"):
        op.drop_index(f"ix_{table}_parent", table_name=table)
        op.drop_column(table, "max_per_person")
        op.drop_column(table, "stats_enabled")
        op.drop_column(table, "parent_id")
    op.drop_index("uq_event_attendee_code", table_name="event_attendees")
    op.drop_column("event_attendees", "code")
    op.drop_column("events", "code_required")
    op.drop_column("events", "code_enabled")
