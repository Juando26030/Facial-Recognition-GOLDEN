-- Espejo en SQL de upgrade() de alembic/versions/0130_crm_cuentas_base.py (mantener igual si la migración cambia).
ALTER TABLE tenants ADD COLUMN legacy_client_code varchar;
ALTER TABLE tenants ADD CONSTRAINT uq_tenants_legacy_client_code UNIQUE (legacy_client_code);
CREATE TABLE crm_counters (name varchar(32) PRIMARY KEY, value bigint NOT NULL DEFAULT 0, ready boolean NOT NULL DEFAULT false, updated_at timestamp NOT NULL DEFAULT now());
INSERT INTO crm_counters (name, value, ready) VALUES ('account', 0, false), ('event', 0, false);
CREATE TABLE crm_accounts (
  id serial PRIMARY KEY, code bigint NOT NULL,
  tenant_id varchar REFERENCES tenants(id) ON DELETE SET NULL,
  name varchar(200) NOT NULL, name_norm varchar(200) NOT NULL, status varchar(12) NOT NULL DEFAULT 'activo',
  nit varchar(40), email varchar(200), phone varchar(60),
  billing_address varchar(300), billing_city varchar(120), billing_state varchar(120), billing_country varchar(120),
  shipping_address varchar(300), shipping_city varchar(120), shipping_country varchar(120),
  billing_contact_name varchar(200), billing_contact_phone varchar(60), payment_term varchar(60), payment_days integer, billing_close varchar(60), agency_percent numeric(5,2),
  owner_staff_id integer REFERENCES staff_users(id) ON DELETE SET NULL, description text, legacy_sugar_id varchar(40), source_created_at timestamp, archived_at timestamp,
  created_at timestamp NOT NULL DEFAULT now(), updated_at timestamp NOT NULL DEFAULT now(), created_by_id integer REFERENCES staff_users(id) ON DELETE SET NULL,
  CONSTRAINT uq_crm_accounts_code UNIQUE (code));
CREATE UNIQUE INDEX uq_crm_accounts_tenant ON crm_accounts (tenant_id) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX uq_crm_accounts_legacy ON crm_accounts (legacy_sugar_id) WHERE legacy_sugar_id IS NOT NULL;
CREATE INDEX ix_crm_accounts_status ON crm_accounts (status);
CREATE INDEX ix_crm_accounts_owner ON crm_accounts (owner_staff_id);
CREATE INDEX ix_crm_accounts_city ON crm_accounts (billing_city);
CREATE INDEX ix_crm_accounts_name_norm ON crm_accounts (name_norm text_pattern_ops);
CREATE TABLE crm_contacts (
  id serial PRIMARY KEY, account_id integer NOT NULL REFERENCES crm_accounts(id) ON DELETE CASCADE,
  first_name varchar(120), last_name varchar(120), full_name_norm varchar(240) NOT NULL DEFAULT '', job_title varchar(120),
  email varchar(200), email_norm varchar(200), phone varchar(60), mobile varchar(60), is_primary boolean NOT NULL DEFAULT false, notes text,
  legacy_sugar_id varchar(40), archived_at timestamp, created_at timestamp NOT NULL DEFAULT now(), updated_at timestamp NOT NULL DEFAULT now(),
  created_by_id integer REFERENCES staff_users(id) ON DELETE SET NULL);
CREATE UNIQUE INDEX uq_crm_contacts_primary ON crm_contacts (account_id) WHERE is_primary;
CREATE UNIQUE INDEX uq_crm_contacts_legacy ON crm_contacts (legacy_sugar_id) WHERE legacy_sugar_id IS NOT NULL;
CREATE INDEX ix_crm_contacts_account ON crm_contacts (account_id);
CREATE INDEX ix_crm_contacts_email_norm ON crm_contacts (email_norm);
CREATE INDEX ix_crm_contacts_name_norm ON crm_contacts (full_name_norm text_pattern_ops);
CREATE TABLE crm_notes (
  id serial PRIMARY KEY, account_id integer NOT NULL REFERENCES crm_accounts(id) ON DELETE CASCADE, contact_id integer REFERENCES crm_contacts(id) ON DELETE CASCADE,
  kind varchar(16) NOT NULL DEFAULT 'note', body text NOT NULL, created_by_id integer REFERENCES staff_users(id) ON DELETE SET NULL,
  created_at timestamp NOT NULL DEFAULT now(), updated_at timestamp NOT NULL DEFAULT now(), legacy_sugar_id varchar(40));
CREATE INDEX ix_crm_notes_account_created ON crm_notes (account_id, created_at);
CREATE INDEX ix_crm_notes_contact ON crm_notes (contact_id);
CREATE TABLE crm_change_log (
  id serial PRIMARY KEY, entity varchar(16) NOT NULL, entity_id integer NOT NULL, field_key varchar(64) NOT NULL, old_value varchar(500), new_value varchar(500),
  changed_by_id integer, source varchar(16) NOT NULL DEFAULT 'edit', changed_at timestamp NOT NULL DEFAULT now());
CREATE INDEX ix_crm_change_log_entity ON crm_change_log (entity, entity_id, changed_at);
