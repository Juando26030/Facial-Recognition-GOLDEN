"""Cuentas de cobro abiertas (Fase 10, bloque B): a qué pertenece cada cuenta (general, evento, formulario o cuenta panelista).

Solo AGREGA columnas con valor por defecto: todo lo que ya existía queda «general» o se deduce de cómo se usa hoy (sin tocar llaves ni pagos). Reversible: la bajada quita las columnas
(las cuentas, sus llaves y las asignaciones a formularios no se tocan).

Revision ID: 0124_payment_acct_scope
Revises: 0123_item_requires_dwell
"""
from alembic import op
import sqlalchemy as sa

revision = "0124_payment_acct_scope"
down_revision = "0123_item_requires_dwell"          # cadena global: 0123 (bloque A) -> 0124 (este)
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payment_accounts", sa.Column("scope", sa.String(12), nullable=False, server_default="general"))
    op.add_column("payment_accounts", sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True))
    op.add_column("payment_accounts", sa.Column("form_id", sa.Integer(), nullable=True))      # sin FK: web_forms ya apunta a payment_accounts (evita un ciclo)
    op.add_column("payment_accounts", sa.Column("panelist_ref", sa.String(120), nullable=True))
    op.create_index("ix_payment_accounts_event_id", "payment_accounts", ["event_id"])
    # Datos existentes, sin cambiar el comportamiento: una cuenta que hoy usan formularios de UN solo evento queda «de ese evento»; si la usa un único formulario, «de ese formulario».
    # Las que no se usan, o se usan en varios eventos, quedan «generales» (valor por defecto). Una cuenta de evento/formulario solo limita las asignaciones NUEVAS.
    op.execute("""
        UPDATE payment_accounts SET scope = 'evento', event_id = (SELECT MIN(f.event_id) FROM web_forms f WHERE f.payment_account_id = payment_accounts.id)
        WHERE (SELECT COUNT(DISTINCT f.event_id) FROM web_forms f WHERE f.payment_account_id = payment_accounts.id) = 1
    """)
    op.execute("""
        UPDATE payment_accounts SET scope = 'formulario', form_id = (SELECT MIN(f.id) FROM web_forms f WHERE f.payment_account_id = payment_accounts.id)
        WHERE scope = 'evento' AND (SELECT COUNT(*) FROM web_forms f WHERE f.payment_account_id = payment_accounts.id) = 1
    """)


def downgrade():
    op.drop_index("ix_payment_accounts_event_id", table_name="payment_accounts")
    op.drop_column("payment_accounts", "panelist_ref")
    op.drop_column("payment_accounts", "form_id")
    op.drop_column("payment_accounts", "event_id")
    op.drop_column("payment_accounts", "scope")
