"""Cliente temporal del evento: `staff_users.client_temp`.

Marca la cuenta de rol `digitador` que ingresa con usuario y contraseña propios, sin la solicitud de ingreso que autoriza el coordinador (app/temp_client.py, app/login_control.py).
Falsa para todas las cuentas existentes. Escrita a mano; sin SET de sesión (pooler de Neon).

Revision ID: 0129_staff_client_temp
Revises: 0128_event_types
"""
from alembic import op
import sqlalchemy as sa

revision = "0129_staff_client_temp"
down_revision = "0128_event_types"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("staff_users", sa.Column("client_temp", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("staff_users", "client_temp")
