"""Fusión de las cadenas 0133 (CRM) y 0140 (código + subcategorías). Sin cambios de esquema."""
revision = "0141_merge_crm_subcat"
down_revision = ("0133_crm_quotes", "0140_codigo_subcategorias")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
