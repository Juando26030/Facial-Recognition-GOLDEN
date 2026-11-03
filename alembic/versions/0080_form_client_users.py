"""Acceso de cliente por FORMULARIO (solo estadísticas). Solo ADITIVA: una tabla nueva.

  form_client_users   (form_id, staff_user_id único, created_by_id, created_at, expires_at)

Enlaza una cuenta de staff con rol «cliente» con UN formulario. Esa cuenta no se autoriza a ningún evento (sin `event_staff_authorizations`), de modo que solo ve la página
`/mi-formulario` (agregados del formulario, sin datos personales). El código anterior ignora la tabla; bajar la migración la elimina (las cuentas quedan, sin acceso a nada).

Permisos: la tabla y su secuencia quedan cubiertas por los `ALTER DEFAULT PRIVILEGES` de `scripts/neon_app_role.py` (el dueño las crea y `golden_app` hereda SELECT/INSERT/UPDATE/DELETE
y USAGE); en la VM, con el rol dueño, igual que las tablas anteriores. Sin bloqueos sobre tablas existentes.

Revision ID: 0080_form_client_users
Revises: 0079_access_log_took_ms
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0080_form_client_users"
down_revision = "0079_access_log_took_ms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "form_client_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("staff_user_id", name="uq_form_client_users_staff"),
    )
    op.create_index("ix_form_client_users_form_id", "form_client_users", ["form_id"])


def downgrade() -> None:
    op.drop_index("ix_form_client_users_form_id", table_name="form_client_users")
    op.drop_table("form_client_users")
