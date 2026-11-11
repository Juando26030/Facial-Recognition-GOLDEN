"""Tipos de evento (Fase 10, bloque C): la «Categoría (tipo de evento)» del calendario.

Tabla `event_types` (lista que el super_admin administra en Configuración: agregar, renombrar, archivar, color opcional) + `events.event_type_id` (nullable: un evento sin tipo es
«Sin categoría»). Siembra Feria, Congreso, Corporativo, Social y Otro. Escrita a mano; sin SET de sesión (pooler de Neon).

Revision ID: 0128_event_types
Revises: 0127_person_change_log
"""
from alembic import op
import sqlalchemy as sa

revision = "0128_event_types"
down_revision = "0127_person_change_log"
branch_labels = None
depends_on = None

SEED = (("Feria", "#E8803A"), ("Congreso", "#2E6FD8"), ("Corporativo", "#1E2A6E"), ("Social", "#C2417C"), ("Otro", "#6B7280"))


def upgrade():
    table = op.create_table(
        "event_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("color", sa.String(9), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
    )
    op.bulk_insert(table, [{"name": n, "color": c, "position": i} for i, (n, c) in enumerate(SEED)])
    op.add_column("events", sa.Column("event_type_id", sa.Integer(), sa.ForeignKey("event_types.id"), nullable=True))
    op.create_index("ix_events_event_type_id", "events", ["event_type_id"])


def downgrade():
    op.drop_index("ix_events_event_type_id", table_name="events")
    op.drop_column("events", "event_type_id")
    op.drop_table("event_types")
