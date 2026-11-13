"""CRM C1c: corridas del importador de SuiteCRM e informe de emparejamiento con los clientes existentes.

Tablas nuevas `crm_import_runs` y `crm_import_pairs`. Sin datos personales en ninguna: conteos, números de fila, motivos y nombres de EMPRESAS. Sin cambios en tablas existentes.
Escrita a mano, sin `SET` de sesión ni tablas temporales (pooler de Neon). La reversa borra las dos tablas. Documentos: docs/crm/ETAPA_C1C_C4_DISENO.md.

Revision ID: 0132_crm_import_runs
Revises: 0131_crm_pipeline_leads
"""
from alembic import op
import sqlalchemy as sa

revision = "0132_crm_import_runs"
down_revision = "0131_crm_pipeline_leads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="suitecrm"),
        sa.Column("mode", sa.String(8), nullable=False, server_default="sample"),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("files_json", sa.Text()),
        sa.Column("options_json", sa.Text()),
        sa.Column("counts_json", sa.Text()),
        sa.Column("cursor_json", sa.Text()),
        sa.Column("report_key", sa.String(300)),
        sa.Column("error", sa.String(500)),
        sa.Column("started_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_crm_import_runs_created", "crm_import_runs", ["created_at"])
    op.create_table(
        "crm_import_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("crm_import_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("tenant_name", sa.String(200)),
        sa.Column("suitecrm_legacy_id", sa.String(40)),
        sa.Column("suitecrm_code", sa.BigInteger(), nullable=True),
        sa.Column("suitecrm_name", sa.String(200)),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bucket", sa.String(12), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_crm_import_pairs_run", "crm_import_pairs", ["run_id", "bucket"])


def downgrade():
    op.drop_table("crm_import_pairs")
    op.drop_table("crm_import_runs")
