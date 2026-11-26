"""Autorización de ingreso del digitador UNA vez por evento (25-nov-2026, pedido de Juan David). Solo ADITIVA.

  event_staff_authorizations.login_approved_at   NULL = el coordinador todavía no autorizó el ingreso de ese digitador en ESE evento. Con fecha = ya lo autorizó una vez:
                                                 los siguientes ingresos no vuelven a pedirlo mientras todos sus eventos en proceso estén autorizados (app/login_control.py).

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0167_staff_auth_login_ok
Revises: 0166_code_search_first
"""
import sqlalchemy as sa
from alembic import op

revision = "0167_staff_auth_login_ok"
down_revision = "0166_code_search_first"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("event_staff_authorizations", sa.Column("login_approved_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("event_staff_authorizations", "login_approved_at")
