"""CRM: campos de la importación de SuiteCRM. Cuentas: categoría, tipo, industria, sitio web. `legacy_json` (texto, solo lectura) en las tablas importables para guardar lo que no tiene columna."""
import sqlalchemy as sa
from alembic import op

revision = "0142_crm_legacy_fields"
down_revision = "0141_merge_crm_subcat"
branch_labels = None
depends_on = None

TABLES = ("crm_accounts", "crm_contacts", "crm_leads", "crm_opportunities", "crm_activities", "crm_products", "crm_quotes", "crm_proformas")


def upgrade():
    op.add_column("crm_accounts", sa.Column("category", sa.String(40), nullable=True))
    op.add_column("crm_accounts", sa.Column("account_type", sa.String(40), nullable=True))
    op.add_column("crm_accounts", sa.Column("industry", sa.String(60), nullable=True))
    op.add_column("crm_accounts", sa.Column("website", sa.String(300), nullable=True))
    for t in TABLES:
        op.add_column(t, sa.Column("legacy_json", sa.Text(), nullable=True))


def downgrade():
    for t in reversed(TABLES):
        op.drop_column(t, "legacy_json")
    for c in ("website", "industry", "account_type", "category"):
        op.drop_column("crm_accounts", c)
