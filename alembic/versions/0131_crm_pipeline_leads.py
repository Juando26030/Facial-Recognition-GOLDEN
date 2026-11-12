"""CRM C2: embudos y etapas, leads, oportunidades y actividades.

Tablas nuevas `crm_pipelines`, `crm_stages` (con un embudo «Eventos» sembrado, editable por un administrador), `crm_leads`, `crm_opportunities` y `crm_activities`. Sin cambios en tablas existentes.
Escrita a mano, sin `SET` de sesión ni tablas temporales (pooler de Neon). La reversa borra las cinco tablas (en orden inverso de dependencia). Documentos: docs/crm/ETAPA_C1C_C4_DISENO.md.

Revision ID: 0131_crm_pipeline_leads
Revises: 0130_crm_cuentas_base
"""
from alembic import op
import sqlalchemy as sa

revision = "0131_crm_pipeline_leads"
down_revision = "0130_crm_cuentas_base"
branch_labels = None
depends_on = None

# Etapas de fábrica (DECISIÓN abierta: Juan David pasa la lista real; se editan en la pantalla de Embudos sin migración).
DEFAULT_STAGES = [("Prospecto", 10, "open"), ("Calificado", 25, "open"), ("Propuesta de valor", 50, "open"), ("Cotización enviada", 65, "open"),
                  ("Negociación", 80, "open"), ("Ganada", 100, "won"), ("Perdida", 0, "lost")]


def upgrade():
    op.create_table(
        "crm_pipelines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_crm_pipelines_name"),
    )
    op.create_table(
        "crm_stages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("crm_pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(8), nullable=False, server_default="open"),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("pipeline_id", "name", name="uq_crm_stages_pipeline_name"),
    )
    op.create_index("ix_crm_stages_pipeline_pos", "crm_stages", ["pipeline_id", "position"])
    op.execute("INSERT INTO crm_pipelines (name, position, is_default) VALUES ('Eventos', 0, true)")
    for pos, (name, prob, kind) in enumerate(DEFAULT_STAGES):
        op.execute(f"INSERT INTO crm_stages (pipeline_id, name, position, probability, kind) SELECT id, '{name}', {pos}, {prob}, '{kind}' FROM crm_pipelines WHERE name = 'Eventos'")

    op.create_table(
        "crm_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("first_name", sa.String(120)),
        sa.Column("last_name", sa.String(120)),
        sa.Column("full_name_norm", sa.String(240), nullable=False, server_default=""),
        sa.Column("company_name", sa.String(200)),
        sa.Column("job_title", sa.String(120)),
        sa.Column("email", sa.String(200)),
        sa.Column("email_norm", sa.String(200)),
        sa.Column("phone", sa.String(60)),
        sa.Column("source", sa.String(60)),
        sa.Column("status", sa.String(16), nullable=False, server_default="nuevo"),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.Text()),
        sa.Column("converted_at", sa.DateTime(), nullable=True),
        sa.Column("converted_account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("converted_contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("converted_opportunity_id", sa.Integer(), nullable=True),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("uq_crm_leads_legacy", "crm_leads", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))
    op.create_index("ix_crm_leads_status", "crm_leads", ["status"])
    op.create_index("ix_crm_leads_owner", "crm_leads", ["owner_staff_id"])
    op.create_index("ix_crm_leads_email_norm", "crm_leads", ["email_norm"])
    op.create_index("ix_crm_leads_name_norm", "crm_leads", ["full_name_norm"], postgresql_ops={"full_name_norm": "text_pattern_ops"})

    op.create_table(
        "crm_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), sa.ForeignKey("crm_pipelines.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("crm_stages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="COP"),
        sa.Column("probability", sa.Integer(), nullable=True),
        sa.Column("expected_close", sa.Date(), nullable=True),
        sa.Column("opp_type", sa.String(60)),
        sa.Column("source", sa.String(60)),
        sa.Column("next_step", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("primary_contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_start", sa.Date(), nullable=True),
        sa.Column("city", sa.String(120)),
        sa.Column("outcome", sa.String(8), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("lost_reason", sa.String(200)),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("next_activity_at", sa.DateTime(), nullable=True),
        sa.Column("stage_entered_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("code", name="uq_crm_opportunities_code"),
    )
    op.create_index("uq_crm_opportunities_event", "crm_opportunities", ["event_id"], unique=True, postgresql_where=sa.text("event_id IS NOT NULL"))
    op.create_index("uq_crm_opportunities_legacy", "crm_opportunities", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))
    op.create_index("ix_crm_opps_board", "crm_opportunities", ["pipeline_id", "stage_id", "stage_entered_at"])
    op.create_index("ix_crm_opps_account", "crm_opportunities", ["account_id"])
    op.create_index("ix_crm_opps_owner", "crm_opportunities", ["owner_staff_id"])
    op.create_index("ix_crm_opps_close", "crm_opportunities", ["expected_close"])
    op.create_index("ix_crm_opps_outcome", "crm_opportunities", ["outcome"])

    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="planned"),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("remind_at", sa.DateTime(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.String(24)),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("crm_opportunities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("legacy_sugar_id", sa.String(40)),
    )
    op.create_index("uq_crm_activities_legacy", "crm_activities", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))
    op.create_index("ix_crm_act_owner_due", "crm_activities", ["owner_staff_id", "status", "due_at"])
    op.create_index("ix_crm_act_account", "crm_activities", ["account_id", "created_at"])
    op.create_index("ix_crm_act_contact", "crm_activities", ["contact_id"])
    op.create_index("ix_crm_act_lead", "crm_activities", ["lead_id"])
    op.create_index("ix_crm_act_opp", "crm_activities", ["opportunity_id", "created_at"])


def downgrade():
    op.drop_table("crm_activities")          # las tablas llevan sus índices: Postgres los borra con ellas
    op.drop_table("crm_opportunities")
    op.drop_table("crm_leads")
    op.drop_table("crm_stages")
    op.drop_table("crm_pipelines")
