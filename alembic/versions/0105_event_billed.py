"""Fase 5 (A): estado «Facturado» + base de datos final del evento.

* `event_states`: se siembra «Facturado» (estado base `finalizado`, después del último estado, regla `client_delivery` encendida). Es un estado más: el administrador puede renombrarlo o
  cambiarle el color; quién puede ponerlo lo decide la regla `client_delivery` (solo comercial o administrador, ver app/routers/events.py).
* `events.billed_at` / `billed_by_id`: quién y cuándo lo facturó (el historial completo queda en `audit_actions`).
* `events.final_db_*`: archivo de la base de datos final procesada por humanos (clave en el almacenamiento, nombre, cuándo y quién).

Revision ID: 0105_event_billed
Revises: 0104_pledge_health_flags
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0105_event_billed"
down_revision = "0104_pledge_health_flags"
branch_labels = None
depends_on = None

_RULES = {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": False, "touch_registration": False,
          "areas": True, "inventory_control": True, "certificates": True, "client_delivery": True}


def upgrade() -> None:
    op.add_column("events", sa.Column("billed_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("billed_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_events_billed_by_id", "events", "staff_users", ["billed_by_id"], ["id"], ondelete="SET NULL")
    op.add_column("events", sa.Column("final_db_key", sa.String(), nullable=True))
    op.add_column("events", sa.Column("final_db_name", sa.String(), nullable=True))
    op.add_column("events", sa.Column("final_db_uploaded_at", sa.DateTime(), nullable=True))
    op.add_column("events", sa.Column("final_db_uploaded_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_events_final_db_by_id", "events", "staff_users", ["final_db_uploaded_by_id"], ["id"], ondelete="SET NULL")
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM event_states WHERE lower(name) = 'facturado'")).first()
    if not exists:
        position = bind.execute(sa.text("SELECT COALESCE(MAX(position), -1) + 1 FROM event_states")).scalar()
        table = sa.table("event_states", sa.column("name", sa.String), sa.column("base_status", sa.String), sa.column("color", sa.String), sa.column("position", sa.Integer),
                         sa.column("is_active", sa.Boolean), sa.column("rules_json", sa.Text))
        op.bulk_insert(table, [{"name": "Facturado", "base_status": "finalizado", "color": "#6f42c1", "position": position, "is_active": True, "rules_json": json.dumps(_RULES)}])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE events SET state_id = (SELECT s.id FROM event_states s WHERE s.base_status = 'finalizado' AND lower(s.name) <> 'facturado' ORDER BY s.position LIMIT 1) "
                         "WHERE state_id IN (SELECT id FROM event_states WHERE lower(name) = 'facturado')"))
    bind.execute(sa.text("DELETE FROM event_states WHERE lower(name) = 'facturado'"))
    op.drop_constraint("fk_events_final_db_by_id", "events", type_="foreignkey")
    op.drop_column("events", "final_db_uploaded_by_id")
    op.drop_column("events", "final_db_uploaded_at")
    op.drop_column("events", "final_db_name")
    op.drop_column("events", "final_db_key")
    op.drop_constraint("fk_events_billed_by_id", "events", type_="foreignkey")
    op.drop_column("events", "billed_by_id")
    op.drop_column("events", "billed_at")
