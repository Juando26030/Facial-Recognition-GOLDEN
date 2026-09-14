"""event_code único en toda la tabla events (no solo dentro de un tenant), y client_code nuevo en
tenants (generado al azar al crear, único, para poder referenciar/asociar un cliente sin exponer
su slug interno). Si tu DB local ya tiene event_code repetidos entre eventos existentes, este
upgrade va a fallar al crear el índice único -- edítalos a mano primero (son pocas filas en un
entorno de prueba).

Revision ID: 0007_unique_codes
Revises: 0006_event_status_lifecycle
Create Date: 2026-09-19
"""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0007_unique_codes"
down_revision = "0006_event_status_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("client_code", sa.String(), nullable=True))

    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text("SELECT client_code FROM tenants WHERE client_code IS NOT NULL"))}
    for (tenant_id,) in conn.execute(sa.text("SELECT id FROM tenants WHERE client_code IS NULL")):
        code = secrets.token_hex(4).upper()
        while code in existing:
            code = secrets.token_hex(4).upper()
        existing.add(code)
        conn.execute(sa.text("UPDATE tenants SET client_code = :code WHERE id = :id"), {"code": code, "id": tenant_id})

    op.alter_column("tenants", "client_code", nullable=False)
    op.create_unique_constraint("uq_tenants_client_code", "tenants", ["client_code"])

    op.create_unique_constraint("uq_events_event_code", "events", ["event_code"])


def downgrade() -> None:
    op.drop_constraint("uq_events_event_code", "events", type_="unique")
    op.drop_constraint("uq_tenants_client_code", "tenants", type_="unique")
    op.drop_column("tenants", "client_code")
