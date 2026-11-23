"""CRM: diseño por bloques de las plantillas de PDF (layout_json) y foto del producto (image_key)."""
import sqlalchemy as sa
from alembic import op

revision = "0144_crm_pdf_layout"
down_revision = "0143_event_review_detail"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crm_doc_templates", sa.Column("layout_json", sa.Text(), nullable=True))
    op.add_column("crm_products", sa.Column("image_key", sa.String(300), nullable=True))


def downgrade():
    op.drop_column("crm_products", "image_key")
    op.drop_column("crm_doc_templates", "layout_json")
