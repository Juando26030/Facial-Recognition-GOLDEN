"""Sprint 2.4 Fase 16 (2026-09-17): AccessLog.registration_method — cómo se registró cada persona
('tradicional'|'autoregistro'|'biometrico'|'qr'), necesario para el reporte Excel rediseñado.

Revision ID: 0023_access_log_registration_method
Revises: 0022_staff_secondary_role
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0023_access_log_registration_method"
down_revision = "0022_staff_secondary_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("access_logs") as batch_op:
        batch_op.add_column(sa.Column("registration_method", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("access_logs") as batch_op:
        batch_op.drop_column("registration_method")
