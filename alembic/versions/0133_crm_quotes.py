"""CRM C3: productos, condiciones comerciales, plantillas, cotizaciones con líneas, proformas, filtros guardados y los contadores `quote` y `proforma`.

Tablas nuevas; sin cambios en las existentes salvo dos filas en `crm_counters` (nacen NO listas: se fijan con scripts/crm_set_counter.py o con el importador).
Escrita a mano, sin `SET` de sesión ni tablas temporales (pooler de Neon). La reversa borra todo lo creado. Documentos: docs/crm/ETAPA_C1C_C4_DISENO.md §3.

Revision ID: 0133_crm_quotes
Revises: 0132_crm_import_runs
"""
from alembic import op
import sqlalchemy as sa

revision = "0133_crm_quotes"
down_revision = "0132_crm_import_runs"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(16, 2)


def _now():
    return sa.text("now()")


def upgrade():
    op.create_table(
        "crm_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sku", sa.String(60)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_norm", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(80)),
        sa.Column("cost", MONEY, nullable=False, server_default="0"),
        sa.Column("price", MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("tax_percent", sa.Numeric(5, 2), nullable=False, server_default="19"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_now()),
    )
    op.create_index("ix_crm_products_name", "crm_products", ["name_norm"])
    op.create_index("uq_crm_products_sku", "crm_products", ["sku"], unique=True, postgresql_where=sa.text("sku IS NOT NULL"))
    op.create_index("uq_crm_products_legacy", "crm_products", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))

    op.create_table(
        "crm_terms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "crm_doc_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("header_text", sa.Text()),
        sa.Column("greeting_text", sa.Text()),
        sa.Column("footer_text", sa.Text()),
        sa.Column("logo_key", sa.String(300)),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_crm_doc_templates_default", "crm_doc_templates", ["kind"], unique=True, postgresql_where=sa.text("is_default AND archived_at IS NULL"))

    op.create_table(
        "crm_quotes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("crm_opportunities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(12), nullable=False, server_default="borrador"),
        sa.Column("approval_status", sa.String(12), nullable=False, server_default="pendiente"),
        sa.Column("invoice_status", sa.String(12), nullable=False, server_default="no_facturada"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("event_start", sa.Date(), nullable=True),
        sa.Column("terms_id", sa.Integer(), sa.ForeignKey("crm_terms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("terms_text", sa.Text()),
        sa.Column("meeting_notes", sa.Text()),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("crm_doc_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subtotal", MONEY, nullable=False, server_default="0"),
        sa.Column("discount_total", MONEY, nullable=False, server_default="0"),
        sa.Column("tax_total", MONEY, nullable=False, server_default="0"),
        sa.Column("total", MONEY, nullable=False, server_default="0"),
        sa.Column("pdf_key", sa.String(300)),
        sa.Column("pdf_generated_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_now()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_crm_quotes_number_version", "crm_quotes", ["number", "version"], unique=True)
    op.create_index("ix_crm_quotes_account", "crm_quotes", ["account_id"])
    op.create_index("ix_crm_quotes_opportunity", "crm_quotes", ["opportunity_id"])
    op.create_index("ix_crm_quotes_stage", "crm_quotes", ["stage", "updated_at"])
    op.create_index("uq_crm_quotes_legacy", "crm_quotes", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))

    op.create_table(
        "crm_quote_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("crm_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("qty", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", MONEY, nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("tax_percent", sa.Numeric(5, 2), nullable=False, server_default="19"),
        sa.Column("line_total", MONEY, nullable=False, server_default="0"),
    )
    op.create_index("ix_crm_quote_lines_quote", "crm_quote_lines", ["quote_id", "position"])

    op.create_table(
        "crm_proformas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("crm_quotes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=False),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="no_pagado"),
        sa.Column("event_name", sa.String(200)),
        sa.Column("city", sa.String(120)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("total", MONEY, nullable=False, server_default="0"),
        sa.Column("pdf_key", sa.String(300)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_now()),
    )
    op.create_index("uq_crm_proformas_number", "crm_proformas", ["number"], unique=True)
    op.create_index("ix_crm_proformas_account", "crm_proformas", ["account_id"])
    op.create_index("uq_crm_proformas_legacy", "crm_proformas", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))

    op.create_table(
        "crm_saved_filters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(14), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_now()),
    )
    op.create_index("ix_crm_saved_filters_owner", "crm_saved_filters", ["owner_staff_id", "scope"])

    op.execute("INSERT INTO crm_counters (name, value, ready) VALUES ('quote', 0, false), ('proforma', 0, false)")


def downgrade():
    op.execute("DELETE FROM crm_counters WHERE name IN ('quote', 'proforma')")
    for table in ("crm_saved_filters", "crm_proformas", "crm_quote_lines", "crm_quotes", "crm_doc_templates", "crm_terms", "crm_products"):
        op.drop_table(table)
