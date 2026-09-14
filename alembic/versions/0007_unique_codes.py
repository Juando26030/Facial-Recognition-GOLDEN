"""event_code único en toda la tabla events (no solo dentro de un tenant), y client_code nuevo en
tenants (generado al azar al crear, único, para poder referenciar/asociar un cliente sin exponer
su slug interno). Si ya hay event_code repetidos entre eventos existentes, esta migración los
renombra ella misma (le agrega un sufijo _2, _3... a todos menos al primero de cada grupo) antes
de crear el índice único, para no depender de que alguien los arregle a mano.

Revision ID: 0007_unique_codes
Revises: 0006_event_status_lifecycle
Create Date: 2026-09-19
"""
import secrets
from collections import defaultdict

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

    # Eventos con event_code repetido: al primero de cada grupo (el id más chico) lo dejamos
    # igual, a los demás les agregamos un sufijo para que el UNIQUE de abajo no falle.
    by_code = defaultdict(list)
    for event_id, code in conn.execute(sa.text("SELECT id, event_code FROM events ORDER BY id")):
        by_code[code].append(event_id)
    for code, ids in by_code.items():
        for suffix, dup_id in enumerate(ids[1:], start=2):
            new_code = f"{code}_{suffix}"
            while new_code in by_code:
                suffix += 1
                new_code = f"{code}_{suffix}"
            conn.execute(sa.text("UPDATE events SET event_code = :c WHERE id = :i"), {"c": new_code, "i": dup_id})

    op.create_unique_constraint("uq_events_event_code", "events", ["event_code"])


def downgrade() -> None:
    op.drop_constraint("uq_events_event_code", "events", type_="unique")
    op.drop_constraint("uq_tenants_client_code", "tenants", type_="unique")
    op.drop_column("tenants", "client_code")
