"""Sprint 4: seguridad de cuentas.

- `rate_limit_events`: intentos (login fallido, solicitud de restablecer, consulta de certificado) para limitar abuso.
- `password_reset_tokens`: enlaces de "olvidé mi contraseña" (solo el hash, de un solo uso, con vencimiento).
- `staff_users.must_change_password`: tras un restablecimiento por un admin/coordinador, la persona elige la suya.

Revision ID: 0036_security
Revises: 0035_ajustes_0923
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0036_security"
down_revision = "0035_ajustes_0923"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rate_limit_kind_key_time", "rate_limit_events", ["kind", "key", "created_at"])
    op.create_index("ix_rate_limit_kind_ip_time", "rate_limit_events", ["kind", "ip", "created_at"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.drop_column("must_change_password")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_rate_limit_kind_ip_time", table_name="rate_limit_events")
    op.drop_index("ix_rate_limit_kind_key_time", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
