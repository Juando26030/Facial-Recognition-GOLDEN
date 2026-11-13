"""CRM, pieza C1a: contador de códigos, cuentas, contactos, línea de tiempo y registro de cambios; alias del código de cliente.

Tablas nuevas `crm_*` (esquema public, sin rol nuevo): `crm_counters` (contadores consecutivos, nacen NO listos), `crm_accounts`, `crm_contacts`, `crm_notes` y `crm_change_log`
(misma forma que `person_change_log`, sin llaves foráneas). En `tenants` se agrega `legacy_client_code` (NULL para todos: esta migración NO cambia ningún `client_code`).
Escrita a mano, sin `SET` de sesión ni tablas temporales (pooler de Neon). La reversa restaura el `client_code` hexadecimal desde `legacy_client_code` ANTES de quitar la columna.
Documentos: docs/crm/README.md, docs/crm/CODIGOS.md.

Revision ID: 0130_crm_cuentas_base
Revises: 0129_staff_client_temp
"""
from alembic import op
import sqlalchemy as sa

revision = "0130_crm_cuentas_base"
down_revision = "0129_staff_client_temp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("legacy_client_code", sa.String(), nullable=True))
    op.create_unique_constraint("uq_tenants_legacy_client_code", "tenants", ["legacy_client_code"])

    op.create_table(
        "crm_counters",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("INSERT INTO crm_counters (name, value, ready) VALUES ('account', 0, false), ('event', 0, false)")

    op.create_table(
        "crm_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_norm", sa.String(200), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="activo"),
        sa.Column("nit", sa.String(40)),
        sa.Column("email", sa.String(200)),
        sa.Column("phone", sa.String(60)),
        sa.Column("billing_address", sa.String(300)),
        sa.Column("billing_city", sa.String(120)),
        sa.Column("billing_state", sa.String(120)),
        sa.Column("billing_country", sa.String(120)),
        sa.Column("shipping_address", sa.String(300)),
        sa.Column("shipping_city", sa.String(120)),
        sa.Column("shipping_country", sa.String(120)),
        sa.Column("billing_contact_name", sa.String(200)),
        sa.Column("billing_contact_phone", sa.String(60)),
        sa.Column("payment_term", sa.String(60)),
        sa.Column("payment_days", sa.Integer()),
        sa.Column("billing_close", sa.String(60)),
        sa.Column("agency_percent", sa.Numeric(5, 2)),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.Text()),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("source_created_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("code", name="uq_crm_accounts_code"),
    )
    op.create_index("uq_crm_accounts_tenant", "crm_accounts", ["tenant_id"], unique=True, postgresql_where=sa.text("tenant_id IS NOT NULL"))
    op.create_index("uq_crm_accounts_legacy", "crm_accounts", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))
    op.create_index("ix_crm_accounts_status", "crm_accounts", ["status"])
    op.create_index("ix_crm_accounts_owner", "crm_accounts", ["owner_staff_id"])
    op.create_index("ix_crm_accounts_city", "crm_accounts", ["billing_city"])
    op.create_index("ix_crm_accounts_name_norm", "crm_accounts", ["name_norm"], postgresql_ops={"name_norm": "text_pattern_ops"})

    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(120)),
        sa.Column("last_name", sa.String(120)),
        sa.Column("full_name_norm", sa.String(240), nullable=False, server_default=""),
        sa.Column("job_title", sa.String(120)),
        sa.Column("email", sa.String(200)),
        sa.Column("email_norm", sa.String(200)),
        sa.Column("phone", sa.String(60)),
        sa.Column("mobile", sa.String(60)),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text()),
        sa.Column("legacy_sugar_id", sa.String(40)),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("uq_crm_contacts_primary", "crm_contacts", ["account_id"], unique=True, postgresql_where=sa.text("is_primary"))
    op.create_index("uq_crm_contacts_legacy", "crm_contacts", ["legacy_sugar_id"], unique=True, postgresql_where=sa.text("legacy_sugar_id IS NOT NULL"))
    op.create_index("ix_crm_contacts_account", "crm_contacts", ["account_id"])
    op.create_index("ix_crm_contacts_email_norm", "crm_contacts", ["email_norm"])
    op.create_index("ix_crm_contacts_name_norm", "crm_contacts", ["full_name_norm"], postgresql_ops={"full_name_norm": "text_pattern_ops"})

    op.create_table(
        "crm_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="note"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("legacy_sugar_id", sa.String(40)),
    )
    op.create_index("ix_crm_notes_account_created", "crm_notes", ["account_id", "created_at"])
    op.create_index("ix_crm_notes_contact", "crm_notes", ["contact_id"])

    op.create_table(
        "crm_change_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("old_value", sa.String(500), nullable=True),
        sa.Column("new_value", sa.String(500), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="edit"),
        sa.Column("changed_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_crm_change_log_entity", "crm_change_log", ["entity", "entity_id", "changed_at"])


def downgrade():
    # 1) restaurar el código hexadecimal de los clientes que ya pasaron al número consecutivo (antes de quitar la columna que lo guarda)
    op.execute("UPDATE tenants SET client_code = legacy_client_code WHERE legacy_client_code IS NOT NULL")
    op.drop_index("ix_crm_change_log_entity", table_name="crm_change_log")
    op.drop_table("crm_change_log")
    op.drop_index("ix_crm_notes_contact", table_name="crm_notes")
    op.drop_index("ix_crm_notes_account_created", table_name="crm_notes")
    op.drop_table("crm_notes")
    op.drop_index("ix_crm_contacts_name_norm", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_email_norm", table_name="crm_contacts")
    op.drop_index("ix_crm_contacts_account", table_name="crm_contacts")
    op.drop_index("uq_crm_contacts_legacy", table_name="crm_contacts")
    op.drop_index("uq_crm_contacts_primary", table_name="crm_contacts")
    op.drop_table("crm_contacts")
    op.drop_index("ix_crm_accounts_name_norm", table_name="crm_accounts")
    op.drop_index("ix_crm_accounts_city", table_name="crm_accounts")
    op.drop_index("ix_crm_accounts_owner", table_name="crm_accounts")
    op.drop_index("ix_crm_accounts_status", table_name="crm_accounts")
    op.drop_index("uq_crm_accounts_legacy", table_name="crm_accounts")
    op.drop_index("uq_crm_accounts_tenant", table_name="crm_accounts")
    op.drop_table("crm_accounts")
    op.drop_table("crm_counters")
    op.drop_constraint("uq_tenants_legacy_client_code", "tenants", type_="unique")
    op.drop_column("tenants", "legacy_client_code")
