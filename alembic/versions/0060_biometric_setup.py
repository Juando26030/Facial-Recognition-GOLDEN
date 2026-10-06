"""Paso guiado de biometría del evento: si el cliente entregará fotos de los asistentes ANTES del evento (`client_photos_before`) y la casilla de garantía del cliente que exige el pre-cálculo
(`precalculo_garantia`).

Revision ID: 0060_biometric_setup
Revises: 0059_aceptar_web
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_biometric_setup"
down_revision = "0059_aceptar_web"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("client_photos_before", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("events", sa.Column("precalculo_garantia", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("events", "precalculo_garantia")
    op.drop_column("events", "client_photos_before")
