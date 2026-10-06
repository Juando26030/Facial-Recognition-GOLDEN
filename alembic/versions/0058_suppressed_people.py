"""Supresión individual (L4): `suppressed_people` guarda SOLO la huella de la cédula de quien pidió la supresión total (`scope=all`), para que una carga masiva, un alta o una inscripción
no la vuelvan a crear por error. Sin nombre ni contacto. No lleva llaves foráneas.

Revision ID: 0058_suppressed_people
Revises: 0057_birth_date_biometric_flag
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_suppressed_people"
down_revision = "0057_birth_date_biometric_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppressed_people",
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("cedula_hash", sa.String(64), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(), nullable=False, server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.PrimaryKeyConstraint("tenant_id", "cedula_hash"),
    )


def downgrade() -> None:
    op.drop_table("suppressed_people")
