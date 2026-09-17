"""Sprint 2.4 Fase 16 (2026-09-17): AccessLog.registration_method — cómo se registró cada persona
('tradicional'|'autoregistro'|'biometrico'|'qr'), necesario para el reporte Excel rediseñado.

Bug real (2026-09-17, encontrado por Juan David al correr esto contra Postgres real): el ID de
esta revisión originalmente era "0023_access_log_registration_method" (35 caracteres) — la tabla
`alembic_version` que Alembic crea sola usa `VARCHAR(32)` por defecto, así que el UPDATE final de
`alembic upgrade head` truncaba con `StringDataRightTruncation`. Postgres corre cada migración en
una transacción (DDL incluido), así que ese fallo revirtió TODO (la propia columna nueva incluida)
— no quedó ninguna migración a medias, solo hubo que acortar el ID y volver a correr. Ver también
la nota en CLAUDE.md sobre este bug, para no repetirlo: cualquier revision ID nuevo debe quedar en
32 caracteres o menos.

Revision ID: 0023_access_log_reg_method
Revises: 0022_staff_secondary_role
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0023_access_log_reg_method"
down_revision = "0022_staff_secondary_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("access_logs") as batch_op:
        batch_op.add_column(sa.Column("registration_method", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("access_logs") as batch_op:
        batch_op.drop_column("registration_method")
