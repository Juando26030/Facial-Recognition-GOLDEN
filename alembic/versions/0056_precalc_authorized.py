"""Pre-cálculo de vectores autorizado por contrato (regla A): solo un super_admin lo activa, en un evento de un tercero, registrando la referencia y la fecha del anexo firmado
(declaraciones, garantías e indemnidad). Sin esto ningún flujo calcula el vector de alguien que aún no aceptó.

Revision ID: 0056_precalc_authorized
Revises: 0055_event_consent_config
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_precalc_authorized"
down_revision = "0055_event_consent_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("precalculo_autorizado", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("events", sa.Column("precalculo_anexo_ref", sa.String(), nullable=True))
    op.add_column("events", sa.Column("precalculo_anexo_fecha", sa.Date(), nullable=True))


def downgrade() -> None:
    for c in ("precalculo_anexo_fecha", "precalculo_anexo_ref", "precalculo_autorizado"):
        op.drop_column("events", c)
