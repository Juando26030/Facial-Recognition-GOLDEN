"""Camino B (/aceptar/<evento>): activación por evento y aceptaciones hechas desde el celular, «por verificar» hasta que el personal confirme la identidad en puerta con el documento o el QR
(la cédula de otra persona no basta para quedar reconocido por rostro).

Revision ID: 0059_aceptar_web
Revises: 0058_suppressed_people
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0059_aceptar_web"
down_revision = "0058_suppressed_people"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("aceptar_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "web_acceptances",
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("event_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by_staff_id", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "event_id"),
    )


def downgrade() -> None:
    op.drop_table("web_acceptances")
    op.drop_column("events", "aceptar_enabled")
